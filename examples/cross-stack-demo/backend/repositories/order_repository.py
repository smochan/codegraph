"""Order repository — SQLAlchemy data access for Order."""
from sqlalchemy.orm import Session

from backend.models import Order


class OrderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_user(self, user_id: int) -> list[Order]:
        return self.session.query(Order).filter(Order.user_id == user_id).all()

    def create(self, user_id: int, total_cents: int) -> Order:
        self.session.add(Order(user_id=user_id, total_cents=total_cents))
        self.session.commit()
        return Order(user_id=user_id, total_cents=total_cents)
