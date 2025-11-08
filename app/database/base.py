from __future__ import annotations

from typing import Any

from sqlalchemy.orm import DeclarativeBase, declared_attr


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models with automatic table naming."""

    __abstract__ = True

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return cls.__name__.lower()

    def to_dict(self) -> dict[str, Any]:
        """Serialize model columns into a dictionary."""

        return {
            key: getattr(self, key)
            for key in self.__mapper__.c.keys()  # type: ignore[attr-defined]
        }
