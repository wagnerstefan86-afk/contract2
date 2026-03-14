"""API endpoints for Policy Profiles and Rules."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.auth import get_current_user
from app.models.benutzer import Benutzer
from app.models.policy_profile import PolicyProfile
from app.schemas.policy import PolicyProfileResponse

router = APIRouter(prefix="/policy", tags=["Policy"])


@router.get("/profiles", response_model=list[PolicyProfileResponse])
async def list_profiles(
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PolicyProfile)
        .options(selectinload(PolicyProfile.rules))
        .order_by(PolicyProfile.created_at.desc())
    )
    return result.scalars().all()


@router.get("/profiles/active", response_model=PolicyProfileResponse)
async def get_active_profile(
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PolicyProfile)
        .where(PolicyProfile.is_active == True)
        .options(selectinload(PolicyProfile.rules))
        .limit(1)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Kein aktives Policy-Profil vorhanden")
    return profile


@router.get("/profiles/{profile_id}", response_model=PolicyProfileResponse)
async def get_profile(
    profile_id: uuid.UUID,
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PolicyProfile)
        .where(PolicyProfile.id == profile_id)
        .options(selectinload(PolicyProfile.rules))
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Policy-Profil nicht gefunden")
    return profile
