from typing import Union


class Foo:
    def method(self) -> str:
        return "foo"


class Bar:
    def method(self) -> str:
        return "bar"


class Holder:
    _b: Union[Foo, Bar]  # noqa: UP007 - intentional pre-PEP 604 syntax test

    def use(self) -> str:
        return self._b.method()
