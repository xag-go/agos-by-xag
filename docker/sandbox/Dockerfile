# AGOS's workspace sandbox image: what an agent needs to do real work in
# /workspace — and nothing that reaches the host.
#
# Build (multi-arch):  docker buildx build --platform linux/amd64,linux/arm64 \
#                        -f docker/sandbox/Dockerfile -t agos-sandbox:<version> docker/sandbox
# Local test build:     docker build -f docker/sandbox/Dockerfile -t agos-sandbox:dev docker/sandbox
#
# Hermes starts it with all capabilities dropped (it re-adds CHOWN, DAC_OVERRIDE,
# FOWNER, SETUID, SETGID to the bounding set for root-started images; here the
# container runs as the unprivileged `agent`, so with no-new-privileges those stay
# unreachable: CapEff is 0), no-new-privileges, memory/CPU/pids limits and the
# workspace's internal network. `docker exec` inherits the image's USER, so the
# terminal runs as `agent` too — never root. Hermes bind-mounts a per-profile home
# onto /root (its tool layout lives there); that folder is owned by `agent`.
# Pinned by digest (the multi-arch index; docs/releases.md "Base images"): a rebuild
# gets the same base until this line is changed on purpose (Dependabot proposes it).
FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc

ARG NODE_MAJOR=22
ARG UV_VERSION=0.8.22
ARG TARGETARCH

# PIP_BREAK_SYSTEM_PACKAGES: Debian marks its Python externally managed (PEP 668),
# which refuses even `pip install --user` — an agent's first move. The terminal runs
# as the unprivileged `agent` (USER below; the sandbox broker refuses a container or
# exec that asks for any other user, engine/sandboxd_rules.py), so pip writes only
# its ~/.local. Were a container ever run as root, root's pip could change only that
# container's own Python, nothing on the host. No `RUN pip install` follows this ENV.
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# tzdata: `date` in the sandbox says the owner's time (TZ, from Hermes's
# terminal.docker_env, engine/rules.py sandbox_env); without it TZ falls back to UTC.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      ca-certificates curl wget git openssh-client gnupg \
      python3 python3-venv python3-pip \
      build-essential pkg-config \
      jq ripgrep fd-find less nano unzip zip xz-utils file tree \
      ffmpeg imagemagick poppler-utils sqlite3 \
      procps iproute2 dnsutils \
      tzdata; \
    ln -s /usr/bin/fdfind /usr/local/bin/fd; \
    ln -s /usr/bin/python3 /usr/local/bin/python; \
    # Node.js LTS (NodeSource) and GitHub CLI (official apt repo), both signed.
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /usr/share/keyrings/nodesource.gpg; \
    echo "deb [signed-by=/usr/share/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
      > /etc/apt/sources.list.d/nodesource.list; \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /usr/share/keyrings/githubcli.gpg; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends nodejs gh; \
    corepack enable; \
    rm -rf /var/lib/apt/lists/*

# uv (pinned) from its release archive for this architecture.
RUN set -eux; \
    case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
      amd64) triple=x86_64-unknown-linux-gnu ;; \
      arm64) triple=aarch64-unknown-linux-gnu ;; \
      *) echo "unsupported arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${triple}.tar.gz" \
      | tar -xz -C /tmp; \
    install -m 0755 "/tmp/uv-${triple}/uv" "/tmp/uv-${triple}/uvx" /usr/local/bin/; \
    rm -rf /tmp/uv-*

# The agent's uid/gid match the host user that owns the workspace files: on
# Linux a bind mount keeps raw ids, so a mismatch is "Permission denied" on
# /workspace (Docker Desktop on macOS hides it). scripts/build-sandbox.sh passes
# the host ids; 1000 is only the default.
ARG AGENT_UID=1000
ARG AGENT_GID=1000
RUN (getent group "${AGENT_GID}" >/dev/null || groupadd --gid "${AGENT_GID}" agent) \
    && useradd --create-home --uid "${AGENT_UID}" --gid "${AGENT_GID}" --shell /bin/bash agent \
    && mkdir -p /workspace /shared \
    && git config --system init.defaultBranch main \
    && git config --system safe.directory '*'

LABEL org.opencontainers.image.title="agos-sandbox" \
      org.opencontainers.image.description="AGOS workspace sandbox (Node, Python/uv, git, gh, ffmpeg)"

WORKDIR /workspace
USER agent
CMD ["sleep", "infinity"]
