#!/bin/sh
# Runs `uv` for the Python services. On a machine without uv the Python checks
# are skipped with a visible notice; in CI (CI=true) a missing uv is an error.
if command -v uv >/dev/null 2>&1; then
  exec uv "$@"
fi
if [ "${CI:-}" = "true" ]; then
  echo "uv is required for the Python services (https://docs.astral.sh/uv/)" >&2
  exit 1
fi
echo "⚠️  uv not installed: Python checks skipped (install: https://docs.astral.sh/uv/)" >&2
exit 0
