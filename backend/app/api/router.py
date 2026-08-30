from fastapi import APIRouter

from app.api.v1.health import router as health_v1_router

api_router = APIRouter()

# Register v1 domain routers
api_router.include_router(health_v1_router, prefix="", tags=["Health & Readiness"])

# Future Phase Routers will be registered here:
# - auth_v1_router (/auth)
# - documents_v1_router (/documents)
# - retrieval_v1_router (/retrieval)
# - rag_v1_router (/rag)
# - keys_v1_router (/keys - BYOK)
# - evaluation_v1_router (/evaluation)
