from __future__ import annotations

import array
import math
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from ..config import load_config
from ..providers import ProviderClient

# When an embedding call fails or the endpoint is unavailable, stop trying for a
# cooldown window so memory writes/searches never repeatedly block on a dead model.
_COOLDOWN_SECONDS = 300.0
_disabled_until = 0.0


def ensure_embedding_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists memory_embeddings (
            memory_id text primary key,
            model text not null,
            dim integer not null,
            vector blob not null,
            updated_at text default current_timestamp
        )
        """
    )


def _client_and_model() -> tuple[ProviderClient | None, str]:
    config = load_config()
    model = (getattr(config.provider, "embedding_model", "") or "").strip()
    if config.provider.type == "none" or not model:
        return None, ""
    return ProviderClient(config.provider), model


def embeddings_enabled() -> bool:
    client, model = _client_and_model()
    return client is not None and bool(model)


def embed_text(text: str) -> list[float] | None:
    """Embed a single string, or None when embeddings are unavailable/cooling down."""
    global _disabled_until
    clean = (text or "").strip()
    if not clean:
        return None
    if time.monotonic() < _disabled_until:
        return None
    client, model = _client_and_model()
    if client is None:
        return None
    try:
        vectors = client.embed([clean], model=model)
    except Exception:
        _disabled_until = time.monotonic() + _COOLDOWN_SECONDS
        return None
    if not vectors or not vectors[0]:
        _disabled_until = time.monotonic() + _COOLDOWN_SECONDS
        return None
    return vectors[0]


def _pack(vector: list[float]) -> bytes:
    return array.array("f", vector).tobytes()


def _unpack(blob: bytes) -> array.array:
    vector = array.array("f")
    vector.frombytes(blob)
    return vector


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def memory_embedding_text(title: str, summary: str, tags: Any) -> str:
    tag_text = " ".join(str(tag) for tag in tags) if isinstance(tags, (list, tuple)) else str(tags or "")
    return f"{title}\n{summary}\n{tag_text}".strip()


def store_memory_embedding(connection_factory: Any, memory_id: str, text: str) -> bool:
    """Embed text (network call, outside any caller transaction) and persist the vector."""
    vector = embed_text(text)
    if not vector:
        return False
    _client, model = _client_and_model()
    with connection_factory() as connection:
        ensure_embedding_table(connection)
        connection.execute(
            """
            insert into memory_embeddings (memory_id, model, dim, vector, updated_at)
            values (?, ?, ?, ?, ?)
            on conflict(memory_id) do update set
                model = excluded.model,
                dim = excluded.dim,
                vector = excluded.vector,
                updated_at = excluded.updated_at
            """,
            (memory_id, model, len(vector), _pack(vector), _iso_now()),
        )
    return True


def _cosine(query: list[float], candidate: array.array) -> float:
    if len(candidate) != len(query):
        return 0.0
    dot = 0.0
    norm_c = 0.0
    for q, c in zip(query, candidate):
        dot += q * c
        norm_c += c * c
    if norm_c <= 0.0:
        return 0.0
    norm_q = math.sqrt(sum(value * value for value in query)) or 1.0
    return dot / (norm_q * math.sqrt(norm_c))


def semantic_ranked_ids(
    connection: sqlite3.Connection,
    query_vector: list[float],
    layer: str | None,
    project_id: str | None,
    include_archived: bool,
    limit: int,
    scan_cap: int = 800,
) -> list[str]:
    """Return memory ids ranked by cosine similarity to the query vector."""
    if not table_exists(connection, "memory_embeddings"):
        return []
    where = ["1 = 1"]
    params: list[Any] = []
    if layer:
        where.append("m.layer = ?")
        params.append(layer)
    if project_id:
        where.append("m.project_id = ?")
        params.append(project_id)
    if not include_archived:
        where.append("m.archived_at is null")
    params.append(scan_cap)
    rows = connection.execute(
        f"""
        select me.memory_id as memory_id, me.vector as vector
        from memory_embeddings me
        join memories m on m.id = me.memory_id
        where {' and '.join(where)}
        order by m.updated_at desc
        limit ?
        """,
        tuple(params),
    ).fetchall()
    scored: list[tuple[str, float]] = []
    for row in rows:
        score = _cosine(query_vector, _unpack(row["vector"]))
        if score > 0.0:
            scored.append((row["memory_id"], score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return [memory_id for memory_id, _score in scored[: max(1, limit)]]


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            "select 1 from sqlite_master where type = 'table' and name = ?", (name,)
        ).fetchone()
        is not None
    )
