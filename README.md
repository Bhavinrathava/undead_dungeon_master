# Undead Dungeon Master
An AI Agentic System for DMing a DnD Game.

---

## Architecture Overview

```
Player Input (Streamlit UI)
        │
        ▼
Session Manager          ← orchestrates everything
    │       │
    │       ▼
    │   Intent Classifier   ← what is the player trying to do?
    │       │
    │   ┌───┴────────────────────────┐
    │   ▼                            ▼
    │ Combat Engine            DM Agent (LLM)
    │ (dice + resolution)      (narration + NPC dialogue)
    │       │                        │
    │       └───────────┬────────────┘
    │                   ▼
    └──────────►  World State  ◄──── Adventure Loader (read-only)
```

---

## Project Structure

```
ai_dungeon_master/
│
├── main.py
├── requirements.txt
├── .env.example
│
├── adventure/
│   ├── __init__.py
│   ├── models.py
│   └── loader.py
│
├── state/
│   ├── __init__.py
│   └── world_state.py
│
├── combat/
│   ├── __init__.py
│   ├── dice.py
│   └── engine.py
│
├── agent/
│   ├── __init__.py
│   ├── prompts.py
│   ├── intent_classifier.py
│   └── dm_agent.py
│
├── session/
│   ├── __init__.py
│   └── session_manager.py
│
├── ui/
│   ├── __init__.py
│   └── app.py
│
├── data/
│   └── adventures/
│       └── starter_adventure.yaml
│
└── tests/
    ├── test_dice.py
    ├── test_combat.py
    └── test_state.py
```

---

## Module Reference

### `main.py`
Entry point. Imports and calls `ui.app.run_app()`. Run with `streamlit run main.py`.

---

### `adventure/models.py`
Pydantic models for all **read-only** adventure content. Loaded once at session start, never mutated during play.

| Class | Purpose |
|---|---|
| `EnemyStatBlock` | Enemy template: name, HP, AC, attack bonus, damage dice, abilities, loot |
| `NPC` | NPC definition: name, role, personality, knowledge list, dialogue hints, secret |
| `Encounter` | One encounter: trigger type, list of enemies, success/failure outcomes, XP reward |
| `Location` | One location: description, connections to other locations, NPCs, encounters, lore, items |
| `PlayerCharacter` | Player definition: class, race, level, HP, AC, inventory, spell slots |
| `Adventure` | Root model: title, setting, premise, all locations, party, win/fail conditions, DM notes |

---

### `adventure/loader.py`
Reads adventure documents and returns a populated `Adventure` model.

| Method | Purpose |
|---|---|
| `load_from_yaml(path)` | Reads a `.yaml` file, parses it, returns `Adventure` |
| `load_from_dict(data)` | Constructs `Adventure` from a raw dict (useful for tests) |
| `load_from_pdf(path)` | *(Phase 2)* PDF ingestion via PyMuPDF + LLM extraction — not yet implemented |

---

### `state/world_state.py`
All **mutable** session state. The single source of truth for everything that changes during play. Every module reads from and writes to this.

| Class | Purpose |
|---|---|
| `CharacterStatus` | Enum: `ALIVE`, `UNCONSCIOUS`, `DEAD` |
| `GamePhase` | Enum: `EXPLORATION`, `COMBAT`, `DIALOGUE`, `REST` |
| `PartyMemberState` | Live party member: current HP, status, conditions, inventory, death saves. Methods: `take_damage()`, `heal()` |
| `EnemyState` | Live enemy instance during combat: current HP, conditions, `instance_id` for disambiguation (e.g. `goblin_1`). Methods: `take_damage()`, `heal()` |
| `CombatState` | Active combat tracker: turn order, current actor, round number, enemy list, combat log. Methods: `advance_turn()`, `log_event()`, `get_enemy()`. Properties: `current_actor`, `living_enemies`, `is_encounter_over` |
| `WorldState` | Root state object. Tracks location, party, active combat, quest flags, collected items, history summary. Methods: `move_to()`, `start_combat()`, `end_combat()`, `get_player()`, `add_to_inventory()`, `to_context_string()` |

