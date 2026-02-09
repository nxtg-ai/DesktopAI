from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from .schemas import UiaElement, UiaSnapshot, WindowEvent

_MAX_UIA_SUMMARY_LEN = 2048


@dataclass(frozen=True)
class DesktopContext:
    window_title: str
    process_exe: str
    timestamp: datetime
    uia_summary: str
    screenshot_b64: Optional[str] = None

    @staticmethod
    def from_event(event: Optional[WindowEvent]) -> Optional[DesktopContext]:
        if event is None:
            return None
        uia_summary = _build_uia_summary(event.uia) if event.uia else ""
        screenshot_b64 = getattr(event, "screenshot_b64", None)
        return DesktopContext(
            window_title=event.title or "",
            process_exe=event.process_exe or "",
            timestamp=event.timestamp,
            uia_summary=uia_summary,
            screenshot_b64=screenshot_b64 if isinstance(screenshot_b64, str) else None,
        )

    def to_llm_prompt(self) -> str:
        parts = [f"Window: {self.window_title}"]
        if self.process_exe:
            parts.append(f"Process: {self.process_exe}")
        if self.uia_summary:
            parts.append(f"UI Elements:\n{self.uia_summary}")
        if self.screenshot_b64:
            parts.append("[Screenshot available]")
        return "\n".join(parts)

    def get_screenshot_bytes(self) -> Optional[bytes]:
        if not self.screenshot_b64:
            return None
        try:
            return base64.b64decode(self.screenshot_b64)
        except Exception:
            return None


def _build_uia_summary(uia: UiaSnapshot) -> str:
    parts: List[str] = []
    if uia.focused_name:
        parts.append(f"Focused: {uia.focused_name}")
    if uia.control_type:
        parts.append(f"Control: {uia.control_type}")
    if uia.document_text:
        parts.append(f"Document: {uia.document_text[:200]}")
    if uia.window_tree:
        tree_lines = _summarize_tree(uia.window_tree, depth=0, max_lines=40)
        parts.append("Tree:\n" + "\n".join(tree_lines))
    text = "\n".join(parts)
    if len(text) > _MAX_UIA_SUMMARY_LEN:
        text = text[:_MAX_UIA_SUMMARY_LEN - 3] + "..."
    return text


def _summarize_tree(elements: List[UiaElement], depth: int, max_lines: int) -> List[str]:
    lines: List[str] = []
    indent = "  " * depth
    for elem in elements:
        if len(lines) >= max_lines:
            lines.append(f"{indent}... (truncated)")
            break
        desc_parts = []
        if elem.control_type:
            desc_parts.append(elem.control_type)
        if elem.name:
            desc_parts.append(f'"{elem.name}"')
        if elem.value:
            desc_parts.append(f"val={elem.value}")
        desc = " ".join(desc_parts) or "(element)"
        lines.append(f"{indent}{desc}")
        if elem.children:
            child_lines = _summarize_tree(elem.children, depth + 1, max_lines - len(lines))
            lines.extend(child_lines)
    return lines
