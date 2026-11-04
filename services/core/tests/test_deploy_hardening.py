"""The shell scripts that run on the server keep their secrets out of reach of other
local users (security audit 2.6 / F9, 1.2 + 10.2 / F7)."""

import re
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[3] / "deploy"
# What runs on a real server (the VM / container test harnesses run throwaway copies).
SERVER_SCRIPTS = ("agos", "install-server.sh", "verify-server.sh")


def test_the_internal_token_never_goes_on_a_curl_command_line() -> None:
    """Any local user reads a process's argv (ps, /proc/<pid>/cmdline): the token
    reaches curl through a pipe (`-H @<(printf ...)`), never as `-H "x-agos-internal: $t"`."""
    on_argv = re.compile(r"""-H\s+\\?["']x-agos-internal:""")
    for name in SERVER_SCRIPTS:
        text = (DEPLOY / name).read_text()
        assert not on_argv.search(text), name
        if "x-agos-internal" in text:
            assert '-H @<(printf "x-agos-internal: %s\\n"' in text or (
                "-H @<(printf 'x-agos-internal: %s\\n'" in text
            ), name


def test_hermes_installer_is_saved_to_a_fresh_private_file() -> None:
    """A predictable /tmp name could be created first by another local user."""
    for name in ("agos", "install-server.sh"):
        text = (DEPLOY / name).read_text()
        assert "/tmp/hermes-install-" not in text, name  # noqa: S108 - the old path
        assert "mktemp" in text, name


def test_the_https_proxy_sets_the_tailscale_identity_itself() -> None:
    """With Caddy in front (deploy/https-setup.sh), the web trusts Tailscale-User-Login:
    Caddy must set it from Tailscale's own answer, never pass the client's on."""
    text = (DEPLOY / "https-setup.sh").read_text()
    caddyfile = text.split("cat > /etc/caddy/Caddyfile <<EOF", 1)[1].split("\nEOF", 1)[0]
    assert "\n  tailscale_auth\n" in caddyfile
    assert "header_up Tailscale-User-Login {http.auth.user.tailscale_user}" in caddyfile
    assert "header_up Tailscale-User-Name {http.auth.user.tailscale_name}" in caddyfile
    assert "header_up -Tailscale-User-Profile-Pic" in caddyfile
    # A wildcard delete runs AFTER Caddy's sets and would remove the login it set.
    assert "-Tailscale-User-*" not in caddyfile


def test_caddy_is_built_from_pinned_checked_sources() -> None:
    text = (DEPLOY / "https-setup.sh").read_text()
    assert "caddyserver.com/api/download" not in text
    assert re.search(r'CADDY_BUILDER="caddy:[0-9.]+-builder@sha256:[0-9a-f]{64}"', text)
    assert re.search(r'CADDY_VERSION="v\d+\.\d+\.\d+"', text)
    for module in re.findall(r'--with "([^"]+)"', text):
        assert re.fullmatch(r"[a-z0-9./-]+@v[0-9][0-9A-Za-z.-]*", module), module
