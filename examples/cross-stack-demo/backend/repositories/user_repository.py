"""User repository — SQLAlchemy data access for User."""
from sqlalchemy.orm import Session

from backend.models import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, user_id: int) -> User | None:
        return self.session.query(User).filter(User.id == user_id).first()

    def list_all(self) -> list[User]:
        return self.session.query(User).all()

    def create(self, email: str, name: str) -> User:
        # Inline constructor so DF1 can trace the WRITES_TO target back
        # to the User model class.
        self.session.add(User(email=email, name=name))
        self.session.commit()
        return User(email=email, name=name)
