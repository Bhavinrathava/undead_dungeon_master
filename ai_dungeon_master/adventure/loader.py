"""
adventure/loader.py
Reads adventure documents and returns a populated Adventure model.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any

import yaml

from .models import Adventure


class AdventureLoader:
    """Loads adventure content from various sources into an Adventure model."""

    @staticmethod
    def load_from_yaml(path: str | Path) -> Adventure:
        """Read a .yaml adventure file and return a validated Adventure."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Adventure file not found: {path}")
        if path.suffix.lower() not in (".yaml", ".yml"):
            raise ValueError(f"Expected a .yaml/.yml file, got: {path.suffix}")

        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        return AdventureLoader.load_from_dict(data)

    @staticmethod
    def load_from_dict(data: dict[str, Any]) -> Adventure:
        """Construct and validate an Adventure from a raw dictionary."""
        return Adventure.model_validate(data)

    @staticmethod
    def load_from_pdf(path: str | Path) -> Adventure:
        """
        (Phase 2) PDF ingestion via PyMuPDF + LLM extraction.
        Not yet implemented.
        """
        raise NotImplementedError(
            f"PDF loading is a Phase 2 feature and has not been implemented yet. (requested: {path})"
        )
