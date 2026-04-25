"""codegraph CLI entry point."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, cast

import networkx as nx
import typer
from rich.console import Console
from rich.table import Table

from codegraph import __version__

if TYPE_CHECKING:
    from codegraph.review.differ import EdgeChange, GraphDiff, NodeChange
    from codegraph.review.rules import Finding

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
    limit: int = typer.Option(
        300, "--limit", help="Max nodes to render (top-N by degree)."
    ),
    output: str | None = typer.Option(
        None, "--output", help="Write to file (required for html/svg)."
    ),
    no_cluster: bool = typer.Option(
        False, "--no-cluster", help="Disable file-based clustering (mermaid)."
    ),
    include_unresolved: bool = typer.Option(
        False,
        "--include-unresolved",
        help="Include unresolved::* phantom nodes (debug only).",
    ),
    include_files: bool = typer.Option(
        False,
        "--include-files",
        help="Include FILE nodes (rendered as bare paths; off by default).",
    ),
) -> None:
    """Render a graph visualization (mermaid stdout, html / svg to file)."""
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

    drop: list[str] = []
    for nid, attrs in g.nodes(data=True):
        if not include_unresolved and isinstance(nid, str) and nid.startswith(
            "unresolved::"
        ):
            drop.append(nid)
            continue
        if not include_files and str(attrs.get("kind") or "") == "FILE":
            drop.append(nid)
    if drop:
        g = cast("nx.MultiDiGraph", g.copy())
        g.remove_nodes_from(drop)

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

    if out == "mermaid":
        from codegraph.viz import render_mermaid
        text = render_mermaid(g, cluster_by_file=not no_cluster)
        if output:
            Path(output).write_text(text)
            console.print(f"[green]✓[/green] wrote mermaid to {output}")
        else:
            print(text)
        return

    if out == "html":
        from codegraph.viz import render_html
        out_path = Path(output) if output else data_dir / "graph.html"
        result_path = render_html(g, out_path)
        console.print(
            f"[green]✓[/green] wrote interactive graph to {result_path} "
            f"({g.number_of_nodes()} nodes, {g.number_of_edges()} edges)"
        )
        console.print(f"[dim]Open with:[/dim] open {result_path}")
        return

    if out == "svg":
        from codegraph.viz import GraphvizUnavailableError, render_svg
        out_path = Path(output) if output else data_dir / "graph.svg"
        try:
            result_path = render_svg(g, out_path)
        except GraphvizUnavailableError as exc:
            console.print(f"[yellow]SVG unavailable:[/yellow] {exc}")
            raise typer.Exit(1) from exc
        console.print(f"[green]✓[/green] wrote SVG to {result_path}")
        return

    console.print(f"[red]Unknown --out value:[/red] {out}")
    raise typer.Exit(2)


# ---- analyze + query ----


def _open_graph(repo_root: Path) -> nx.MultiDiGraph | None:
    from codegraph.graph.store_networkx import to_digraph
    from codegraph.graph.store_sqlite import SQLiteGraphStore

    data_dir = _get_data_dir(repo_root)
    db_path = data_dir / "graph.db"
    if not db_path.exists():
        console.print(
            "[yellow]No graph found. Run [bold]codegraph build[/bold] first.[/yellow]"
        )
        return None
    store = SQLiteGraphStore(db_path)
    try:
        return to_digraph(store)
    finally:
        store.close()


@app.command()
def analyze(
    fmt: str = typer.Option("markdown", "--format", help="markdown|json"),
    output: str | None = typer.Option(
        None, "--output", help="Write report to file instead of stdout."
    ),
    hotspot_limit: int = typer.Option(20, "--hotspots", help="Top-N hotspots."),
) -> None:
    """Whole-project audit: dead code, cycles, untested, hotspots, metrics."""
    from codegraph.analysis.report import (
        report_to_json,
        report_to_markdown,
        run_full_analyze,
    )

    graph = _open_graph(Path.cwd())
    if graph is None:
        raise typer.Exit(1)

    report = run_full_analyze(graph, hotspot_limit=hotspot_limit)
    text = (
        report_to_json(report) if fmt == "json" else report_to_markdown(report)
    )
    if output:
        Path(output).write_text(text)
        console.print(f"[green]✓[/green] wrote report to {output}")
    else:
        print(text)


@app.command()
def explore(
    output: str = typer.Option(
        ".codegraph/explore", "--output", "-o", help="Output directory."
    ),
    top_files: int = typer.Option(
        25, "--top-files", help="How many file-detail pages to generate."
    ),
    callgraph_limit: int = typer.Option(
        400,
        "--callgraph-limit",
        help="Cap nodes shown on the callgraph page (degree-ranked).",
    ),
) -> None:
    """Build an interactive multi-page dashboard (overview + drill-downs)."""
    from codegraph.viz.explore import render_explore

    graph = _open_graph(Path.cwd())
    if graph is None:
        raise typer.Exit(1)

    out_dir = Path(output)
    if not out_dir.is_absolute():
        out_dir = Path.cwd() / out_dir
    result = render_explore(
        graph,
        out_dir,
        top_files=top_files,
        callgraph_limit=callgraph_limit,
    )
    console.print(
        f"[green]✓[/green] dashboard written to {result.out_dir} "
        f"({len(result.pages)} pages)"
    )
    console.print(f"[bold]Open:[/bold] open {result.out_dir / 'index.html'}")


@app.command()
def serve(
    port: int = typer.Option(8765, "--port", "-p", help="Port to bind."),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind."),
    no_open: bool = typer.Option(
        False, "--no-open", help="Don't auto-open the browser."
    ),
    explore_dir: str = typer.Option(
        ".codegraph/explore",
        "--explore-dir",
        help="Folder of pyvis pages (architecture/callgraph/...) to also serve.",
    ),
) -> None:
    """Run the interactive dashboard as a local web app."""
    from codegraph.graph.builder import GraphBuilder
    from codegraph.graph.store_networkx import to_digraph
    from codegraph.graph.store_sqlite import SQLiteGraphStore
    from codegraph.viz.explore import render_explore
    from codegraph.web import DashboardState
    from codegraph.web import serve as run_server

    repo_root = Path.cwd()
    data_dir = _get_data_dir(repo_root)
    db_path = data_dir / "graph.db"
    if not db_path.exists():
        console.print(
            "[yellow]No graph found. Run [bold]codegraph build[/bold] first.[/yellow]"
        )
        raise typer.Exit(1)

    explore_path = Path(explore_dir)
    if not explore_path.is_absolute():
        explore_path = repo_root / explore_path

    def _load_graph() -> nx.MultiDiGraph:
        store = SQLiteGraphStore(db_path)
        try:
            return to_digraph(store)
        finally:
            store.close()

    def _rebuild() -> nx.MultiDiGraph:
        store = SQLiteGraphStore(db_path)
        try:
            GraphBuilder(repo_root, store).build(incremental=False)
            graph = to_digraph(store)
        finally:
            store.close()
        # Refresh pyvis pages too so the Files / Explorers tabs stay in sync.
        try:
            render_explore(graph, explore_path)
        except Exception as exc:
            console.print(
                f"[yellow]warn:[/yellow] failed to refresh explore pages: {exc}"
            )
        return graph

    # Make sure pyvis pages exist on first run.
    if not (explore_path / "architecture.html").exists():
        console.print("[dim]First run: generating pyvis pages...[/dim]")
        try:
            render_explore(_load_graph(), explore_path)
        except Exception as exc:
            console.print(f"[yellow]warn:[/yellow] {exc}")

    state = DashboardState(
        repo_root=repo_root,
        explore_dir=explore_path,
        graph_loader=_load_graph,
        rebuild=_rebuild,
    )
    run_server(state, host=host, port=port, open_browser=not no_open)


@app.command()
def review(
    target: str = typer.Option("main", help="Target branch to PR into."),
    block_on: str = typer.Option(
        "high", "--block-on", help="critical|high|med|low"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="Exit non-zero if any finding has at least this severity. "
        "Defaults to --block-on.",
    ),
    baseline: str | None = typer.Option(
        None, "--baseline", help="Path to baseline graph.db (default: .codegraph/baseline.db)."
    ),
    fmt: str = typer.Option(
        "markdown", "--format", help="markdown|json|sarif"
    ),
    output: str | None = typer.Option(
        None, "--output", help="Write report to file instead of stdout."
    ),
    rules_file: str | None = typer.Option(
        None, "--rules", help="Path to rules YAML (default: .codegraph/rules.yml)."
    ),
) -> None:
    """Diff vs baseline; produce a risk-scored PR review."""
    from codegraph.review.baseline import load_baseline
    from codegraph.review.differ import diff_graphs
    from codegraph.review.rules import (
        evaluate_rules,
        load_rules,
        severity_at_least,
    )

    repo_root = Path.cwd()
    data_dir = _get_data_dir(repo_root)
    db_path = data_dir / "graph.db"
    if not db_path.exists():
        console.print(
            "[yellow]No graph found. Run [bold]codegraph build[/bold] first.[/yellow]"
        )
        raise typer.Exit(1)

    baseline_path = Path(baseline) if baseline else data_dir / "baseline.db"
    old_graph = load_baseline(baseline_path)
    if old_graph is None:
        console.print(
            f"[yellow]No baseline found at {baseline_path}. "
            f"Run [bold]codegraph baseline save[/bold] first.[/yellow]"
        )
        raise typer.Exit(2)

    new_graph = _open_graph(repo_root)
    if new_graph is None:
        raise typer.Exit(1)

    diff = diff_graphs(old_graph, new_graph)
    rules = load_rules(Path(rules_file) if rules_file else None)
    findings = evaluate_rules(
        diff, new_graph=new_graph, old_graph=old_graph, rules=rules
    )

    threshold = (fail_on or block_on).lower()
    text = _render_review(diff, findings, fmt=fmt, target=target)
    if output:
        Path(output).write_text(text)
        console.print(f"[green]✓[/green] wrote review to {output}")
    else:
        print(text)

    blocking = [f for f in findings if severity_at_least(f.severity, threshold)]
    if blocking:
        raise typer.Exit(1)


def _render_review(
    diff: GraphDiff,
    findings: list[Finding],
    *,
    fmt: str,
    target: str,
) -> str:
    import json

    if fmt == "json":
        payload = {
            "target": target,
            "diff": {
                "added_nodes": [_nc_to_dict(n) for n in diff.added_nodes],
                "removed_nodes": [_nc_to_dict(n) for n in diff.removed_nodes],
                "modified_nodes": [_nc_to_dict(n) for n in diff.modified_nodes],
                "added_edges": [_ec_to_dict(e) for e in diff.added_edges],
                "removed_edges": [_ec_to_dict(e) for e in diff.removed_edges],
            },
            "findings": [_finding_to_dict(f) for f in findings],
        }
        return json.dumps(payload, indent=2, sort_keys=True)
    if fmt == "sarif":
        return _render_sarif(findings)
    return _render_markdown(diff, findings, target=target)


def _nc_to_dict(n: NodeChange) -> dict[str, object]:
    return {
        "qualname": n.qualname,
        "kind": n.kind,
        "file": n.file,
        "line_start": n.line_start,
        "signature": n.signature,
        "change_kind": n.change_kind,
        "details": n.details,
    }


def _ec_to_dict(e: EdgeChange) -> dict[str, object]:
    return {
        "src_qualname": e.src_qualname,
        "dst_qualname": e.dst_qualname,
        "kind": e.kind,
        "change_kind": e.change_kind,
    }


def _finding_to_dict(f: Finding) -> dict[str, object]:
    return {
        "rule_id": f.rule_id,
        "severity": f.severity,
        "message": f.message,
        "qualname": f.qualname,
        "file": f.file,
        "line": f.line,
        "score": f.score,
        "reasons": list(f.reasons),
    }


def _render_markdown(
    diff: GraphDiff, findings: list[Finding], *, target: str
) -> str:
    lines: list[str] = [f"# codegraph review (target: {target})", ""]
    lines.append(
        f"**Diff**: +{len(diff.added_nodes)} / -{len(diff.removed_nodes)} / "
        f"~{len(diff.modified_nodes)} nodes, "
        f"+{len(diff.added_edges)} / -{len(diff.removed_edges)} edges"
    )
    lines.append("")
    lines.append(f"## Findings ({len(findings)})")
    if not findings:
        lines.append("")
        lines.append("_No findings._")
        return "\n".join(lines) + "\n"
    lines.append("")
    lines.append("| severity | rule | qualname | file:line | score | message |")
    lines.append("|---|---|---|---|---|---|")
    for f in findings:
        loc = f"{f.file}:{f.line}" if f.file else ""
        lines.append(
            f"| {f.severity} | {f.rule_id} | `{f.qualname}` | {loc} | "
            f"{f.score} | {f.message} |"
        )
    return "\n".join(lines) + "\n"


def _render_sarif(findings: list[Finding]) -> str:
    import json

    _sev_map = {
        "low": "note",
        "med": "warning",
        "high": "error",
        "critical": "error",
    }
    rule_ids = sorted({f.rule_id for f in findings})
    sarif = {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "codegraph",
                        "informationUri": "https://github.com/smochan/codegraph",
                        "rules": [
                            {"id": rid, "name": rid} for rid in rule_ids
                        ],
                    }
                },
                "results": [
                    {
                        "ruleId": f.rule_id,
                        "level": _sev_map.get(f.severity, "warning"),
                        "message": {"text": f.message},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": f.file or ""},
                                    "region": {
                                        "startLine": max(1, f.line or 1)
                                    },
                                }
                            }
                        ]
                        if f.file
                        else [],
                        "properties": {
                            "score": f.score,
                            "qualname": f.qualname,
                            "reasons": list(f.reasons),
                        },
                    }
                    for f in findings
                ],
            }
        ],
    }
    return json.dumps(sarif, indent=2, sort_keys=True)


def _print_node_table(
    graph: nx.MultiDiGraph, node_ids: list[str], title: str
) -> None:
    table = Table(title=title)
    table.add_column("kind", style="cyan")
    table.add_column("qualname")
    table.add_column("file")
    table.add_column("line", justify="right")
    for nid in node_ids:
        attrs = graph.nodes.get(nid) or {}
        table.add_row(
            str(attrs.get("kind") or ""),
            str(attrs.get("qualname") or nid),
            str(attrs.get("file") or ""),
            str(attrs.get("line_start") or ""),
        )
    console.print(table)


@query_app.command("callers")
def query_callers(
    symbol: str,
    depth: int = typer.Option(1, "--depth"),
) -> None:
    """Show transitive callers of SYMBOL up to ``depth`` hops."""
    from codegraph.analysis.blast_radius import blast_radius
    from codegraph.analysis.report import find_symbol

    graph = _open_graph(Path.cwd())
    if graph is None:
        raise typer.Exit(1)
    target = find_symbol(graph, symbol)
    if target is None:
        console.print(f"[yellow]Symbol '{symbol}' not found.[/yellow]")
        raise typer.Exit(1)
    result = blast_radius(graph, target, depth=depth)
    console.print(
        f"[bold]Callers of[/bold] {symbol} "
        f"(depth={depth}): {result.size} nodes across {len(result.files)} files"
    )
    _print_node_table(graph, result.nodes[:50], "Callers")
    if result.size > 50:
        console.print(f"[dim]… {result.size - 50} more[/dim]")


@query_app.command("subgraph")
def query_subgraph(
    symbol: str,
    depth: int = typer.Option(2, "--depth"),
) -> None:
    """Print the symbol's depth-N neighborhood as Mermaid."""
    from codegraph.analysis.report import find_symbol
    from codegraph.graph.store_networkx import subgraph_around

    graph = _open_graph(Path.cwd())
    if graph is None:
        raise typer.Exit(1)
    target = find_symbol(graph, symbol)
    if target is None:
        console.print(f"[yellow]Symbol '{symbol}' not found.[/yellow]")
        raise typer.Exit(1)
    sub = subgraph_around(graph, target, depth=depth)
    lines = ["flowchart LR"]
    safe: dict[str, str] = {}
    for nid, attrs in sub.nodes(data=True):
        sid = "n_" + str(nid)[:16]
        safe[nid] = sid
        label = str(attrs.get("name") or nid).replace('"', "'")
        kind = attrs.get("kind", "")
        lines.append(f'    {sid}["{kind}: {label}"]')
    seen: set[tuple[str, str, str]] = set()
    for src, dst, data in sub.edges(data=True):
        if src not in safe or dst not in safe:
            continue
        ek = str(data.get("kind", ""))
        key = (src, dst, ek)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"    {safe[src]} -->|{ek}| {safe[dst]}")
    print("\n".join(lines))


