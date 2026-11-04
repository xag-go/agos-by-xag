"""The durable job queue: AGOS's own background work as rows (migration 147, ADR 0026).

`queue` writes a job on the caller's connection (inside its Unit of Work it commits
or rolls back with the change) and holds the retry rule; `runner` is the one loop
that claims due jobs with a lease, runs each kind's handler, retries a failure with
backoff and dead-letters the last one (an error in the System Log, so Settings →
Errors lists it); `recurring` plans the next job of each recurring kind. Each kind's
handler is registered by the service that owns the work (actions/background_jobs.py).
This package imports nothing on purpose.
"""
