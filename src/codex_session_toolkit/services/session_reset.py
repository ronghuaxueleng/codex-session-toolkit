"""Reset one local session while preserving its identity and metadata."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from ..errors import ToolkitError
from ..models import SessionResetResult
from ..paths import CodexPaths
from ..stores.desktop_state import reset_thread_for_empty_session
from ..stores.history import remove_history_entries_for_session
from ..stores.index import upsert_session_index
from ..stores.session_files import (
    iter_session_files,
    reset_session_file_to_metadata,
    session_id_from_filename,
)
from ..support import normalize_iso
from ..validation import validate_jsonl_file, validate_session_id

DEFAULT_RESET_SESSION_TITLE = "空会话（已重置）"


def reset_session(
    paths: CodexPaths,
    input_value: str,
    *,
    title: str = DEFAULT_RESET_SESSION_TITLE,
    create_backup: bool = False,
    dry_run: bool = False,
) -> SessionResetResult:
    session_path = _resolve_session_path(paths, input_value)
    session_id = session_id_from_filename(session_path)
    if not session_id:
        raise ToolkitError(f"Could not determine session id from: {session_path}")
    validate_jsonl_file(session_path, "Session rollout", "session", expected_session_id=session_id)

    original_bytes, reset_bytes = reset_session_file_to_metadata(session_path, dry_run=True)
    history_entries_removed = remove_history_entries_for_session(
        paths.history_file,
        session_id,
        dry_run=True,
    )
    thread_rows_updated = reset_thread_for_empty_session(
        paths.latest_state_db(),
        session_id,
        title=title,
        dry_run=True,
    )
    backup_path = _next_reset_backup_path(session_path) if create_backup else None

    if dry_run:
        return SessionResetResult(
            session_id=session_id,
            session_path=session_path,
            backup_path=backup_path,
            dry_run=True,
            original_bytes=original_bytes,
            reset_bytes=reset_bytes,
            history_entries_removed=history_entries_removed,
            thread_rows_updated=thread_rows_updated,
            index_updated=True,
        )

    if backup_path is not None:
        shutil.copy2(session_path, backup_path)
    reset_session_file_to_metadata(session_path)
    history_entries_removed = remove_history_entries_for_session(paths.history_file, session_id)
    thread_rows_updated = reset_thread_for_empty_session(
        paths.latest_state_db(),
        session_id,
        title=title,
    )
    upsert_session_index(
        paths.index_file,
        session_id,
        title,
        normalize_iso(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
    )
    validate_jsonl_file(session_path, "Reset session rollout", "session", expected_session_id=session_id)

    return SessionResetResult(
        session_id=session_id,
        session_path=session_path,
        backup_path=backup_path,
        dry_run=False,
        original_bytes=original_bytes,
        reset_bytes=reset_bytes,
        history_entries_removed=history_entries_removed,
        thread_rows_updated=thread_rows_updated,
        index_updated=True,
    )


def _resolve_session_path(paths: CodexPaths, input_value: str) -> Path:
    raw_value = (input_value or "").strip()
    if not raw_value:
        raise ToolkitError("Missing session id or rollout path.")

    candidate = Path(raw_value).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    normalized = candidate.resolve(strict=False)
    for root in (paths.sessions_dir, paths.archived_sessions_dir):
        try:
            normalized.relative_to(root.resolve(strict=False))
        except ValueError:
            continue
        if normalized.is_file() and normalized.name.startswith("rollout-"):
            return normalized

    validate_session_id(raw_value)
    matches = [
        session_file
        for session_file in iter_session_files(paths)
        if session_id_from_filename(session_file) == raw_value
    ]
    if not matches:
        raise ToolkitError(f"No local session found for: {raw_value}")
    active_matches = [path for path in matches if path.is_relative_to(paths.sessions_dir)]
    return sorted(active_matches or matches, reverse=True)[0]


def _next_reset_backup_path(session_path: Path) -> Path:
    epoch = int(time.time())
    while True:
        candidate = session_path.with_name(session_path.name + f".bak.reset.{epoch}")
        if not candidate.exists():
            return candidate
        epoch += 1
