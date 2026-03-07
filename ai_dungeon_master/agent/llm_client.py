"""
agent/llm_client.py
Thin wrapper around the Anthropic SDK for a single Claude call.
"""

from __future__ import annotations

from pathlib import Path

import anthropic
from dotenv import load_dotenv

# Load .env from the package root (ai_dungeon_master/) if present
load_dotenv(Path(__file__).parent.parent / ".env")


DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 1024


class LLMClient:
    """Sends a prompt to Claude and returns the response text."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def call(self, system: str, user: str) -> str:
        """
        Send a system + user message to Claude and return the response text.

        Args:
            system: The system prompt (e.g. DM instructions + context).
            user:   The player's input for this turn.

        Returns:
            The assistant's response as a plain string.
        """
        message = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return message.content[0].text