`to_context_string()` is the key method — it serializes the full world state into a compact string injected into every LLM prompt.

---

### `combat/dice.py`
Pure dice utilities. No state, no LLM, no side effects.

| Function | Purpose |
|---|---|
| `roll(notation)` | Rolls from D&D notation string e.g. `"2d6+3"`. Returns `(total, individual_rolls)` |
| `roll_d20(modifier)` | Rolls a d20 with modifier. Returns `(total, raw_roll)` |
| `is_critical_hit(raw_roll)` | Returns `True` if raw roll is 20 |
| `is_critical_miss(raw_roll)` | Returns `True` if raw roll is 1 |

---

### `combat/engine.py`
All mechanical combat resolution. No LLM calls. Returns structured result objects that the DM Agent then narrates.

| Method | Purpose |
|---|---|
| `start_encounter(encounter, state)` | Rolls initiative for all combatants, creates and returns a `CombatState` |
| `resolve_player_attack(attacker, target_name, state)` | Rolls attack (d20 + bonus vs AC), rolls damage on hit, updates enemy HP in state. Returns `AttackResult` |
| `resolve_enemy_attack(enemy, target_name, state)` | Rolls enemy attack against a player, updates player HP in state. Returns `AttackResult` |
| `run_enemy_turn(state)` | Runs all enemy actions for the current enemy turn. Picks targets, calls `resolve_enemy_attack()`. Returns list of `AttackResult` |
| `advance_turn(state)` | Moves to the next actor in initiative order. Increments round counter when order wraps |
| `end_encounter(state)` | Marks combat over, collects loot from defeated enemies, calls `state.end_combat()` |

**Result dataclasses returned by engine (consumed by DM Agent for narration):**

| Dataclass | Fields |
|---|---|
| `AttackResult` | `attacker`, `target`, `hit`, `critical`, `raw_roll`, `total_roll`, `damage`, `target_hp_remaining`, `target_defeated` |
| `InitiativeResult` | `turn_order` (list of names), `rolls` (dict of name → roll) |

---

### `agent/prompts.py`
Builds the system prompt sent to the LLM on every turn. No LLM calls here — pure string construction.

| Function | Purpose |
|---|---|
| `build_system_prompt(adventure, state)` | Assembles full system prompt: DM persona + adventure setting/premise + current location description + relevant lore + world state string |
| `build_combat_narration_prompt(attack_results, state)` | Builds a focused prompt for narrating combat outcomes from mechanical results |
| `get_location_context(location_id, adventure)` | Extracts the relevant location block (description, lore, NPCs) for the current location |

---

### `agent/intent_classifier.py`
Classifies raw player input into one of five intents so the session manager knows how to route it.

| Item | Purpose |
|---|---|
| `PlayerIntent` | Enum: `COMBAT_ACTION`, `DIALOGUE`, `MOVE`, `SKILL_CHECK`, `EXPLORE` |
| `classify(player_input, state)` | Takes raw text + world state, returns a `PlayerIntent`. MVP uses keyword/regex matching. Phase 2 upgrades to a lightweight LLM call |

**Classification logic (MVP — regex/keyword):**

| Intent | Trigger keywords |
|---|---|
| `COMBAT_ACTION` | "attack", "hit", "strike", "shoot", "cast [spell] at", "stab", "swing" |
| `DIALOGUE` | "say", "ask", "tell", "talk to", "speak to", "shout" |
| `MOVE` | "go to", "move to", "travel", "head to", "walk", "ride" |
| `SKILL_CHECK` | "search", "investigate", "perception", "check", "roll", "examine", "look for" |
| `EXPLORE` | anything else — free-form action |

---

### `agent/dm_agent.py`
The only module that calls the LLM. Receives player input + world state + adventure, returns narration text.

