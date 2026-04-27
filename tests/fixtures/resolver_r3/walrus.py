class Foo:
    def method(self) -> str:
        return "foo"


class C:
    def __init__(self) -> None:
        # Walrus is intentionally unsupported in R3 — must not crash.
        if (x := Foo()):
            self._b = x

    def use(self) -> str:
        return self._b.method()
