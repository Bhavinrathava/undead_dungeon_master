"""
state/world_state.py
The mutable session state. Single source of truth for everything that
changes during a game session. Gets serialized into LLM context each turn.
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Union
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CharacterStatus(str, Enum):
    ALIVE = "alive"
    UNCONSCIOUS = "unconscious"
    DEAD = "dead"


class GamePhase(str, Enum):
    EXPLORATION = "exploration"
    COMBAT = "combat"
    DIALOGUE = "dialogue"
    REST = "rest"


# ---------------------------------------------------------------------------
# Shared stat-block sub-models
# ---------------------------------------------------------------------------


class AbilityScore(BaseModel):
    score: int
    modifier: int

    def fmt(self, label: str) -> str:
        sign = "+" if self.modifier >= 0 else ""
        return f"{label} {self.score}({sign}{self.modifier})"


class AbilityScores(BaseModel):
    STR: AbilityScore
    DEX: AbilityScore
    CON: AbilityScore
    INT: AbilityScore
    WIS: AbilityScore
    CHA: AbilityScore

    def as_compact_string(self) -> str:
        return "  ".join(
            getattr(self, attr).fmt(attr)
            for attr in ("STR", "DEX", "CON", "INT", "WIS", "CHA")
        )


class SavingThrow(BaseModel):
    modifier: int
    proficient: bool = False


class SavingThrows(BaseModel):
    STR: SavingThrow
    DEX: SavingThrow
    CON: SavingThrow
    INT: SavingThrow
    WIS: SavingThrow
    CHA: SavingThrow

    def proficient_summary(self) -> str:
        """Only saving throws with proficiency, formatted for context."""
        parts = []
        for attr in ("STR", "DEX", "CON", "INT", "WIS", "CHA"):
            st = getattr(self, attr)
            if st.proficient:
                sign = "+" if st.modifier >= 0 else ""
                parts.append(f"{attr} {sign}{st.modifier}*")
        return "  ".join(parts) if parts else "none"


class SkillScore(BaseModel):
    modifier: int
    proficient: bool = False
    expertise: bool = False  # doubles proficiency bonus


class Attack(BaseModel):
    name: str
    attack_bonus: Union[int, str] = 0  # str allows "—" for shove/special
    damage: str = ""
    damage_type: str = ""
    range: str = "5 ft. melee"
    note: str = ""

    def as_compact_string(self) -> str:
        bonus = (
            f"+{self.attack_bonus}"
            if isinstance(self.attack_bonus, int) and self.attack_bonus >= 0
            else str(self.attack_bonus)
        )
        parts = [self.name, bonus]
        if self.damage:
            parts.append(f"{self.damage} {self.damage_type}".strip())
        if self.range and self.range != "5 ft. melee":
            parts.append(f"({self.range})")
        return " ".join(parts)


class Feat(BaseModel):
    name: str
    source: str = ""
    description: str = ""


class ClassFeature(BaseModel):
    name: str
    description: str = ""


class SpecialAbility(BaseModel):
    name: str
    description: str = ""


class Proficiencies(BaseModel):
    armor: list[str] = Field(default_factory=list)
    weapons: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Party models (mutable copies of PlayerCharacter during a session)
# ---------------------------------------------------------------------------


class PartyMemberState(BaseModel):
    # Identity
    name: str
    character_class: str
    subclass: str = ""
    race: str
    background: str = ""
    alignment: str = ""
    level: int = 1

    # Vitals
    max_hp: int
    current_hp: int
    ac: int
    speed: int = 30
    size: str = "Medium"
    hit_dice: str = "1d8"
    proficiency_bonus: int = 2
    initiative: int = 0          # DEX modifier
    passive_perception: int = 10

    # Status
    status: CharacterStatus = CharacterStatus.ALIVE
    conditions: list[str] = Field(default_factory=list)
    death_save_successes: int = 0
    death_save_failures: int = 0

    # Full stat block (populated from character sheet)
    ability_scores: Optional[AbilityScores] = None
    saving_throws: Optional[SavingThrows] = None
    # skills keyed by D&D skill name e.g. "Athletics", "Sleight_of_Hand"
    skills: dict[str, SkillScore] = Field(default_factory=dict)

    # Offense
    attack_bonus: int = 0        # legacy flat bonus; prefer attacks list
    damage_dice: str = "1d8"     # legacy; prefer attacks list
    attacks: list[Attack] = Field(default_factory=list)

    # Features, feats, proficiencies
    feats: list[Feat] = Field(default_factory=list)
    class_features: list[ClassFeature] = Field(default_factory=list)
    proficiencies: Optional[Proficiencies] = None
    background_feature: str = ""

    # Resources
    inventory: list[str] = Field(default_factory=list)
    equipment_worn: list[str] = Field(default_factory=list)
    spell_slots: dict[int, int] = Field(default_factory=dict)

    # Alliance
    group: str = "party"     # faction tag; default "party" for all player characters

    # Roleplay identity
    personality_traits: str = ""
    ideals: str = ""
    bonds: str = ""
    flaws: str = ""

    # -----------------------------------------------------------------------
    # Derived helpers
    # -----------------------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        return self.status != CharacterStatus.DEAD

    @property
    def is_conscious(self) -> bool:
        return self.status == CharacterStatus.ALIVE

    def proficient_skills(self) -> list[tuple[str, SkillScore]]:
        return [(k, v) for k, v in self.skills.items() if v.proficient]

    def expertise_skills(self) -> list[tuple[str, SkillScore]]:
        return [(k, v) for k, v in self.skills.items() if v.expertise]

    # -----------------------------------------------------------------------
    # Mutation helpers
    # -----------------------------------------------------------------------

    def take_damage(self, amount: int) -> None:
        self.current_hp = max(0, self.current_hp - amount)
        if self.current_hp == 0 and self.status == CharacterStatus.ALIVE:
            self.status = CharacterStatus.UNCONSCIOUS

    def modify_ac(self, delta: int) -> None:
        self.ac += delta

    def modify_attribute(self, attribute: str, delta: int) -> None:
        if not self.ability_scores:
            return
        ability = getattr(self.ability_scores, attribute.upper(), None)
        if ability is None:
            raise ValueError(f"Unknown attribute: {attribute!r}")
        ability.score += delta
        ability.modifier = (ability.score - 10) // 2

    def heal(self, amount: int) -> None:
        if self.status == CharacterStatus.DEAD:
            return
        self.current_hp = min(self.max_hp, self.current_hp + amount)
        if self.current_hp > 0:
            self.status = CharacterStatus.ALIVE
            self.death_save_successes = 0
            self.death_save_failures = 0

    # -----------------------------------------------------------------------
    # Context serialization
    # -----------------------------------------------------------------------

    def to_context_string(self) -> str:
        lines: list[str] = []

        # Header
        cls_str = (
            f"{self.character_class}/{self.subclass}"
            if self.subclass
            else self.character_class
        )
        meta = " | ".join(
            x
            for x in [self.race, self.background, self.alignment]
            if x
        )
        status_tag = (
            f" [{self.status.value.upper()}]"
            if self.status != CharacterStatus.ALIVE
            else ""
        )
        lines.append(f"- {self.name} ({cls_str} Lv{self.level}{' | ' + meta if meta else ''}){status_tag}")

        # Vitals
        cond_str = f" | Conditions: {', '.join(self.conditions)}" if self.conditions else ""
        lines.append(
            f"  HP {self.current_hp}/{self.max_hp} | AC {self.ac} | "
            f"Speed {self.speed} ft. | Init {'+' if self.initiative >= 0 else ''}{self.initiative} | "
            f"Passive Perc {self.passive_perception}{cond_str}"
        )

        # Ability scores
        if self.ability_scores:
            lines.append(f"  {self.ability_scores.as_compact_string()}")

        # Saving throws
        if self.saving_throws:
            lines.append(f"  Saving Throws (proficient): {self.saving_throws.proficient_summary()}")

        # Skills — proficient and expertise only for brevity
        prof = self.proficient_skills()
        if prof:
            skill_parts = []
            for name, sk in prof:
                sign = "+" if sk.modifier >= 0 else ""
                tag = "**" if sk.expertise else "*"
                skill_parts.append(f"{name} {sign}{sk.modifier}{tag}")
            lines.append(f"  Skills (prof/expertise): {', '.join(skill_parts)}")

        # Feats
        if self.feats:
            lines.append(f"  Feats: {' | '.join(f.name for f in self.feats)}")

        # Class features
        if self.class_features:
            lines.append(
                f"  Class Features: {' | '.join(f.name for f in self.class_features)}"
            )

        # Attacks
        if self.attacks:
            atk_str = " | ".join(a.as_compact_string() for a in self.attacks)
            lines.append(f"  Attacks: {atk_str}")

        # Inventory
        if self.inventory:
            lines.append(f"  Inventory: {', '.join(self.inventory)}")

        # Roleplay traits (condensed)
        rp_parts = []
        if self.personality_traits:
            rp_parts.append(f"Trait: {self.personality_traits}")
        if self.flaws:
            rp_parts.append(f"Flaw: {self.flaws}")
        if rp_parts:
            lines.append(f"  {' / '.join(rp_parts)}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Enemy state (mutable during combat)
# ---------------------------------------------------------------------------


class EnemyState(BaseModel):
    """
    Mutable enemy instance during combat.
    Copied from EnemyStatBlock at encounter start.
    """

    instance_id: str          # unique id e.g. "scout_1", "varek"
    name: str                 # display name
    race: str = ""
    alignment: str = ""
    group: str = ""           # faction tag — matches NPC.group; "ally" = fights for player

    # Vitals
    max_hp: int
    current_hp: int
    ac: int
    speed: int = 30
    size: str = "Medium"
    initiative: int = 0
    proficiency_bonus: int = 2

    # Legacy flat combat stats (kept for backward compat)
    attack_bonus: int = 0
    damage_dice: str = "1d6"
    damage_type: str = "slashing"

    # Full stat block
    ability_scores: Optional[AbilityScores] = None
    saving_throws: Optional[SavingThrows] = None
    skills: dict[str, SkillScore] = Field(default_factory=dict)
    passive_perception: Optional[int] = None

    # Attacks and features
    attacks: list[Attack] = Field(default_factory=list)
    feats: list[Feat] = Field(default_factory=list)
    # special_abilities: rich objects (from YAML abilities list of {name, description})
    special_abilities: list[SpecialAbility] = Field(default_factory=list)
    # abilities: legacy flat string list (backward compat — prefer special_abilities)
    abilities: list[str] = Field(default_factory=list)

    conditions: list[str] = Field(default_factory=list)
    is_alive: bool = True

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def key_skills_summary(self, top_n: int = 4) -> str:
        """Return the highest-modifier skills for context, sorted descending."""
        sorted_skills = sorted(
            self.skills.items(), key=lambda kv: kv[1].modifier, reverse=True
        )[:top_n]
        parts = []
        for name, sk in sorted_skills:
            sign = "+" if sk.modifier >= 0 else ""
            tag = "**" if sk.expertise else ("*" if sk.proficient else "")
            parts.append(f"{name} {sign}{sk.modifier}{tag}")
        return ", ".join(parts)

    def ability_names(self) -> list[str]:
        """Flat list of ability/feature names for compact context rendering."""
        names = list(self.abilities)
        names += [sa.name for sa in self.special_abilities]
        return names

    def take_damage(self, amount: int) -> None:
        self.current_hp = max(0, self.current_hp - amount)
        if self.current_hp == 0:
            self.is_alive = False

    def modify_ac(self, delta: int) -> None:
        self.ac += delta

    def modify_attribute(self, attribute: str, delta: int) -> None:
        if not self.ability_scores:
            return
        ability = getattr(self.ability_scores, attribute.upper(), None)
        if ability is None:
            raise ValueError(f"Unknown attribute: {attribute!r}")
        ability.score += delta
        ability.modifier = (ability.score - 10) // 2

    def heal(self, amount: int) -> None:
        if not self.is_alive:
            return
        self.current_hp = min(self.max_hp, self.current_hp + amount)

    def to_context_string(self) -> str:
        meta = " | ".join(x for x in [self.race, self.alignment] if x)
        cond_str = f" | [{', '.join(self.conditions)}]" if self.conditions else ""
        header = (
            f"  - {self.instance_id} ({self.name}"
            f"{' | ' + meta if meta else ''}): "
            f"{self.current_hp}/{self.max_hp} HP | AC {self.ac} | "
            f"Init {'+' if self.initiative >= 0 else ''}{self.initiative}{cond_str}"
        )
        lines = [header]

        if self.ability_scores:
            lines.append(f"    {self.ability_scores.as_compact_string()}")

        key_skills = self.key_skills_summary()
        if key_skills:
            lines.append(f"    Key Skills: {key_skills}")

        ability_names = self.ability_names()
        if ability_names:
            lines.append(f"    Abilities: {', '.join(ability_names)}")

        if self.attacks:
            atk_str = " | ".join(a.as_compact_string() for a in self.attacks)
            lines.append(f"    Attacks: {atk_str}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Combat state
# ---------------------------------------------------------------------------


class CombatState(BaseModel):
    encounter_id: str
    is_active: bool = True

    # Initiative
    turn_order: list[str] = Field(
        default_factory=list
    )  # instance_ids / player names in order
    current_turn_index: int = 0
    round_number: int = 1

    # Combatants
    enemies: list[EnemyState] = Field(default_factory=list)
    party: list[PartyMemberState] = Field(default_factory=list)

    # Log of mechanical events this combat (for LLM context)
    combat_log: list[str] = Field(default_factory=list)

    @property
    def current_actor(self) -> str:
        if not self.turn_order:
            return ""
        return self.turn_order[self.current_turn_index]

    @property
    def living_enemies(self) -> list[EnemyState]:
        return [e for e in self.enemies if e.is_alive]

    @property
    def living_party(self) -> list[PartyMemberState]:
        return [p for p in self.party if p.is_alive]

    @property
    def is_encounter_over(self) -> bool:
        return len(self.living_enemies) == 0

    def get_enemy(self, instance_id: str) -> Optional[EnemyState]:
        return next(
            (e for e in self.enemies if e.instance_id == instance_id), None
        )

    def get_party_member(self, name: str) -> Optional[PartyMemberState]:
        return next(
            (p for p in self.party if p.name.lower() == name.lower()), None
        )

    def advance_turn(self) -> str:
        """Move to next actor. Increments round when we wrap. Returns new current actor."""
        self.current_turn_index += 1
        if self.current_turn_index >= len(self.turn_order):
            self.current_turn_index = 0
            self.round_number += 1
        return self.current_actor

    def log_event(self, message: str) -> None:
        self.combat_log.append(f"[R{self.round_number}] {message}")


# ---------------------------------------------------------------------------
# World state
# ---------------------------------------------------------------------------


class WorldState(BaseModel):
    # Session metadata
    adventure_title: str = ""
    turn_count: int = 0
    phase: GamePhase = GamePhase.EXPLORATION

    # Location
    current_location_id: str = ""
    visited_location_ids: list[str] = Field(default_factory=list)

    # Party
    party: list[PartyMemberState] = Field(default_factory=list)

    # Combat (None when not in combat)
    combat: Optional[CombatState] = None

    # Progress tracking
    completed_encounter_ids: list[str] = Field(default_factory=list)
    active_quest_flags: dict[str, bool] = Field(
        default_factory=dict
    )  # {flag_id: bool}
    collected_items: list[str] = Field(default_factory=list)
    revealed_lore: list[str] = Field(default_factory=list)

    # Context window management
    history_summary: str = ""  # rolling summary of past turns injected into prompts

    # -----------------------------------------------------------------------
    # Convenience properties
    # -----------------------------------------------------------------------

    @property
    def in_combat(self) -> bool:
        return self.combat is not None and self.combat.is_active

    @property
    def living_party(self) -> list[PartyMemberState]:
        return [p for p in self.party if p.is_alive]

    @property
    def party_wiped(self) -> bool:
        return all(not p.is_alive for p in self.party)

    # -----------------------------------------------------------------------
    # Party helpers
    # -----------------------------------------------------------------------

    def get_player(self, name: str) -> Optional[PartyMemberState]:
        return next(
            (p for p in self.party if p.name.lower() == name.lower()), None
        )

    def add_to_inventory(self, player_name: str, item: str) -> bool:
        player = self.get_player(player_name)
        if player:
            player.inventory.append(item)
            return True
        return False

    def remove_from_inventory(self, player_name: str, item: str) -> bool:
        """Remove the first matching item (case-insensitive) from a player's inventory.

        Returns True if the item was found and removed, False otherwise.
        """
        player = self.get_player(player_name)
        if player is None:
            return False
        item_lower = item.lower()
        for i, inv_item in enumerate(player.inventory):
            if inv_item.lower() == item_lower:
                player.inventory.pop(i)
                return True
        return False

    # -----------------------------------------------------------------------
    # Location helpers
    # -----------------------------------------------------------------------

    def move_to(self, location_id: str) -> None:
        self.current_location_id = location_id
        if location_id not in self.visited_location_ids:
            self.visited_location_ids.append(location_id)

    # -----------------------------------------------------------------------
    # Combat helpers
    # -----------------------------------------------------------------------

    def start_combat(self, combat: CombatState) -> None:
        self.combat = combat
        self.phase = GamePhase.COMBAT

    def end_combat(self) -> None:
        if self.combat:
            self.completed_encounter_ids.append(self.combat.encounter_id)
            self.combat.is_active = False
            self.combat = None
        self.phase = GamePhase.EXPLORATION

    # -----------------------------------------------------------------------
    # LLM context serialization
    # -----------------------------------------------------------------------

    def to_context_string(self) -> str:
        """
        Serialize world state into a compact string for injection
        into the DM Agent's system prompt.
        """
        lines = [
            f"## World State (Turn {self.turn_count})",
            f"Phase: {self.phase.value}",
            f"Location: {self.current_location_id}",
            f"Visited: {', '.join(self.visited_location_ids) or 'none'}",
            "",
            "### Party",
        ]

        for p in self.party:
            lines.append(p.to_context_string())

        if self.in_combat:
            lines += [
                "",
                "### Active Combat",
                f"Encounter: {self.combat.encounter_id}",
                f"Round: {self.combat.round_number}  |  Current actor: {self.combat.current_actor}",
                f"Turn order: {' -> '.join(self.combat.turn_order)}",
            ]
            if self.combat.living_party:
                lines.append("Party:")
                for p in self.combat.living_party:
                    cond_str = f" | [{', '.join(p.conditions)}]" if p.conditions else ""
                    status_tag = (
                        f" [{p.status.value.upper()}]"
                        if p.status != CharacterStatus.ALIVE
                        else ""
                    )
                    lines.append(
                        f"  - {p.name}{status_tag}: "
                        f"{p.current_hp}/{p.max_hp} HP | AC {p.ac}{cond_str}"
                    )
            lines.append("Living enemies:")
            for e in self.combat.living_enemies:
                lines.append(e.to_context_string())

            if self.combat.combat_log:
                lines += ["", "Recent combat events:"]
                for entry in self.combat.combat_log[-5:]:  # last 5 events only
                    lines.append(f"  {entry}")

        if self.active_quest_flags:
            lines += ["", "### Quest Flags"]
            for flag, value in self.active_quest_flags.items():
                lines.append(f"  {flag}: {value}")

        if self.history_summary:
            lines += ["", "### Session Summary", self.history_summary]

        return "\n".join(lines)
