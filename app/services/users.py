from __future__ import annotations

from datetime import date
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database import Department, Database, User, UserRole, CardType
from app.utils.logger import logger


class UserService:
    """Data access helpers for working with users."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_by_phone(self, phone: str) -> User | None:
        async with self.database.session() as session:
            return await self._get_by_phone(session, phone)

    async def _get_by_phone(self, session: AsyncSession, phone: str) -> User | None:
        result = await session.execute(select(User).where(User.phone == phone))
        return result.scalars().first()

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        async with self.database.session() as session:
            result = await session.execute(
                select(User).where(
                    User.telegram_id == telegram_id,
                    User.is_active.is_(True),
                )
            )
            return result.scalars().first()

    async def get_by_id(self, user_id: int) -> User | None:
        async with self.database.session() as session:
            return await session.get(User, user_id)

    async def attach_telegram_account(
        self, user: User, telegram_id: int
    ) -> User:
        async with self.database.session() as session:
            db_user = await session.get(User, user.id)
            if db_user is None:
                raise NoResultFound(f"User id={user.id} not found")
            db_user.telegram_id = telegram_id
            await session.commit()
            await session.refresh(db_user)
            logger.log(
                "User telegram attached",
                user_id=db_user.id,
                telegram_id=telegram_id,
            )
            return db_user

    async def list_responsibles(self) -> list[User]:
        async with self.database.session() as session:
            result = await session.execute(
                select(User).where(
                    User.role == UserRole.RESPONSIBLE,
                    User.is_active.is_(True),
                )
            )
            return list(result.scalars().all())

    async def list_members(self, manager_id: int) -> list[User]:
        async with self.database.session() as session:
            result = await session.execute(
                select(User).where(User.manager_id == manager_id)
            )
            return list(result.scalars().all())

    async def list_users(self) -> list[User]:
        async with self.database.session() as session:
            result = await session.execute(select(User))
            return list(result.scalars().all())

    async def list_admins(self) -> list[User]:
        async with self.database.session() as session:
            result = await session.execute(
                select(User).where(
                    User.role == UserRole.ADMIN,
                    User.is_active.is_(True),
                )
            )
            return list(result.scalars().all())

    async def export_users(self, manager_id: int | None = None) -> list[dict]:
        async with self.database.session() as session:
            manager_alias = aliased(User)
            stmt = (
                select(
                    User.id,
                    User.full_name,
                    User.phone,
                    User.role,
                    User.department,
                    User.line_expiry,
                    User.is_active,
                    manager_alias.full_name.label("manager_name"),
                )
                .outerjoin(manager_alias, User.manager_id == manager_alias.id)
            )
            if manager_id is not None:
                stmt = stmt.where(User.manager_id == manager_id)

            result = await session.execute(stmt.order_by(User.full_name))
            rows = result.all()
            data: list[dict] = []
            for row in rows:
                data.append(
                    {
                        "id": row.id,
                        "full_name": row.full_name,
                        "phone": row.phone,
                        "role": row.role.value,
                        "department": row.department.value if row.department else None,
                        "line_expiry": row.line_expiry,
                        "is_active": row.is_active,
                        "manager": row.manager_name,
                    }
                )
            return data

    async def create_user(
        self,
        *,
        full_name: str,
        phone: str,
        role: UserRole,
        manager_id: int | None,
        department: Department | None,
        line_expiry: date | None,
        line_type: CardType | None = None,
        can_approve_directly: bool = False,
    ) -> User:
        async with self.database.session() as session:
            try:
                user = User(
                    full_name=full_name,
                    phone=phone,
                    role=role,
                    manager_id=manager_id,
                    department=department,
                    line_expiry=line_expiry,
                    line_type=line_type,
                    can_approve_directly=can_approve_directly,
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
                logger.log(
                    "User created",
                    user_id=user.id,
                    role=role.value,
                    manager_id=manager_id,
                    department=department.value if department else None,
                    can_approve_directly=can_approve_directly,
                )
                return user
            except Exception:
                await session.rollback()
                raise

    async def deactivate_user(self, user_id: int) -> User:
        async with self.database.session() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise NoResultFound(f"User id={user_id} not found")

            for member in list(user.members):
                member.manager_id = None

            user.is_active = False
            user.telegram_id = None

            await session.commit()
            await session.refresh(user)

            logger.log(
                "User deactivated",
                user_id=user.id,
            )
            return user
