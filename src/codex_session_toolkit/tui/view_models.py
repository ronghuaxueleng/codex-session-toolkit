"""TUI-specific view models."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING

from .. import APP_COMMAND
from ..models import BundleSummary

if TYPE_CHECKING:
    from .menu_catalog import (
        SECTION_NOTES,
        TUI_ACTION_NOTES,
        build_tui_menu_actions,
        build_tui_menu_sections,
        tui_action_section,
    )


@dataclass(frozen=True)
class ToolkitAppContext:
    target_provider: str
    active_sessions_dir: str
    config_path: str
    bundle_root_label: str = "./codex_bundles"
    desktop_bundle_root_label: str = "./codex_bundles"
    entry_command: str = APP_COMMAND


@dataclass(frozen=True)
class TuiMenuAction:
    action_id: str
    hotkey: str
    label: str
    section_id: str
    cli_args: tuple[str, ...]
    is_dangerous: bool = False
    is_dry_run: bool = False


@dataclass(frozen=True)
class TuiMenuSection:
    title: str
    section_id: str
    border_codes: tuple[str, ...]


@dataclass(frozen=True)
class BundleBrowserSnapshot:
    entries: list[BundleSummary]
    machine_options: list[tuple[str, str]]
    export_group_options: list[tuple[str, str]]
    current_machine_label: str
    current_export_group_label: str


@dataclass(frozen=True)
class BatchBundleImportSelection:
    entries: list[BundleSummary]
    machine_filter: str
    machine_label: str
    export_group_filter: str
    export_group_label: str
    latest_only: bool
    project_filter: str = ""
    project_label: str = ""
    project_source_path: str = ""
    target_project_path: str = ""


@dataclass(frozen=True)
class BundleMachineFolderOption:
    machine_key: str
    machine_label: str
    bundle_count: int
    export_groups: tuple[str, ...]


@dataclass(frozen=True)
class BundleCategoryFolderOption:
    export_group: str
    export_group_label: str
    bundle_count: int
    entries: list[BundleSummary]


@dataclass(frozen=True)
class BundleProjectFolderOption:
    project_key: str
    project_label: str
    project_path: str
    bundle_count: int
    entries: list[BundleSummary]
    local_status: str
    local_status_label: str
    local_target_path: str


_LEGACY_MENU_EXPORTS = {
    "SECTION_NOTES",
    "TUI_ACTION_NOTES",
    "build_tui_menu_actions",
    "build_tui_menu_sections",
    "tui_action_section",
}

__all__ = [
    "SECTION_NOTES",
    "TUI_ACTION_NOTES",
    "BatchBundleImportSelection",
    "BundleBrowserSnapshot",
    "BundleCategoryFolderOption",
    "BundleMachineFolderOption",
    "BundleProjectFolderOption",
    "ToolkitAppContext",
    "TuiMenuAction",
    "TuiMenuSection",
    "build_tui_menu_actions",
    "build_tui_menu_sections",
    "tui_action_section",
]


def __getattr__(name: str):
    if name in _LEGACY_MENU_EXPORTS:
        value = getattr(import_module(".menu_catalog", package=__package__), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
