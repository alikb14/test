from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings


class Database:
    """Database engine and session factory."""

    def __init__(self, settings: Settings) -> None:
        self._engine = create_async_engine(settings.database_url, echo=False, future=True)
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    @property
    def engine(self):
        return self._engine

    def session(self) -> AsyncSession:
        return self._session_factory()


__all__ = ["Database"]
