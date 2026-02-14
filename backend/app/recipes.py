"""Pre-built automation recipes matched to desktop context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Recipe:
    recipe_id: str
    name: str
    description: str
    steps: List[Dict[str, Any]]
    context_patterns: List[str]  # regex patterns for process_exe/title matching
    keywords: List[str]          # chat trigger keywords


BUILTIN_RECIPES: List[Recipe] = [
    Recipe(
        recipe_id="reply_to_email",
        name="Draft Email Reply",
        description="Draft a reply to the currently open email",
        steps=[
            {"action": "observe_desktop"},
            {"action": "compose_text", "params": {"intent": "reply"}},
            {"action": "send_keys", "params": {"keys": "{TAB}{ENTER}"}},
        ],
        context_patterns=[r"(?i)outlook|thunderbird|mail"],
        keywords=["reply", "draft reply", "respond", "draft", "email reply"],
    ),
    Recipe(
        recipe_id="summarize_document",
        name="Summarize Active Document",
        description="Generate a summary of the current document",
        steps=[
            {"action": "observe_desktop"},
            {"action": "compose_text", "params": {"intent": "summarize"}},
        ],
        context_patterns=[r"(?i)word|docs|notepad|pdf|reader"],
        keywords=["summarize", "summary", "tldr"],
    ),
    Recipe(
        recipe_id="schedule_focus",
        name="Start Focus Session",
        description="Minimize distractions and set a focus timer",
        steps=[
            {"action": "focus_window"},
            {"action": "observe_desktop"},
        ],
        context_patterns=[r".*"],  # available everywhere
        keywords=["focus", "focus time", "concentrate"],
    ),
]


def match_recipes(context) -> List[Recipe]:
    """Filter recipes whose context_patterns match the current desktop context."""
    if context is None:
        return []
    text = f"{context.process_exe} {context.window_title}"
    matched = []
    for recipe in BUILTIN_RECIPES:
        for pattern in recipe.context_patterns:
            if re.search(pattern, text):
                matched.append(recipe)
                break
    return matched


def match_recipe_by_keywords(text: str) -> Optional[Recipe]:
    """Find a recipe whose keywords match the given text."""
    lower = text.lower()
    for recipe in BUILTIN_RECIPES:
        for keyword in recipe.keywords:
            if keyword in lower:
                return recipe
    return None
