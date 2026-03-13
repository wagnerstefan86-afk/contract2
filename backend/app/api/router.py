from fastapi import APIRouter

from app.api.vertraege import router as vertraege_router
from app.api.analysen import router as analysen_router
from app.api.fundstellen import router as fundstellen_router
from app.api.einstellungen import router as einstellungen_router
from app.api.protokoll import router as protokoll_router
from app.api.demo import router as demo_router

api_router = APIRouter()
api_router.include_router(vertraege_router)
api_router.include_router(analysen_router)
api_router.include_router(fundstellen_router)
api_router.include_router(einstellungen_router)
api_router.include_router(protokoll_router)
api_router.include_router(demo_router)
