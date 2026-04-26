def my_decorator(arg: str):
    def wrap(fn):
        return fn

    return wrap


@my_decorator("foo")
def handler() -> None:
    pass
