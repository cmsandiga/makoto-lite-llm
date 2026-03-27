from pydantic import BaseModel


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class PaginatedRequest(BaseModel):
    page: int = 1
    page_size: int = 50


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
