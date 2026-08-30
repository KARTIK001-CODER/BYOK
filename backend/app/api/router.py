from fastapi import APIRouter

from app.api.v1.auth import router as auth_v1_router
from app.api.v1.health import router as health_v1_router
from app.api.v1.organizations import router as organizations_v1_router

api_router = APIRouter()

# Register v1 domain routers
api_router.include_router(health_v1_router, prefix="", tags=["Health & Readiness"])
api_router.include_router(auth_v1_router, prefix="", tags=["Authentication"])
api_router.include_router(organizations_v1_router, prefix="", tags=["Multi-Tenancy"])

# Future Phase Routers will be registered here:
# - documents_v1_router (/documents - Ingestion)
# - retrieval_v1_router (/retrieval - Search & Rerank)
# - rag_v1_router (/rag - Generation)
# - keys_v1_router (/keys - BYOK Vault)
# - evaluation_v1_router (/evaluation - Grounding)
