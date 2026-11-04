#!/usr/bin/env bash
# The gateways' cage is bwrap (docs/adr/0025). Where the kernel restricts user
# namespaces to AppArmor-profiled programs (Ubuntu 24.04) and the release ships no
# loaded profile for bwrap, it fails ("setting up uid map: Permission denied"): this
# adds Ubuntu's own bwrap-userns-restrict profile (newer Ubuntu ships it enabled),
# which lets bwrap make its namespace and strips every capability from what runs
# inside. Run as root by cage-setup.sh install (install-server.sh); re-runs do
# nothing once bwrap works.
#
# - the system's own copy (/usr/share/apparmor/extra-profiles) is preferred to
#   AGOS's (deploy/apparmor/), which is the same profile;
# - a profile the admin disabled (/etc/apparmor.d/disable/) is left alone;
# - it never stops the install by itself: when the profile can't be loaded (an
#   older AppArmor that can't read it) the installer's cage self-test after it
#   (cage-setup.sh self-test) stops with code cage_refused and the exact fix;
# - agos uninstall leaves the profile in place (it confines /usr/bin/bwrap only).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME=bwrap-userns-restrict
PROFILES="${AGOS_APPARMOR_DIR:-/etc/apparmor.d}"
EXTRA="${AGOS_APPARMOR_EXTRA:-/usr/share/apparmor/extra-profiles}"
RESTRICT="${AGOS_USERNS_RESTRICT:-/proc/sys/kernel/apparmor_restrict_unprivileged_userns}"
OFF="the cage self-test will say what to do (code cage_refused)"

bwrap_runs() { runuser -u nobody -- bwrap --dev-bind / / -- true 2>/dev/null; }

[[ "$(cat "$RESTRICT" 2>/dev/null)" == 1 ]] || exit 0
bwrap_runs && exit 0
printf '\n==> %s\n' "AppArmor profile for bwrap (the gateways' cage)"
if [[ -e "$PROFILES/disable/$NAME" ]]; then
  echo "  $NAME is disabled on this server ($PROFILES/disable/$NAME): left as it is, so $OFF" >&2
  exit 0
fi
if [[ ! -e "$PROFILES/$NAME" ]]; then
  src="$HERE/apparmor/$NAME"
  [[ -f "$EXTRA/$NAME" ]] && src="$EXTRA/$NAME"
  install -m 0644 "$src" "$PROFILES/$NAME" || { echo "  could not write $PROFILES/$NAME: $OFF" >&2; exit 0; }
  echo "  $PROFILES/$NAME from $src (agos uninstall leaves it: it confines bwrap only)"
fi
if ! apparmor_parser -r -W "$PROFILES/$NAME"; then
  echo "  apparmor_parser could not load $NAME (an older AppArmor?): $OFF" >&2
  exit 0
fi
bwrap_runs || echo "  bwrap still can't run here: $OFF" >&2
exit 0
