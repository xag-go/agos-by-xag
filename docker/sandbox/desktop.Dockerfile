# AGOS workspace sandbox WITH a screen: the same sandbox (agos-sandbox:1, same agent
# user, same mounts, same internal network behind AGOS's egress proxy) plus Hermes's
# Bot Desktop stack, so the agent's browser and computer use run INSIDE the
# workspace's container, never on the machine. Package set mirrors Hermes's own
# docker/sandbox-desktop.Dockerfile (tools/bot_desktop/sandbox_host.py _REQUIRED).
#
#   docker build -f docker/sandbox/desktop.Dockerfile -t agos-sandbox:desktop docker/sandbox
ARG BASE=agos-sandbox:1
# hadolint ignore=DL3006
FROM ${BASE}
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
USER root

ARG CUA_DRIVER_VERSION=0.28.2
ARG TARGETARCH
ENV DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    XDG_RUNTIME_DIR=/tmp/hermes-runtime \
    LANG=C.UTF-8

# Screen: Xvnc + a light Xfce (the launcher starts each part itself).
RUN apt-get -o Acquire::Retries=3 update && \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        tigervnc-standalone-server xfce4-panel xfwm4 xfdesktop4 xfce4-settings xfce4-terminal \
        dbus-x11 x11-xserver-utils x11-utils x11-xkb-utils xauth fonts-dejavu-core \
        fonts-noto-core fonts-noto-color-emoji fonts-arabeyes \
        at-spi2-core libgtk-3-0 libnss3 libasound2 libxss1 python3-pil && \
    rm -rf /var/lib/apt/lists/*

# Chromium (Playwright build, same as Hermes) + agent-browser, the CLI Hermes's
# browser tools drive. Baked so the first browser step doesn't download anything.
RUN for i in 1 2 3; do \
        npx --yes playwright@1 install --with-deps chromium && break || \
        { [ "$i" = 3 ] && exit 1; sleep 10; }; \
    done && chmod -R a+rX /opt/playwright && \
    npm install -g --ignore-scripts --no-audit --fetch-retries=5 "agent-browser@^0.26.0" && \
    agent-browser --version

# cua-driver: computer_use's driver (pinned release).
RUN case "${TARGETARCH:-amd64}" in amd64) arch=x86_64 ;; arm64) arch=arm64 ;; *) exit 1 ;; esac; \
    mkdir -p /opt/cua-driver; \
    curl -fsSL "https://github.com/trycua/cua/releases/download/cua-driver-rs-v${CUA_DRIVER_VERSION}/cua-driver-rs-${CUA_DRIVER_VERSION}-linux-${arch}-binary.tar.gz" \
        | tar -xz -C /opt/cua-driver; \
    ln -sf /opt/cua-driver/cua-driver /usr/local/bin/cua-driver; \
    cua-driver --version

RUN mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix && \
    mkdir -p /tmp/hermes-runtime && chown agent /tmp/hermes-runtime && chmod 0700 /tmp/hermes-runtime && \
    printf 'PLAYWRIGHT_BROWSERS_PATH=/opt/playwright\nXDG_RUNTIME_DIR=/tmp/hermes-runtime\n' >> /etc/environment

LABEL org.opencontainers.image.title="agos-sandbox-desktop" \
      org.opencontainers.image.description="AGOS workspace sandbox with a screen (browser + computer use)"

USER agent
WORKDIR /workspace
CMD ["sleep", "infinity"]
