"""Pure code that AGOS's core and its agos-guard plugin share.

The plugin runs inside Hermes and cannot import agos_core, so every module here is
also kept, byte for byte, in hermes_plugin/agos_guard/ (`scripts/sync_shared.py`
writes the copies; tests/test_shared_copies.py fails when they drift). The core
imports the module from here and never from the plugin.

Must not: import anything but the standard library (also no relative imports), or
hold state.
"""
