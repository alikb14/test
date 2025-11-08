from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.database import Database

from .cards import CardService
from .requests import RequestService
from .users import UserService


@dataclass(slots=True)
class ServiceRegistry:
    database: Database
    cards: CardService
    requests: RequestService
    users: UserService


def build_services(settings: Settings) -> ServiceRegistry:
    database = Database(settings)
    cards = CardService(database, settings.media_root)
    requests = RequestService(database)
    users = UserService(database)
    return ServiceRegistry(database=database, cards=cards, requests=requests, users=users)


__all__ = ["ServiceRegistry", "build_services"]
