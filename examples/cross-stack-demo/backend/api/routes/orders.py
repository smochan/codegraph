"""Order routes — FastAPI handlers for /api/orders."""
from fastapi import APIRouter

from backend.repositories.order_repository import OrderRepository
from backend.services.order_service import OrderService

router = APIRouter()


def _get_service() -> OrderService:
    repo = OrderRepository(session=None)  # type: ignore[arg-type]
    return OrderService(repo=repo)


@router.get("/api/orders")
def list_orders(user_id: int) -> list[dict]:
    service = _get_service()
    return service.list_orders(user_id=user_id)


@router.post("/api/orders")
def create_order(user_id: int, total_cents: int) -> dict:
    service = _get_service()
    return service.create_order(user_id=user_id, total_cents=total_cents)
