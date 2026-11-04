"""Ownership of AGOS's tables: chats, their turns and messages, channels, rooms.

Part of the registry's TABLES (merged in order by db/ownership/tables.py); same
rules as db/ownership/__init__.py.

Must not: hold key or file entries (keys.py, files.py), or another area's tables.
"""

from __future__ import annotations

from agos_core.db.ownership.base import CHANGED, CHAT, ID, MADE, WS, Table, agos, cols

__all__ = [
    "TABLES",
]

TABLES: dict[str, Table] = {
    "workspaces": Table(
        agos(
            "AGOS's workspaces: one per project, each on its own Hermes root; Hermes has "
            "profiles and roots but no product 'workspace' with trash or archive; its "
            "name and one-line description are the Co-Founder's Hermes display_name and "
            "description (the root profile's profile.yaml)",
            "H: hermes_cli/profiles.py:916,958 read_profile_meta/write_profile_meta "
            "(description, display_name; no archive or trash)",
        ),
        cols(
            id="fixed id, the folder and Hermes root name",
            archived_at="archived by the owner (AGOS's list only)",
            deleted_at="in AGOS's trash",
            trash_name="the folder's name under .trash/ (<id>--<ms>) while deleted",
            created_at=MADE,
            updated_at=CHANGED,
        ),
    ),
    "chats": Table(
        agos(
            "AGOS's chat list: the link from an AGOS chat (DM, group, member, Kanban "
            "card) to its Hermes session; the transcript itself is Hermes's state.db",
            "H: hermes_state_common.py:382 sessions (no AGOS kind, members or card link)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            title=agos(
                "a plain chat's name only until its Hermes session has a title; a group's "
                "name only until its Hermes room holds it (cleared when Hermes confirms the "
                "room or its rename_room; held again while a new room is made). Then "
                "Hermes's is shown (db/chats.py title_from). Empty for a DM (its partner's "
                "Hermes display_name, db/chats.py dm_title; an old name kept only for a "
                "member whose profile is gone, team.move_dm_titles) and a card chat (its "
                "Hermes card's title, kanban_board.move_card_chat_titles)",
                "H: hermes_state_common.py:421 sessions.title; gateway/hosted_rooms.py:88-91 "
                "hosted_rooms.name, :913 rename_room; hermes_cli/profiles.py:916 "
                "read_profile_meta display_name; hermes_cli/kanban_db.py:804 tasks (title, assignee)",
            ),
            channel="where the chat lives in AGOS (web, Telegram, …)",
            created_at=MADE,
            updated_at=CHANGED,
            hermes_key="the link: the Hermes session key the chat is",
            deleted_at=agos(
                "hidden only where Hermes has nothing to archive: a group (a Hermes room "
                "has no archive), a chat with no session yet, or one linked to a Telegram "
                "place (its Hermes conversation is his live Telegram chat). A chat with "
                "Hermes sessions is hidden by Hermes's own per-session archive "
                "(chat_store.hide; old marks moved once by chat_store.move_hidden)",
                "H: gateway/platforms/api_server.py _handle_patch_session (PATCH "
                "/api/sessions/{id}) -> hermes_state_sessions.py:992 set_session_archived; "
                "gateway/hosted_rooms.py has no archive",
            ),
            agent="the member (Hermes profile) the chat talks to: the profile its Hermes "
            "conversation lives in. A card chat's is the card's Hermes assignee when it was "
            "made; a reassigned card gets a new chat with its new assignee (kanban_board.card "
            "reads the assignee from Hermes)",
            kind="chat, group, member or card chat (AGOS's own kinds)",
            members=agos(
                "the owner's choice of a group's members, also the ones a Hermes room can't "
                "hold yet (a member whose profile isn't ready, a group with nobody ready, "
                "past the 2-6 limit). A room's roster is fixed when Hermes makes it: AGOS "
                "reads it back (the plugin reports hosted_rooms.members) and makes a new "
                "room when it differs (actions/rooms.py ensure_room)",
                "H: gateway/hosted_rooms.py:857-891 create_room is the only writer of "
                "members_json; tui_gateway/methods_groups.py:19-22 has no members method",
            ),
            kanban_card="the Kanban card a card chat is about",
        ),
        writer="db/chats.py",
    ),
    "chat_turns": Table(
        agos(
            "the live marker of a turn in AGOS's UI (running, stopping, who spoke, which "
            "reply row); Hermes's run record has no AGOS reply id or speaker",
            "H: agent.log 'Turn ended' / on_session_end hook (the end reason is read from there)",
        ),
        cols(
            id=ID,
            chat_id=CHAT,
            workspace_id=WS,
            hermes_run_id="the link: Hermes's run id of the turn",
            status="live state of the turn for the UI (starting … stopped)",
            asked_up_to="the owner's messages handed to Hermes up to this id",
            reply_id="AGOS's own reply row (rooms, notices)",
            activity=agos(
                "only the approvals shown in the chat (Hermes doesn't persist them); the "
                "thinking, notes and helpers are read from Hermes's session. A group "
                "chat's answers from before keep their whole old `own` form (a hosted "
                "room's log is pruned by Hermes; migration 122, db/old_copies.py)",
                "H: hermes_state_common.py:461-463 messages.reasoning*",
            ),
            error="why the turn failed, as AGOS showed it",
            started_at="when the turn started",
            ended_at="when the turn ended",
            speaker="the member who answered (group chats)",
            via="where the turn came from (web, Telegram, automation)",
        ),
        writer="db/chat_turns.py",
    ),
    "message_rows": Table(
        agos(
            "AGOS's own lines: notices, /command answers and room lines. Hermes sends a "
            "command's answer to the platform without a transcript row, and a group's room "
            "is replaced (a new room) on every member change, its old log pruned later",
            "H: gateway/slash_commands.py:299 (a command's _handle_*_command returns its "
            "reply text, sent to the platform; gateway/run_turn.py:1718 append_to_transcript "
            "runs on the turn path only); "
            "gateway/hosted_rooms.py:38,570 (a disbanded room's log goes after 90 days or "
            "past 512 tombstones)",
        ),
        cols(
            id=ID,
            chat_id=CHAT,
            author="owner or agent",
            body="the line's text",
            created_at=MADE,
            speaker="the member who said it (rooms)",
            kind="chat, handoff, review, question or answer",
            reply_to="the line it answers",
            reply_excerpt="the quoted text shown above the reply",
            edited_at="when the owner edited it",
        ),
        writer="db/chat_lines.py",
    ),
    "messages": Table(
        agos("a view over message_rows (AGOS's own lines), read by the chat screens"),
        cols(
            id="message_rows.id",
            chat_id="message_rows.chat_id",
            author="message_rows.author",
            body="message_rows.body",
            created_at="message_rows.created_at",
            speaker="message_rows.speaker",
            kind="message_rows.kind",
            reply_to="message_rows.reply_to",
            reply_excerpt="message_rows.reply_excerpt",
            edited_at="message_rows.edited_at",
        ),
        view=True,
    ),
    "message_attachments": Table(
        agos(
            "files the owner uploaded (in the workspace folder), linked to the AGOS room "
            "line or the Hermes message they went with",
            "H: tui_gateway/hosted_room_service.py:454 send (a room takes text only); "
            "hermes_state_common.py:449-480 messages (no table of a message's files)",
        ),
        cols(
            id=ID,
            message_id="the AGOS line it is attached to",
            chat_id=CHAT,
            inbox_id="the hand-over item that carried it to Hermes",
            hermes_uid="the link: the Hermes message it went with",
            kind="image, audio or file",
            name="the file name shown",
            mime="its type",
            size="its size",
            path="where it sits in the workspace folder",
            duration="audio length",
            transcript=agos(
                "a room line's voice-note words only: the same words go into the Hermes "
                "room as text (engine/attachments.py turn_content), and this copy is kept "
                "because the room's log is pruned (AGOS remakes a room on every member "
                "change, as message_rows); a Hermes chat's words are read from Hermes's "
                "message (db/hermes_chats.py owner_words)",
                "H: gateway/hosted_rooms.py:38,570 (a disbanded room's log is pruned)",
            ),
        ),
        writer="db/chat_attachments.py",
    ),
    "chat_edits": Table(
        agos(
            "an edit in the middle of a chat and whether Hermes was told: AGOS keeps the "
            "turns after it and tells Hermes a note; Hermes's own rewind takes back every "
            "turn from the edited one on",
            "H: hermes_cli/commands.py:103 /undo; hermes_state_messages.py:1834 "
            "rewind_to_message, hermes_state_rewind.py:45 rewind_user_turn (rows after it "
            "go inactive)",
        ),
        cols(
            id=ID,
            chat_id=CHAT,
            message_id="the edited line",
            before="the text before",
            after="the text after",
            created_at=MADE,
            told_at="when the note went to Hermes",
            hermes="whether the line was Hermes's (1) or AGOS's",
        ),
        writer="db/chat_edits.py",
    ),
    "chat_addresses": Table(
        agos(
            "which Telegram chat/topic an AGOS chat (Hermes's `agos` platform) is linked "
            "to, with the owner's label and whether AGOS's cards go there",
            "H: gateway/channel_directory.py:65 (names only); hermes_state_telegram.py:49 "
            "telegram_dm_topic_bindings (a DM topic to a Telegram session) and "
            "hermes_cli/config_defaults.py:2180 gateway.profile_routes (a chat to a "
            "profile): neither links a Telegram place to another platform's chat",
        ),
        cols(
            id=ID,
            chat_id=CHAT,
            connection_id="the bot connection",
            address="the Telegram chat[:topic] id",
            notify="whether AGOS's cards go there",
            created_at=MADE,
        ),
        writer="db/chat_addresses.py",
    ),
    "channel_connections": Table(
        agos(
            "the owner's bot connections and which workspace each serves; the token is "
            "in Hermes's .env and the lamp is Hermes's gateway_state.json",
            "H: plugins/platforms/telegram/adapter.py:663 (the bot's @name in memory only); "
            "the bot's on/off is Hermes's platforms.telegram.enabled",
        ),
        cols(
            id=ID,
            kind="telegram or buzz",
            name="the owner's name for it",
            identity="the bot's @name (Hermes keeps it in memory only)",
            created_at=MADE,
            workspace_id=WS,
            engine="which side runs it (agos or hermes)",
        ),
        writer="db/channel_connections.py",
    ),
    "channel_outbox": Table(
        agos(
            "AGOS's own cards and relays waiting to go to Telegram (no outgoing-send hook in Hermes)",
            "H: hermes_cli/plugins.py:109 VALID_HOOKS (none sends an outgoing message)",
        ),
        cols(
            id=ID,
            connection_id="the bot connection",
            address="the Telegram chat[:topic]",
            body="the card's text",
            buttons="the card's buttons",
            task_id="the AGOS item it is about",
            source="what produced it (dedupe)",
            sent_id="the Telegram message id once sent",
            attempts="send attempts",
            error="the last send error",
            created_at=MADE,
            closed_at="when the card was closed",
            claimed_at="when a sender took it",
            close_text="the text the card closes with",
        ),
        writer="db/channel_outbox.py",
    ),
    "channel_reactions": Table(
        agos(
            "the 👀 kept on his Telegram message while AGOS (not a Hermes turn) answers "
            "it; Hermes's own telegram.reactions handles every turn Hermes runs",
            "H: plugins/platforms/telegram/adapter.py:7109,7148 (_reactions_enabled, "
            "on_processing_complete: per Hermes turn; no hook for an answer made elsewhere)",
        ),
        cols(
            id=ID,
            connection_id="the bot connection",
            chat_id=CHAT,
            tg_chat="Telegram chat id",
            tg_message="his message there",
            created_at=MADE,
            outcome="how the turn ended",
            claimed_at="when a sender took it",
            done_at="when the reaction was set",
            attempts="attempts",
        ),
        writer="db/channel_reactions.py",
    ),
    "hermes_inbox": Table(
        agos(
            "the transport of AGOS's own `agos` platform: messages handed to Hermes",
            "H: a custom platform brings its own transport (plugin _register_platform)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            chat_ref="the conversation it goes to",
            text="the message",
            created_at=MADE,
            taken_at="when Hermes took it",
            done_at="when Hermes finished it",
            kind="message, command, bind…",
            media="attached files",
        ),
        writer="db/hermes_inbox.py",
    ),
    "group_rooms": Table(
        agos(
            "the bridge from an AGOS group chat to its Hermes room (relay cursor, "
            "generation for disband+recreate, the settled discussion); the room itself "
            "(name, members, log) is Hermes's",
            "H: gateway/hosted_rooms.py:88-100 hosted_rooms (no link to an AGOS chat, no "
            "reader cursor)",
        ),
        cols(
            chat_id=CHAT,
            workspace_id=WS,
            room_id="the link: the Hermes room",
            generation="how many times the room was recreated",
            cursor="how far AGOS relayed the room's lines",
            state="wanted, ready or failed",
            error="why the room failed",
            discussion="the discussion the chat's live answer closes",
            updated_at=CHANGED,
        ),
        writer="db/group_rooms.py",
    ),
    "room_events": Table(
        agos(
            "which room events AGOS already relayed (outlives the room's later prune)",
            "H: gateway/hosted_rooms.py:38,570 _prune_disbanded_rooms_locked",
        ),
        cols(
            workspace_id=WS,
            room_id="the Hermes room",
            event_id="the event",
            seq="its order",
            kind="its kind",
            message_id="the AGOS line it became",
            created_at=MADE,
        ),
        writer="db/group_rooms.py",
    ),
}
