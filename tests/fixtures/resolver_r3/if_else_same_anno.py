class Base:
    def run(self) -> str:
        return "base"


class Foo(Base):
    def run(self) -> str:
        return "foo"


class Bar(Base):
    def run(self) -> str:
        return "bar"


class Facade:
    def __init__(self, flag: bool) -> None:
        if flag:
            self._b: Base = Foo()
        else:
            self._b: Base = Bar()

    def use(self) -> str:
        return self._b.run()
