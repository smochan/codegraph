"""Order service — business logic for orders."""
from backend.repositories.order_repository import OrderRepository


class OrderService:
    def __init__(self, repo: OrderRepository) -> None:
        self.repo = repo

    def list_orders(self, user_id: int) -> list[dict]:
        orders = self.repo.list_for_user(user_id)
        return [
            {"id": o.id, "user_id": o.user_id, "total_cents": o.total_cents}
            for o in orders
        ]

    def create_order(self, user_id: int, total_cents: int) -> dict:
        order = self.repo.create(user_id=user_id, total_cents=total_cents)
        return {"id": order.id, "user_id": order.user_id, "total_cents": order.total_cents}
