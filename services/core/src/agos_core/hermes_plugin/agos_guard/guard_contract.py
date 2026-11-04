"""The names AGOS's core and its agos-guard plugin (inside Hermes) agree on.

Owns: the policy file's name and its action types, the mark of an "Ask me" approval, AGOS's own Telegram button data,
the note under a message whose key was hidden, and the plugin's speech-to-text
provider name and model. The core writes and shows them; the plugin reads them.

Must not: import anything but the standard library, or hold state. This file is
copied byte for byte into hermes_plugin/agos_guard/ (scripts/sync_shared.py): edit
it in agos_core/shared/ and run the script.
"""

from __future__ import annotations

__all__ = [
    "ACTIONS",
    "AGOS_BUTTONS",
    "ASK_MARK",
    "KEY_NOTE",
    "POLICY_FILE",
    "STT_DEFAULT_MODEL",
    "STT_NAME",
]

# The owner's Autonomy rules for a profile, written by AGOS into its Hermes home.
POLICY_FILE = "agos-guard.json"

# The action types the rules are about, with the words the owner sees.
ACTIONS = {
    "files": "Create or change files",
    "commands": "Run commands",
    "messages": "Send messages",
    "apps_change": "Change things in connected apps",
    "apps_delete": "Delete in connected apps",
    "browser": "Use the browser",
    "desktop": "Use the desktop (mouse and keyboard)",
    "images": "Make images or audio",
    "memory": "Save to memory and skills",
    "cards": "Create Kanban cards",
}

# In an approval the guard asks for because of the owner's Autonomy rule "Ask me"
# (never a risky command): Full access never answers those, they wait for him.
ASK_MARK = "[AGOS rule: Ask me]"

# AGOS's own button data (actions/channels.py::button). Hermes's are different.
AGOS_BUTTONS = (
    r"^(chatcmd:(once|deny):\d+|tok:(go|stop):[A-Za-z0-9_-]+|kask:(once|deny|approve|reject):\d+"
    r"|kask:ans:\d+:[a-z0-9_-]{1,32}|krev:ok:[A-Za-z0-9_-]{1,64}|fdone:[A-Za-z0-9_-]{1,64})$"
)

# Under a message whose key AGOS hid (keys.py keeps the same words: it also runs as a
# script in Hermes's runtime, where it imports nothing).
KEY_NOTE = "[AGOS hid a key in this message. Keys go in Settings → Keys, never in chat.]"

# The plugin's speech-to-text provider (stt_gemini.py) as Hermes's config names it.
STT_NAME = "gemini"
STT_DEFAULT_MODEL = (
    "gemini-3-flash-preview"  # hears Moroccan Darija right every time (Lite models misheard it)
)
