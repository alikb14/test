from __future__ import annotations

from aiogram import Router

from . import admin, auth, common, requests, responsible, user

router = Router(name="root")
router.include_router(auth.router)
router.include_router(admin.router)
router.include_router(responsible.router)
router.include_router(user.router)
router.include_router(requests.router)
router.include_router(common.router)

__all__ = ["router"]