@query_app.command("untested")
def query_untested(limit: int = typer.Option(50, "--limit")) -> None:
    """List functions/methods with no test-side caller."""
    from codegraph.analysis import find_untested

    graph = _open_graph(Path.cwd())
    if graph is None:
        raise typer.Exit(1)
    rows = find_untested(graph)
    console.print(f"[bold]{len(rows)} untested[/bold]")
    table = Table()
    table.add_column("qualname")
    table.add_column("file")
    table.add_column("line", justify="right")
    table.add_column("callers", justify="right")
    for u in rows[:limit]:
        table.add_row(u.qualname, u.file, str(u.line_start), str(u.incoming_calls))
    console.print(table)


@query_app.command("deadcode")
def query_deadcode(limit: int = typer.Option(50, "--limit")) -> None:
    """List definitions with no incoming reference edges."""
    from codegraph.analysis import find_dead_code

    graph = _open_graph(Path.cwd())
    if graph is None:
        raise typer.Exit(1)
    rows = find_dead_code(graph)
    console.print(f"[bold]{len(rows)} dead-code candidates[/bold]")
    table = Table()
    table.add_column("kind")
    table.add_column("qualname")
    table.add_column("file")
    table.add_column("line", justify="right")
    for d in rows[:limit]:
        table.add_row(d.kind, d.qualname, d.file, str(d.line_start))
    console.print(table)


