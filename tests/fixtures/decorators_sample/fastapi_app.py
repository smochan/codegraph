"""FastAPI fixture for entry-point detection."""
from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/items")
def create_item(name: str) -> dict[str, str]:
    return {"name": name}


def _validate_item(name: str) -> bool:
    return bool(name)
