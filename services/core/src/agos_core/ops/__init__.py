"""The operation registry (Command pattern; ARCHITECTURE.md §10): each owner action
is declared once and every caller runs that one declaration.

- `spec`: `OperationSpec`, the declaration (name, input model, gate, effect, audit
  title, who may run it: the owner only, or also the Co-Founder / agents). Pure
  data, so the engine's Co-Founder tables can read it.
- `specs/`: every declaration, one module per service (`SPECS`).
- `operation`: `Operation` = a declaration bound to its service's `do` / `undo`;
  `Actor`, `OpContext`.
- `registry`: binding and running (`run(..., actor, idempotency_key)`): validation,
  permission, workspace scope, idempotency, the audit row (db/op_runs.py).
- `catalog`: the tables each caller needs, derived from the declarations: the
  Co-Founder's kinds and effects, the web parity rows, the agent tools.
- `cofounder`: the Co-Founder's do / undo for the declared kinds.

This package imports nothing on purpose.
"""
