"""
SQLAlchemy ORM models package.

Future phases will define:
- Document & Chunk models
- Embedding & Vector Index models
- User & Key Vault models (BYOK encrypted credentials)
"""

from app.db.base import Base

__all__ = ["Base"]
