"""
tests/test_adventure_loader.py
Tests for adventure/loader.py and adventure/models.py.
"""

import pytest
from pathlib import Path
from pydantic import ValidationError

from adventure import AdventureLoader, Adventure, Location, Encounter, NPC, EnemyStatBlock, PlayerCharacter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STARTER_YAML = Path(__file__).parent.parent / "data" / "adventures" / "starter_adventure.yaml"

MINIMAL_DICT = {
    "title": "Test Adventure",
    "setting": "A blank void.",
    "premise": "You exist.",
}

FULL_DICT = {
    "title": "Full Test Adventure",
    "setting": "A dark forest.",
    "premise": "Something lurks.",
    "win_condition": "Survive.",
    "fail_condition": "Die.",
    "dm_notes": "The monster is afraid of light.",
    "party": [
        {
            "name": "Brynn",
            "character_class": "Ranger",
            "race": "Elf",
            "level": 2,
            "max_hp": 20,
            "current_hp": 20,
            "ac": 14,
            "attack_bonus": 4,
            "damage_dice": "1d8+2",
            "inventory": ["longbow", "arrows x20"],
            "spell_slots": {},
        }
    ],
    "locations": [
        {
            "id": "camp",
            "name": "Base Camp",
            "description": "A small clearing with a dying fire.",
            "is_starting_location": True,
            "connections": ["dark_forest"],
            "lore": ["This camp was used by hunters."],
            "items": ["lantern", "rope"],
            "npcs": [
                {
                    "name": "Old Maren",
                    "role": "guide",
                    "personality": "Gruff but reliable.",
                    "knowledge": ["The monster fears fire."],
                    "dialogue_hints": "Speaks in short sentences.",
                    "secret": "She has seen it before and ran.",
                }
            ],
            "encounters": [],
        },
        {
            "id": "dark_forest",
            "name": "The Dark Forest",
            "description": "Dense pine trees. No moonlight reaches the ground.",
            "connections": ["camp"],
            "lore": [],
            "items": [],
            "npcs": [],
            "encounters": [
                {
                    "id": "beast_attack",
                    "name": "Beast Attack",
                    "trigger": "on_enter",
                    "description": "Something charges from the shadows.",
                    "success_outcome": "The beast retreats.",
                    "failure_outcome": "The party is mauled.",
                    "xp_reward": 100,
                    "is_optional": False,
                    "enemies": [
                        {
                            "name": "Shadow Beast",
                            "hp": 15,
                            "ac": 12,
                            "attack_bonus": 3,
                            "damage_dice": "1d8+1",
                            "damage_type": "slashing",
                            "abilities": ["Darkvision"],
                            "loot": ["beast hide"],
                            "description": "A large, dark creature with pale eyes.",
                        }
                    ],
                }
            ],
        },
    ],
}


# ---------------------------------------------------------------------------
# load_from_dict — happy path
# ---------------------------------------------------------------------------


class TestLoadFromDict:
    def test_minimal_dict_loads(self):
        adv = AdventureLoader.load_from_dict(MINIMAL_DICT)
        assert isinstance(adv, Adventure)
        assert adv.title == "Test Adventure"

    def test_optional_fields_default(self):
        adv = AdventureLoader.load_from_dict(MINIMAL_DICT)
        assert adv.win_condition == ""
        assert adv.fail_condition == ""
        assert adv.dm_notes == ""
        assert adv.party == []
        assert adv.locations == []

    def test_full_dict_loads(self):
        adv = AdventureLoader.load_from_dict(FULL_DICT)
        assert adv.title == "Full Test Adventure"
        assert adv.win_condition == "Survive."
        assert adv.dm_notes == "The monster is afraid of light."

    def test_party_parsed(self):
        adv = AdventureLoader.load_from_dict(FULL_DICT)
        assert len(adv.party) == 1
        brynn = adv.party[0]
        assert isinstance(brynn, PlayerCharacter)
        assert brynn.name == "Brynn"
        assert brynn.character_class == "Ranger"
        assert brynn.level == 2
        assert brynn.max_hp == 20
        assert "longbow" in brynn.inventory

    def test_locations_parsed(self):
        adv = AdventureLoader.load_from_dict(FULL_DICT)
        assert len(adv.locations) == 2
        camp = adv.locations[0]
        assert isinstance(camp, Location)
        assert camp.id == "camp"
        assert camp.is_starting_location is True
        assert "dark_forest" in camp.connections

    def test_npc_parsed(self):
        adv = AdventureLoader.load_from_dict(FULL_DICT)
        camp = adv.locations[0]
        assert len(camp.npcs) == 1
        npc = camp.npcs[0]
        assert isinstance(npc, NPC)
        assert npc.name == "Old Maren"
        assert npc.role == "guide"
        assert "The monster fears fire." in npc.knowledge
        assert npc.secret != ""

    def test_encounter_parsed(self):
        adv = AdventureLoader.load_from_dict(FULL_DICT)
        forest = adv.locations[1]
        assert len(forest.encounters) == 1
        enc = forest.encounters[0]
        assert isinstance(enc, Encounter)
        assert enc.id == "beast_attack"
        assert enc.trigger == "on_enter"
        assert enc.xp_reward == 100
        assert enc.is_optional is False

    def test_enemy_stat_block_parsed(self):
        adv = AdventureLoader.load_from_dict(FULL_DICT)
        enc = adv.locations[1].encounters[0]
        assert len(enc.enemies) == 1
        enemy = enc.enemies[0]
        assert isinstance(enemy, EnemyStatBlock)
        assert enemy.name == "Shadow Beast"
        assert enemy.hp == 15
        assert enemy.ac == 12
        assert "Darkvision" in enemy.abilities
        assert "beast hide" in enemy.loot


