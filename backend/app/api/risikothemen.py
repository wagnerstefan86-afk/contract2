"""API endpoints for RisikoThema (LLM-generated topic clusters)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.auth import get_current_user
from app.models.benutzer import Benutzer
from app.models.risikothema import RisikoThema
from app.schemas.risikothema import RisikoThemaResponse

router = APIRouter(prefix="/risikothemen", tags=["Risikothemen"])


@router.get("/vertrag/{vertrag_id}", response_model=list[RisikoThemaResponse])
async def risikothemen_fuer_vertrag(
    vertrag_id: uuid.UUID,
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all risk topics for a contract, with nested findings."""
    result = await db.execute(
        select(RisikoThema)
        .where(RisikoThema.vertrag_id == vertrag_id)
        .options(selectinload(RisikoThema.fundstellen))
        .order_by(RisikoThema.sortierung)
    )
    return result.scalars().all()
