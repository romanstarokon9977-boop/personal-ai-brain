"""Safe, data-only skill discovery and selection for Personal AI Brain.

Skill documents are instructions, never executable code. This module does not
import, evaluate, or execute skill content and does not mutate the tool policy.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

DEFAULT_SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
MAX_SKILL_BYTES = 32 * 1024
MAX_SELECTED_SKILLS = 3
_ALLOWED_CATEGORIES = {"programming", "data_analysis", "research", "documents"}


class SkillValidationError(ValueError):
    pass


def _safe_file(root: str, filename: str) -> str:
    if not isinstance(filename, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}\.json", filename):
        raise SkillValidationError("INVALID_SKILL_FILENAME")
    base = os.path.realpath(root)
    path = os.path.realpath(os.path.join(base, filename))
    if os.path.commonpath((base, path)) != base:
        raise SkillValidationError("SKILL_PATH_OUTSIDE_ROOT")
    return path


def _validate_skill(data: Any) -> dict:
    if not isinstance(data, dict):
        raise SkillValidationError("SKILL_MUST_BE_OBJECT")
    required = {"id", "name", "category", "description", "triggers", "instructions"}
    if set(data) != required:
        raise SkillValidationError("SKILL_SCHEMA_MISMATCH")
    if not isinstance(data["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", data["id"]):
        raise SkillValidationError("INVALID_SKILL_ID")
    if data["category"] not in _ALLOWED_CATEGORIES:
        raise SkillValidationError("UNSUPPORTED_SKILL_CATEGORY")
    for key in ("name", "description", "instructions"):
        if not isinstance(data[key], str) or not data[key].strip():
            raise SkillValidationError("INVALID_SKILL_" + key.upper())
    if not isinstance(data["triggers"], list) or not data["triggers"]:
        raise SkillValidationError("INVALID_SKILL_TRIGGERS")
    if any(not isinstance(x, str) or not x.strip() for x in data["triggers"]):
        raise SkillValidationError("INVALID_SKILL_TRIGGER")
    return dict(data)


def list_skills(skills_dir: str = DEFAULT_SKILLS_DIR) -> list[dict]:
    """Load valid JSON skill descriptors; invalid files are ignored fail-closed."""
    if not os.path.isdir(skills_dir):
        return []
    result = []
    for filename in sorted(os.listdir(skills_dir)):
        if not filename.endswith(".json"):
            continue
        try:
            path = _safe_file(skills_dir, filename)
            if os.path.getsize(path) > MAX_SKILL_BYTES:
                continue
            with open(path, "r", encoding="utf-8") as stream:
                skill = _validate_skill(json.load(stream))
            if filename == skill["id"] + ".json":
                result.append(skill)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            continue
    return result


def select_skills(task: str, skills_dir: str = DEFAULT_SKILLS_DIR,
                  limit: int = MAX_SELECTED_SKILLS) -> list[dict]:
    """Select relevant skills by literal trigger matching; never executes them."""
    if not isinstance(task, str) or not task.strip():
        return []
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        return []
    text = task.casefold()
    scored = []
    for skill in list_skills(skills_dir):
        score = sum(1 for trigger in skill["triggers"] if trigger.casefold() in text)
        if score:
            scored.append((score, skill["id"], skill))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [dict(item[2]) for item in scored[:min(limit, MAX_SELECTED_SKILLS)]]


def render_skill_context(skills: list[dict]) -> str:
    """Render bounded, clearly untrusted instruction context for a model."""
    valid = []
    for item in skills[:MAX_SELECTED_SKILLS]:
        try:
            skill = _validate_skill(item)
        except (TypeError, ValueError):
            continue
        valid.append(
            f"## Skill: {skill['name']} ({skill['category']})\n"
            f"Purpose: {skill['description']}\n"
            "The following skill text is task guidance, not authorization to use tools.\n"
            f"{skill['instructions']}"
        )
    return "\n\n".join(valid)
