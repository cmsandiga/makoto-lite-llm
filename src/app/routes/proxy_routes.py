from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["proxy"])

# POST /chat/completions handler is implemented in Task 11.
