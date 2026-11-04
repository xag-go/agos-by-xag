#!/usr/bin/env bash
# HTTPS for agos.<domain> on the server's Tailscale IP only, with a DNS-challenge
# certificate (no public port). Uses Caddy + its Cloudflare DNS module, and takes
# who is asking from Tailscale itself (caddy-tailscale's tailscale_auth).
#
#   sudo deploy/https-setup.sh agos.example.com     (asks for the DNS API token)
set -euo pipefail
HOST="${1:?usage: https-setup.sh <hostname>}"
TS_IP="$(tailscale ip -4 | head -1)"
[[ "$TS_IP" == 100.* ]] || { echo "Tailscale isn't up (tailscale up first)" >&2; exit 1; }
read -r -s -p "DNS API token (Cloudflare, DNS edit for the zone): " TOKEN; echo
[[ -n "$TOKEN" ]] || { echo "no token" >&2; exit 1; }

# Caddy with two modules: the Cloudflare DNS challenge, and Tailscale's own login
# check (tailscale_auth asks this machine's tailscaled who the peer is). Built from
# pinned versions in Caddy's builder image, pinned by digest: Go checks every module
# against go.sum and Go's checksum database (sum.golang.org), so nothing unverified
# is downloaded (the caddyserver.com download API builds whatever is newest and
# publishes no checksum).
CADDY_VERSION="v2.11.7"
CADDY_BUILDER="caddy:2.11.7-builder@sha256:c4cd20eaa0b69112fd5d4f721ffc9671687e1d5d0b155c8620cf7546dbef94c0"
CADDY_MODULES=(
  --with "github.com/caddy-dns/cloudflare@v0.2.4"
  --with "github.com/tailscale/caddy-tailscale@v0.0.0-20260826180304-de41b249af4f"
)
has_modules() {
  local mods
  mods="$(/usr/local/bin/caddy list-modules 2>/dev/null)" || return 1
  grep -q '^dns.providers.cloudflare$' <<<"$mods" && grep -q '^http.authentication.providers.tailscale$' <<<"$mods"
}
if ! has_modules; then
  command -v docker >/dev/null || { echo "Docker is needed to build Caddy (install AGOS first)" >&2; exit 1; }
  build="$(mktemp -d)"
  trap 'rm -rf "$build"' EXIT
  docker run --rm -v "$build:/out" -e CGO_ENABLED=0 "$CADDY_BUILDER" \
    xcaddy build "$CADDY_VERSION" --output /out/caddy "${CADDY_MODULES[@]}"
  install -m 0755 -o root -g root "$build/caddy" /usr/local/bin/caddy
  has_modules || { echo "the Caddy build lacks its modules" >&2; exit 1; }
  echo "Caddy $CADDY_VERSION built: sha256 $(sha256sum /usr/local/bin/caddy | cut -d" " -f1)"
fi
install -d -m 0750 /etc/caddy
umask 077
printf 'CF_API_TOKEN=%s\n' "$TOKEN" > /etc/caddy/dns.env
cat > /etc/caddy/Caddyfile <<EOF
{
  admin off
}
${HOST}:443 {
  bind ${TS_IP}
  tls {
    dns cloudflare {env.CF_API_TOKEN}
  }
  # Who is asking comes from Tailscale itself, never from the client: tailscale_auth
  # refuses a peer tailscaled can't name (a tagged node, Funnel), and the identity
  # headers are SET from its answer, replacing anything the client sent (otherwise
  # any tailnet device could send Tailscale-User-Login: <owner> and be the owner).
  tailscale_auth
  reverse_proxy 127.0.0.1:3000 {
    header_up Tailscale-User-Login {http.auth.user.tailscale_user}
    header_up Tailscale-User-Name {http.auth.user.tailscale_name}
    header_up -Tailscale-User-Profile-Pic
  }
}
EOF
cat > /etc/systemd/system/agos-https.service <<EOF
[Unit]
Description=AGOS HTTPS (Tailscale only)
After=tailscaled.service agos-web.service
Wants=tailscaled.service

[Service]
EnvironmentFile=/etc/caddy/dns.env
ExecStart=/usr/local/bin/caddy run --config /etc/caddy/Caddyfile
Restart=always
RestartSec=5
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now agos-https
echo "HTTPS on https://${HOST} (bound to ${TS_IP} only). Point the DNS A record ${HOST} → ${TS_IP}."
