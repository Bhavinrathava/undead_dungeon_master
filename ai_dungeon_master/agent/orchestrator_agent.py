from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ai_dungeon_master.adventure.models import Adventure
from ai_dungeon_master.agent.action_classifier_agent import ActionClassifierAgent
from ai_dungeon_master.agent.dm_agent import DMAgent, DMPersonality
from ai_dungeon_master.agent.llm_client import LLMClient
from ai_dungeon_master.agent.resolver_agent import ResolverAgent, SkillCheckEvent
from ai_dungeon_master.combat.combat_engine import CombatEngine
from ai_dungeon_master.dice.dice_engine import DiceEngine
from ai_dungeon_master.state.world_state import WorldState

logger = logging.getLogger(__name__)

_NARRATOR_SYSTEM = """\
You are the narrator of a tabletop dungeon master adventure. \
The player is asking you a general question — not talking to an NPC, not taking an action. \
Answer briefly and helpfully in the voice of an omniscient narrator. \
Keep your response short (1-3 sentences). Do not invent major new plot details."""


@dataclass
class TurnResult:
    """Everything produced by a single player turn."""
    dm_response: str
    skill_check: SkillCheckEvent | None = None
    trace: list[dict] = field(default_factory=list)


class OrchestratorAgent:
    def __init__(
        self,
        llm_client: LLMClient,
        personality: DMPersonality = DMPersonality.STORYTELLER,
    ):
        self.llm = llm_client
        self.classifier = ActionClassifierAgent(llm_client)
        self.resolver_agent = ResolverAgent(llm_client)
        self.dm_agent = DMAgent(personality=personality)

    # ------------------------------------------------------------------
    # Combat helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_player_turn(world_state: WorldState) -> bool:
        """Return True when the current combat actor is a party member."""
        if not world_state.in_combat:
            return True
        actor = world_state.combat.current_actor
        return any(p.name == actor for p in world_state.party)

    def _process_npc_turn(self, world_state: WorldState) -> str:
        """Resolve one NPC/enemy combat turn mechanically.

        Advances the turn and returns a mechanical summary string for the DM
        to narrate. Returns an empty string for dead/missing actors (silently
        skipped).
        """
        combat = world_state.combat
        actor_id = combat.current_actor
        enemy = combat.get_enemy(actor_id)

        # Actor is dead or not found — skip silently.
        if enemy is None or not enemy.is_alive:
            combat.advance_turn()
            return ""

        # Ally NPC — they fight for the player; skip mechanical resolution for now.
        if enemy.group == "ally":
            combat.advance_turn()
            logger.info("Orchestrator/NPC-turn — %s (ally) holds position", enemy.name)
            return f"[{enemy.name} stands ready, supporting the party]"

        # Pick target: living party member with lowest HP.
        living = combat.living_party
        if not living:
            world_state.end_combat()
            logger.info("Orchestrator/NPC-turn — party wiped, ending combat")
            return "[COMBAT ENDED — party defeated]"

        target = min(living, key=lambda p: p.current_hp)

        # Resolve attack.
        sides, count, _ = DiceEngine.parse_notation(enemy.damage_dice)
        engine = CombatEngine(world_state, DiceEngine())
        result = engine.resolve_attack(
            attacker_hit_modifier=enemy.attack_bonus,
            defender_ac=target.ac,
            dmg_sides=sides,
            dmg_count=count,
            dmg_modifier=0,
        )
        outcome = result["result"]
        damage = result["damage"]
        raw_roll = result["attack_roll"]

        if outcome != "miss":
            target.take_damage(damage)
            combat.log_event(
                f"{actor_id} → {target.name}: {outcome}, {damage} dmg"
            )
        else:
            combat.log_event(f"{actor_id} → {target.name}: miss")

        logger.info(
            "Orchestrator/NPC-turn — %s attacks %s: %s  dmg=%d  target HP=%d/%d",
            enemy.name, target.name, outcome, damage,
            target.current_hp, target.max_hp,
        )

        combat.advance_turn()

        if outcome == "miss":
            return (
                f"[{enemy.name} attacks {target.name}: MISS "
                f"(roll {raw_roll} +{enemy.attack_bonus} vs AC {target.ac})]"
            )
        return (
            f"[{enemy.name} attacks {target.name}: {outcome.upper()} | "
            f"Roll: {raw_roll} (+{enemy.attack_bonus}) | "
            f"Damage: {damage} {enemy.damage_type} | "
            f"{target.name} HP: {target.current_hp}/{target.max_hp}]"
        )

    # ------------------------------------------------------------------
    # Main turn orchestration
    # ------------------------------------------------------------------

    def orchestrate(
        self,
        player_input: str,
        world_state_str: str,
        adventure_context: str,
        world_state: WorldState,
        adventure: Adventure,
    ) -> TurnResult:
        logger.info("─── Turn start — player: %r ───", player_input)
        trace: list[dict] = []

        intent = self.classifier.classify_action(
            player_input=player_input,
            world_state=world_state_str,
            adventure_context=adventure_context,
        )
        trace.append({
            "step": "classify",
            "action_type": intent["action_type"],
            "actor": intent.get("actor"),
            "target": intent.get("target"),
            "additional_info": intent.get("additional_info"),
        })

        if intent["action_type"] == "NARRATOR_INTERACTION":
            logger.info("Orchestrator — NARRATOR_INTERACTION, bypassing resolver and DM agent")
            response = self.llm.call(
                system=_NARRATOR_SYSTEM,
                user=f"Adventure context:\n{adventure_context}\n\nWorld state:\n{world_state_str}\n\nPlayer: {player_input}",
            )
            logger.info("Orchestrator — narrator response: %r", response[:120])
            trace.append({"step": "narrator_response", "response": response})
            logger.info("─── Turn end ───")
            return TurnResult(dm_response=response, skill_check=None, trace=trace)

        resolution, skill_check_event = self.resolver_agent.resolve_action(
            intent=intent,
            player_input=player_input,
            world_state=world_state,
            adventure=adventure,
        )
        logger.info("Orchestrator — resolution: %r", resolution[:120] if resolution else "(none)")
        resolve_step: dict = {"step": "resolve", "resolution": resolution}
        if skill_check_event:
            resolve_step["skill_check"] = {
                "skill_name": skill_check_event.skill_name,
                "raw_roll": skill_check_event.raw_roll,
                "modifier": skill_check_event.modifier,
                "total": skill_check_event.total,
                "dc_full": skill_check_event.dc_full,
                "dc_partial": skill_check_event.dc_partial,
                "outcome": skill_check_event.outcome.value,
            }
        trace.append(resolve_step)

        dm_response = self.dm_agent.generate_dm_response(
            llm=self.llm,
            player_input=player_input,
            adventure_context=adventure_context,
            world_state=world_state_str,
            action=resolution,
        )
        logger.info("Orchestrator — DM response: %r", dm_response[:120])
        trace.append({"step": "dm_response", "response": dm_response})

        # ── Auto-process NPC turns until it's the player's turn again ─────
        # This runs after combat initiation OR after a player's combat action.
        if world_state.in_combat and not self._is_player_turn(world_state):
            npc_summaries: list[str] = []
            guard = 0
            while (
                world_state.in_combat
                and not self._is_player_turn(world_state)
                and guard < 20
            ):
                summary = self._process_npc_turn(world_state)
                if summary:
                    npc_summaries.append(summary)
                guard += 1

            if npc_summaries:
                combined = "\n".join(npc_summaries)
                logger.info(
                    "Orchestrator — %d NPC turn(s) resolved: %r",
                    len(npc_summaries), combined[:120],
                )
                npc_narration = self.dm_agent.generate_dm_response(
                    llm=self.llm,
                    player_input="[Enemy actions this round]",
                    adventure_context=adventure_context,
                    world_state=world_state.to_context_string(),
                    action=combined,
                )
                dm_response = dm_response + "\n\n" + npc_narration
                trace.append({
                    "step": "npc_turns",
                    "summaries": npc_summaries,
                    "narration": npc_narration,
                })

        logger.info("─── Turn end ───")
        return TurnResult(dm_response=dm_response, skill_check=skill_check_event, trace=trace)
