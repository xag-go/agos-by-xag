#!/usr/bin/env bash
# The gateways' cage (engine/cage.py, docs/adr/0025) on this machine, for the
# installer. AGOS requires it (audit F9): no working cage = no workspace's agents.
#
#   cage-setup.sh install          as root: bubblewrap from the system's package
#                                  manager (apt-get, dnf, zypper, pacman, apk), user
#                                  namespaces where the kernel has them off (Debian's
#                                  unprivileged_userns_clone, max_user_namespaces=0),
#                                  and bwrap's AppArmor profile (bwrap-apparmor.sh,
#                                  Ubuntu 24.04's user-namespace restriction)
#   cage-setup.sh self-test USER   the cage's own kind of bwrap run, as USER (the AGOS
#                                  user). On failure it prints
#                                    ERROR cage_refused: <what is wrong>
#                                    What to do: <the exact fix for this machine>
#                                  and exits 3 (docs/errors.md `cage_refused`).
#
# bwrap maps only the caller's own uid into its namespace: no setuid helper and no
# uidmap/newuidmap package is needed. `install` never stops by itself; the
# self-test decides. Test hooks: AGOS_PROC_SYS (default /proc/sys), AGOS_SYSCTL_DIR
# (/etc/sysctl.d), AGOS_APPARMOR_DIR (/etc/apparmor.d).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PROC_SYS="${AGOS_PROC_SYS:-/proc/sys}"
SYSCTL_DIR="${AGOS_SYSCTL_DIR:-/etc/sysctl.d}"
PROFILES="${AGOS_APPARMOR_DIR:-/etc/apparmor.d}"
PROFILE=bwrap-userns-restrict
SYSCTL_FILE="$SYSCTL_DIR/60-agos-userns.conf"
# bwrap-apparmor.sh reads the same machine.
export AGOS_APPARMOR_DIR="$PROFILES"
export AGOS_USERNS_RESTRICT="${AGOS_USERNS_RESTRICT:-$PROC_SYS/kernel/apparmor_restrict_unprivileged_userns}"
CODE=cage_refused
REFUSED=3

package_manager() {
  local p
  for p in apt-get dnf zypper pacman apk; do
    command -v "$p" >/dev/null 2>&1 && { echo "$p"; return 0; }
  done
  return 1
}

install_command() { # the command that installs bubblewrap with package manager $1
  case "$1" in
    apt-get) echo "apt-get install -y -q bubblewrap" ;;
    dnf) echo "dnf install -y bubblewrap" ;;
    zypper) echo "zypper --non-interactive install bubblewrap" ;;
    pacman) echo "pacman -S --noconfirm --needed bubblewrap" ;;
    apk) echo "apk add bubblewrap" ;;
  esac
}

knob() { cat "$PROC_SYS/$1" 2>/dev/null; } # a kernel setting ("" when it doesn't exist)

# The user-namespace settings some kernels ship turned off, and their "on" value.
KNOBS=("kernel/unprivileged_userns_clone=1" "user/max_user_namespaces=15000")

cmd_install() {
  if command -v bwrap >/dev/null 2>&1; then
    echo "  [ok] bubblewrap is installed ($(command -v bwrap))"
  else
    local pm
    if pm="$(package_manager)"; then
      echo "  installing bubblewrap ($pm)"
      local words; read -r -a words <<<"$(install_command "$pm")"
      "${words[@]}" || echo "  WARNING: $pm could not install bubblewrap (the self-test below says what to do)" >&2
    else
      echo "  WARNING: no known package manager to install bubblewrap with" >&2
    fi
  fi
  local entry name want key
  for entry in "${KNOBS[@]}"; do
    name="${entry%=*}"; want="${entry#*=}"; key="${name//\//.}"
    if [[ "$(knob "$name")" == 0 ]]; then
      echo "  turning on user namespaces ($key = $want, kept in $SYSCTL_FILE)"
      mkdir -p "$SYSCTL_DIR" && printf '# Written by the AGOS installer: the workspaces'"'"' cage (bwrap) needs it.\n%s = %s\n' "$key" "$want" >> "$SYSCTL_FILE"
      printf '%s\n' "$want" > "$PROC_SYS/$name" 2>/dev/null || echo "  WARNING: $key could not be changed now" >&2
    fi
  done
  bash "$HERE/bwrap-apparmor.sh"
  return 0
}

