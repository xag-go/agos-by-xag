"""Settings from the environment. Invalid config stops the process at start,
printing variable names, never values."""

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from agos_core.engine import unit_limits

# AGOS's own sandbox image (docker/sandbox/Dockerfile): Node, Python/uv, git, gh, ffmpeg,
# a non-root default user, arm64 + amd64. `scripts/build-sandbox.sh` builds it.
DEFAULT_SANDBOX_IMAGE = "agos-sandbox:1"
# Where AGOS keeps its data when AGOS_DATA_DIR isn't set: ~/agos-data.
DEFAULT_DATA_DIR_NAME = "agos-data"
# Hermes version AGOS is tested with (see docs/hermes-upgrade.md).
HERMES_TESTED_VERSION = "0.22.2"


@dataclass(frozen=True)
class EngineConfig:
    """Hermes Agent, driven by agos-core (ADR 0010). Absent = no engine: the app
    works with its data only (demo mode, tests)."""

    hermes_bin: str
    docker_bin: str
    hermes_home: Path
    profile_prefix: str
    sandbox_image: str
    host_home: Path
    # One Hermes root per workspace (ADR 0020), the only layout: the Co-Founder is the
    # root's default profile, its team members are profiles under it. The shared
    # home (`hermes_home`) only keeps General Settings' login and keys.
    roots_dir: Path
    # The Hermes install's own runtime (`<install home>/tools`). Every Hermes process
    # AGOS runs gets it as HERMES_RUNTIME_DIR: a root outside ~/.hermes would
    # otherwise install a Python of its own and rewrite the shared launcher.
    runtime_dir: Path | None = None
    # How a root's gateway runs: Hermes's systemd user service (it restarts it), or
    # ("spawn", tests only) a process AGOS starts once and nothing restarts.
    gateway_supervisor: str = "systemd"
    # Hermes's own Managed Scope (hermes_cli/managed_scope.py): the settings that
    # are ONE value for every workspace (fallback chain, loop detector, run budget,
    # Kanban's cap, time limits, timezone) live in one `config.yaml` here, which
    # every Hermes process AGOS runs reads as HERMES_MANAGED_DIR (actions/
    # hermes_managed.py). Default: beside the roots (<roots>/../hermes-managed).
    managed_dir: Path | None = None
    # The git checkout `hermes update` updates (docs/hermes-upgrade.md: the launcher
    # at hermes_bin runs it). Default ~/.hermes/hermes-agent; tests point elsewhere.
    hermes_src: Path | None = None
    # Resource limits written into each gateway's drop-in (engine/unit_limits.py):
    # scaled to this machine's RAM, overridable per value, None = turned off
    # (AGOS_GATEWAY_LIMITS=off).
    gateway_limits: unit_limits.GatewayLimits | None = None
    # The sandbox broker (ADR 0025 step 4: engine/cage.py + engine/sandboxd.py).
    # "required": no working bwrap = no gateway starts (code cage_refused); "off":
    # the owner's choice, gateways keep the real Docker socket. `_engine` reads
    # AGOS_SANDBOXD (default "required"; "auto"/"on" read as "required"); the
    # dataclass default is "off" so a test's hand-built EngineConfig never cages or
    # starts a daemon unless it says so.
    sandboxd: str = "off"
    # Where the per-workspace broker sockets live (short paths, per boot):
    # /run/user/<uid>/agos-sandboxd unless AGOS_SANDBOXD_RUN_DIR says otherwise.
    sandboxd_run_dir: Path | None = None
    # The broker's systemd user unit (AGOS_SANDBOXD_UNIT): each AGOS on this user
    # (live, the staging copy) runs its own, or one replaces the other's.
    sandboxd_unit: str = "agos-sandboxd.service"
    # AGOS's own secrets the cage hides from every gateway (engine/cage.py argv):
    # the internal token file, and AGOS's system folder (agos.db, master.key).
    cage_hidden_files: tuple[Path, ...] = ()
    cage_hidden_dirs: tuple[Path, ...] = ()
    # bwrap made its sandbox here once (engine/sandbox_broker.py marker): a later
    # refusal says so. None = <roots>/../system/cage.ok.
    cage_ok_file: Path | None = None

    @property
    def managed_home(self) -> Path:
        return self.managed_dir or self.roots_dir.parent / "hermes-managed"

    def runtime_env(self) -> dict[str, str]:
        """HERMES_RUNTIME_DIR (see runtime_dir) and HERMES_MANAGED_DIR (see
        managed_dir) for every Hermes process AGOS starts."""
        env = {"HERMES_RUNTIME_DIR": str(self.runtime_dir)} if self.runtime_dir else {}
        env["HERMES_MANAGED_DIR"] = str(self.managed_home)
        return env


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    internal_token_file: Path
    documents_url: str | None
    engine: EngineConfig | None = None
    # Where the SLI probes look (actions/slis.py); None = no probe (tests, rigs).
    slo_core_url: str | None = None
    slo_web_url: str | None = None


