from pydantic import BaseModel


class StatusResponse(BaseModel):
    status: str = "ok"


class StatusMessageResponse(BaseModel):
    status: str = "ok"
    message: str


class LogoutAllResponse(BaseModel):
    status: str = "ok"
    revoked_count: int


class HealthResponse(BaseModel):
    status: str = "ok"
