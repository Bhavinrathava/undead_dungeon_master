"""
agent/resolver_agent.py
Resolves a classified action into a concrete outcome string that gets
forwarded to the DM agent as context for its narrative response.

Handlers:
  TALK            — NPC knowledge-based dialogue (no roll required).
  TALK_SKILL_CHECK — Skill-gated secret reveal: full / partial / failure
                     depending on a d20 roll vs the secret's DC thresholds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from ai_dungeon_master.adventure.models import Adventure, NPC, NPCSecret
from ai_dungeon_master.agent.action_classifier_agent import ClassifiedAction
from ai_dungeon_master.agent.llm_client import LLMClient
from ai_dungeon_master.combat.combat_engine import CombatEngine
from ai_dungeon_master.dice.dice_engine import DiceEngine
from ai_dungeon_master.state.world_state import CombatState, EnemyState, PartyMemberState, WorldState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Outcome enum
# ---------------------------------------------------------------------------


class SkillCheckOutcome(str, Enum):
    FULL_REVEAL = "FULL_REVEAL"
    PARTIAL_REVEAL = "PARTIAL_REVEAL"
    FAILURE = "FAILURE"


@dataclass
class SkillCheckEvent:
    """Raw mechanical details of a completed skill check, surfaced to the UI."""

    skill_name: str
    raw_roll: int
    modifier: int
    total: int
    dc_full: int
    dc_partial: int
    outcome: SkillCheckOutcome


# ---------------------------------------------------------------------------
# NPC system prompts
# ---------------------------------------------------------------------------

_TALK_SYSTEM = """\
You are {name}, a {role}.
Personality: {personality}{dialogue_style}

What you know:
{knowledge}

Stay in character. Speak in first person. Be concise and true to your personality.
Respond only with your spoken words — no stage directions, no narration."""

_SKILL_CHECK_FULL_REVEAL = """\
You are {name}, a {role}.
Personality: {personality}{dialogue_style}

You have just been successfully pressured — through persuasion, intimidation, or sharp insight \
the other person has seen through you. You must reveal your secret, even though you desperately \
did not want to.

Your secret: {secret_text}
Why you were hiding it: {concealment_reason}

Respond in character: confess the secret in your own words. Show the emotional weight — \
shame, fear, relief, or whatever fits your personality. Speak in first person only. \
No stage directions."""

_SKILL_CHECK_PARTIAL_REVEAL = """\
You are {name}, a {role}.
Personality: {personality}{dialogue_style}

You are being pressed on something sensitive. You haven't broken, but something slipped — \
a hesitation, a poorly chosen word, a tell you couldn't suppress.

Use one of these behavioural hints as a basis for what leaks out:
{hints}

Why you are hiding the full truth: {concealment_reason}

Respond in character: let something slip that you immediately regret or try to cover up. \
Do NOT reveal the full secret. Speak in first person only. No stage directions."""

_SKILL_CHECK_FAILURE = """\
You are {name}, a {role}.
Personality: {personality}{dialogue_style}

You are being pressed on something you absolutely will not discuss. You shut it down — \
deflect, change the subject, get hostile, or give a flat denial. Whatever fits your personality.

Why you are guarding this: {concealment_reason}

