#!/usr/bin/env bash
# AGOS one-command setup for Linux and macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/xag-go/agos-by-xag/main/install.sh | bash
#   ./install.sh [options]          (from a copy of the repository)
#
# Linux (Ubuntu 22.04 / 24.04): installs AGOS on this machine (deploy/install-server.sh
# does the work). macOS: AGOS runs inside a small Ubuntu virtual machine made with
# Lima; this script makes the VM, runs the same Linux installer inside it and puts
# an `agos` command on the Mac. You open http://localhost:3000 in both cases.
#
# Every question has a default and a flag (deploy/install-server.sh --help), so
# `install.sh --yes` installs with no questions at all.
#
# Which AGOS: the newest stable release (a vX.Y.Z tag, docs/releases.md), checked
# against its signature before anything runs. AGOS_CHANNEL=beta takes betas too;
# AGOS_REF=<branch or tag> installs that instead (AGOS_CHANNEL=main follows a branch).
set -euo pipefail

# The one place the public repository is named (owner/name on GitHub).
AGOS_GITHUB_REPO="xag-go/agos-by-xag"
AGOS_REPO_URL="${AGOS_REPO_URL:-https://github.com/$AGOS_GITHUB_REPO.git}"
AGOS_REF="${AGOS_REF:-}"
AGOS_CHANNEL="${AGOS_CHANNEL:-}"
# Raw URL of this script in that repository (what the Mac's VM downloads).
AGOS_RAW_URL="${AGOS_RAW_URL:-https://raw.githubusercontent.com/$AGOS_GITHUB_REPO/${AGOS_REF:-main}/install.sh}"

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
# Questions read the keyboard, also when this script arrives through a pipe.
tty_ok() { [[ -r /dev/tty ]] && { : </dev/tty; } 2>/dev/null; }
ask_yes() { # ask_yes "question" default(y|n)
  local answer="" default="$2"
  if [[ "${AGOS_YES:-0}" == 1 ]] || ! tty_ok; then [[ "$default" == y ]]; return; fi
  read -r -p "$1 [$( [[ "$default" == y ]] && echo Y/n || echo y/N )] " answer </dev/tty || true
  answer="${answer:-$default}"
  [[ "$answer" =~ ^[Yy] ]]
}
for arg in "$@"; do [[ "$arg" == "--yes" || "$arg" == "-y" ]] && export AGOS_YES=1; done

# The release to install (AGOS_REF) and the channel agos update follows afterwards.
newest_release() { # newest_release stable|beta: the newest release tag on the repository ("" = none)
  local re='^v[0-9]+\.[0-9]+\.[0-9]+$'
  [[ "$1" == beta ]] && re='^v[0-9]+\.[0-9]+\.[0-9]+(-(beta|rc)\.[0-9]+)?$'
  # Version order with a beta before its release ("~" sorts first in sort -V).
  { git ls-remote --tags --refs "$AGOS_REPO_URL" 'v*' 2>/dev/null | sed 's|.*refs/tags/||' | grep -E "$re" || true; } |
    sed -E 's/-(beta|rc)\./~\1./' | sort -V | sed 's/~/-/' | awk 'END {print}'
}
pick_release() {
  if [[ -n "$AGOS_REF" ]]; then
    # A ref given by hand: a release tag keeps the stable channel, a branch follows it.
    if [[ -z "$AGOS_CHANNEL" ]]; then
      if [[ "$AGOS_REF" =~ ^v[0-9] ]]; then AGOS_CHANNEL=stable; else AGOS_CHANNEL=main; fi
    fi
    return 0
  fi
  AGOS_CHANNEL="${AGOS_CHANNEL:-stable}"
  [[ "$AGOS_CHANNEL" == main ]] || AGOS_REF="$(newest_release "$AGOS_CHANNEL")"
  if [[ -z "$AGOS_REF" ]]; then
    [[ "$AGOS_CHANNEL" == main ]] || echo "  No $AGOS_CHANNEL release is published yet: installing the main branch." >&2
    AGOS_REF=main  # the channel stays: the first release past this code is the next update
  fi
}

