"""User service — business logic for users."""
from backend.repositories.user_repository import UserRepository


class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self.repo = repo

    def get_user(self, user_id: int) -> dict | None:
        user = self.repo.get_by_id(user_id)
        if user is None:
            return None
        return {"id": user.id, "email": user.email, "name": user.name}

    def list_users(self) -> list[dict]:
        users = self.repo.list_all()
        return [
            {"id": u.id, "email": u.email, "name": u.name} for u in users
        ]

    def create_user(self, email: str, name: str) -> dict:
        user = self.repo.create(email=email, name=name)
        return {"id": user.id, "email": user.email, "name": user.name}
