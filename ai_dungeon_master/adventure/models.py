"""
adventure/models.py
Read-only Pydantic models for adventure content.
Loaded once at session start, never mutated during play.
"""

from __future__ import annotations
from pydantic import BaseModel, Field


class EnemyAbility(BaseModel):
    """A named special ability on an enemy stat block."""

    name: str
    description: str = ""


class EnemyStatBlock(BaseModel):
    """Enemy template — the static definition used to spawn EnemyState instances."""

    name: str
    hp: int
    ac: int
    attack_bonus: int = 0
    damage_dice: str = "1d6"
    damage_type: str = "slashing"
    group: str = ""         # faction tag for grouping in combat
    abilities: list[EnemyAbility] = Field(default_factory=list)
    loot: list[str] = Field(default_factory=list)
    description: str = ""


class NPCSecret(BaseModel):
    """Structured secret metadata for an NPC — used by the resolver for skill checks."""

    text: str = ""
    concealment_reason: str = ""
    reveal_threshold: int = 20
    partial_reveal_threshold: int = 10
    skill_type: list[str] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)


class NPC(BaseModel):
    """A named non-player character with personality, knowledge, and secrets."""

    name: str
    role: str
    personality: str
    knowledge: list[str] = Field(default_factory=list)
    dialogue_hints: str = ""
    secret: NPCSecret | None = None

    # Alliance / faction
    group: str = ""         # faction tag e.g. "ninger_brotherhood", "city_guard"
    ally: bool = False      # True → NPC joins the player team when combat starts

    # Combat stats (used when this NPC is dragged into combat)
    hp: int = 8
    ac: int = 10
    attack_bonus: int = 0
    damage_dice: str = "1d4"
    damage_type: str = "bludgeoning"
    initiative_modifier: int = 0  # DEX modifier for initiative rolls


class Encounter(BaseModel):
    """One discrete encounter: enemies, trigger condition, and outcomes."""

    id: str
    name: str
    trigger: str  # e.g. "on_enter", "on_examine", "manual"
    description: str = ""
    success_outcome: str = ""
    failure_outcome: str = ""
    xp_reward: int = 0
    is_optional: bool = False
    enemies: list[EnemyStatBlock] = Field(default_factory=list)


class Location(BaseModel):
    """One discrete location in the adventure."""

    id: str
    name: str
    description: str
    connections: list[str] = Field(default_factory=list)
    npcs: list[NPC] = Field(default_factory=list)
    encounters: list[Encounter] = Field(default_factory=list)
    lore: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    is_starting_location: bool = False


class PlayerCharacter(BaseModel):
    """Player character definition — static template, not mutable session state."""

    name: str
    character_class: str
    race: str
    level: int = 1
    max_hp: int
    current_hp: int
    ac: int
    attack_bonus: int = 0
    damage_dice: str = "1d4"
    inventory: list[str] = Field(default_factory=list)
    spell_slots: dict[int, int] = Field(default_factory=dict)


class Adventure(BaseModel):
    """Root adventure document — all read-only content for one adventure."""

    title: str
    setting: str
    premise: str
    win_condition: str = ""
    fail_condition: str = ""
    dm_notes: str = ""
    party: list[PlayerCharacter] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)

    # -----------------------------------------------------------------------
    # Convenience helpers
    # -----------------------------------------------------------------------

    def get_location(self, location_id: str) -> Location | None:
        return next((loc for loc in self.locations if loc.id == location_id), None)

    @property
    def starting_location(self) -> Location | None:
        return next(
            (loc for loc in self.locations if loc.is_starting_location),
            self.locations[0] if self.locations else None,
        )
