"""Service-layer classes used as SERVICE fixtures."""
from __future__ import annotations


def Injectable():
    def deco(cls):
        return cls
    return deco


class UserService:
    def get_user(self, uid: str) -> dict:
        return {"id": uid}

    def delete_user(self, uid: str) -> None:
        del uid


@Injectable()
class PaymentProcessor:
    def charge(self, amount: int) -> bool:
        return amount > 0


class User:
    """Plain class — should not get any role."""

    def __init__(self, name: str) -> None:
        self.name = name
