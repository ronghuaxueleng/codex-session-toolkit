"""Session rollout file helpers."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Iterable

from ..errors import ToolkitError
from ..models import SessionSummary
from ..paths import CodexPaths
from ..support import project_path_matches
from ..validation import validate_session_id
from .desktop_state import load_thread_metadata
from .history import first_history_messages
from .index import is_weak_thread_name, load_existing_index
from .session_parser import (
    looks_like_session_meta_text,
    normalize_session_text,
    parse_session_file,
    parse_session_summary_file,
)
from .session_parser import (
    parse_jsonl_records as _parse_jsonl_records,
)


def iter_session_files(paths: CodexPaths, *, active_only: bool = False) -> Iterable[Path]:
    if paths.sessions_dir.exists():
        yield from sorted(paths.sessions_dir.rglob("rollout-*.jsonl"))
    if not active_only and paths.archived_sessions_dir.exists():
        yield from sorted(paths.archived_sessions_dir.rglob("rollout-*.jsonl"))


def session_id_from_filename(path: Path) -> str | None:
    name = path.name
    match = re.match(r"^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-(.+)\.jsonl$", name)
    return match.group(1) if match else None


def session_timestamp_from_filename(path: Path) -> str:
    match = re.match(r"^rollout-(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})-(.+)\.jsonl$", path.name)
    if not match:
        return ""
    return f"{match.group(1)} {match.group(2)}:{match.group(3)}"


def first_user_prompt_from_session(session_file: Path) -> str:
    try:
        return parse_session_file(session_file).first_user_prompt
    except ToolkitError:
        return ""


def workspace_name_from_cwd(cwd: str) -> str:
    normalized = (cwd or "").strip()
    if not normalized:
        return ""

    stripped = normalized.rstrip("\\/")
    if not stripped:
        return normalized

    if "\\" in stripped:
        return PureWindowsPath(stripped).name or stripped
    return Path(stripped).name or PureWindowsPath(stripped).name or stripped


def build_session_preview(
    history_preview: str,
    session_file: Path,
    cwd: str,
    *,
    first_user_prompt: str | None = None,
) -> str:
    prompt = first_user_prompt_from_session(session_file) if first_user_prompt is None else first_user_prompt
    for candidate in (prompt, history_preview):
        normalized = normalize_session_text(candidate)
        if normalized and not looks_like_session_meta_text(normalized):
            return normalized

    workspace_name = workspace_name_from_cwd(cwd)
    timestamp_label = session_timestamp_from_filename(session_file)
    if workspace_name and timestamp_label:
        return f"{workspace_name} · {timestamp_label}"
    if workspace_name:
        return f"工作区：{workspace_name}"
    if timestamp_label:
        return f"会话开始于 {timestamp_label}"
    return session_file.name


def parse_jsonl_records(path: Path) -> list[tuple[str, dict | None]]:
    return _parse_jsonl_records(path)


def read_session_payload(path: Path) -> dict:
    return dict(parse_session_file(path).session_meta)


def extract_session_field_from_file(field_name: str, session_file: Path) -> str:
    try:
        value = parse_session_file(session_file).session_meta.get(field_name)
    except ToolkitError:
        return ""
    return value if isinstance(value, str) else ""


def extract_last_timestamp(session_file: Path) -> str:
    try:
        return parse_session_file(session_file).last_timestamp
    except ToolkitError:
        return ""


def find_session_file(paths: CodexPaths, session_id: str) -> Path | None:
    validate_session_id(session_id)
    for session_file in iter_session_files(paths):
        if session_id_from_filename(session_file) == session_id:
            return session_file
    return None


def session_meta_line(session_file: Path) -> str:
    with session_file.open("r", encoding="utf-8") as fh:
        for raw in fh:
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("type") == "session_meta":
                return raw if raw.endswith("\n") else raw + "\n"
    raise ToolkitError(f"Session file does not contain session_meta: {session_file}")


def reset_session_file_to_metadata(session_file: Path, *, dry_run: bool = False) -> tuple[int, int]:
    metadata_line = session_meta_line(session_file)
    original_bytes = session_file.stat().st_size
    reset_bytes = len(metadata_line.encode("utf-8"))
    if dry_run:
        return original_bytes, reset_bytes

    fd, temp_name = tempfile.mkstemp(prefix=session_file.name + ".", dir=session_file.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(metadata_line)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(temp_path, session_file.stat().st_mode)
        os.replace(temp_path, session_file)
    finally:
        temp_path.unlink(missing_ok=True)
    return original_bytes, reset_bytes


def collect_session_summaries(
    paths: CodexPaths,
    *,
    pattern: str = "",
    limit: int | None = None,
    active_only: bool = False,
    desktop_only: bool = False,
    project_path: str = "",
) -> list[SessionSummary]:
    summaries: list[SessionSummary] = []
    session_files = sorted(iter_session_files(paths, active_only=active_only), reverse=True)
    session_ids_by_path = {
        session_file: session_id_from_filename(session_file) or session_file.stem
        for session_file in session_files
    }
    relevant_session_ids = set(session_ids_by_path.values())
    thread_metadata = load_thread_metadata(paths.latest_state_db(), session_ids=relevant_session_ids)
    existing_index = load_existing_index(paths.index_file)
    history_session_ids = None
    if limit is not None and not pattern and not project_path and not desktop_only:
        history_session_ids = {session_ids_by_path[session_file] for session_file in session_files[: max(1, limit)]}
    history_preview = first_history_messages(paths.history_file, session_ids=history_session_ids)

    for session_file in session_files:
        session_id = session_ids_by_path[session_file]
        session_scope = "archived" if str(session_file).startswith(str(paths.archived_sessions_dir)) else "active"
        history_text = history_preview.get(session_id, "")
        thread_name = _session_thread_name(
            session_id,
            desktop_title=str(thread_metadata.get(session_id, {}).get("title") or ""),
            index_thread_name=str(existing_index.get(session_id, {}).get("thread_name") or ""),
        )
        include_first_user_prompt = not thread_name and (not history_text or looks_like_session_meta_text(history_text))
        try:
            parsed_session = parse_session_summary_file(
                session_file,
                include_first_user_prompt=include_first_user_prompt,
            )
        except ToolkitError:
            parsed_session = None

        session_kind = parsed_session.session_kind if parsed_session is not None else "unknown"
        if desktop_only and session_kind != "desktop":
            continue

        cwd = parsed_session.cwd if parsed_session is not None else ""
        if project_path and not project_path_matches(cwd, project_path):
            continue
        model_provider = parsed_session.model_provider if parsed_session is not None else ""
        preview = build_session_preview(
            history_text,
            session_file,
            cwd,
            first_user_prompt=parsed_session.first_user_prompt if parsed_session is not None else "",
        )
        summary = SessionSummary(
            session_id=session_id,
            scope=session_scope,
            path=session_file,
            preview=preview,
            kind=session_kind,
            cwd=cwd,
            model_provider=model_provider,
            thread_name=thread_name,
        )

        if pattern:
            combined = " ".join(
                [
                    summary.session_id,
                    summary.scope,
                    summary.kind,
                    summary.model_provider,
                    summary.thread_name,
                    summary.cwd,
                    summary.preview,
                    str(summary.path),
                ]
            )
            if pattern not in combined:
                continue

        summaries.append(summary)
        if limit is not None and len(summaries) >= max(1, limit):
            break

    return summaries


def _session_thread_name(session_id: str, *, desktop_title: str, index_thread_name: str) -> str:
    for candidate in (desktop_title, index_thread_name):
        value = normalize_session_text(candidate)
        if value and not is_weak_thread_name(value, session_id):
            return value
    return ""


def collect_session_ids_for_kind(
    paths: CodexPaths,
    *,
    session_kind: str,
    active_only: bool = False,
) -> list[str]:
    session_ids: list[str] = []
    seen_session_ids: set[str] = set()

    for path in iter_session_files(paths, active_only=active_only):
        try:
            parsed = parse_session_file(path)
        except ToolkitError:
            continue

        session_id = parsed.session_id
        if session_id and parsed.session_kind == session_kind and session_id not in seen_session_ids:
            session_ids.append(session_id)
            seen_session_ids.add(session_id)

    return session_ids


def collect_session_ids_for_project(
    paths: CodexPaths,
    *,
    project_path: str,
    active_only: bool = False,
) -> list[str]:
    if not project_path:
        return []

    session_ids: list[str] = []
    seen_session_ids: set[str] = set()
    for summary in collect_session_summaries(
        paths,
        pattern="",
        limit=None,
        active_only=active_only,
        project_path=project_path,
    ):
        if summary.session_id in seen_session_ids:
            continue
        session_ids.append(summary.session_id)
        seen_session_ids.add(summary.session_id)
    return session_ids


def extract_timestamp_from_rollout_name(filename: str) -> str:
    match = re.match(r"^rollout-(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-", filename)
    return match.group(1) if match else ""
