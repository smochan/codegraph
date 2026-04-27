class Service:
    def run(self) -> str:
        return "ok"


class Handler:
    def __init__(self) -> None:
        self._svc: Service = Service()

    def go(self) -> str:
        return self._svc.run()
