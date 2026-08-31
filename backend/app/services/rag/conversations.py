import logging
import re
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundException
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole

logger = logging.getLogger("app.services.rag.conversations")


class ConversationService:
    """Domain service managing multi-tenant conversation threads and message persistence."""

    @staticmethod
    def generate_conversation_title(query: str) -> str:
        """
        Derive a clean, concise conversation title directly from the initial query
        without making an external LLM request.
        """
        cleaned = re.sub(r"\s+", " ", query.strip())
        # Remove common prompt prefixes if present
        cleaned = re.sub(
            r"^(please\s+|can\s+you\s+|tell\s+me\s+about\s+|what\s+is\s+|how\s+does\s+|explain\s+)",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        if not cleaned:
            return "New Conversation"
        cleaned = cleaned[0].upper() + cleaned[1:]
        if len(cleaned) > 60:
            cleaned = cleaned[:57] + "..."
        return cleaned

    @classmethod
    async def create_conversation(
        cls,
        session: AsyncSession,
        organization_id: str,
        user_id: str,
        title: str | None = None,
        knowledge_base_ids: list[str] | None = None,
        metadata: dict | None = None,
    ) -> Conversation:
        """Explicitly create a new conversation thread."""
        conv_title = title.strip() if title and title.strip() else "New Conversation"
        conv = Conversation(
            organization_id=organization_id,
            user_id=user_id,
            title=conv_title,
            knowledge_base_ids=knowledge_base_ids,
            conversation_metadata=metadata,
        )
        session.add(conv)
        await session.flush()
        await session.refresh(conv)
        return conv

    @classmethod
    async def get_or_create_conversation(
        cls,
        session: AsyncSession,
        organization_id: str,
        user_id: str,
        conversation_id: str | None,
        initial_query: str,
        knowledge_base_ids: list[str] | None = None,
    ) -> Conversation:
        """Fetch an existing conversation or create a new one with an auto-derived title."""
        if conversation_id:
            stmt = (
                select(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.organization_id == organization_id,
                )
                .options(selectinload(Conversation.messages))
            )
            result = await session.execute(stmt)
            conv = result.scalar_one_or_none()
            if not conv:
                raise NotFoundException(
                    message=f"Conversation '{conversation_id}' not found or access denied."
                )
            if knowledge_base_ids and not conv.knowledge_base_ids:
                conv.knowledge_base_ids = knowledge_base_ids
                await session.flush()
            return conv

        # Derive title and create
        title = cls.generate_conversation_title(initial_query)
        return await cls.create_conversation(
            session=session,
            organization_id=organization_id,
            user_id=user_id,
            title=title,
            knowledge_base_ids=knowledge_base_ids,
        )

    @classmethod
    async def get_conversation(
        cls,
        session: AsyncSession,
        organization_id: str,
        conversation_id: str,
        load_messages: bool = True,
    ) -> Conversation:
        """Retrieve a conversation by ID with tenant isolation check."""
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.organization_id == organization_id,
        )
        if load_messages:
            stmt = stmt.options(selectinload(Conversation.messages))

        result = await session.execute(stmt)
        conv = result.scalar_one_or_none()
        if not conv:
            raise NotFoundException(
                message=f"Conversation '{conversation_id}' not found or access denied."
            )
        return conv

    @classmethod
    async def list_conversations(
        cls,
        session: AsyncSession,
        organization_id: str,
        user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Conversation], int]:
        """List conversations for an organization with pagination and message counts."""
        base_where = [Conversation.organization_id == organization_id]
        if user_id:
            base_where.append(Conversation.user_id == user_id)

        # Count total
        count_stmt = select(func.count(Conversation.id)).where(*base_where)
        total_result = await session.execute(count_stmt)
        total = total_result.scalar_one()

        # Query items
        stmt = (
            select(Conversation)
            .where(*base_where)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
            .options(selectinload(Conversation.messages))
        )
        result = await session.execute(stmt)
        conversations = list(result.scalars().all())
        return conversations, total

    @classmethod
    async def delete_conversation(
        cls,
        session: AsyncSession,
        organization_id: str,
        conversation_id: str,
    ) -> bool:
        """Delete a conversation thread and all cascaded messages with tenant scoping."""
        stmt = delete(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.organization_id == organization_id,
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount > 0

    @classmethod
    async def add_message(
        cls,
        session: AsyncSession,
        conversation_id: str,
        role: MessageRole | str,
        content: str,
        metadata: dict | None = None,
    ) -> Message:
        """Append a message to a conversation thread and touch the conversation's updated_at timestamp."""
        role_enum = MessageRole(role) if isinstance(role, str) else role
        msg = Message(
            conversation_id=conversation_id,
            role=role_enum,
            content=content,
            message_metadata=metadata,
            created_at=datetime.now(UTC),
        )
        session.add(msg)
        await session.flush()
        await session.refresh(msg)
        return msg

    @classmethod
    async def get_recent_messages(
        cls,
        session: AsyncSession,
        conversation_id: str,
        limit: int = 10,
    ) -> list[Message]:
        """Fetch the most recent messages for a conversation in chronological order."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
