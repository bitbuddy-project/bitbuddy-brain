from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def db_connection(path: Path | str, row_factory: type | None = None) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(str(path))
    if row_factory:
        connection.row_factory = row_factory
    try:
        with connection:
            yield connection
    finally:
        connection.close()
