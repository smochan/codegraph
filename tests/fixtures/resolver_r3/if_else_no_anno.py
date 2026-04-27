class Foo:
    def method(self) -> str:
        return "foo"


class Bar:
    def method(self) -> str:
        return "bar"


class Facade:
    def __init__(self, x: bool) -> None:
        if x:
            self._b = Foo()
        else:
            self._b = Bar()

    def use(self) -> str:
        return self._b.method()
