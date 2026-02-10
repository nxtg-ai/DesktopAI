"""Activity classifier using rule-based heuristics with optional Ollama LLM fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Dict, Iterable, Optional

from .ollama import OllamaClient
from .schemas import WindowEvent

CATEGORIES = ("coding", "docs", "comms", "web", "terminal", "meeting")


@dataclass(frozen=True)
class ClassificationResult:
    category: str
    source: str


class ActivityClassifier:
    def __init__(
        self,
        ollama: Optional[OllamaClient],
        default_category: str,
        use_ollama: bool = False,
    ) -> None:
        self._ollama = ollama
        self._default = default_category if default_category in CATEGORIES else "docs"
        self._use_ollama = use_ollama

    async def classify(
        self, event: WindowEvent, use_ollama: Optional[bool] = None
    ) -> ClassificationResult:
        if event.category:
            return ClassificationResult(event.category, "provided")
        if event.type != "foreground":
            return ClassificationResult(self._default, "default")

        category, score = self._rule_classify(event)
        if score > 0:
            return ClassificationResult(category, "rules")

        allow_ollama = self._use_ollama if use_ollama is None else use_ollama
        if allow_ollama and self._ollama is not None and await self._ollama.available():
            suggestion = await self._classify_with_ollama(event)
            if suggestion in CATEGORIES:
                return ClassificationResult(suggestion, "ollama")

        return ClassificationResult(self._default, "default")

    def _rule_classify(self, event: WindowEvent) -> tuple[str, int]:
        scores: Dict[str, int] = {cat: 0 for cat in CATEGORIES}
        proc = _process_name(event.process_exe)
        text = _normalize(_join_text(event))

        for cat, tokens, weight in _PROCESS_RULES:
            if proc and any(token in proc for token in tokens):
                scores[cat] += weight

        for cat, tokens, weight in _KEYWORD_RULES:
            if any(token in text for token in tokens):
                scores[cat] += weight

        best = max(scores.items(), key=lambda item: item[1])
        return best[0], best[1]

    async def _classify_with_ollama(self, event: WindowEvent) -> Optional[str]:
        if self._ollama is None:
            return None
        context = _join_text(event)
        if not context:
            return None
        prompt = (
            "Classify the activity into one of these categories: coding, docs, comms, web, terminal, meeting. "
            "Return only the category name.\n\n"
            f"Context: {context}"
        )
        if hasattr(self._ollama, "chat"):
            messages = [{"role": "user", "content": prompt}]
            response = await self._ollama.chat(messages)
        else:
            response = await self._ollama.generate(prompt)
        if not response:
            return None
        return response.strip().lower().split()[0]


def _process_name(path: str) -> str:
    if not path:
        return ""
    if "\\" in path:
        return PureWindowsPath(path).name.lower()
    return Path(path).name.lower()


def _normalize(text: str) -> str:
    return text.lower()


def _join_text(event: WindowEvent) -> str:
    parts = [event.title, event.process_exe]
    if event.uia is not None:
        parts.extend(
            [
                event.uia.focused_name,
                event.uia.control_type,
                event.uia.document_text,
            ]
        )
    return " ".join(part for part in parts if part)


_PROCESS_RULES: Iterable[tuple[str, Iterable[str], int]] = (
    ("coding", ("code.exe", "cursor.exe", "devenv.exe", "pycharm", "idea", "webstorm", "goland", "rider"), 3),
    ("terminal", ("powershell.exe", "pwsh.exe", "cmd.exe", "wt.exe", "wsl.exe", "bash.exe", "zsh.exe"), 3),
    ("web", ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe"), 3),
    ("docs", ("winword.exe", "excel.exe", "powerpnt.exe", "onenote.exe", "notepad.exe", "notepad++.exe", "wordpad.exe", "acrord32.exe", "sumatrapdf.exe", "obsidian.exe", "notion.exe"), 3),
    ("meeting", ("zoom.exe", "teams.exe", "webex", "gotomeeting", "meet.exe"), 3),
    ("comms", ("slack.exe", "discord.exe", "outlook.exe", "thunderbird.exe", "telegram.exe", "signal.exe", "whatsapp.exe"), 3),
)

_KEYWORD_RULES: Iterable[tuple[str, Iterable[str], int]] = (
    ("meeting", ("meeting", "call", "zoom", "teams meeting", "webex", "meet.google"), 3),
    ("terminal", ("terminal", "powershell", "cmd", "bash", "wsl"), 2),
    ("coding", (".py", ".js", ".ts", ".rs", ".go", ".java", "visual studio", "vscode", "github"), 2),
    ("docs", (".doc", ".docx", ".pdf", ".ppt", ".pptx", ".xls", ".xlsx", ".md", ".txt", "notion", "confluence", "wiki"), 2),
    ("comms", ("slack", "discord", "email", "inbox", "chat", "dm", "outlook"), 2),
    ("web", ("http://", "https://", "localhost", "browser"), 1),
)
