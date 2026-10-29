from fastapi import APIRouter

from app.api.v1 import admin, attendance, auth, people, recognition

api_router = APIRouter()
for module in (auth, people, recognition, attendance, admin):
    api_router.include_router(module.router)
