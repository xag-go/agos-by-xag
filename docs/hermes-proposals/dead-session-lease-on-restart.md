# Proposal for Hermes: a restarted gateway takes a dead process's turn lease at once, and stops posting "Still waiting"

Found by AGOS's failure tests (`services/core/tests/failure/test_recovery.py`,
[resilience-tests.md](../guides/resilience-tests.md#found-by-these-tests)), read
against Hermes `d923a5eb48` (2026-10-15).

## What happens

AGOS kills a workspace's gateway with SIGKILL in the middle of an answer and
starts it again with Hermes's own service start. The new process resumes the cut
answer, but only after about 5 minutes. Meanwhile it posts this line into the
owner's chat every 15 seconds, about 20 lines in all:

> ⏳ Still waiting for the other Hermes process on this session (Ns)...

In one run out of two, the owner's cut message was missing from the chat
afterwards: the resume starts from Hermes's own note.

## Where it comes from

- The turn lease (`agent/turn_facade_lease.py`) has `LEASE_TTL_SECONDS = 300`
  and waits up to `LEASE_WAIT_SECONDS = 1800`. `acquire_session_turn_lease`
  (`hermes_state_compression.py`) calls `on_wait` every
  `wait_notice_interval_seconds = 15`, and the lease code turns each call into a
  status line that goes to the platform.
- A holder is reclaimed early only when `_compression_lock_holder_process_is_dead`
  (`hermes_state.py`) can **prove** its pid is gone. It answers "alive" when the
  holder's pid namespace can't be checked (`holder_pid_checkable`: an unstamped
  or foreign holder waits for the TTL). It also answers "alive" whenever the pid
  exists, and a SIGKILLed child that its parent has not reaped yet still exists
  as a zombie. Either way the wait falls back to the full 300 s TTL, which
  matches the ~5 minutes we saw. We have not proved which of the two holds on
  AGOS's rig.

## Proposal

1. **A dead holder is dead.** In `_compression_lock_holder_process_is_dead`,
   count a zombie as dead (`psutil.Process(pid).status() ==
psutil.STATUS_ZOMBIE`). Also stamp the holder with the process's start time
   (`pid=<n>:start=<ticks>`), so a reused pid with another start time is dead
   too. Today's rule stays: any real doubt keeps the lease.
2. **The same gateway's own restart is not "another process".** When the holder
   string names the same platform and profile as the new process (the restarted
   gateway is the only writer of its sessions), and its pid is not a live process
   of the same start time, take the lease at once.
3. **One notice, not twenty.** On messaging platforms, post the waiting notice
   once, then edit it in place or say nothing more until the turn starts. Or make
   `wait_notice_interval_seconds` a config setting (for example
   `agent.lease_wait_notice_seconds`, where 0 means once).
4. **Keep the user's message.** When a resume comes after a lost lease, carry the
   unadmitted user message into the resumed turn
   (`carry_unadmitted_user_message` exists), so the chat never loses what the user
   wrote.

## Why not in AGOS

Hermes owns its session database and its leases (Hermes is the engine). AGOS
must not edit `state.db` or clear a lease behind Hermes's back. Filtering the
status lines out of the owner's chat would also hide a real wait from him.

## How to check it

In AGOS's failure tests, the "gateway killed mid-answer" case should resume in
a few seconds after the restart, with at most one waiting line and the owner's
message still in the chat.
