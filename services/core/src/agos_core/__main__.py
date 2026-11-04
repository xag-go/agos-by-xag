"""`python -m agos_core`: run the API (used by the container).

It listens on 127.0.0.1 unless AGOS_CORE_HOST says otherwise: the container sets
0.0.0.0 for its own private network (every route still needs the internal token).
"""

import logging
import os

import uvicorn

from agos_core.api.app import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[core] %(message)s")
    host = os.environ.get("AGOS_CORE_HOST", "").strip() or "127.0.0.1"
    uvicorn.run(create_app(), host=host, port=8000, server_header=False, log_level="warning")


if __name__ == "__main__":
    main()
