import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger("app.services.documents.storage")


class StorageService(ABC):
    """Abstract protocol for file storage (Local FS, S3, R2, GCS)."""

    @abstractmethod
    async def upload_file(
        self,
        storage_key: str,
        content: bytes,
        content_type: str,
    ) -> str:
        """Persist file content under the specified storage key."""
        pass

    @abstractmethod
    async def download_file(self, storage_key: str) -> bytes:
        """Retrieve binary file content by storage key."""
        pass

    @abstractmethod
    async def delete_file(self, storage_key: str) -> bool:
        """Delete file associated with storage key."""
        pass

    @abstractmethod
    async def file_exists(self, storage_key: str) -> bool:
        """Check if a file exists under storage key."""
        pass


class LocalStorageService(StorageService):
    """Filesystem-backed storage service for local development and testing."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        if base_dir is None:
            settings = get_settings()
            self.base_dir = Path(settings.STORAGE_LOCAL_DIR).resolve()
        else:
            self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, storage_key: str) -> Path:
        """Safely resolve storage key to filesystem path, preventing path traversal."""
        clean_key = storage_key.strip().lstrip("/\\")
        resolved = (self.base_dir / clean_key).resolve()
        if not str(resolved).startswith(str(self.base_dir)):
            raise ValueError(f"Path traversal detected for storage key: {storage_key}")
        return resolved

    async def upload_file(
        self,
        storage_key: str,
        content: bytes,
        content_type: str,
    ) -> str:
        _ = content_type
        file_path = self._resolve_path(storage_key)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> None:
            with open(file_path, "wb") as f:
                f.write(content)

        await asyncio.to_thread(_write)
        logger.info("Stored file at: %s (%d bytes)", storage_key, len(content))
        return storage_key

    async def download_file(self, storage_key: str) -> bytes:
        file_path = self._resolve_path(storage_key)
        if not file_path.exists():
            raise FileNotFoundError(f"Storage file not found: {storage_key}")

        def _read() -> bytes:
            with open(file_path, "rb") as f:
                return f.read()

        return await asyncio.to_thread(_read)

    async def delete_file(self, storage_key: str) -> bool:
        file_path = self._resolve_path(storage_key)

        def _delete() -> bool:
            if file_path.exists():
                file_path.unlink()
                return True
            return False

        deleted = await asyncio.to_thread(_delete)
        if deleted:
            logger.info("Deleted file at: %s", storage_key)
        return deleted

    async def file_exists(self, storage_key: str) -> bool:
        file_path = self._resolve_path(storage_key)
        return await asyncio.to_thread(file_path.exists)


# Global storage service factory instance
_storage_service: StorageService | None = None


def get_storage_service() -> StorageService:
    """Retrieve configured storage service instance."""
    global _storage_service
    if _storage_service is None:
        _storage_service = LocalStorageService()
    return _storage_service


def set_storage_service(service: StorageService | None) -> None:
    """Override storage service (e.g. for testing with mock or temp directory)."""
    global _storage_service
    _storage_service = service
