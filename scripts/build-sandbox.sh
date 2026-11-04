#!/usr/bin/env bash
# Builds AGOS's workspace sandbox images. Default: this machine's architecture,
# tagged agos-sandbox:1, then agos-sandbox:desktop on top of it (the same sandbox
# plus Hermes's Bot Desktop stack). Every workspace's Hermes runs the :desktop one,
# like Hermes's own default sandbox (hermes-sandbox:desktop); the plain one is the
# base and runs AGOS's small helper containers (egress proxy, local MCP servers).
# Pass --multi to build linux/amd64 + linux/arm64 with buildx (needs a registry
# to push to, or --load for one arch only).
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${AGOS_SANDBOX_TAG:-agos-sandbox:1}"
DESKTOP="${TAG%:*}:desktop"
# The sandbox's agent user gets this machine's user ids (the one running AGOS),
# so it can read and write the workspace folders mounted into it.
IDS=(--build-arg "AGENT_UID=$(id -u)" --build-arg "AGENT_GID=$(id -g)")
if [[ "${1:-}" == "--multi" ]]; then
  docker buildx build --platform linux/amd64,linux/arm64 "${IDS[@]}" -f docker/sandbox/Dockerfile \
    -t "$TAG" "${@:2}" docker/sandbox
  docker buildx build --platform linux/amd64,linux/arm64 --build-arg "BASE=$TAG" \
    -f docker/sandbox/desktop.Dockerfile -t "$DESKTOP" "${@:2}" docker/sandbox
else
  docker build "${IDS[@]}" -f docker/sandbox/Dockerfile -t "$TAG" docker/sandbox
  docker build --build-arg "BASE=$TAG" -f docker/sandbox/desktop.Dockerfile -t "$DESKTOP" \
    docker/sandbox
fi
docker run --rm "$TAG" sh -c 'id agent && git --version && node --version && uv --version && gh --version | head -1'
docker run --rm "$DESKTOP" sh -c 'command -v Xvnc xfwm4 cua-driver agent-browser'
echo "built $TAG and $DESKTOP"