@query_app.command("cycles")
def query_cycles() -> None:
    """List import + call cycles."""
    from codegraph.analysis import find_cycles

    graph = _open_graph(Path.cwd())
    if graph is None:
        raise typer.Exit(1)
    rep = find_cycles(graph)
    console.print(
        f"[bold]Cycles[/bold]: {len(rep.import_cycles)} import, "
        f"{len(rep.call_cycles)} call"
    )
    for label, cycles in (
        ("Import cycles", rep.import_cycles),
        ("Call cycles", rep.call_cycles),
    ):
        if not cycles:
            continue
        console.print(f"\n[cyan]{label}:[/cyan]")
        for cyc in cycles[:25]:
            console.print("  - " + " → ".join(cyc))


@baseline_app.command("save")
def baseline_save(
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output baseline path (default: .codegraph/baseline.db).",
    ),
) -> None:
    """Snapshot the current graph as the local baseline."""
    from codegraph.review.baseline import save_baseline

    repo_root = Path.cwd()
    data_dir = _get_data_dir(repo_root)
    db_path = data_dir / "graph.db"
    if not db_path.exists():
        console.print(
            "[yellow]No graph found. Run [bold]codegraph build[/bold] first.[/yellow]"
        )
        raise typer.Exit(1)
    out_path = Path(output) if output else data_dir / "baseline.db"
    save_baseline(db_path, out_path)
    console.print(f"[green]✓[/green] saved baseline to {out_path}")


