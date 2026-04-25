"""codegraph CLI entry point."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

import networkx as nx
import typer
from rich.console import Console
from rich.table import Table

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

_DATA_DIR_STATE: dict[str, Path | None] = {"value": None}


def _get_data_dir(repo_root: Path) -> Path:
    val = _DATA_DIR_STATE.get("value")
    if val is not None:
        return val
    from codegraph.config import default_data_dir
    return default_data_dir(repo_root)


def _stub(name: str) -> None:
    console.print(
        f"[yellow]TODO[/yellow] \\[{name}] not yet implemented (Phase 0 skeleton)."
    )


@app.callback()
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version and exit."),
    data_dir: str | None = typer.Option(
        None, "--data-dir", help="Override .codegraph/ data directory."
    ),
) -> None:
    if data_dir:
        _DATA_DIR_STATE["value"] = Path(data_dir)
    else:
        _DATA_DIR_STATE["value"] = None
    if version:
        console.print(f"codegraph {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


def _detect_languages(repo_root: Path, limit: int = 5000) -> dict[str, int]:
    ext_map: dict[str, int] = {}
    count = 0
    for p in repo_root.rglob("*"):
        if count >= limit:
            break
        if not p.is_file():
            continue
        parts = p.relative_to(repo_root).parts
        if any(
            part.startswith(".")
            or part in ("node_modules", "venv", "__pycache__", "dist", "build")
            for part in parts
        ):
            continue
        ext = p.suffix.lower()
        if ext:
            ext_map[ext] = ext_map.get(ext, 0) + 1
            count += 1
    return ext_map


def _detect_branch(repo_root: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            cwd=repo_root, capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            branch = r.stdout.strip()
            if "/" in branch:
                branch = branch.split("/", 1)[1]
            return branch
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root, capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "main"


def _update_gitignore(repo_root: Path) -> None:
    gi_path = repo_root / ".gitignore"
    entry = ".codegraph/"
    if gi_path.exists():
        content = gi_path.read_text()
        if entry not in content:
            with gi_path.open("a") as f:
                f.write(f"\n{entry}\n")
    else:
        gi_path.write_text(f"{entry}\n")


@app.command()
def init(
    non_interactive: bool = typer.Option(
        False, "--non-interactive",
        help="Write default config without prompting.",
    ),
) -> None:
    """Interactive setup: detect languages, write `.codegraph.yml`."""
    import questionary

    from codegraph.config import load_config, save_config

    repo_root = Path.cwd()
    cfg = load_config(repo_root)

    if non_interactive:
        save_config(repo_root, cfg)
        _update_gitignore(repo_root)
        console.print("[green]✓[/green] Wrote .codegraph.yml with defaults.")
        console.print("Next step: [bold]codegraph build[/bold]")
        return

    ext_map = _detect_languages(repo_root)
    lang_exts = {
        "python": [".py"],
        "typescript": [".ts", ".tsx"],
        "javascript": [".js", ".jsx", ".mjs", ".cjs"],
    }
    detected: list[str] = []
    for lang, exts in lang_exts.items():
        if any(ext_map.get(e, 0) > 0 for e in exts):
            detected.append(lang)

    console.print("\n[bold]Detected languages:[/bold]")
    for lang in detected:
        exts = lang_exts.get(lang, [])
        total = sum(ext_map.get(e, 0) for e in exts)
        console.print(f"  {lang}: {total} files")

    confirmed = questionary.checkbox(
        "Confirm languages to include:",
        choices=list(lang_exts.keys()),
    ).ask() or detected
    cfg.languages = confirmed

    default_branch = _detect_branch(repo_root)
    branch = questionary.text(
        "Default branch:", default=default_branch
    ).ask() or default_branch
    cfg.default_branch = branch

    backend = questionary.select(
        "Baseline backend (s3/sql land in Phase 4):",
        choices=["local", "none"],
        default="local",
    ).ask() or "local"
    cfg.baseline = {"backend": backend}

    extra = questionary.text(
        "Extra ignore patterns (comma/newline separated, optional):",
        default="",
    ).ask() or ""
    cfg.ignore = [
        p.strip() for p in extra.replace("\n", ",").split(",") if p.strip()
    ]

    install_hook = questionary.confirm(
        "Install git pre-push hook? (Phase 2 implementation)", default=False
    ).ask() or False
    cfg.install_hook = install_hook

    register_mcp = questionary.confirm(
        "Register MCP server in .mcp.json? (Phase 3 implementation)",
        default=False,
    ).ask() or False
    cfg.register_mcp = register_mcp

    save_config(repo_root, cfg)
    _update_gitignore(repo_root)

    console.print("\n[green]✓[/green] Wrote .codegraph.yml")
    console.print("Next step: [bold]codegraph build[/bold]")


@app.command()
def build(
    incremental: bool = typer.Option(True, help="Incremental build when possible."),
) -> None:
    """Parse the repo and (re)build the graph."""
    import time

    from codegraph.config import load_config
    from codegraph.graph.builder import GraphBuilder
    from codegraph.graph.store_sqlite import SQLiteGraphStore

    repo_root = Path.cwd()
    cfg = load_config(repo_root)
    data_dir = _get_data_dir(repo_root)
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "graph.db"

    console.print(f"[bold]Building graph[/bold] in {db_path}...")
    store = SQLiteGraphStore(db_path)
    builder = GraphBuilder(repo_root, store, ignore=cfg.ignore)

    t0 = time.monotonic()
    stats = builder.build(incremental=incremental)
    elapsed = time.monotonic() - t0

    table = Table(title="Build Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Files scanned", str(stats.files_scanned))
    table.add_row("Files parsed", str(stats.files_parsed))
    table.add_row("Files skipped (unchanged)", str(stats.files_skipped))
    table.add_row("Nodes added", str(stats.nodes_added))
    table.add_row("Edges added", str(stats.edges_added))
    table.add_row("Errors", str(len(stats.errors)))
    table.add_row("Time", f"{elapsed:.2f}s")
    console.print(table)

    if stats.errors:
        console.print(f"[yellow]Warnings ({len(stats.errors)}):[/yellow]")
        for e in stats.errors[:10]:
            console.print(f"  {e}")

    store.close()


@app.command()
def status() -> None:
    """Show graph freshness, last build, and drift indicators."""
    import hashlib

    from codegraph.graph.schema import NodeKind
    from codegraph.graph.store_sqlite import SQLiteGraphStore

    repo_root = Path.cwd()
    data_dir = _get_data_dir(repo_root)
    db_path = data_dir / "graph.db"

    if not db_path.exists():
        console.print(
            "[yellow]No graph database found. "
            "Run [bold]codegraph build[/bold] first.[/yellow]"
        )
        raise typer.Exit(1)

    store = SQLiteGraphStore(db_path)
    n_nodes = store.count_nodes()
    n_edges = store.count_edges()
    last_build = store.get_meta("last_build_time") or "unknown"
    last_sha = store.get_meta("last_git_sha") or "unknown"

    drift = 0
    for file_node in store.iter_nodes(kind=NodeKind.FILE):
        file_path = repo_root / file_node.file
        if file_path.exists() and file_node.content_hash:
            h = hashlib.sha256()
            with file_path.open("rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            if h.hexdigest() != file_node.content_hash:
                drift += 1
        elif not file_path.exists():
            drift += 1

    table = Table(title="Graph Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Nodes", str(n_nodes))
    table.add_row("Edges", str(n_edges))
    table.add_row("Last build", last_build)
    table.add_row("Git SHA", last_sha)
    table.add_row("Drifted files", str(drift))
    console.print(table)
    store.close()


@app.command()
def viz(
    out: str = typer.Option("mermaid", "--out", help="mermaid|html|svg"),
    scope: str = typer.Option("", "--scope", help="Path or symbol to focus on."),
    limit: int = typer.Option(80, "--limit", help="Max nodes to render."),
) -> None:
    """Render a graph visualization."""
    if out in ("html", "svg"):
        console.print(
            f"[yellow]TODO[/yellow] {out} rendering deferred to Phase 6."
        )
        raise typer.Exit()

    from codegraph.graph.store_networkx import subgraph_around, to_digraph
    from codegraph.graph.store_sqlite import SQLiteGraphStore

    repo_root = Path.cwd()
    data_dir = _get_data_dir(repo_root)
    db_path = data_dir / "graph.db"

    if not db_path.exists():
        console.print(
            "[yellow]No graph found. Run codegraph build first.[/yellow]"
        )
        raise typer.Exit(1)

    store = SQLiteGraphStore(db_path)
    g = to_digraph(store)
    store.close()

    if scope:
        target_id: str | None = None
        for nid, attrs in g.nodes(data=True):
            if (
                attrs.get("name") == scope
                or attrs.get("qualname") == scope
                or attrs.get("file") == scope
            ):
                target_id = nid
                break
        if target_id:
            g = subgraph_around(g, target_id, depth=2)
        else:
            console.print(
                f"[yellow]Symbol '{scope}' not found in graph.[/yellow]"
            )

    nodes_to_show = list(g.nodes())
    if len(nodes_to_show) > limit:
        degree_sorted = sorted(
            g.degree(), key=lambda x: x[1], reverse=True
        )
        top_ids = {n for n, _ in degree_sorted[:limit]}
        g = cast("nx.MultiDiGraph", g.subgraph(top_ids).copy())

    lines = ["flowchart LR"]
    node_label: dict[str, str] = {}
    for nid, attrs in g.nodes(data=True):
        label = str(attrs.get("name") or str(nid)[:20])
        label = label.replace('"', "'")
        safe_id = (
            str(nid)
            .replace(":", "_")
            .replace(".", "_")
            .replace("/", "_")
            .replace("-", "_")
        )
        kind = attrs.get("kind", "")
        node_label[nid] = safe_id
        lines.append(f'    {safe_id}["{kind}: {label}"]')
    seen_edges: set[tuple[str, str, str]] = set()
    for src, dst, data in g.edges(data=True):
        if src not in node_label or dst not in node_label:
            continue
        ek = str(data.get("kind", ""))
        key = (src, dst, ek)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        lines.append(f"    {node_label[src]} -->|{ek}| {node_label[dst]}")

    print("\n".join(lines))


# ---- stub subcommands ----

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
