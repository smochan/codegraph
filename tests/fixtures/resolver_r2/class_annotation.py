class Service:
    def run(self) -> str:
        return "ok"


class Handler:
    svc: Service

    def go(self) -> str:
        return self.svc.run()
