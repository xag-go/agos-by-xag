# CLAUDE.md

@AGENTS.md

Claude Code specifics:

- Work in a git worktree, one branch per change. Never commit in the main checkout.
- Run the full chain (step 3 in AGENTS.md) from the main session as a systemd user unit, not from a
  subagent: a subagent's background processes end when it ends.
- Report the exact commands you ran and their output.
