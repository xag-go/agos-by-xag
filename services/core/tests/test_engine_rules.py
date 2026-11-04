"""The rules for what a workspace's sandbox may see (no Docker, no Hermes)."""

import json
from pathlib import Path

import pytest

from agos_core.engine.rules import (
    DISABLED_TOOLSETS,
    TEAM_FOLDERS,
    WORKSPACE_MOUNT,
    Grant,
    Mount,
    MountRefusedError,
    build_mounts,
    check_sandbox_mounts,
    host_secret_dirs,
    profile_config,
    profile_name,
)


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    home = tmp_path / "home"
    data = tmp_path / "agos-data"
    hermes = home / ".hermes"
    for d in (
        data / "workspaces" / "a" / "files",
        data / "workspaces" / "b" / "files",
        data / "system",
        hermes / "profiles" / "agos-a",
        home / ".ssh",
        home / "Reports",
        home / "Reports" / "q3",
    ):
        d.mkdir(parents=True)
    return {"home": home, "data": data, "hermes": hermes}


def mounts_for(world: dict[str, Path], ws: str, grants: list[Grant]) -> list[Mount]:
    return build_mounts(
        world["data"] / "workspaces" / ws / "files",
        grants,
        workspaces_dir=world["data"] / "workspaces",
        forbidden=(world["data"], world["hermes"], *host_secret_dirs(world["home"])),
    )


def test_own_folder_only_by_default(world: dict[str, Path]) -> None:
    mounts = mounts_for(world, "a", [])
    # The workspace, writable; what the team uses (shown in playbooks/), read-only.
    assert [(m.container_path, m.read_only) for m in mounts] == [
        (WORKSPACE_MOUNT, False),
        *[(f"{WORKSPACE_MOUNT}/playbooks/{k}", True) for k in TEAM_FOLDERS],
    ]
    assert mounts[0].host_path == (world["data"] / "workspaces" / "a" / "files").resolve()


def test_grants_are_read_only_unless_read_write(world: dict[str, Path]) -> None:
    reports = str(world["home"] / "Reports")
    mounts = mounts_for(
        world,
        "a",
        [
            Grant("reports", reports, "read"),
            Grant("q3", str(world["home"] / "Reports" / "q3"), "read-write"),
        ],
    )
    shared = [m.spec().split(":", 1)[1] for m in mounts if m.container_path.startswith("/shared")]
    assert shared == ["/shared/reports:ro", "/shared/q3"]


@pytest.mark.parametrize(
    "target",
    [
        "home",  # contains .ssh and Hermes
        "ssh",
        "hermes",
        "profile",
        "data",
        "system",
        "other-workspace",
    ],
)
def test_private_places_are_refused(world: dict[str, Path], target: str) -> None:
    path = {
        "home": world["home"],
        "ssh": world["home"] / ".ssh",
        "hermes": world["hermes"],
        "profile": world["hermes"] / "profiles" / "agos-a",
        "data": world["data"],
        "system": world["data"] / "system",
        "other-workspace": world["data"] / "workspaces" / "b" / "files",
    }[target]
    with pytest.raises(MountRefusedError):
        mounts_for(world, "a", [Grant("x", str(path), "read")])


def test_disk_root_symlink_and_mount_syntax_are_refused(world: dict[str, Path]) -> None:
    with pytest.raises(MountRefusedError):
        mounts_for(world, "a", [Grant("x", "/", "read")])
    link = world["home"] / "innocent"
    link.symlink_to(world["home"] / ".ssh")
    with pytest.raises(MountRefusedError):
        mounts_for(world, "a", [Grant("x", str(link), "read")])
    odd = world["home"] / "a:b"
    odd.mkdir()
    with pytest.raises(MountRefusedError):
        mounts_for(world, "a", [Grant("x", str(odd), "read")])
    with pytest.raises(MountRefusedError):
        mounts_for(world, "a", [Grant("../x", str(world["home"] / "Reports"), "read")])
    with pytest.raises(MountRefusedError):
        mounts_for(world, "a", [Grant("x", "relative/path", "read")])


def test_workspace_folder_must_be_under_workspaces(world: dict[str, Path]) -> None:
    with pytest.raises(MountRefusedError):
        build_mounts(
            world["home"] / "Reports",
            [],
            workspaces_dir=world["data"] / "workspaces",
            forbidden=(world["data"],),
        )


