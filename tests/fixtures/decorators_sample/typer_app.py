"""Typer fixture for entry-point detection."""
import typer

app = typer.Typer()


@app.command()
def greet(name: str) -> None:
    print(f"hello {name}")


@app.command("bye")
def farewell(name: str) -> None:
    print(f"bye {name}")


@app.callback()
def main_callback(ctx: typer.Context) -> None:
    pass


def _internal_helper() -> str:
    return "helper"
