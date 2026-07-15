"""Archived session cleanup service."""

from __future__ import annotations

from ..models import ArchivedSessionDeleteResult
from ..paths import CodexPaths
from .session_deletion import delete_sessions


def delete_archived_sessions(
    paths: CodexPaths,
    *,
    session_ids: set[str] | None = None,
    dry_run: bool = False,
) -> ArchivedSessionDeleteResult:
    result = delete_sessions(
        paths,
        input_values=sorted(session_ids or set()),
        scope_filter="archived",
        delete_all=not session_ids,
        dry_run=dry_run,
    )
    return ArchivedSessionDeleteResult(
        archive_root=paths.archived_sessions_dir,
        dry_run=result.dry_run,
        files_to_delete=result.files_to_delete,
        deleted_files=result.deleted_files,
        session_ids=result.session_ids,
        bytes_to_delete=result.bytes_to_delete,
        index_entries_removed=result.index_entries_removed,
        thread_rows_removed=result.thread_rows_removed,
        thread_rows_restored=result.thread_rows_restored,
        empty_dirs_removed=result.empty_dirs_removed,
        errors=result.errors,
    )