| Method | Purpose |
|---|---|
| `respond(player_input, intent, combat_results, adventure, state)` | Core method. Builds prompt via `prompts.py`, calls LLM, returns narration string. `combat_results` is `None` outside combat — the agent narrates the mechanical outcome when provided |
| `narrate_encounter_start(encounter, state, adventure)` | Called when a new encounter triggers. Returns scene-setting narration before combat begins |
| `narrate_encounter_end(encounter, loot, state, adventure)` | Called after `end_encounter()`. Narrates victory, describes loot, transitions scene |
| `narrate_npc_dialogue(npc, player_input, state, adventure)` | Voices an NPC response in character using NPC personality, knowledge, and secrets from adventure data |

**LLM call contract:** every call receives `system = build_system_prompt(...)` + the last N turns of chat history + the current player input. Combat narration calls additionally receive the `AttackResult` data serialized into the user message.

---

### `session/session_manager.py`
The orchestrator. The only module that touches everything else. Manages the main game loop.

| Method | Purpose |
|---|---|
| `__init__(adventure_path)` | Loads adventure via `AdventureLoader`, initializes `WorldState` from party + starting location |
| `process_input(player_input)` | Main entry point per turn. Classifies intent → routes through combat engine if needed → calls DM Agent → updates state → returns narration string |
| `_handle_combat_action(player_input)` | Called when intent is `COMBAT_ACTION`. Parses target, calls `engine.resolve_player_attack()`, then `engine.run_enemy_turn()`, then asks DM Agent to narrate results |
| `_handle_dialogue(player_input)` | Identifies which NPC the player is addressing, calls `dm_agent.narrate_npc_dialogue()` |
| `_handle_move(player_input)` | Validates the destination is connected to current location, calls `state.move_to()`, checks if new location triggers an encounter |
| `_handle_explore(player_input)` | Passes directly to DM Agent for free narration |
| `_check_encounter_trigger(location_id)` | After any movement or action, checks if current location has an untriggered `on_enter` encounter and fires it |
| `_update_history_summary()` | Periodically compresses old turn history into `state.history_summary` to keep LLM context window manageable |

**Turn flow:**
```
process_input(text)
  → classify intent
  → if COMBAT_ACTION and in_combat:
      engine.resolve_player_attack()
      engine.run_enemy_turn()
      engine.advance_turn()
      if encounter over: engine.end_encounter()
  → dm_agent.respond(input, intent, combat_results, adventure, state)
  → state.turn_count += 1
  → return narration
```

---

### `ui/app.py`
Streamlit interface. Thin layer — all logic lives in session manager.

| Component | Purpose |
|---|---|
| `run_app()` | Entry point called by `main.py`. Initializes session state, renders layout |
| Chat window | Main column. Displays full message history. Player input at bottom via `st.chat_input` |
| Party status sidebar | Right sidebar. Displays each party member's name, class, HP bar, status, and conditions. Updates every turn |
| On player input | Calls `session_manager.process_input(text)`, appends player message + DM response to chat history, rerenders |

---

### `data/adventures/starter_adventure.yaml`
The adventure document for **The Medallion of Hodenfort**. Defines the full adventure in YAML matching the `Adventure` model schema.

| Section | Contents |
|---|---|
| `title`, `setting`, `premise` | Tone, world context, opening narration |
| `dm_notes` | DM-only context (Damien's secret, pacing notes) — injected into system prompt, never shown to players |
| `party` | Default party of 3: Aldric (Fighter), Sable (Rogue), Voss (Cleric) |
| `locations` | 5 locations: `svengard` → `the_road` → `ambush_site` → `forest_trail` → `ninger_hideout` |
| Encounters | 2 encounters: `ninger_ambush` (4 enemies incl. Varek) and `hideout_guards` (3 scouts) |

---

### `tests/`

| File | What it tests |
|---|---|
| `test_dice.py` | `roll()` notation parsing, modifier math, crit detection, edge cases |
| `test_combat.py` | `start_encounter()` initiative rolling, `resolve_player_attack()` hit/miss/crit logic, HP updates, `end_encounter()` loot collection |
| `test_state.py` | `WorldState` transitions: `start_combat()`, `end_combat()`, `move_to()`, `take_damage()` / `heal()`, `to_context_string()` output |