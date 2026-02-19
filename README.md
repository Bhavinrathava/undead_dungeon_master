# Undead Dungeon Master

This is an AI Agentic System for DMing a DnD Game. 

## Project Structure

```
ai_dungeon_master/
│
├── main.py                        # streamlit entry point
├── requirements.txt
├── .env.example
│
├── adventure/                     # READ-ONLY adventure content
│   ├── __init__.py
│   ├── models.py                  # Adventure, Location, Encounter, NPC, EnemyStatBlock, PlayerCharacter
│   └── loader.py                  # loads YAML → Adventure model (PDF later)
│
├── state/                         # MUTABLE session state
│   ├── __init__.py
│   └── world_state.py             # WorldState, CombatState — serializes to LLM context string
│
├── combat/                        # Pure Python, zero LLM calls
│   ├── __init__.py
│   ├── dice.py                    # roll(), roll_d20(), crit detection
│   └── engine.py                  # start_encounter(), resolve_attack(), next_turn(), end_encounter()
│
├── agent/                         # All LLM interaction lives here
│   ├── __init__.py
│   ├── prompts.py                 # system prompt builder — DM persona + world state + adventure context
│   ├── intent_classifier.py       # classifies input → COMBAT_ACTION | DIALOGUE | MOVE | SKILL_CHECK | EXPLORE
│   └── dm_agent.py                # main agent — takes input + state, calls combat engine if needed, returns narration
│
├── session/                       # Orchestration layer
│   ├── __init__.py
│   └── session_manager.py         # main loop — routes input through modules, updates state, returns response
│
├── ui/                            # Streamlit only
│   ├── __init__.py
│   └── app.py                     # chat interface + party status sidebar
│
├── data/
│   └── adventures/
│       └── starter_adventure.yaml # your first adventure doc
│
└── tests/
    ├── test_dice.py
    ├── test_combat.py
    └── test_state.py
```