# ---------------------------------------------------------------- macOS ----------
mac_install() {
  local vm="${AGOS_VM_NAME:-agos}" cpus="${AGOS_VM_CPUS:-4}" mem="${AGOS_VM_MEMORY:-8}" disk="${AGOS_VM_DISK:-60}"
  say "AGOS on macOS: a small Ubuntu virtual machine (Lima) runs AGOS"
  [[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 13 ]] || die "macOS 13 (Ventura) or newer is needed."
  if ! command -v brew >/dev/null; then
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [[ -x "$b" ]] && eval "$("$b" shellenv)"; done
  fi
  if ! command -v brew >/dev/null; then
    ask_yes "Homebrew (the Mac's package manager) is needed to install Lima. Install Homebrew now?" y \
      || die "Install Homebrew from https://brew.sh, then run this again."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [[ -x "$b" ]] && eval "$("$b" shellenv)"; done
  fi
  command -v limactl >/dev/null || { say "Installing Lima"; brew install lima; }

  if ! limactl list -q 2>/dev/null | grep -qx "$vm"; then
    say "Creating the VM '$vm' (Ubuntu 24.04, $cpus CPUs, ${mem} GB RAM, ${disk} GB disk)"
    # No Mac folders shared into the VM: AGOS keeps its data inside the VM.
    # Lima forwards the VM's 127.0.0.1 ports to the Mac's 127.0.0.1 by itself.
    limactl create --tty=false --name="$vm" --cpus="$cpus" --memory="$mem" --disk="$disk" \
      --set '.mounts=[]' template://ubuntu-24.04
  fi
  limactl list "$vm" --format '{{.Status}}' | grep -q Running || limactl start "$vm"

  say "Installing AGOS inside the VM"
  # The Lima user has sudo without a password inside the VM. Any flags given here
  # go to the Linux installer as they are.
  # The release is picked (and checked) inside the VM, where git is.
  local env=(AGOS_REPO_URL="$AGOS_REPO_URL" AGOS_YES="${AGOS_YES:-0}" AGOS_HOST_OS=macos)
  for v in AGOS_REF AGOS_CHANNEL AGOS_VERIFY AGOS_USER AGOS_USER_MODE AGOS_DATA_DIR AGOS_PROVIDER AGOS_VOICE AGOS_REMOTE AGOS_SANDBOXD; do
    [[ -n "${!v:-}" ]] && env+=("$v=${!v}")
  done
  if [[ -n "${AGOS_PROVIDER_KEY:-}" ]]; then
    # The key goes through the VM's standard input, never a command line.
    printf '%s' "$AGOS_PROVIDER_KEY" | limactl shell "$vm" -- bash -c 'umask 077; cat > /tmp/agos-provider-key'
    env+=(AGOS_PROVIDER_KEY_FILE=/tmp/agos-provider-key)
  fi
  local cmd
  cmd="curl -fsSL $(printf '%q' "$AGOS_RAW_URL") -o /tmp/agos-install.sh && env $(printf '%q ' "${env[@]}") bash /tmp/agos-install.sh $(printf '%q ' "$@")"
  limactl shell "$vm" -- bash -c "$cmd"

  say "The 'agos' command on this Mac"
  local bin=/usr/local/bin
  [[ -w "$bin" ]] || bin="$(brew --prefix)/bin"
  cat > "$bin/agos" <<EOF
#!/bin/bash
# AGOS runs in the Lima VM '$vm'; this forwards every agos command into it.
VM="$vm"
case "\${1:-}" in
  open) open http://localhost:3000; exit ;;
  vm-start) limactl start "\$VM"; exit ;;
  vm-stop) limactl stop "\$VM"; exit ;;
esac
if ! limactl list "\$VM" --format '{{.Status}}' 2>/dev/null | grep -q Running; then
  [[ "\${1:-}" == uninstall ]] || limactl start "\$VM" >/dev/null
fi
if [[ "\${1:-}" == uninstall ]]; then
  read -r -p "Delete the whole AGOS virtual machine '\$VM' with all its data? [y/N] " a
  [[ "\$a" =~ ^[Yy] ]] || { echo "Kept. (To remove AGOS but keep the VM: limactl shell \$VM -- agos uninstall)"; exit 0; }
  limactl delete -f "\$VM" && rm -f "\$0" && echo "AGOS and its VM are removed."; exit
