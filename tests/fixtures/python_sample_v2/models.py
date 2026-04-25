"""Sample models module (v2 - modified signatures, removed `fetch`)."""
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

    def speak(self, loud: bool = False) -> str:
        greeting = "WOOF!" if loud else "Woof!"
        return f"{greeting} I am {self.name}"


@dataclass
class Cat(Animal):
    """A cat."""

    indoor: bool = True

    def speak(self) -> str:
        return f"Meow from {self.name}"
