class Foo:
    def method(self) -> str:
        return "foo"


class Bar:
    def method(self) -> str:
        return "bar"


class Holder:
    _b: Foo | Bar

    def use(self) -> str:
        return self._b.method()
