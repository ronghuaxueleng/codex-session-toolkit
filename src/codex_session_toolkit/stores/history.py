"""History JSONL helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import AbstractSet, Sequence


def first_history_messages(history_file: Path, session_ids: AbstractSet[str] | None = None) -> dict[str, str]:
    first_messages: dict[str, str] = {}
    if not history_file.exists():
        return first_messages
    if session_ids is not None and not session_ids:
        return first_messages

    remaining = set(session_ids) if session_ids is not None else None

    with history_file.open("r", encoding="utf-8") as fh:
        for raw in fh:
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            session_id = obj.get("session_id")
            text = obj.get("text")
            if remaining is not None and session_id not in remaining:
                continue
            if isinstance(session_id, str) and session_id and session_id not in first_messages and isinstance(text, str) and text:
                first_messages[session_id] = text.replace("\n", " ")
                if remaining is not None:
                    remaining.discard(session_id)
                    if not remaining:
                        break
    return first_messages


def collect_history_lines_for_session(history_file: Path, session_id: str) -> list[str]:
    lines: list[str] = []
    if not history_file.exists():
        return lines

    with history_file.open("r", encoding="utf-8") as fh:
        for raw in fh:
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if obj.get("session_id") == session_id:
                lines.append(raw if raw.endswith("\n") else raw + "\n")
    return lines


def first_history_text(history_lines: Sequence[str]) -> str:
    for raw in history_lines:
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        text = obj.get("text")
        if isinstance(text, str):
            return text.replace("\n", " ")
    return ""