class ConfigError(RuntimeError):
    pass


def data_dir_of(source: dict[str, str]) -> str:
    """AGOS_DATA_DIR, else ~/agos-data (the home of the user AGOS runs as)."""
    raw = (source.get("AGOS_DATA_DIR") or "").strip()
    if raw:
        return raw
    home = source.get("HOME") or str(Path.home())
    return str(Path(home) / DEFAULT_DATA_DIR_NAME)


def _engine(source: dict[str, str]) -> EngineConfig | None:
    kind = source.get("AGOS_ENGINE", "")
    if kind in ("", "none"):
        return None
    if kind != "hermes":
        raise ConfigError("AGOS_ENGINE must be 'hermes' or 'none'")
    # Hermes keeps every profile under <HOME>/.hermes/profiles whatever
    # HERMES_HOME says, so the only setting is the home it runs as.
    host_home = Path(source.get("AGOS_HERMES_USER_HOME") or source.get("HOME") or Path.home())
    if not host_home.is_absolute():
        raise ConfigError("AGOS_HERMES_USER_HOME must be an absolute path")
    hermes_home = host_home / ".hermes"
    hermes_bin = source.get("AGOS_HERMES_BIN") or shutil.which("hermes") or ""
    docker_bin = source.get("AGOS_DOCKER_BIN") or shutil.which("docker") or ""
    if not hermes_bin:
        raise ConfigError("AGOS_HERMES_BIN: the hermes command was not found")
    if not docker_bin:
        raise ConfigError("AGOS_DOCKER_BIN: the docker command was not found")
    prefix = source.get("AGOS_PROFILE_PREFIX") or "agos-"
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,15}", prefix):
        raise ConfigError("AGOS_PROFILE_PREFIX must be lowercase letters, digits or '-'")
    roots_dir, runtime_dir = _roots(source, hermes_home)
    managed_raw = (source.get("AGOS_HERMES_MANAGED_DIR") or "").strip()
    if managed_raw and not Path(managed_raw).is_absolute():
        raise ConfigError("AGOS_HERMES_MANAGED_DIR must be an absolute path")
    return EngineConfig(
        hermes_bin=hermes_bin,
        docker_bin=docker_bin,
        hermes_home=hermes_home,
        profile_prefix=prefix,
        sandbox_image=source.get("AGOS_SANDBOX_IMAGE") or DEFAULT_SANDBOX_IMAGE,
        host_home=host_home,
        roots_dir=roots_dir,
        runtime_dir=runtime_dir,
        gateway_supervisor=_supervisor(source),
        managed_dir=Path(managed_raw) if managed_raw else None,
        hermes_src=Path(src_raw) if (src_raw := source.get("AGOS_HERMES_SRC")) else None,
        gateway_limits=_gateway_limits(source),
        sandboxd=_sandboxd(source),
        sandboxd_run_dir=_sandboxd_run_dir(source),
        sandboxd_unit=_sandboxd_unit(source),
        cage_hidden_files=(_token_file(source),),
        cage_hidden_dirs=(Path(data_dir_of(source)) / "system",),
        cage_ok_file=Path(data_dir_of(source)) / "system" / "cage.ok",
    )


def _token_file(source: dict[str, str]) -> Path:
    token_file = source.get("AGOS_INTERNAL_TOKEN_FILE") or str(
        Path(data_dir_of(source)) / "system" / "internal.token"
    )
    if not Path(token_file).is_absolute():
        raise ConfigError("AGOS_INTERNAL_TOKEN_FILE must be an absolute path")
    return Path(token_file)


def _sandboxd(source: dict[str, str]) -> str:
    """ "required" (the default) or the owner's "off" (audit F9: safe with nothing to
    configure). The older "auto" and "on" read as "required": neither may start a
    gateway uncaged any more (engine/cage.py `enabled`)."""
    value = (source.get("AGOS_SANDBOXD") or "required").strip().lower()
    if value not in ("required", "auto", "on", "off"):
        raise ConfigError("AGOS_SANDBOXD must be 'required' (the default) or 'off'")
    return "off" if value == "off" else "required"


