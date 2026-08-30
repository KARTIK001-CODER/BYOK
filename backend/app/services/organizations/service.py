import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization

logger = logging.getLogger("app.services.organizations")


def slugify(text: str) -> str:
    """Convert text into a URL-friendly slug."""
    text = text.lower().strip()
    # Replace non-alphanumeric characters with hyphens
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "org"


class OrganizationService:
    """Service handling multi-tenant organization and membership operations."""

    @staticmethod
    async def generate_unique_slug(session: AsyncSession, base_name: str) -> str:
        """Generate a collision-free organization slug."""
        base_slug = slugify(base_name)
        candidate = base_slug
        counter = 1

        while True:
            stmt = select(Organization.id).where(Organization.slug == candidate)
            result = await session.execute(stmt)
            if result.scalar_one_or_none() is None:
                return candidate
            counter += 1
            candidate = f"{base_slug}-{counter}"

    @staticmethod
    async def create_organization(
        session: AsyncSession,
        name: str,
        slug: str | None = None,
    ) -> Organization:
        """Create a new Organization record."""
        if not slug:
            slug = await OrganizationService.generate_unique_slug(session, name)
        else:
            slug = slugify(slug)
            # Verify uniqueness if custom slug supplied
            existing = await OrganizationService.get_by_slug(session, slug)
            if existing:
                slug = await OrganizationService.generate_unique_slug(session, slug)

        org = Organization(name=name.strip(), slug=slug)
        session.add(org)
        await session.flush()
        logger.info("Created organization id=%s with slug=%s", org.id, org.slug)
        return org

    @staticmethod
    async def get_by_id(session: AsyncSession, org_id: str) -> Organization | None:
        """Fetch organization by primary key."""
        stmt = select(Organization).where(Organization.id == org_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_slug(session: AsyncSession, slug: str) -> Organization | None:
        """Fetch organization by slug."""
        stmt = select(Organization).where(Organization.slug == slug)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_membership(
        session: AsyncSession,
        organization_id: str,
        user_id: str,
        role: OrganizationRole = OrganizationRole.MEMBER,
    ) -> OrganizationMembership:
        """Create an organization membership association."""
        membership = OrganizationMembership(
            organization_id=organization_id,
            user_id=user_id,
            role=role,
        )
        session.add(membership)
        await session.flush()
        logger.info(
            "Created membership user_id=%s org_id=%s role=%s",
            user_id,
            organization_id,
            role.value,
        )
        return membership

    @staticmethod
    async def get_membership(
        session: AsyncSession,
        organization_id: str,
        user_id: str,
    ) -> OrganizationMembership | None:
        """Fetch active membership for a specific user and organization."""
        stmt = (
            select(OrganizationMembership)
            .where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user_id,
            )
            .options(selectinload(OrganizationMembership.organization))
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_memberships(
        session: AsyncSession,
        user_id: str,
    ) -> list[OrganizationMembership]:
        """Fetch all organizations a user belongs to."""
        stmt = (
            select(OrganizationMembership)
            .where(OrganizationMembership.user_id == user_id)
            .options(selectinload(OrganizationMembership.organization))
            .order_by(OrganizationMembership.created_at.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
