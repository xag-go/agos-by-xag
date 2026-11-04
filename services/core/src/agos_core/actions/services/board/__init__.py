"""The Board service (cards on Hermes's board: review stages, status cards), split out of
actions/reviews.py and actions/status_cards.py, and the Kanban reads and rules split out
of actions/kanban_board.py (kanban_workflow, kanban_db, card_text).

Each module imports only the modules before it in the service's dependency order (no
cycles); the package itself imports nothing, so loading one part stays cheap.

Must not: import its own modules here (loading one part stays cheap) or hold code.
"""

__all__: list[str] = []
