"""Database layer: settings-driven engine, session factory, declarative Base.

Portable-type conventions (docs/DATABASE.md §1, ADR 0002) that every model
follows so the schema runs on PostgreSQL (canonical) and SQLite (dev/test):

- primary keys: ``sa.Uuid`` (native UUID on PostgreSQL, CHAR(32) on SQLite)
- money: ``Numeric`` — never float
- semi-structured: ``sa.JSON`` (JSONB on PostgreSQL, TEXT on SQLite)
- timestamps: ``DateTime(timezone=True)`` with ``server_default=func.now()``
"""

from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import (
    DateTime,
    MetaData,
    StaticPool,
    create_engine,
    event,
    func,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    # NOTE: no "ck" entry on purpose. A convention containing
    # %(constraint_name)s REWRAPS explicitly-named CHECK constraints
    # (e.g. ck_dm_not_self -> ck_duplicate_matches_ck_dm_not_self), which
    # would break the doc-mandated names. Every CHECK constraint in
    # app/models is explicitly named (docs/DATABASE.md §1).
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """``created_at``/``updated_at`` on every table (docs/DATABASE.md §1)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _is_sqlite_memory(url: str) -> bool:
    return url == "sqlite://" or ":memory:" in url


def _make_engine(database_url: str) -> Engine:
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if _is_sqlite(database_url):
        # FastAPI serves requests across threads; SQLite needs this to be
        # shared safely (with StaticPool for the in-memory test database).
        kwargs["connect_args"] = {"check_same_thread": False}
        if _is_sqlite_memory(database_url):
            kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, **kwargs)

    if _is_sqlite(database_url):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
                if not _is_sqlite_memory(database_url):
                    cursor.execute("PRAGMA journal_mode=WAL")
            finally:
                cursor.close()

    return engine


engine = _make_engine(get_settings().database_url)

SessionLocal = sessionmaker(
    bind=engine, class_=Session, autoflush=False, expire_on_commit=False
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