fi
exec limactl shell "\$VM" -- agos "\$@"
EOF
  chmod +x "$bin/agos"
  # Start the VM again after the Mac restarts (Lima's own launchd service).
  limactl start-at-login "$vm" --enabled >/dev/null 2>&1 || echo "  (could not set the VM to start at login; run: limactl start-at-login $vm)"
  say "Done. Open http://localhost:3000 on this Mac (or type: agos open)."
}

# ---------------------------------------------------------------- Linux ----------
linux_install() {
  local here src
  here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || here=""
  local sudo=()
  [[ $EUID -eq 0 ]] || sudo=(sudo)
  if [[ ${#sudo[@]} -gt 0 ]]; then
    command -v sudo >/dev/null || die "Run this as root, or install sudo first."
    echo "AGOS installs system services, so it needs your admin (sudo) password once."
    # shellcheck disable=SC2024  # the password comes from the keyboard, also under a pipe
    sudo -v </dev/tty 2>/dev/null || sudo -v || die "sudo did not work."
  fi
  if [[ -n "$here" && -f "$here/deploy/install-server.sh" && -f "$here/deploy/hermes.pin" ]]; then
    src="$here"  # run from a copy of the repository
  else
    command -v git >/dev/null || { "${sudo[@]}" apt-get update -qq && "${sudo[@]}" apt-get install -y -qq git ca-certificates; } \
      || die "git is needed (sudo apt-get install git)."
    src="$(mktemp -d "${TMPDIR:-/tmp}/agos-setup.XXXXXX")"
    pick_release
    say "Downloading AGOS $AGOS_REF from $AGOS_REPO_URL"
    # Only the installer is needed here (a mirror without shallow clones gets a full one).
    git clone -q --depth 1 --branch "$AGOS_REF" "$AGOS_REPO_URL" "$src" 2>/dev/null \
      || { rm -rf "$src" && git clone -q --branch "$AGOS_REF" "$AGOS_REPO_URL" "$src"; } \
      || die "Could not download $AGOS_REPO_URL ($AGOS_REF)."
    if [[ "$AGOS_REF" =~ ^v[0-9] ]]; then
      # The release's own checker, run on what was downloaded, before any of it runs as root.
      bash "$src/deploy/release-verify.sh" "$AGOS_REF" "$(git -C "$src" rev-parse HEAD)" "$src/.cosign" \
        || die "AGOS $AGOS_REF was not installed: it is not the signed release (see above)."
    fi
    chmod -R a+rX "$src"
  fi
  [[ -n "$AGOS_REF" ]] || pick_release
  # A key given in the environment goes to the installer in a private file, never
  # on a command line (where other users could see it).
  local key_file="${AGOS_PROVIDER_KEY_FILE:-}"
  if [[ -n "${AGOS_PROVIDER_KEY:-}" ]]; then
    key_file="$(umask 077; mktemp "${TMPDIR:-/tmp}/agos-key.XXXXXX")"
    printf '%s' "$AGOS_PROVIDER_KEY" > "$key_file"
  fi
  # The engine runs as root; it remembers who ran it for the "current user" choice.
  exec "${sudo[@]}" env AGOS_REPO_URL="$AGOS_REPO_URL" AGOS_REF="$AGOS_REF" AGOS_CHANNEL="$AGOS_CHANNEL" \
    AGOS_VERIFY="${AGOS_VERIFY:-}" \
    AGOS_INVOKING_USER="${SUDO_USER:-$(id -un)}" \
    "AGOS_YES=${AGOS_YES:-0}" "AGOS_USER=${AGOS_USER:-}" "AGOS_USER_MODE=${AGOS_USER_MODE:-}" \
    "AGOS_DATA_DIR=${AGOS_DATA_DIR:-}" "AGOS_PROVIDER=${AGOS_PROVIDER:-}" \
    "AGOS_PROVIDER_KEY_FILE=$key_file" \
    "AGOS_VOICE=${AGOS_VOICE:-}" "AGOS_REMOTE=${AGOS_REMOTE:-}" "AGOS_HOST_OS=${AGOS_HOST_OS:-linux}" \
    "AGOS_SANDBOXD=${AGOS_SANDBOXD:-}" \
    bash "$src/deploy/install-server.sh" "$@"
}

case "$(uname -s)" in
  Darwin) mac_install "$@" ;;
  Linux) linux_install "$@" ;;
  *) die "Unsupported system $(uname -s). On Windows use install.ps1 (see docs/INSTALL.md)." ;;
esac
