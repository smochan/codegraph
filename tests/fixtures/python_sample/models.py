"""Sample models module."""
from __future__ import annotations

from dataclasses import dataclass


class Animal:
    """Base animal class."""

    def __init__(self, name: str) -> None:
        self.name = name

    def speak(self) -> str:
        raise NotImplementedError


class Dog(Animal):
    """A dog."""

    def speak(self) -> str:
        return f"Woof! I am {self.name}"

    def fetch(self, item: str) -> str:
        result = self.speak()
        return f"{result} fetching {item}"


@dataclass
class Cat(Animal):
    """A cat."""

    indoor: bool = True

    def speak(self) -> str:
        return f"Meow from {self.name}"
