from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.knowledge_base import KnowledgeBase
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.models.user import User
from app.services.auth.password import PasswordService
from app.services.auth.tokens import TokenService
from app.services.documents.storage import LocalStorageService, set_storage_service


@pytest.fixture(autouse=True)
def override_settings(tmp_path: Path) -> None:
    """Override application settings with test settings for all tests."""
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)

    test_settings = Settings(
        APP_ENV="test",
        APP_NAME="RAGForge-Test",
        DEBUG=True,
        LOG_LEVEL="DEBUG",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        CORS_ORIGINS=["http://testserver", "http://localhost:3000"],
        JWT_SECRET_KEY="test-jwt-secret-key-must-be-32-chars-long!",
        JWT_ALGORITHM="HS256",
        ACCESS_TOKEN_EXPIRE_MINUTES=15,
        REFRESH_TOKEN_EXPIRE_DAYS=7,
        STORAGE_BACKEND="local",
        STORAGE_LOCAL_DIR=str(storage_dir),
        MAX_UPLOAD_SIZE_MB=25,
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    set_storage_service(LocalStorageService(base_dir=storage_dir))


@pytest.fixture
async def db_engine():
    """Create in-memory SQLite async engine and tables for tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional async database session for tests."""
    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client with database dependency override."""
    app.dependency_overrides[get_db] = lambda: db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def test_user_and_org(db_session: AsyncSession) -> dict[str, object]:
    """Create a verified test user with default organization and tokens."""
    pwd_hash = PasswordService.hash("StrongPassword123!")
    user = User(
        email="testuser@example.com",
        password_hash=pwd_hash,
        full_name="Test User",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    org = Organization(name="Test User's Workspace", slug="test-users-workspace")
    db_session.add(org)
    await db_session.flush()

    membership = OrganizationMembership(
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.OWNER,
    )
    db_session.add(membership)
    await db_session.flush()

    raw_refresh, _ = await TokenService.create_refresh_token(db_session, user.id)
    await db_session.commit()

    return {
        "user": user,
        "org": org,
        "membership": membership,
        "raw_refresh_token": raw_refresh,
        "password": "StrongPassword123!",
    }


@pytest.fixture
async def test_kb(db_session: AsyncSession, test_user_and_org: dict) -> KnowledgeBase:
    """Create a test knowledge base belonging to test_user_and_org's organization."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]

    kb = KnowledgeBase(
        organization_id=org.id,
        name="Research Docs",
        slug="research-docs",
        description="Core research documents",
        created_by=user.id,
        is_active=True,
    )
    db_session.add(kb)
    await db_session.commit()
    await db_session.refresh(kb)
    return kb
