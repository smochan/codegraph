"""User routes — FastAPI handlers for /api/users."""
from fastapi import APIRouter

from backend.repositories.user_repository import UserRepository
from backend.services.user_service import UserService

router = APIRouter()


def _get_service() -> UserService:
    # In a real app, this would inject a session-scoped repo via Depends.
    repo = UserRepository(session=None)  # type: ignore[arg-type]
    return UserService(repo=repo)


@router.get("/api/users/{user_id}")
def get_user(user_id: int) -> dict:
    service = _get_service()
    return service.get_user(user_id) or {}


@router.get("/api/users")
def list_users() -> list[dict]:
    service = _get_service()
    return service.list_users()


@router.post("/api/users")
def create_user(email: str, name: str) -> dict:
    service = _get_service()
    return service.create_user(email=email, name=name)
