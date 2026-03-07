from __future__ import annotations
from typing import TYPE_CHECKING

from ai_dungeon_master.dice.dice_engine import DiceEngine

if TYPE_CHECKING:
    from ai_dungeon_master.state.world_state import WorldState


class CombatEngine:
    def __init__(self, world_state: WorldState, dice_engine: DiceEngine = None):
        self.ws = world_state
        self.dice = dice_engine or DiceEngine()

    # ------------------------------------------------------------------
    # Participant lookup
    # ------------------------------------------------------------------

    def get_participant(self, target_id: str):
        combat = self.ws.combat
        return combat.get_party_member(target_id) or combat.get_enemy(target_id)

    def _is_defeated(self, target_id: str) -> bool:
        from ai_dungeon_master.state.world_state import EnemyState
        p = self.get_participant(target_id)
        if p is None:
            return False
        if isinstance(p, EnemyState):
            return not p.is_alive
        # PartyMemberState — defeated when unconscious or dead
        return not p.is_conscious

    # ------------------------------------------------------------------
    # Dice / resolution
    # ------------------------------------------------------------------

    def resolve_attack(
        self,
        attacker_hit_modifier: int,
        defender_ac: int,
        dmg_sides: int,
        dmg_count: int = 1,
        dmg_modifier: int = 0,
    ) -> dict:
        """Resolve a single attack action.

        Args:
            attacker_hit_modifier: Flat bonus added to the d20 attack roll.
            defender_ac:           Defender's Armour Class threshold.
            dmg_sides:             Faces on each damage die (e.g. 6 for d6).
            dmg_count:             Number of damage dice.
            dmg_modifier:          Flat bonus added to the damage roll.

        Returns:
            {
                "result":     "hit" | "miss" | "critical_hit",
                "attack_roll": raw d20 value (before modifier),
                "damage":      damage dealt (0 on a miss),
            }
        """
        attack_roll = self.dice.roll(sides=20)

        # Natural 20 is a critical hit — double the damage dice
        if attack_roll == 20:
            damage = self.dice.roll(sides=dmg_sides, count=dmg_count * 2, modifier=dmg_modifier)
            return {"result": "critical_hit", "attack_roll": attack_roll, "damage": damage}

        # Natural 1 always misses
        if attack_roll == 1 or (attack_roll + attacker_hit_modifier) < defender_ac:
            return {"result": "miss", "attack_roll": attack_roll, "damage": 0}

        damage = self.dice.roll(sides=dmg_sides, count=dmg_count, modifier=dmg_modifier)
        return {"result": "hit", "attack_roll": attack_roll, "damage": damage}

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def execute(self, tool_call: dict) -> dict:
        tool = tool_call["tool"]

        if tool == "apply_damage":
            p = self.get_participant(tool_call["target_id"])
            p.take_damage(tool_call["amount"])
            self.ws.combat.log_event(f"{tool_call['target_id']} took {tool_call['amount']} damage")

        elif tool == "apply_healing":
            p = self.get_participant(tool_call["target_id"])
            p.heal(tool_call["amount"])

        elif tool == "add_condition":
            p = self.get_participant(tool_call["target_id"])
            if tool_call["condition"] not in p.conditions:
                p.conditions.append(tool_call["condition"])

        elif tool == "modify_ac":
            p = self.get_participant(tool_call["target_id"])
            p.modify_ac(tool_call["delta"])

        elif tool == "advance_turn":
            self.ws.combat.advance_turn()

        elif tool == "end_combat":
            self.ws.end_combat()

        return self.post_action_check(tool_call.get("target_id"))

    def post_action_check(self, target_id: str = None) -> dict:
        return {
            "target_defeated": self._is_defeated(target_id) if target_id else False,
            "encounter_over": self.ws.combat.is_encounter_over if self.ws.in_combat else True,
            "party_wiped": self.ws.party_wiped,
        }