Respond in character: refuse or deflect firmly. Speak in first person only. No stage directions."""


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class ResolverAgent:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self._dice = DiceEngine()

    def resolve_action(
        self,
        intent: ClassifiedAction,
        player_input: str,
        world_state: WorldState,
        adventure: Adventure,
    ) -> tuple[str, SkillCheckEvent | None]:
        """
        Dispatch to the appropriate handler based on action_type.
        Returns (resolution_string, skill_check_event_or_None).
        resolution_string is forwarded to the DM agent as context.
        """
        action_type = intent["action_type"]
        logger.info("Resolver — dispatching action_type=%s", action_type)

        # Any action during active combat is handled by the combat handler.
        # This covers ATTACK (in-combat strike), MOVE (disengage), etc.
        if world_state.in_combat:
            return self._resolve_combat_action(
                intent, player_input, world_state, adventure
            )

        if action_type == "TALK":
            return (
                self._resolve_talk(
                    intent, player_input, world_state, adventure
                ),
                None,
            )

        if action_type == "TALK_SKILL_CHECK":
            return self._resolve_talk_skill_check(
                intent, player_input, world_state, adventure
            )

        if action_type == "ATTACK":
            return self._resolve_attack(
                intent, player_input, world_state, adventure
            )

        logger.warning(
            "Resolver — no handler for action_type=%s, returning empty",
            action_type,
        )
        return "", None

    # ------------------------------------------------------------------
    # TALK
    # ------------------------------------------------------------------

    def _resolve_talk(
        self,
        intent: ClassifiedAction,
        player_input: str,
        world_state: WorldState,
        adventure: Adventure,
    ) -> tuple[str, None]:
        """NPC responds using only their public knowledge — no roll."""
        npc = self._find_npc(
            intent.get("target"), world_state.current_location_id, adventure
        )
        if npc is None:
            logger.warning(
                "Resolver/TALK — NPC %r not found at location %r",
                intent.get("target"),
                world_state.current_location_id,
            )
            return "", None

        logger.info("Resolver/TALK — NPC=%s", npc.name)
        response = self.llm.call(
            system=_TALK_SYSTEM.format(
                name=npc.name,
                role=npc.role,
                personality=npc.personality,
                dialogue_style=self._dialogue_style(npc),
                knowledge=self._knowledge_str(npc),
            ),
            user=player_input,
        )
        logger.debug("Resolver/TALK — NPC response: %r", response)
        return response, None

    # ------------------------------------------------------------------
    # TALK_SKILL_CHECK
    # ------------------------------------------------------------------

    def _resolve_talk_skill_check(
        self,
        intent: ClassifiedAction,
        player_input: str,
        world_state: WorldState,
        adventure: Adventure,
    ) -> tuple[str, SkillCheckEvent | None]:
        """
        Roll a skill check against the NPC's secret DC thresholds.
        Falls back to plain TALK if the NPC has no secret.
        """
        npc = self._find_npc(
            intent.get("target"), world_state.current_location_id, adventure
        )
        if npc is None:
            logger.warning(
                "Resolver/SKILL_CHECK — NPC %r not found at location %r",
                intent.get("target"),
                world_state.current_location_id,
            )
            return "", None

        # No secret → treat as a plain TALK (no event)
        if npc.secret is None:
            logger.info(
                "Resolver/SKILL_CHECK — NPC=%s has no secret, falling back to TALK",
                npc.name,
            )
            return self._resolve_talk(
                intent, player_input, world_state, adventure
            )

        secret = npc.secret

        # --- Determine skill + modifier ---
        skill_name, modifier = self._best_skill_modifier(
            actor_name=intent.get("actor"),
            skill_types=secret.skill_type,
            world_state=world_state,
        )

        # --- Roll d20 ---
        raw_roll = self._dice.roll(sides=20)
        total = raw_roll + modifier
        sign = "+" if modifier >= 0 else ""
        logger.info(
            "Resolver/SKILL_CHECK — NPC=%s | skill=%s | roll=%d %s%d = %d | DC full=%d partial=%d",
            npc.name,
            skill_name,
            raw_roll,
            sign,
            modifier,
            total,
            secret.reveal_threshold,
            secret.partial_reveal_threshold,
        )

        # --- Evaluate outcome ---
        outcome = self._evaluate_outcome(total, secret)
        logger.info("Resolver/SKILL_CHECK — outcome=%s", outcome.value)

        # --- Generate NPC dialogue ---
        npc_dialogue = self._generate_skill_check_dialogue(
            npc=npc,
            secret=secret,
            outcome=outcome,
            player_input=player_input,
        )
        logger.debug("Resolver/SKILL_CHECK — NPC dialogue: %r", npc_dialogue)

        # --- Build result block for DM agent ---
        result_str = (
            f"[Skill check: {skill_name} | "
            f"Roll: {raw_roll} {sign}{modifier} = {total} | "
            f"DC: {secret.reveal_threshold} (full) / {secret.partial_reveal_threshold} (partial) | "
            f"Outcome: {outcome.value}]\n\n"
            f"{npc.name}: {npc_dialogue}"
        )

        event = SkillCheckEvent(
            skill_name=skill_name,
            raw_roll=raw_roll,
            modifier=modifier,
            total=total,
            dc_full=secret.reveal_threshold,
            dc_partial=secret.partial_reveal_threshold,
            outcome=outcome,
        )
        return result_str, event

    def _evaluate_outcome(
        self, total: int, secret: NPCSecret
    ) -> SkillCheckOutcome:
        if total >= secret.reveal_threshold:
            return SkillCheckOutcome.FULL_REVEAL
        if total >= secret.partial_reveal_threshold:
            return SkillCheckOutcome.PARTIAL_REVEAL
        return SkillCheckOutcome.FAILURE

    def _generate_skill_check_dialogue(
        self,
        npc: NPC,
        secret: NPCSecret,
        outcome: SkillCheckOutcome,
        player_input: str,
    ) -> str:
        if outcome == SkillCheckOutcome.FULL_REVEAL:
            template = _SKILL_CHECK_FULL_REVEAL
            kwargs = dict(
                name=npc.name,
                role=npc.role,
                personality=npc.personality,
                dialogue_style=self._dialogue_style(npc),
                secret_text=secret.text,
                concealment_reason=secret.concealment_reason,
            )
        elif outcome == SkillCheckOutcome.PARTIAL_REVEAL:
            hints_str = (
                "\n".join(f"- {h}" for h in secret.hints)
                if secret.hints
                else "- You shift uncomfortably and avoid eye contact."
            )
            template = _SKILL_CHECK_PARTIAL_REVEAL
            kwargs = dict(
                name=npc.name,
                role=npc.role,
                personality=npc.personality,
                dialogue_style=self._dialogue_style(npc),
                hints=hints_str,
                concealment_reason=secret.concealment_reason,
            )
        else:
            template = _SKILL_CHECK_FAILURE
            kwargs = dict(
                name=npc.name,
                role=npc.role,
                personality=npc.personality,
                dialogue_style=self._dialogue_style(npc),
                concealment_reason=secret.concealment_reason,
            )

        return self.llm.call(
            system=template.format(**kwargs), user=player_input
        )

    # ------------------------------------------------------------------
    # Skill resolution helpers
    # ------------------------------------------------------------------

    def _best_skill_modifier(
        self,
        actor_name: str | None,
        skill_types: list[str],
        world_state: WorldState,
    ) -> tuple[str, int]:
        """
        Return (skill_name, modifier) — the highest applicable skill modifier
        for the acting party member. Falls back to 0 if nothing matches.
        """
        actor = world_state.get_player(actor_name) if actor_name else None
        if actor is None and world_state.living_party:
            actor = world_state.living_party[0]
        if actor is None or not skill_types:
            return (skill_types[0] if skill_types else "skill", 0)

        best_name = skill_types[0]
        best_mod = 0
        for skill_type in skill_types:
            normalized = skill_type.replace(" ", "_")
            for key, score in actor.skills.items():
                if key.lower() == normalized.lower():
                    if score.modifier > best_mod:
                        best_name = key
                        best_mod = score.modifier
                    break

        return (best_name, best_mod)

    # ------------------------------------------------------------------
    # NPC lookup / formatting helpers
    # ------------------------------------------------------------------

    def _find_npc(
        self,
        target: str | None,
        location_id: str,
        adventure: Adventure,
    ) -> NPC | None:
        """Return the NPC whose name matches *target* in the current location."""
        if not target:
            return None
        location = adventure.get_location(location_id)
        if location is None:
            return None
        target_lower = target.lower()
        return next(
            (npc for npc in location.npcs if npc.name.lower() == target_lower),
            None,
        )

    def _knowledge_str(self, npc: NPC) -> str:
        return (
            "\n".join(f"- {k}" for k in npc.knowledge)
            if npc.knowledge
            else "- Nothing of note."
        )

    def _dialogue_style(self, npc: NPC) -> str:
        return (
            f"\nDialogue style: {npc.dialogue_hints}"
            if npc.dialogue_hints
            else ""
        )

    # ------------------------------------------------------------------
    # In-combat action resolution
    # ------------------------------------------------------------------

    def _resolve_combat_action(
        self,
        intent: ClassifiedAction,
        player_input: str,
        world_state: WorldState,
        adventure: Adventure,
    ) -> tuple[str, None]:
        """Handle any player action during an active combat turn.

        ATTACK → roll mechanically, apply damage, advance turn.
        All other action types → advance turn, let the DM narrate freely.
        """
        combat = world_state.combat
        action_type = intent["action_type"]

        # Non-attack in-combat action (move, talk, item, etc.) — just advance turn.
        if action_type != "ATTACK":
            next_actor = combat.advance_turn()
            logger.info(
                "Resolver/COMBAT — %s action (non-attack), turn advanced to %s",
                action_type, next_actor,
            )
            return f"[{action_type} action in combat — turn advanced to {next_actor}]", None

        # ── Identify attacker ─────────────────────────────────────────────
        actor_name = intent.get("actor")
        attacker: PartyMemberState | None = (
            world_state.get_player(actor_name) if actor_name else None
        )
        if attacker is None and world_state.living_party:
            attacker = world_state.living_party[0]
        if attacker is None:
            logger.warning("Resolver/COMBAT — no living party member to act")
            return "[No living party member to act]", None

        # ── Identify target ───────────────────────────────────────────────
        target_name = intent.get("target")
        target = None
        if target_name:
            t_lower = target_name.lower()
            for e in combat.living_enemies:
                if t_lower in e.instance_id.lower() or t_lower in e.name.lower():
                    target = e
                    break
        if target is None and combat.living_enemies:
            target = combat.living_enemies[0]
        if target is None:
            logger.warning("Resolver/COMBAT — no living enemies to attack")
            return "[No living enemies to attack]", None

        # ── Pick attack stats ─────────────────────────────────────────────
        if attacker.attacks:
            atk = attacker.attacks[0]
            hit_bonus = (
                atk.attack_bonus
                if isinstance(atk.attack_bonus, int)
                else attacker.attack_bonus
            )
            sides, count, dmg_mod = DiceEngine.parse_notation(
                atk.damage or attacker.damage_dice
            )
        else:
            hit_bonus = attacker.attack_bonus
            sides, count, dmg_mod = DiceEngine.parse_notation(attacker.damage_dice)

        logger.info(
            "Resolver/COMBAT — %s attacks %s | hit+%d vs AC %d | %dd%d+%d",
            attacker.name, target.instance_id, hit_bonus, target.ac,
            count, sides, dmg_mod,
        )

        # ── Roll ──────────────────────────────────────────────────────────
        engine = CombatEngine(world_state, self._dice)
        result = engine.resolve_attack(
            attacker_hit_modifier=hit_bonus,
            defender_ac=target.ac,
            dmg_sides=sides,
            dmg_count=count,
            dmg_modifier=dmg_mod,
        )
        outcome = result["result"]
        damage = result["damage"]
        raw_roll = result["attack_roll"]

        if outcome != "miss":
            target.take_damage(damage)
            combat.log_event(
                f"{attacker.name} → {target.instance_id}: {outcome}, {damage} dmg"
            )
        else:
            combat.log_event(f"{attacker.name} → {target.instance_id}: miss")

        logger.info(
            "Resolver/COMBAT — outcome=%s  damage=%d  target HP=%d/%d",
            outcome, damage, target.current_hp, target.max_hp,
        )

        # ── Check encounter end ───────────────────────────────────────────
        if combat.is_encounter_over:
            world_state.end_combat()
            return (
                f"[ATTACK — {attacker.name} vs {target.name} | "
                f"Roll: {raw_roll} (+{hit_bonus}) | {outcome.upper()} | "
                f"Damage: {damage}]\n"
                f"[COMBAT ENDED — all enemies defeated]"
            ), None

        # ── Advance turn ──────────────────────────────────────────────────
        next_actor = combat.advance_turn()
        return (
            f"[ATTACK — {attacker.name} vs {target.name} | "
            f"Roll: {raw_roll} (+{hit_bonus}) | {outcome.upper()} | "
            f"Damage: {damage} | {target.name} HP: {target.current_hp}/{target.max_hp}]\n"
            f"Next actor: {next_actor}"
        ), None

    # ------------------------------------------------------------------
    # Combat initiation
    # ------------------------------------------------------------------

    def _npc_to_enemy_state(self, npc: NPC, instance_id: str) -> EnemyState:
        """Convert a read-only NPC into a mutable EnemyState for combat."""
        return EnemyState(
            instance_id=instance_id,
            name=npc.name,
            max_hp=npc.hp,
            current_hp=npc.hp,
            ac=npc.ac,
            attack_bonus=npc.attack_bonus,
            damage_dice=npc.damage_dice,
            damage_type=npc.damage_type,
            initiative=npc.initiative_modifier,
            group=npc.group,
        )

    def _resolve_attack(
        self,
        intent: ClassifiedAction,
        player_input: str,
        world_state: WorldState,
        adventure: Adventure,
    ) -> tuple[str, None]:
        """Initiate combat when the player attacks an NPC outside of combat.

        Steps:
        1. Guard — already in combat.
        2. Find target NPC.
        3. Gather all NPCs at the location sharing the target's group as enemies.
        4. Gather ally NPCs (npc.ally == True) as ally combatants.
        5. Roll d20 + initiative modifier for every combatant.
        6. Build CombatState, start combat, return a summary string for the DM.
        """
        if world_state.in_combat:
            logger.info("Resolver/ATTACK — already in combat, forwarding to DM")
            return "[Already in combat]", None

        npc = self._find_npc(
            intent.get("target"), world_state.current_location_id, adventure
        )
        if npc is None:
            logger.warning(
                "Resolver/ATTACK — NPC %r not found at location %r",
                intent.get("target"),
                world_state.current_location_id,
            )
            return "", None

        logger.info("Resolver/ATTACK — target=%s  group=%r", npc.name, npc.group)

        location = adventure.get_location(world_state.current_location_id)
        location_npcs: list[NPC] = location.npcs if location else []

        # ── Gather enemy NPCs ──────────────────────────────────────────────
        # Always include the directly attacked NPC.
        # If it belongs to a faction, pull in every other NPC at this location
        # that shares that faction and isn't flagged as an ally.
        enemy_npcs: list[NPC] = [npc]
        if npc.group:
            for loc_npc in location_npcs:
                if (
                    loc_npc.name != npc.name
                    and loc_npc.group == npc.group
                    and not loc_npc.ally
                ):
                    enemy_npcs.append(loc_npc)
                    logger.info(
                        "Resolver/ATTACK — adding faction member %s to enemies",
                        loc_npc.name,
                    )

        # ── Gather ally NPCs ───────────────────────────────────────────────
        # NPCs marked ally=True join the player side.  They are stored in
        # CombatState.enemies with group="ally" so the DM can distinguish them.
        ally_npcs: list[NPC] = [
            n
            for n in location_npcs
            if n.ally and n.group != npc.group and n.name != npc.name
        ]
        for a in ally_npcs:
            logger.info("Resolver/ATTACK — %s joins as ally", a.name)

        # ── Convert to EnemyState (unique instance_ids) ───────────────────
        name_counts: dict[str, int] = {}

        def _to_state(src_npc: NPC, override_group: str = "") -> EnemyState:
            key = src_npc.name.lower().replace(" ", "_")
            name_counts[key] = name_counts.get(key, 0) + 1
            iid = f"{key}_{name_counts[key]}"
            state = self._npc_to_enemy_state(src_npc, iid)
            if override_group:
                state.group = override_group
            return state

        enemy_states: list[EnemyState] = [_to_state(e) for e in enemy_npcs]
        ally_states: list[EnemyState] = [_to_state(a, override_group="ally") for a in ally_npcs]
        all_combatant_states = enemy_states + ally_states

        # ── Roll initiatives ───────────────────────────────────────────────
        # Rolls are local; we do NOT overwrite the DEX-modifier `initiative`
        # field on the models.  Turn order encodes the result.
        initiative_rolls: list[tuple[str, int]] = []

        for pm in world_state.living_party:
            rolled = self._dice.roll(sides=20) + pm.initiative
            initiative_rolls.append((pm.name, rolled))

        for es in all_combatant_states:
            rolled = self._dice.roll(sides=20) + es.initiative
            initiative_rolls.append((es.instance_id, rolled))

        # Sort descending; ties retain insertion order (party declared first)
        initiative_rolls.sort(key=lambda x: x[1], reverse=True)
        turn_order = [name for name, _ in initiative_rolls]

        # ── Build and start CombatState ────────────────────────────────────
        safe_name = npc.name.lower().replace(" ", "_")
        encounter_id = f"combat_{safe_name}_{world_state.turn_count}"

        combat = CombatState(
            encounter_id=encounter_id,
            enemies=all_combatant_states,
            party=list(world_state.living_party),
            turn_order=turn_order,
        )

        for combatant_name, roll in initiative_rolls:
            combat.log_event(f"Initiative — {combatant_name}: {roll}")

        world_state.start_combat(combat)
        logger.info(
            "Resolver/ATTACK — combat started  id=%s  turn_order=%s",
            encounter_id,
            turn_order,
        )

        # ── Build result string for DM narration ───────────────────────────
        enemy_summary = ", ".join(
            f"{e.instance_id} ({e.current_hp}/{e.max_hp} HP, AC {e.ac})"
            for e in enemy_states
        )
        ally_summary = (
            "  Allies: " + ", ".join(
                f"{a.instance_id} ({a.current_hp}/{a.max_hp} HP)"
                for a in ally_states
            )
            if ally_states
            else ""
        )
        order_summary = " → ".join(
            f"{name} ({roll})" for name, roll in initiative_rolls
        )
        result_str = (
            f"[COMBAT INITIATED — Round 1]\n"
            f"Enemies: {enemy_summary}\n"
            f"{ally_summary}\n"
            f"Turn order: {order_summary}\n"
            f"First to act: {combat.current_actor}"
        ).strip()

        return result_str, None
