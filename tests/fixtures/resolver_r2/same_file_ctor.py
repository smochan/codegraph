from dataclasses import dataclass


@dataclass
class Widget:
    name: str


WIDGETS = [Widget("a"), Widget("b")]
