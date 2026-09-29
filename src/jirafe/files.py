import json
import os
import threading
import time

from .constants import REPLACE_ATTEMPTS, REPLACE_RETRY_DELAY_S


def write_json(
        path,
        payload
):
    """Replaces a JSON file atomically: a reader sees the old content or the new one, never half of it."""
    # One temporary file per thread: the background sync and an on-demand sync may write the same file at
    # the same time.
    temporary = path.with_suffix(f".{threading.get_ident()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8"
    )
    for attempt in range(1, REPLACE_ATTEMPTS + 1):
        try:
            os.replace(
                temporary,
                path
            )
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(REPLACE_RETRY_DELAY_S)
