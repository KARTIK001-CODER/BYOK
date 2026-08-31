from app.api.v1.auth import router as auth_router
from app.api.v1.documents import router as documents_router
from app.api.v1.embeddings import router as embeddings_router
from app.api.v1.health import router as health_router
from app.api.v1.ingestion import router as ingestion_router
from app.api.v1.knowledge_bases import router as knowledge_bases_router
from app.api.v1.organizations import router as organizations_router
from app.api.v1.retrieval import router as retrieval_router

__all__ = [
    "health_router",
    "auth_router",
    "organizations_router",
    "knowledge_bases_router",
    "documents_router",
    "ingestion_router",
    "embeddings_router",
    "retrieval_router",
]
