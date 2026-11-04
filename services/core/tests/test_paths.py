"""Mandatory test 2 (ARCHITECTURE §12): `..`, absolute paths and symlinks outside
the roots are rejected, for reads and writes."""

from pathlib import Path

import pytest

from agos_core.storage.paths import PathOutsideRootsError, Roots, make_roots, resolve_safe_path


@pytest.fixture
def tree(tmp_path: Path) -> dict[str, Path]:
    tmp = tmp_path.resolve()
    workspace = tmp / "workspaces" / "investor"
    shared = tmp / "reports"
    outside = tmp / "workspaces" / "ecommerce"
    for d in (workspace, shared, outside):
        d.mkdir(parents=True)
    (workspace / "notes.md").write_text("ok")
    (shared / "q3.csv").write_text("ok")
    (outside / "secret.md").write_text("no")
    (workspace / "link-out").symlink_to(outside)
    (workspace / "file-out.md").symlink_to(outside / "secret.md")
    (workspace / "link-in.md").symlink_to(workspace / "notes.md")
    return {"tmp": tmp, "workspace": workspace, "shared": shared, "outside": outside}


def roots(t: dict[str, Path]) -> Roots:
    return make_roots(write=[t["workspace"]], read=[t["shared"]])


def test_inside_relative_and_absolute(tree: dict[str, Path]) -> None:
    ws = tree["workspace"]
    assert resolve_safe_path(roots(tree), "notes.md", "read") == ws / "notes.md"
    assert resolve_safe_path(roots(tree), str(ws / "notes.md"), "write") == ws / "notes.md"
    assert (
        resolve_safe_path(roots(tree), "new/deep/file.txt", "write")
        == ws / "new" / "deep" / "file.txt"
    )


def test_read_only_root(tree: dict[str, Path]) -> None:
    file = tree["shared"] / "q3.csv"
    assert resolve_safe_path(roots(tree), str(file), "read") == file
    with pytest.raises(PathOutsideRootsError):
        resolve_safe_path(roots(tree), str(file), "write")


@pytest.mark.parametrize("mode", ["read", "write"])
@pytest.mark.parametrize(
    "attempt",
    [
        "../ecommerce/secret.md",
        "../../",
        "a/../../ecommerce",
        "..",
        "/etc/passwd",
        "/",
        "link-out/secret.md",
        "link-out",
        "file-out.md",
        "link-out/new.txt",
        "notes.md\0.png",
    ],
)
def test_escapes_are_rejected(tree: dict[str, Path], mode: str, attempt: str) -> None:
    with pytest.raises(PathOutsideRootsError):
        resolve_safe_path(roots(tree), attempt, mode)  # type: ignore[arg-type]


def test_outside_absolute(tree: dict[str, Path]) -> None:
    for attempt in (tree["outside"] / "secret.md", tree["tmp"]):
        with pytest.raises(PathOutsideRootsError):
            resolve_safe_path(roots(tree), str(attempt), "read")


def test_symlink_inside_is_followed(tree: dict[str, Path]) -> None:
    assert resolve_safe_path(roots(tree), "link-in.md", "read") == tree["workspace"] / "notes.md"


def test_same_prefix_sibling_is_outside(tree: dict[str, Path]) -> None:
    sibling = Path(f"{tree['workspace']}-evil")
    sibling.mkdir()
    with pytest.raises(PathOutsideRootsError):
        resolve_safe_path(roots(tree), str(sibling), "read")


def test_error_does_not_echo_the_path(tree: dict[str, Path]) -> None:
    with pytest.raises(PathOutsideRootsError) as error:
        resolve_safe_path(roots(tree), "/etc/IGNORE_PREVIOUS_INSTRUCTIONS", "read")
    assert "IGNORE" not in str(error.value)


def test_no_roots_allows_nothing() -> None:
    with pytest.raises(PathOutsideRootsError):
        resolve_safe_path(make_roots(), "x", "read")