def _sandboxd_run_dir(source: dict[str, str]) -> Path | None:
    """Inside /run/user/<uid>/agos-sandboxd (staging: its `stg/`): every gateway's
    cage hides that family folder whole (engine/cage.py argv), so a run dir
    beside it would leave this instance's sockets in reach of the other's cages."""
    raw = (source.get("AGOS_SANDBOXD_RUN_DIR") or "").strip()
    if not raw:
        return None
    if not Path(raw).is_absolute():
        raise ConfigError("AGOS_SANDBOXD_RUN_DIR must be an absolute path")
    path = Path(os.path.normpath(raw))
    family = Path(f"/run/user/{os.getuid()}/agos-sandboxd")
    if not path.is_relative_to(family):
        raise ConfigError(f"AGOS_SANDBOXD_RUN_DIR must be {family} or a folder inside it")
    return path


def _sandboxd_unit(source: dict[str, str]) -> str:
    value = (source.get("AGOS_SANDBOXD_UNIT") or "agos-sandboxd.service").strip()
    # Only a broker unit name: ensure() writes this unit, so another AGOS unit
    # (agos-update-watch.service, ...) must never be accepted.
    if not re.fullmatch(r"agos-[a-z0-9-]*sandboxd\.service", value):
        raise ConfigError("AGOS_SANDBOXD_UNIT must be an agos-<name>-sandboxd.service unit name")
    return value


def _gateway_limits(source: dict[str, str]) -> unit_limits.GatewayLimits | None:
    try:
        return unit_limits.from_env(source)
    except unit_limits.LimitsError as error:
        raise ConfigError(str(error)) from error


def _supervisor(source: dict[str, str]) -> str:
    value = (source.get("AGOS_HERMES_GATEWAY_SUPERVISOR") or "systemd").strip().lower()
    if value not in ("systemd", "spawn"):
        raise ConfigError("AGOS_HERMES_GATEWAY_SUPERVISOR must be 'systemd' or 'spawn'")
    return value


def _roots(source: dict[str, str], hermes_home: Path) -> tuple[Path, Path | None]:
    """Where the workspaces' Hermes roots live (AGOS_HERMES_ROOTS, default
    <data folder>/hermes) and the install's runtime (AGOS_HERMES_RUNTIME_DIR,
    default <hermes home>/tools)."""
    raw = (source.get("AGOS_HERMES_ROOTS") or "").strip()
    data_dir = data_dir_of(source)
    runtime_raw = (source.get("AGOS_HERMES_RUNTIME_DIR") or "").strip()
    runtime = Path(runtime_raw) if runtime_raw else hermes_home / "tools"
    if runtime_raw and not runtime.is_absolute():
        raise ConfigError("AGOS_HERMES_RUNTIME_DIR must be an absolute path")
    if raw.lower() in ("off", "none", "0"):
        # The shared-home layout is gone (ADR 0020): every workspace has a root.
        raise ConfigError("AGOS_HERMES_ROOTS can't be off: every workspace runs on its own root")
    roots = Path(raw) if raw else Path(data_dir) / "hermes"
    if not roots.is_absolute():
        raise ConfigError("AGOS_HERMES_ROOTS must be an absolute path")
    # Hermes maps any home under ~/.hermes back to ~/.hermes (get_default_hermes_root):
    # roots there would all share one root again.
    try:
        roots.resolve().relative_to(hermes_home.resolve())
    except ValueError:
        return roots, runtime
    raise ConfigError("AGOS_HERMES_ROOTS must be outside the Hermes home (~/.hermes)")


def _probe_url(source: dict[str, str], name: str, default: str, *, live: bool) -> str | None:
    """AGOS_SLO_<name>_URL; an install with Hermes probes its usual address unless
    it says "off" (docs/compliance/sre.md)."""
    raw = (source.get(f"AGOS_SLO_{name}_URL") or "").strip()
    if raw.lower() == "off":
        return None
    if raw and not re.fullmatch(r"https?://[^\s/]+(/[^\s]*)?", raw):
        raise ConfigError(f"AGOS_SLO_{name}_URL must be an http(s) address or 'off'")
    return raw.rstrip("/") or (default if live else None)


def load_settings(env: dict[str, str] | None = None) -> Settings:
    source = env if env is not None else dict(os.environ)
    data_dir = data_dir_of(source)
    if not Path(data_dir).is_absolute():
        raise ConfigError("AGOS_DATA_DIR must be an absolute path")
    token_file = _token_file(source)
    return Settings(
        data_dir=Path(data_dir),
        internal_token_file=token_file,
        documents_url=source.get("AGOS_DOCUMENTS_URL") or None,
        engine=(engine := _engine(source)),
        slo_core_url=_probe_url(source, "CORE", "http://127.0.0.1:8766", live=engine is not None),
        slo_web_url=_probe_url(source, "WEB", "http://127.0.0.1:3000", live=engine is not None),
    )
