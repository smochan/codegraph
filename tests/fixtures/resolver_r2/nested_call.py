def helper(x: int) -> int:
    return x + 1


def outer(items: list[int]) -> list[int]:
    def inner(x: int) -> int:
        return helper(x) * 2

    return [inner(i) for i in items]
