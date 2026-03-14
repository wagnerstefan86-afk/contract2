import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.database import engine, Base, async_session
from app.api.router import api_router
from app.config import settings

# Configure logging so discovery pipeline output is visible
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


async def _bootstrap_admin():
    """Create or promote the initial admin user on startup if configured via env."""
    if not settings.initial_admin_email or not settings.initial_admin_password:
        return

    from app.models.benutzer import Benutzer, BenutzerRolle, BenutzerStatus
    from app.auth import hash_passwort

    async with async_session() as db:
        result = await db.execute(
            select(Benutzer).where(Benutzer.email == settings.initial_admin_email.lower().strip())
        )
        existing = result.scalar_one_or_none()

        if existing:
            if existing.rolle != BenutzerRolle.ADMIN.value or existing.status != BenutzerStatus.AKTIV.value:
                existing.rolle = BenutzerRolle.ADMIN.value
                existing.status = BenutzerStatus.AKTIV.value
                await db.commit()
                logger.info(f"Bestehender Benutzer '{existing.email}' zum Admin befördert")
            else:
                logger.info(f"Admin '{existing.email}' bereits vorhanden")
        else:
            admin = Benutzer(
                name=settings.initial_admin_name,
                email=settings.initial_admin_email.lower().strip(),
                passwort_hash=hash_passwort(settings.initial_admin_password),
                rolle=BenutzerRolle.ADMIN.value,
                status=BenutzerStatus.AKTIV.value,
            )
            db.add(admin)
            await db.commit()
            logger.info(f"Initial-Admin '{admin.email}' erstellt")


async def _seed_policies():
    """Seed the default policy profile on startup if none exists."""
    try:
        from app.services.policy_seed import seed_policy_profile
        async with async_session() as db:
            await seed_policy_profile(db)
    except Exception as e:
        logger.warning(f"Policy-Seed übersprungen: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (replace with alembic migrations later)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Bootstrap admin user
    await _bootstrap_admin()
    # Seed policy profile
    await _seed_policies()
    yield


app = FastAPI(
    title="Vertragsprüfung API",
    description="API für KI-gestützte Vertragsprüfung mit hoher Erkennungsrate",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
