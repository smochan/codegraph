class C:
    def use(self) -> None:
        # No declaration of self._missing anywhere — must not crash and
        # must not produce a CALLS edge to a phantom symbol.
        return self._missing.method()