# ---------------------------------------------------------------------------
# load_from_dict — validation errors
# ---------------------------------------------------------------------------


class TestLoadFromDictValidation:
    def test_missing_title_raises(self):
        with pytest.raises(ValidationError):
            AdventureLoader.load_from_dict({"setting": "x", "premise": "y"})

    def test_missing_setting_raises(self):
        with pytest.raises(ValidationError):
            AdventureLoader.load_from_dict({"title": "T", "premise": "y"})

    def test_missing_premise_raises(self):
        with pytest.raises(ValidationError):
            AdventureLoader.load_from_dict({"title": "T", "setting": "x"})

    def test_invalid_party_member_raises(self):
        bad = {**MINIMAL_DICT, "party": [{"name": "X"}]}  # missing required fields
        with pytest.raises(ValidationError):
            AdventureLoader.load_from_dict(bad)

    def test_invalid_enemy_hp_type_raises(self):
        bad = {
            **MINIMAL_DICT,
            "locations": [
                {
                    "id": "room",
                    "name": "Room",
                    "description": "A room.",
                    "encounters": [
                        {
                            "id": "fight",
                            "name": "Fight",
                            "trigger": "on_enter",
                            "enemies": [
                                {
                                    "name": "Goblin",
                                    "hp": "not_a_number",  # should be int
                                    "ac": 12,
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        with pytest.raises(ValidationError):
            AdventureLoader.load_from_dict(bad)


# ---------------------------------------------------------------------------
# load_from_yaml — starter adventure
# ---------------------------------------------------------------------------


class TestLoadFromYaml:
    def test_loads_starter_adventure(self):
        adv = AdventureLoader.load_from_yaml(STARTER_YAML)
        assert isinstance(adv, Adventure)
        assert adv.title == "The Medallion of Hodenfort"

    def test_all_locations_present(self):
        adv = AdventureLoader.load_from_yaml(STARTER_YAML)
        ids = [loc.id for loc in adv.locations]
        assert ids == ["svengard", "the_road", "ambush_site", "forest_trail", "ninger_hideout"]

    def test_starting_location_is_svengard(self):
        adv = AdventureLoader.load_from_yaml(STARTER_YAML)
        assert adv.starting_location is not None
        assert adv.starting_location.id == "svengard"

    def test_party_loaded(self):
        adv = AdventureLoader.load_from_yaml(STARTER_YAML)
        assert len(adv.party) == 1
        assert adv.party[0].name == "Aldric"
        assert adv.party[0].character_class == "Fighter"

    def test_ambush_encounter_has_four_enemies(self):
        adv = AdventureLoader.load_from_yaml(STARTER_YAML)
        ambush_site = adv.get_location("ambush_site")
        assert ambush_site is not None
        enc = ambush_site.encounters[0]
        assert enc.id == "ninger_ambush"
        assert len(enc.enemies) == 4

    def test_varek_stat_block(self):
        adv = AdventureLoader.load_from_yaml(STARTER_YAML)
        enc = adv.get_location("ambush_site").encounters[0]
        varek = next(e for e in enc.enemies if e.name == "Varek")
        assert varek.hp == 18
        assert varek.ac == 15
        assert varek.attack_bonus == 6

    def test_hideout_encounter_has_three_enemies(self):
        adv = AdventureLoader.load_from_yaml(STARTER_YAML)
        hideout = adv.get_location("ninger_hideout")
        enc = hideout.encounters[0]
        assert enc.id == "hideout_guards"
        assert len(enc.enemies) == 3

    def test_svengard_npc_is_damien(self):
        adv = AdventureLoader.load_from_yaml(STARTER_YAML)
        svengard = adv.get_location("svengard")
        assert len(svengard.npcs) == 1
        assert svengard.npcs[0].name == "Damien"

    def test_location_connections(self):
        adv = AdventureLoader.load_from_yaml(STARTER_YAML)
        assert "the_road" in adv.get_location("svengard").connections
        assert "svengard" in adv.get_location("the_road").connections
        assert "ambush_site" in adv.get_location("the_road").connections

    def test_lore_is_list_of_strings(self):
        adv = AdventureLoader.load_from_yaml(STARTER_YAML)
        for loc in adv.locations:
            assert isinstance(loc.lore, list)
            for entry in loc.lore:
                assert isinstance(entry, str)

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            AdventureLoader.load_from_yaml("data/adventures/nonexistent.yaml")

    def test_wrong_extension_raises(self, tmp_path):
        bad_file = tmp_path / "adventure.txt"
        bad_file.write_text("title: oops")
        with pytest.raises(ValueError, match="Expected a .yaml/.yml file"):
            AdventureLoader.load_from_yaml(bad_file)

    def test_accepts_yml_extension(self, tmp_path):
        yml_file = tmp_path / "adventure.yml"
        yml_file.write_text("title: T\nsetting: s\npremise: p\n")
        adv = AdventureLoader.load_from_yaml(yml_file)
        assert adv.title == "T"


# ---------------------------------------------------------------------------
# load_from_pdf — phase 2 stub
# ---------------------------------------------------------------------------


class TestLoadFromPdf:
    def test_raises_not_implemented(self):
        with pytest.raises(NotImplementedError):
            AdventureLoader.load_from_pdf("some/adventure.pdf")

    def test_error_message_mentions_phase_2(self):
        with pytest.raises(NotImplementedError, match="Phase 2"):
            AdventureLoader.load_from_pdf("some/adventure.pdf")


# ---------------------------------------------------------------------------
# Adventure model helpers
# ---------------------------------------------------------------------------


class TestAdventureHelpers:
    def test_get_location_returns_correct_location(self):
        adv = AdventureLoader.load_from_dict(FULL_DICT)
        loc = adv.get_location("camp")
        assert loc is not None
        assert loc.name == "Base Camp"

    def test_get_location_returns_none_for_unknown_id(self):
        adv = AdventureLoader.load_from_dict(FULL_DICT)
        assert adv.get_location("nonexistent") is None

    def test_starting_location_flagged_location(self):
        adv = AdventureLoader.load_from_dict(FULL_DICT)
        assert adv.starting_location.id == "camp"

    def test_starting_location_falls_back_to_first(self):
        # No location has is_starting_location=True — should fall back to first
        data = {
            **MINIMAL_DICT,
            "locations": [
                {"id": "only", "name": "Only", "description": "Only location."}
            ],
        }
        adv = AdventureLoader.load_from_dict(data)
        assert adv.starting_location.id == "only"

    def test_starting_location_none_when_no_locations(self):
        adv = AdventureLoader.load_from_dict(MINIMAL_DICT)
        assert adv.starting_location is None

    def test_enemy_defaults(self):
        data = {
            **MINIMAL_DICT,
            "locations": [
                {
                    "id": "room",
                    "name": "Room",
                    "description": "A room.",
                    "encounters": [
                        {
                            "id": "fight",
                            "name": "Fight",
                            "trigger": "manual",
                            "enemies": [{"name": "Goblin", "hp": 5, "ac": 11}],
                        }
                    ],
                }
            ],
        }
        adv = AdventureLoader.load_from_dict(data)
        goblin = adv.locations[0].encounters[0].enemies[0]
        assert goblin.attack_bonus == 0
        assert goblin.damage_dice == "1d6"
        assert goblin.damage_type == "slashing"
        assert goblin.abilities == []
        assert goblin.loot == []
        assert goblin.description == ""
