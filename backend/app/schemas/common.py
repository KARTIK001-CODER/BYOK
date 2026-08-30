from pydantic import BaseModel, Field


class PaginatedResponse[T](BaseModel):
    """Standardized envelope for paginated resource lists."""

    items: list[T]
    total: int = Field(..., description="Total number of items matching filter")
    limit: int = Field(..., description="Number of items returned per page")
    offset: int = Field(..., description="Starting offset")
