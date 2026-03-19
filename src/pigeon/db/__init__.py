"""Database backend registry."""

from pigeon.db.base import Database, SessionRecord, UsageRecord

_BACKENDS: dict[str, type[Database]] = {}


def register_backend(name: str, cls: type[Database]) -> None:
    _BACKENDS[name] = cls


def get_database(name: str, **kwargs) -> Database | None:
    if name == "none":
        return None
    if name not in _BACKENDS:
        raise ValueError(
            f"Unknown database backend: {name}. "
            f"Available: {', '.join(_BACKENDS.keys())}, none"
        )
    return _BACKENDS[name](**kwargs)


# Register built-in backends
from pigeon.db.postgres_db import PostgresDatabase  # noqa: E402
from pigeon.db.sqlite_db import SQLiteDatabase  # noqa: E402

register_backend("sqlite", SQLiteDatabase)
register_backend("postgres", PostgresDatabase)

__all__ = ["Database", "SessionRecord", "UsageRecord", "get_database"]
