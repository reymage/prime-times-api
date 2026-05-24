"""
YAML-based prompt loader.
Editors modify prompts/ptd.yaml; no redeployment needed.
"""
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import settings

logger = logging.getLogger(__name__)

_PROMPTS_CACHE: dict[str, Any] | None = None


def _load_raw() -> dict[str, Any]:
    global _PROMPTS_CACHE
    if _PROMPTS_CACHE is not None:
        return _PROMPTS_CACHE

    prompts_dir = Path(settings.PROMPTS_DIR)
    if not prompts_dir.is_absolute():
        # Resolve relative to the api/ working directory
        prompts_dir = Path(os.getcwd()) / prompts_dir

    yaml_path = prompts_dir / "ptd.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"Prompts file not found: {yaml_path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    _PROMPTS_CACHE = data
    logger.info("Loaded prompts from %s", yaml_path)
    return data


def get_prompt(node: str, story_type: str = "general") -> dict[str, str]:
    """
    Return the prompt dict for a given node and story_type.
    story_type overrides are merged on top of the base node prompt.
    """
    raw = _load_raw()

    base: dict[str, str] = dict(raw.get(node, {}))
    overrides: dict[str, Any] = raw.get("story_type_overrides", {})
    story_overrides: dict[str, str] = overrides.get(story_type, {})

    # Append story-type-specific extras to system/user prompts
    extra_key = f"{node}_extra"
    if extra_key in story_overrides:
        base["system"] = (base.get("system", "") + "\n\n" + story_overrides[extra_key]).strip()

    return base


def get_newsroom_context() -> str:
    return _load_raw().get("newsroom_context", "")


def invalidate_cache() -> None:
    """Force reload on next access (useful in tests)."""
    global _PROMPTS_CACHE
    _PROMPTS_CACHE = None
