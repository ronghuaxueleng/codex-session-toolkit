"""Session deletion service for active and archived rollout files."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..models import SessionDeleteResult
from ..paths import CodexPaths
from ..stores.desktop_state import delete_thread_rows_by_session_ids, redirect_thread_rows_by_session_paths
from ..stores.index import remove_session_index_entries
from ..stores.session_files import session_id_from_filename


def delete_sessions(
    paths: CodexPaths,
    *,
    input_values: Iterable[str] = (),
    scope_filter: str = "all",
    delete_all: bool = False,
    dry_run: bool = False,
) -> SessionDeleteResult:
    files_to_delete = _resolve_session_files(
        paths,
        input_values=input_values,
        scope_filter=scope_filter,
        delete_all=delete_all,
    )
    session_ids = sorted(
        {
            session_id
            for session_id in (session_id_from_filename(path) for path in files_to_delete)
            if session_id
        }
    )
    bytes_to_delete = sum(_file_size(path) for path in files_to_delete)
    state_db = paths.latest_state_db() or Path()
    excluded_paths = set(files_to_delete)
    active_session_paths = _active_session_paths(paths, set(session_ids), excluded_paths=excluded_paths)
    active_session_ids = set(active_session_paths)
    removable_index_session_ids = set(session_ids) - active_session_ids

    if dry_run:
        return SessionDeleteResult(
            dry_run=True,
            files_to_delete=files_to_delete,
            session_ids=session_ids,
            bytes_to_delete=bytes_to_delete,
            index_entries_removed=remove_session_index_entries(
                paths.index_file,
                removable_index_session_ids,
                dry_run=True,
            ),
            thread_rows_removed=delete_thread_rows_by_session_ids(
                state_db,
                removable_index_session_ids,
                managed_roots=_managed_roots(paths),
                dry_run=True,
            ),
            thread_rows_restored=redirect_thread_rows_by_session_paths(
                state_db,
                active_session_paths,
                managed_roots=_managed_roots(paths),
                dry_run=True,
            ),
        )

    deleted_files: list[Path] = []
    errors: list[tuple[Path, str]] = []
    for session_file in files_to_delete:
        try:
            session_file.unlink()
            deleted_files.append(session_file)
        except OSError as exc:
            errors.append((session_file, str(exc)))

    deleted_session_ids = sorted(
        {
            session_id
            for session_id in (session_id_from_filename(path) for path in deleted_files)
            if session_id
        }
    )
    deleted_session_id_set = set(deleted_session_ids)
    active_session_paths = _active_session_paths(paths, deleted_session_id_set)
    removable_session_ids = deleted_session_id_set - set(active_session_paths)
    thread_rows_restored = redirect_thread_rows_by_session_paths(
        state_db,
        active_session_paths,
        managed_roots=_managed_roots(paths),
    )
    thread_rows_removed = delete_thread_rows_by_session_ids(
        state_db,
        removable_session_ids,
        managed_roots=_managed_roots(paths),
    )
    index_entries_removed = remove_session_index_entries(paths.index_file, removable_session_ids)

    return SessionDeleteResult(
        dry_run=False,
        files_to_delete=files_to_delete,
        deleted_files=deleted_files,
        session_ids=deleted_session_ids,
        bytes_to_delete=bytes_to_delete,
        index_entries_removed=index_entries_removed,
        thread_rows_removed=thread_rows_removed,
        thread_rows_restored=thread_rows_restored,
        empty_dirs_removed=_remove_empty_session_dirs(paths),
        errors=errors,
    )


def _resolve_session_files(
    paths: CodexPaths,
    *,
    input_values: Iterable[str],
    scope_filter: str,
    delete_all: bool,
) -> list[Path]:
    requested_paths: list[Path] = []
    seen_paths: set[Path] = set()
    session_files = _session_files_for_scope(paths, scope_filter=scope_filter)

    if delete_all:
        return session_files

    session_files_by_id: dict[str, list[Path]] = {}
    for session_file in session_files:
        session_id = session_id_from_filename(session_file)
        if session_id:
            session_files_by_id.setdefault(session_id, []).append(session_file)

    for raw_value in input_values:
        exact_path = _managed_session_path(paths, raw_value, scope_filter=scope_filter)
        if exact_path is not None and exact_path not in seen_paths:
            requested_paths.append(exact_path)
            seen_paths.add(exact_path)
            continue

        for matched_path in session_files_by_id.get(raw_value, []):
            if matched_path not in seen_paths:
                requested_paths.append(matched_path)
                seen_paths.add(matched_path)
    return requested_paths


def _managed_session_path(paths: CodexPaths, raw_value: str, *, scope_filter: str) -> Path | None:
    candidate = Path(raw_value).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    normalized = candidate.resolve(strict=False)
    for root in _scope_roots(paths, scope_filter=scope_filter):
        root_path = root.resolve(strict=False)
        try:
            normalized.relative_to(root_path)
        except ValueError:
            continue
        if normalized.exists() and normalized.is_file() and normalized.name.startswith("rollout-"):
            return normalized
    return None


def _scope_roots(paths: CodexPaths, *, scope_filter: str) -> tuple[Path, ...]:
    if scope_filter == "active":
        return (paths.sessions_dir,)
    if scope_filter == "archived":
        return (paths.archived_sessions_dir,)
    return _managed_roots(paths)


def _managed_roots(paths: CodexPaths) -> tuple[Path, ...]:
    return (paths.sessions_dir, paths.archived_sessions_dir)


def _session_files_for_scope(paths: CodexPaths, *, scope_filter: str) -> list[Path]:
    session_files: list[Path] = []
    for root in _scope_roots(paths, scope_filter=scope_filter):
        if root.exists():
            session_files.extend(sorted(root.rglob("rollout-*.jsonl")))
    return session_files


def _active_session_paths(
    paths: CodexPaths,
    session_ids: set[str],
    *,
    excluded_paths: set[Path] | None = None,
) -> dict[str, Path]:
    if not session_ids or not paths.sessions_dir.exists():
        return {}
    ignored_paths = excluded_paths or set()
    active_paths: dict[str, Path] = {}
    for session_file in sorted(paths.sessions_dir.rglob("rollout-*.jsonl"), reverse=True):
        if session_file in ignored_paths:
            continue
        session_id = session_id_from_filename(session_file)
        if session_id in session_ids and session_id not in active_paths:
            active_paths[session_id] = session_file
    return active_paths


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _remove_empty_session_dirs(paths: CodexPaths) -> int:
    removed = 0
    directories = []
    for root in _managed_roots(paths):
        if root.exists():
            directories.extend(path for path in root.rglob("*") if path.is_dir())
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        try:
            directory.rmdir()
            removed += 1
        except OSError:
            continue
    return removed