@baseline_app.command("status")
def baseline_status() -> None:
    """Show whether a local baseline exists."""
    repo_root = Path.cwd()
    data_dir = _get_data_dir(repo_root)
    baseline_path = data_dir / "baseline.db"
    if baseline_path.exists():
        size = baseline_path.stat().st_size
        console.print(
            f"[green]✓[/green] baseline present: {baseline_path} ({size} bytes)"
        )
    else:
        console.print(
            f"[yellow]No baseline at {baseline_path}.[/yellow] "
            f"Run [bold]codegraph baseline save[/bold]."
        )
        raise typer.Exit(1)


@baseline_app.command("push")
def baseline_push(
    target: str = typer.Option("main", help="Target branch label."),
) -> None:
    """Register the current graph as the baseline for ``target`` (CI use)."""
    from codegraph.review.baseline import save_baseline

    repo_root = Path.cwd()
    data_dir = _get_data_dir(repo_root)
    db_path = data_dir / "graph.db"
    if not db_path.exists():
        console.print(
            "[yellow]No graph found. Run [bold]codegraph build[/bold] first.[/yellow]"
        )
        raise typer.Exit(1)
    out_path = data_dir / "baseline.db"
    save_baseline(db_path, out_path)
    console.print(
        f"[green]✓[/green] pushed baseline for [bold]{target}[/bold] -> {out_path}"
    )