# The cage's kind of run: a mount namespace over the whole system with a masked
# folder, as engine/cage.py builds it (bwrap --dev-bind / / ... --tmpfs ...).
probe() {
  local who="$1"
  if [[ "$(id -un)" == "$who" ]]; then
    bwrap --dev-bind / / --die-with-parent --tmpfs /tmp -- true
  else
    runuser -u "$who" -- bwrap --dev-bind / / --die-with-parent --tmpfs /tmp -- true
  fi
}

refuse() { # refuse "what is wrong" "what to do"
  printf '\nERROR %s: Workspace isolation (the bwrap cage around each workspace'"'"'s agents) can'"'"'t run on this machine: %s.\n' "$CODE" "$1" >&2
  [[ -z "${SAID:-}" ]] || printf '  bwrap said: %s\n' "$SAID" >&2
  printf 'What to do: %s\n' "$2" >&2
  printf '  Then run the installer again (finished steps are skipped).\n' >&2
  printf '  More: docs/troubleshooting.md, "The cage refused to start" (code %s in docs/errors.md).\n' "$CODE" >&2
  exit "$REFUSED"
}

cmd_self_test() {
  local who="${1:?self-test needs the AGOS user}" out entry name want key pm
  if ! command -v bwrap >/dev/null 2>&1; then
    if pm="$(package_manager)"; then
      refuse "bubblewrap (bwrap) is not installed" "sudo $(install_command "$pm")"
    fi
    refuse "bubblewrap (bwrap) is not installed" "install your system's bubblewrap package (it provides /usr/bin/bwrap)"
  fi
  if out="$(probe "$who" 2>&1)"; then
    echo "  [ok] the cage works here (bwrap, as $who)"
    return 0
  fi
  SAID="$(head -c 300 <<<"$out" | head -1)"
  for entry in "${KNOBS[@]}"; do
    name="${entry%=*}"; want="${entry#*=}"; key="${name//\//.}"
    if [[ "$(knob "$name")" == 0 ]]; then
      refuse "the kernel has user namespaces turned off ($key = 0)" \
        "echo '$key = $want' | sudo tee $SYSCTL_FILE && sudo sysctl --system"
    fi
  done
  if [[ "$(cat "$AGOS_USERNS_RESTRICT" 2>/dev/null)" == 1 ]]; then
    if [[ -e "$PROFILES/disable/$PROFILE" ]]; then
      refuse "AppArmor blocks bwrap's user namespace and bwrap's profile is disabled ($PROFILES/disable/$PROFILE)" \
        "sudo rm $PROFILES/disable/$PROFILE && sudo apparmor_parser -r -W $PROFILES/$PROFILE"
    fi
    if [[ -e "$PROFILES/$PROFILE" ]]; then
      refuse "AppArmor blocks bwrap's user namespace and bwrap's profile ($PROFILES/$PROFILE) is not loaded" \
        "sudo apparmor_parser -r -W $PROFILES/$PROFILE   (it prints why when it can't load it)"
    fi
    refuse "AppArmor blocks bwrap's user namespace (Ubuntu 24.04) and bwrap has no AppArmor profile" \
      "sudo bash $HERE/bwrap-apparmor.sh"
  fi
  refuse "this system does not let programs make a user namespace (a container, or a locked-down VPS?)" \
    "install AGOS on a virtual machine or a server you control. Only if you accept that every workspace's agents can then reach this machine's Docker: run the installer with --no-cage"
}

case "${1:-}" in
  install) cmd_install ;;
  self-test) shift; cmd_self_test "$@" ;;
  *) sed -n '2,/^set -uo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 2 ;;
esac