def test_profile_config_is_locked_down(world: dict[str, Path]) -> None:
    config = profile_config(image="img:1", mounts=mounts_for(world, "a", []))
    assert config["terminal.backend"] == "docker"
    assert config["terminal.docker_mount_cwd_to_workspace"] == "false"
    assert json.loads(config["terminal.docker_forward_env"]) == []
    assert json.loads(config["terminal.credential_files"]) == []
    assert json.loads(config["terminal.docker_extra_args"]) == []
    volumes = json.loads(config["terminal.docker_volumes"])
    assert volumes[0].endswith(":/workspace")
    assert all(v.endswith(":ro") for v in volumes[1:])  # only the workspace is writable
    assert set(json.loads(config["agent.disabled_toolsets"])) == set(DISABLED_TOOLSETS)
    assert {"browser", "vision"} <= set(DISABLED_TOOLSETS)
    assert "cronjob" not in DISABLED_TOOLSETS
    assert config["approvals.mode"] == "manual"  # Hermes never self-approves


def test_profile_names() -> None:
    assert profile_name("agos-", "argan-store") == "agos-argan-store"
    long_a, long_b = "a" * 63, "a" * 62 + "b"
    assert len(profile_name("agos-", long_a)) <= 64
    assert profile_name("agos-", long_a) != profile_name("agos-", long_b)
    with pytest.raises(ValueError):
        profile_name("agos-", "../etc")
    with pytest.raises(ValueError):
        profile_name("Bad", "a")


def test_sandbox_check(world: dict[str, Path]) -> None:
    mounts = mounts_for(world, "a", [Grant("r", str(world["home"] / "Reports"), "read")])
    profile = world["hermes"] / "profiles" / "agos-a"
    team = [(str(m.host_path), m.container_path, False) for m in mounts[2:]]
    good = [
        (str(mounts[0].host_path), "/workspace", True),
        (str(mounts[1].host_path), "/shared/r", False),
        (str(profile / "skills"), "/root/.hermes/skills", False),
        *team,
    ]
    assert check_sandbox_mounts(good, mounts, profile_home=profile).ok
    # A removed folder that is still mounted.
    stale = check_sandbox_mounts(good, [mounts[0], *mounts[2:]], profile_home=profile)
    assert not stale.ok and stale.unexpected == ["/shared/r (ro)"]
    # Read-only granted, writable mounted.
    widened = [good[0], (good[1][0], "/shared/r", True), *good[2:]]
    assert not check_sandbox_mounts(widened, mounts, profile_home=profile).ok
    # The team's folders mounted writable: refused too.
    loose = [*good[:3], *[(s, d, True) for s, d, _ in team]]
    assert not check_sandbox_mounts(loose, mounts, profile_home=profile).ok
    # Another profile's files, or anything writable under /root/.hermes.
    other = world["hermes"] / "profiles" / "agos-b" / "skills"
    assert not check_sandbox_mounts(
        [*good, (str(other), "/root/.hermes/skills2", False)], mounts, profile_home=profile
    ).ok
    assert not check_sandbox_mounts(
        [*good, (str(profile / "cache"), "/root/.hermes/cache", True)], mounts, profile_home=profile
    ).ok
    # Missing grant.
    assert check_sandbox_mounts([good[0], *good[2:]], mounts, profile_home=profile).missing == [
        "/shared/r (ro)"
    ]


def test_the_brains_read_only_skills_mount_is_accepted(tmp_path: Path) -> None:
    """Hermes mounts skills.external_dirs (the AGOS Brain) read-only into the
    sandbox: accepted from the Brain's folder only, never writable, never another."""
    from agos_core.engine.rules import check_sandbox_mounts

    profile = tmp_path / "profiles" / "agos-a"
    brain = tmp_path / "brain" / "skills"
    profile.mkdir(parents=True)
    brain.mkdir(parents=True)
    ro = [(str(brain), "/root/.hermes/external_skills/0", False)]
    assert check_sandbox_mounts(ro, [], profile_home=profile, shared_skills=(brain,)).ok
    assert not check_sandbox_mounts(ro, [], profile_home=profile).ok
    rw = [(str(brain), "/root/.hermes/external_skills/0", True)]
    assert not check_sandbox_mounts(rw, [], profile_home=profile, shared_skills=(brain,)).ok
    other = [(str(tmp_path), "/root/.hermes/external_skills/0", False)]
    assert not check_sandbox_mounts(other, [], profile_home=profile, shared_skills=(brain,)).ok