@hook_app.command("install")
def hook_install(
    target: str = typer.Option(
        "main", "--target", help="Target branch the hook reviews against."
    ),
    hook: str = typer.Option(
        "pre-push", "--hook", help="Git hook name to install (pre-push|pre-commit)."
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite an existing non-codegraph hook."
    ),
) -> None:
    """Install a git hook that runs ``codegraph review``."""
    from codegraph.review.hook import install_hook

    repo_root = Path.cwd()
    try:
        path = install_hook(repo_root, hook=hook, target=target, force=force)
    except FileNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    except FileExistsError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]✓[/green] installed git hook at {path}")


@hook_app.command("uninstall")
def hook_uninstall(
    hook: str = typer.Option(
        "pre-push", "--hook", help="Git hook name to remove."
    ),
) -> None:
    """Remove the codegraph-managed git hook."""
    from codegraph.review.hook import uninstall_hook

    repo_root = Path.cwd()
    if uninstall_hook(repo_root, hook=hook):
        console.print(f"[green]✓[/green] removed {hook} hook")
    else:
        console.print(
            f"[yellow]No codegraph-managed {hook} hook to remove.[/yellow]"
        )


@mcp_app.command("serve")
def mcp_serve(
    db: str | None = typer.Option(
        None,
        "--db",
        help="Path to graph.db (default: .codegraph/graph.db in cwd).",
    ),
    name: str = typer.Option(
        "codegraph",
        "--name",
        help="Server name advertised over MCP.",
    ),
) -> None:
    """Run as an MCP stdio server exposing focused subgraph tools to AI assistants."""
    from codegraph.mcp_server.server import run

    db_path = Path(db) if db else None
    try:
        run(db_path=db_path, server_name=name)
    except KeyboardInterrupt:
        raise typer.Exit(0) from None


if __name__ == "__main__":
    app()
