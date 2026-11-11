"""Database engine and session helpers. SQLite locally; any Postgres (e.g. Neon's free tier) in production."""

import logging
from collections.abc import Iterator

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

log = logging.getLogger("kharcha.db")

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, pool_pre_ping=True)


def init_db() -> None:
    # Import models so SQLModel knows every table before create_all.
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    added = add_missing_columns()
    if added:
        _after_upgrade(added)


def reset_db() -> None:
    from app import models  # noqa: F401

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def add_missing_columns() -> list[str]:
    """A tiny migration step: create_all makes new tables but never new columns, so add any
    column a model has that the database table doesn't, filled with the model's default."""
    # Fresh connections: an old pooled SQLite connection can remember the table layout from before a
    # change and wrongly report "duplicate column".
    engine.dispose()
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    quote = engine.dialect.identifier_preparer.quote
    added: list[str] = []
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                col_type = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f"ALTER TABLE {quote(table.name)} ADD COLUMN {quote(col.name)} {col_type}"))
                default = col.default.arg if col.default is not None else None
                if default is not None and not callable(default):
                    conn.execute(text(f"UPDATE {quote(table.name)} SET {quote(col.name)} = :v"), {"v": default})
                added.append(f"{table.name}.{col.name}")
    if added:
        log.info("Database upgraded, added columns: %s", ", ".join(added))
    return added


def _after_upgrade(added: list[str]) -> None:
    """One-time fixes for data made before a column existed."""
    if "user.is_demo" in added:
        # Before logins existed, the first user was the demo student.
        with engine.begin() as conn:
            first = conn.execute(text('SELECT MIN(id) FROM "user"')).scalar()
            if first is not None:
                conn.execute(text('UPDATE "user" SET is_demo = :t WHERE id = :id'), {"t": True, "id": first})


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
