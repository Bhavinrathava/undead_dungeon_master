import json
import logging
from typing import TypedDict

from ai_dungeon_master.agent.llm_client import LLMClient

logger = logging.getLogger(__name__)

VALID_ACTIONS = ["ATTACK", "TALK", "TALK_SKILL_CHECK", "NARRATOR_INTERACTION"]

SYSTEM_PROMPT = """\
You are an intent classifier for a dungeon master game.
Given the current world state, adventure context, and the player's input, \
extract the player's intent and return it as a JSON object with exactly these four fields:

{
  "action_type": "ATTACK | TALK | TALK_SKILL_CHECK | MOVE | NARRATOR_INTERACTION",
  "actor": "who is performing the action",
  "target": "who or what the action is directed at, or null if none",
  "additional_info": "relevant details such as weapon used, spell name, topic of conversation, direction of travel, etc. — or null if none"
}

Action type rules:
- ATTACK: the player wants to fight, strike, or engage in combat with something.
- TALK: the player wants to have a normal conversation, greet an NPC, or ask about \
something the NPC would answer openly. No pressure, no probing for secrets.
- TALK_SKILL_CHECK: the player is trying to persuade, intimidate, deceive, or read an NPC — \
anything that involves pressing them for information they may be reluctant to share, \
calling their bluff, or socially influencing their behaviour. Use this when the player \
is pushing for something the NPC might resist.
- MOVE: the player wants to travel, go somewhere, explore, or change location.
- NARRATOR_INTERACTION: the player is addressing the narrator/DM directly — asking a general \
question about the world, rules, their surroundings, or the situation. Not directed at any \
NPC and not a game action. Use this when the player wants information or clarification from \
the narrator rather than doing something.

Examples:

Player input: "I greet Damien and ask how his day is going"
{
  "action_type": "TALK",
  "actor": "player",
  "target": "Damien",
  "additional_info": "casual greeting"
}

Player input: "I try to persuade Damien to tell me what the medallion really is"
{
  "action_type": "TALK_SKILL_CHECK",
  "actor": "player",
  "target": "Damien",
  "additional_info": "pressing Damien about the medallion"
}

Player input: "I stare Damien down and tell him I know he's hiding something"
{
  "action_type": "TALK_SKILL_CHECK",
  "actor": "player",
  "target": "Damien",
  "additional_info": "intimidating Damien about what he is concealing"
}

Player input: "I attack the goblin with my sword"
{
  "action_type": "ATTACK",
  "actor": "player",
  "target": "goblin",
  "additional_info": "sword"
}

Player input: "I head north towards the mountains"
{
  "action_type": "MOVE",
  "actor": "player",
  "target": "mountains",
  "additional_info": "heading north"
}

Player input: "I run away from the dragon"
{
  "action_type": "MOVE",
  "actor": "player",
  "target": null,
  "additional_info": "fleeing from the dragon"
}

Player input: "What do I know about this dungeon?"
{
  "action_type": "NARRATOR_INTERACTION",
  "actor": "player",
  "target": null,
  "additional_info": "asking about the dungeon"
}

Player input: "Can I see anything unusual in this room?"
{
  "action_type": "NARRATOR_INTERACTION",
  "actor": "player",
  "target": null,
  "additional_info": "asking about the current room"
}

Respond with only the raw JSON object. No markdown fences, no explanation."""


class ClassifiedAction(TypedDict):
    action_type: str
    actor: str
    target: str | None
    additional_info: str | None


_FALLBACK: ClassifiedAction = {
    "action_type": "MOVE",
    "actor": "player",
    "target": None,
    "additional_info": None,
}


class ActionClassifierAgent:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def classify_action(
        self, player_input: str, world_state: str, adventure_context: str
    ) -> ClassifiedAction:
        """Classify the player's intent and return a structured action dict."""
        logger.info("Classifier — input: %r", player_input)

        user_message = (
            f"Adventure context:\n{adventure_context}\n\n"
            f"World state:\n{world_state}\n\n"
            f"Player input: {player_input}"
        )
        raw = self.llm.call(system=SYSTEM_PROMPT, user=user_message).strip()
        logger.debug("Classifier — raw LLM response: %s", raw)

        # Strip markdown code fences the model sometimes wraps around JSON
        clean = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        try:
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            logger.warning("Classifier — JSON parse failed, using fallback. Raw: %r", raw)
            return _FALLBACK

        action_type = str(parsed.get("action_type", "")).upper()
        if action_type not in VALID_ACTIONS:
            logger.warning("Classifier — unknown action_type %r, using fallback", action_type)
            return _FALLBACK

        result = ClassifiedAction(
            action_type=action_type,
            actor=parsed.get("actor") or "player",
            target=parsed.get("target") or None,
            additional_info=parsed.get("additional_info") or None,
        )
        logger.info(
            "Classifier — result: action=%s  actor=%s  target=%s  info=%s",
            result["action_type"], result["actor"], result["target"], result["additional_info"],
        )
        return result
