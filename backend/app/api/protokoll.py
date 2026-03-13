import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.protokoll import Protokoll

router = APIRouter(prefix="/protokoll", tags=["Protokoll"])


@router.get("/analyse/{analyse_id}")
async def protokoll_fuer_analyse(analyse_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Protokoll).where(Protokoll.analyse_id == analyse_id).order_by(Protokoll.erstellt_am.asc())
    )
    rows = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "ebene": r.ebene,
            "nachricht": r.nachricht,
            "details": r.details,
            "erstellt_am": r.erstellt_am.isoformat(),
        }
        for r in rows
    ]
