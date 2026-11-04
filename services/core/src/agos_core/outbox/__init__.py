"""The outbox: AGOS's own notifications (phone push, ...) written as rows inside the
change that causes them and delivered after it by one loop with retry and backoff.

`delivery` holds the queue, the loop and the channel table; each channel's sender
is registered by the service that owns the channel (actions/outbox_push.py).
This package imports nothing on purpose.
"""
