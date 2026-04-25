"""codegraph CLI entry point.

This is a Phase-0 skeleton. Each subcommand is wired to a stub that prints
its intended behavior so the surface is testable end-to-end before
implementation lands in subsequent phases.
"""

from __future__ import annotations

import typer
from rich.console import Console

from codegraph import __version__

app = typer.Typer(
    name="codegraph",
    help="Build, analyze, review, and visualize code graphs across languages.",
    no_args_is_help=True,
    add_completion=False,
    invoke_without_command=True,
)
query_app = typer.Typer(help="Query small, focused subgraphs.", no_args_is_help=True)
baseline_app = typer.Typer(help="Manage baseline snapshots.", no_args_is_help=True)
hook_app = typer.Typer(help="Manage git hooks.", no_args_is_help=True)
mcp_app = typer.Typer(help="Run codegraph as an MCP server.", no_args_is_help=True)
app.add_typer(query_app, name="query")
app.add_typer(baseline_app, name="baseline")
app.add_typer(hook_app, name="hook")
app.add_typer(mcp_app, name="mcp")

console = Console()


def _stub(name: str) -> None:
    console.print(
        f"[yellow]TODO[/yellow] \\[{name}] not yet implemented (Phase 0 skeleton)."
    )


@app.callback()
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version and exit."),
) -> None:
    if version:
        console.print(f"codegraph {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
def init() -> None:
    """Interactive setup: detect languages, write `.codegraph.yml`, optionally install hooks."""
    _stub("init")


@app.command()
def build(incremental: bool = typer.Option(True, help="Incremental build when possible.")) -> None:
    """Parse the repo and (re)build the graph."""
    _stub("build")


@app.command()
def status() -> None:
    """Show graph freshness, last build, and drift indicators."""
    _stub("status")


@app.command()
def viz(
    out: str = typer.Option("mermaid", "--out", help="mermaid|html|svg"),
    scope: str = typer.Option("", "--scope", help="Path or symbol to focus on."),
) -> None:
    """Render a graph visualization."""
    _stub("viz")


@app.command()
def analyze(
    fmt: str = typer.Option("markdown", "--format", help="markdown|json"),
) -> None:
    """Whole-project audit: dead code, cycles, untested, hotspots."""
    _stub("analyze")


@app.command()
def review(
    target: str = typer.Option("main", help="Target branch to PR into."),
    block_on: str = typer.Option("high", help="critical|high|medium"),
) -> None:
    """Diff vs baseline; produce risk-scored PR review."""
    _stub("review")


@query_app.command("callers")
def query_callers(symbol: str, depth: int = 1) -> None:
    """Show reverse CALLS subgraph for a symbol."""
    _stub("query callers")


@query_app.command("subgraph")
def query_subgraph(symbol: str, depth: int = 2) -> None:
    """Return a small subgraph anchored at a symbol."""
    _stub("query subgraph")


@query_app.command("untested")
def query_untested() -> None:
    """List functions with no TESTED_BY edge."""
    _stub("query untested")


@query_app.command("deadcode")
def query_deadcode() -> None:
    """List nodes with zero incoming references (excl. entrypoints)."""
    _stub("query deadcode")


@query_app.command("cycles")
def query_cycles() -> None:
    """List strongly-connected components in the import / call graph."""
    _stub("query cycles")


@baseline_app.command("push")
def baseline_push(target: str = typer.Option("main")) -> None:
    """Register the current graph as the baseline for `target` (CI use)."""
    _stub("baseline push")


@hook_app.command("install")
def hook_install() -> None:
    """Install the git pre-push hook."""
    _stub("hook install")


@hook_app.command("uninstall")
def hook_uninstall() -> None:
    """Remove the git pre-push hook."""
    _stub("hook uninstall")


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Run as an MCP server exposing focused subgraph tools to AI assistants."""
    _stub("mcp serve")


if __name__ == "__main__":
    app()
