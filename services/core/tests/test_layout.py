from pathlib import Path

import pytest

from agos_core.storage.folders import FolderNotAllowedError, check_added_folder, share_name
from agos_core.storage.layout import (
    DataLayout,
    WorkspaceFolderExistsError,
    create_workspace_folders,
    data_layout,
    ensure_data_layout,
    move_workspace_to_trash,
    purge_trash,
    restore_workspace_from_trash,
    workspace_paths,
)


@pytest.fixture
def layout(tmp_path: Path) -> DataLayout:
    result = data_layout(tmp_path.resolve() / "data")
    ensure_data_layout(result)
    return result


def test_creates_private_folders(layout: DataLayout) -> None:
    paths = create_workspace_folders(layout, "investor")
    for d in (paths.files, paths.automations):
        assert d.is_dir()
    assert not (paths.root / "memory").exists() and not (paths.root / "connectors").exists()
    assert paths.root.stat().st_mode & 0o777 == 0o700
    with pytest.raises(WorkspaceFolderExistsError):
        create_workspace_folders(layout, "investor")


@pytest.mark.parametrize("bad", ["../system", "a/b", "", ".hidden", "-x", "UPPER", "x" * 64])
def test_bad_ids_never_become_paths(layout: DataLayout, bad: str) -> None:
    with pytest.raises(ValueError):
        workspace_paths(layout, bad)


def test_trash_cycle(layout: DataLayout) -> None:
    create_workspace_folders(layout, "content")
    day = 86_400_000
    now = 1_788_000_000_000
    name = move_workspace_to_trash(layout, "content", now)
    assert not workspace_paths(layout, "content").root.exists()
    assert restore_workspace_from_trash(layout, name) == "content"
    trashed = move_workspace_to_trash(layout, "content", now)
    assert purge_trash(layout, 30, now + 19 * day) == []
    assert purge_trash(layout, 30, now + 31 * day) == [trashed]


def test_added_folders(layout: DataLayout, tmp_path: Path) -> None:
    reports = tmp_path.resolve() / "reports"
    reports.mkdir()
    assert check_added_folder(layout, str(reports)) == reports
    other = create_workspace_folders(layout, "ecommerce").files
    assert check_added_folder(layout, str(other)) == other


def test_private_folders_refused(layout: DataLayout, tmp_path: Path) -> None:
    for bad in (
        layout.root,
        tmp_path.resolve(),
        Path("/"),
        layout.system,
        layout.system / "x",
        layout.trash,
        layout.global_dir,
    ):
        bad.mkdir(parents=True, exist_ok=True)
        with pytest.raises(FolderNotAllowedError):
            check_added_folder(layout, str(bad))
    link = tmp_path / "innocent"
    link.symlink_to(layout.system)
    with pytest.raises(FolderNotAllowedError):
        check_added_folder(layout, str(link))


def test_relative_file_missing_refused(layout: DataLayout, tmp_path: Path) -> None:
    file = tmp_path / "a.txt"
    file.write_text("x")
    for bad in ("reports", str(file), str(tmp_path / "missing")):
        with pytest.raises(FolderNotAllowedError):
            check_added_folder(layout, bad)


def test_share_names() -> None:
    assert share_name(Path("/Users/me/Q3 Reports"), []) == "q3-reports"
    assert share_name(Path("/x/files"), ["files"]) == "files-2"
    assert share_name(Path("/x/..."), []) == "folder"


def test_the_unused_folders_go_only_when_empty(layout: DataLayout) -> None:
    """memory/ and connectors/ were made in every workspace and never used: the
    empty ones go once; one with anything in it stays."""
    from agos_core.storage.layout import remove_unused_folders

    a = create_workspace_folders(layout, "investor").root
    b = create_workspace_folders(layout, "argan").root
    for root in (a, b):
        (root / "memory").mkdir()
        (root / "connectors").mkdir()
    (b / "memory" / "notes.md").write_text("keep me")
    removed = remove_unused_folders(layout)
    assert sorted(removed) == sorted([a / "memory", a / "connectors", b / "connectors"])
    assert (b / "memory" / "notes.md").read_text() == "keep me"
    assert remove_unused_folders(layout) == []
    assert (a / "files").is_dir() and (a / "automations").is_dir()
