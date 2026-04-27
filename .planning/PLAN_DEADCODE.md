# PLAN_DEADCODE — Entry-Point Awareness for Dead-Code Analysis

**Status**: Draft  
**Target release**: 0.2.0  
**Phases**: D1 (Python), D2 (TypeScript), D3 (config-driven)

---

## 1. Current Dead-Code Logic

### Where the "no incoming references" check lives

**`codegraph/analysis/dead_code.py`**

- Line 15-17: `_CANDIDATE_KINDS` = `{FUNCTION, METHOD, CLASS}` — only these node kinds are checked.
- Line 18: `_ENTRYPOINT_NAMES` = `{"main", "__main__"}` — hard-coded name exclusions.
- Lines 32-37: `_is_dunder` and `_is_test_function` — pattern-based name exclusions.
- Lines 57-88: `find_dead_code()` main loop.
  - Line 71-76: The core check — iterates `graph.in_edges(nid, keys=True)` and looks for any edge whose key is in `REFERENCE_EDGE_KINDS`.
  - Line 79-88: If no such edge exists, appends to `dead` list.

**`codegraph/analysis/_common.py`**

- Lines 16-23: `REFERENCE_EDGE_KINDS` = `{CALLS, IMPORTS, INHERITS, IMPLEMENTS}`. Only these four edge kinds count as "referenced". A node decorated with `@app.command()` has zero of these incoming — the decorator call is outgoing from that node, not incoming.

### What currently counts as a reference

An incoming edge of kind CALLS, IMPORTS, INHERITS, or IMPLEMENTS. The Typer command functions (`init`, `build`, `status`, `viz`, `analyze`, `explore`, `serve`, `review`, `_stub`, `_root`, `query_callers`, `query_subgraph`, `query_untested`, `query_deadcode`, `query_cycles`, `baseline_save`, `baseline_status`, `baseline_push`, `hook_install`, `hook_uninstall`, `mcp_serve`) are all invoked by the Typer runtime via reflection — no static CALLS edge exists.

### What the parser already captures

**`codegraph/parsers/python.py` line 284-298**: `_get_function_decorators()` collects decorator text and stores it in `metadata={"decorators": decorators}` on every FUNCTION and METHOD node. The raw decorator strings (e.g. `"@app.command()"`, `"@pytest.fixture"`) are already stored in the graph. They are never consulted during dead-code analysis.

**`codegraph/parsers/typescript.py`**: Functions and methods are recorded but no decorator metadata is collected. The TS parser does not call an equivalent of `_get_function_decorators`.

---

## 2. Decorator Catalog — Entry-Point Patterns

### Category A: Python AST decorators (already in `metadata["decorators"]`)

These appear as `decorated_definition` nodes in tree-sitter. The raw text is already stored. Match against these prefixes/patterns at analysis time (no parser change needed for Python).

| Framework | Decorator patterns |
|-----------|-------------------|
| Typer | `@app.command`, `@<name>.command`, `@app.callback` |
| Click | `@click.command`, `@click.group`, `@<name>.command`, `@<name>.group` |
| FastAPI | `@app.get`, `@app.post`, `@app.put`, `@app.delete`, `@app.patch`, `@app.head`, `@app.options`, `@app.trace`, `@app.websocket`, `@router.get`, `@router.post`, `@router.put`, `@router.delete`, `@router.patch`, `@router.websocket`, `@router.<any>` |
| Flask | `@app.route`, `@app.before_request`, `@app.after_request`, `@app.teardown_request`, `@app.errorhandler`, `@bp.route`, `@blueprint.route` |
| Celery | `@app.task`, `@celery.task`, `@shared_task` |
| pytest | `@pytest.fixture`, `@pytest.mark.*` |
| asyncio/aiohttp | `@app.on_event`, `@app.middleware`, `@router.on_event` |
| Django | `@admin.register`, `@receiver`, `@login_required`, `@permission_required` |
| SQLAlchemy | `@event.listens_for` |

### Category B: Python name-convention entry points (handled in `find_dead_code` filter)

These need no decorator check — they match by name or file structure.

| Pattern | Detection method |
|---------|-----------------|
| `test_*` functions | Already handled: `_is_test_function` at dead_code.py:37 |
| `__all__` exports | Out of scope for D1; document as known limitation |
| Abstract methods with `@abstractmethod` | Add to decorator patterns |
| `if __name__ == "__main__"` body | Caller conventions — functions directly invoked here already have a CALLS edge from their containing scope; no extra work needed |

### Category C: TypeScript/JS patterns (require parser change)

These require the TS parser to collect decorator metadata before analysis can use them.

**Decorator-based (Class decorators — NestJS, TypeORM)**

| Framework | Decorator patterns |
|-----------|-------------------|
| NestJS | `@Controller`, `@Get`, `@Post`, `@Put`, `@Delete`, `@Patch`, `@Injectable`, `@Module`, `@Guard`, `@Interceptor`, `@Pipe`, `@EventPattern`, `@MessagePattern` |
| TypeORM | `@Entity`, `@Column`, `@PrimaryColumn`, `@PrimaryGeneratedColumn`, `@ManyToOne`, `@OneToMany` |
| General | Any `@<decorator>` on a class or method |

**Call-pattern-based (not decorators on the AST)**

| Framework | Detection method |
|-----------|-----------------|
| Express | Top-level calls matching `app.get(...)`, `app.post(...)`, `router.get(...)`, etc. — the callee is a string literal; the function argument is the handler |
| Jest/Vitest | Top-level calls to `describe(...)`, `it(...)`, `test(...)` — already partially excluded by test-file detection |

**File-location / export convention**

| Pattern | Detection method |
|---------|-----------------|
| Next.js pages | Default export from a file whose path matches `pages/**` or `app/**/page.tsx` |
| Exported React hooks named `use*` | Named export from any file where name starts with `use` |

---

## 3. Recommended Approach: `entry_point` Flag on Node

### Option A: Virtual ROOT node with synthetic edges
Add a synthetic `ROOT` node and emit `CALLS` edges from ROOT to every detected entry point during parsing. Dead-code check then finds incoming CALLS edges as normal.

**Downside**: Pollutes the graph with phantom edges; `viz` and `blast_radius` break in surprising ways; the ROOT node itself appears in all queries.

### Option B: `entry_point` flag in node metadata (RECOMMENDED)
Store `metadata["entry_point"] = True` on each node whose decorator/name/location matches. In `find_dead_code`, skip any node where `attrs.get("metadata", {}).get("entry_point")` is True.

**Why this wins**:
- Zero schema change (metadata is already a JSON dict column).
- No graph topology change; viz and analysis tools are unaffected.
- The flag is inspectable via `codegraph query subgraph` and the dashboard.
- Easy to extend: D3 config patterns just set the same flag.
- Reversible: re-running `build` regenerates all flags from source.

### Implementation touch-points for Option B

**Python parser** (`codegraph/parsers/python.py`):

- In `_handle_function` (line 260): after collecting `decorators`, call a new helper `_is_entry_point(name, decorators)` that checks the pattern catalog. Set `metadata["entry_point"] = True` if matched.
- In `_handle_class` (line 168): same check — a class with `@admin.register` or `@app.route` (Flask class-based views) should be flagged.
- The helper `_is_entry_point(name: str, decorators: list[str]) -> bool` lives in `codegraph/parsers/python.py` or a shared `codegraph/parsers/_entrypoints.py`.

**TypeScript parser** (`codegraph/parsers/typescript.py`):

- Add `_get_ts_decorators(node, src) -> list[str]` — mirror of the Python version but for TS `decorator` nodes (tree-sitter-typescript does expose `decorator` as a child of `class_declaration` and `method_definition`).
- In `_handle_class`, `_handle_method`, `_handle_function_decl`, `_handle_lexical_decl`: collect decorators, call `_is_entry_point_ts(name, decorators, rel, is_exported)`.
- File-location rules (Next.js pages) can be evaluated in `parse_file` and applied to default-export nodes.

**Dead-code analyzer** (`codegraph/analysis/dead_code.py`):

- Line 57, inside the main loop: add one early-continue check before the edge scan:
  ```python
  if (attrs.get("metadata") or {}).get("entry_point"):
      continue
  ```
  This is the only change needed in `dead_code.py`.

---

## 4. Schema Impact

### `codegraph/graph/schema.py`

No change required. `Node.metadata: dict[str, Any]` already supports arbitrary keys. The `entry_point` bool is stored alongside `decorators`.

### `codegraph/graph/store_sqlite.py`

No DDL change required. `metadata` is already a TEXT column storing JSON (line 37). No migration needed.

### Migration strategy for existing `graph.db` files

Because `entry_point` is derived from source at parse time:
- Users simply run `codegraph build` (or `codegraph build --no-incremental`) after upgrading.
- The builder already uses `INSERT OR REPLACE` for nodes (line 63), so re-parsing any file overwrites the metadata field with the new flag.
- No ALTER TABLE or migration script is needed.
- Document in CHANGELOG: "After upgrading to 0.2.0 run `codegraph build` to regenerate entry-point metadata."

---

## 5. Config Knobs

Add an optional `dead_code` key to `.codegraph.yml`:

```yaml
# .codegraph.yml
dead_code:
  # Additional decorator patterns treated as entry points.
  # Matched as prefix of the decorator string (leading @ is optional).
  entry_point_decorators:
    - "@app.command"          # already built-in, shown for illustration
    - "@my_framework.handler"
    - "celery_app.task"

  # Name-glob patterns treated as entry points (fnmatch syntax).
  entry_point_names:
    - "handle_*"
    - "on_*"

  # File-path globs: any function/class in these files is an entry point.
  entry_point_files:
    - "src/handlers/**"
    - "lambdas/*.py"
```

**Model changes** (`codegraph/config.py`):

Add `dead_code: DeadCodeConfig = Field(default_factory=DeadCodeConfig)` to `CodegraphConfig`. `DeadCodeConfig` is a new Pydantic model with `entry_point_decorators: list[str]`, `entry_point_names: list[str]`, `entry_point_files: list[str]`.

The config is passed into `GraphBuilder` which forwards it to each extractor. Extractors merge user patterns with the built-in catalog before calling `_is_entry_point`.

---

## 6. Test Plan

### New fixture

Create `tests/fixtures/framework_entrypoints/` with the following files:

**`tests/fixtures/framework_entrypoints/typer_app.py`**
```python
import typer
app = typer.Typer()

@app.command()
def greet(name: str) -> None:
    """Say hello."""
    print(f"Hello {name}")

@app.command()
def farewell(name: str) -> None:
    print(f"Bye {name}")

@app.callback()
def main_callback(ctx: typer.Context) -> None:
    pass

def _internal_helper() -> str:
    return "helper"
```

**`tests/fixtures/framework_entrypoints/fastapi_app.py`**
```python
from fastapi import FastAPI, APIRouter
app = FastAPI()
router = APIRouter()

@app.get("/health")
def health_check():
    return {"status": "ok"}

@router.post("/items")
def create_item(name: str):
    return {"name": name}

def _validate_item(name: str) -> bool:
    return bool(name)
```

**`tests/fixtures/framework_entrypoints/pytest_fixtures.py`**
```python
import pytest

@pytest.fixture
def db_connection():
    return {"connected": True}

@pytest.fixture(scope="session")
def app_client():
    return object()

def _setup_db():
    pass
```

### New test file: `tests/test_dead_code_entrypoints.py`

Tests to assert:

1. `greet`, `farewell`, `main_callback` from `typer_app.py` are NOT in the dead-code list.
2. `health_check`, `create_item` from `fastapi_app.py` are NOT in the dead-code list.
3. `db_connection`, `app_client` from `pytest_fixtures.py` are NOT in the dead-code list.
4. `_internal_helper`, `_validate_item`, `_setup_db` ARE in the dead-code list (they have no incoming refs and no entry-point decorator).
5. Each entry-point node has `metadata["entry_point"] == True` after parsing.

Test structure: build graph from `tests/fixtures/framework_entrypoints/` using `GraphBuilder`, call `find_dead_code()`, assert membership.

### Existing test to update

`tests/test_analysis.py` — verify that running `find_dead_code` on a graph that includes nodes with `metadata["entry_point"] = True` skips them regardless of incoming-edge count.

---

## 7. Edge Cases and Known Limitations

| Case | Status |
|------|--------|
| `getattr(module, name)(...)` dynamic dispatch | Out of scope — document as known limitation. Dynamic string-based lookup cannot be statically resolved; affected functions will still be flagged. |
| `__all__` exports in `__init__.py` | Out of scope for D1. Functions listed in `__all__` are public API but have no incoming CALLS edges by definition. Treat as D3 item. |
| Celery `@shared_task` with `bind=True` | Covered by decorator prefix match on `@shared_task`. |
| Flask class-based views (subclass of `MethodView`) | The class will have an INHERITS edge to `MethodView`; methods `get`/`post` inside it are called via the class. Flask's `add_url_rule` is a dynamic dispatch — class methods are still dead by static analysis. Flag the class via `@app.route` decorator on registration or document as limitation. |
| Next.js App Router `generateStaticParams`, `generateMetadata` | These are named exports with conventional names; add to `entry_point_names` built-in list in D2. |
| Python `__init_subclass__`, `__class_getitem__` | Already excluded by `_is_dunder` check. |
| Pytest `conftest.py` fixtures used across files | The fixture function has no incoming CALLS edge from test files (pytest resolves by name). Covered by `@pytest.fixture` decorator pattern. |

---

## 8. Phased Plan

### Phase D1 — Python entry points (covers ~80% of false positives)

**Scope**: Typer, Click, FastAPI, Flask, Celery, pytest fixtures, `@abstractmethod`, Django signals/admin.

**Files to change**:
- `codegraph/parsers/python.py` — add `_is_entry_point(name, decorators)` helper; set flag in `_handle_function` and `_handle_class`.
- `codegraph/analysis/dead_code.py` — add four-line early-continue check using the flag.
- `codegraph/config.py` — add `DeadCodeConfig` model; add `dead_code` field to `CodegraphConfig`.

**Files to add**:
- `tests/fixtures/framework_entrypoints/typer_app.py`
- `tests/fixtures/framework_entrypoints/fastapi_app.py`
- `tests/fixtures/framework_entrypoints/pytest_fixtures.py`
- `tests/test_dead_code_entrypoints.py`

**Estimate**: 1 day.  
**Acceptance**: Running `codegraph analyze` on this repo reports 0 false positives from `cli.py`.

---

### Phase D2 — TypeScript entry points

**Scope**: NestJS decorators (`@Controller`, `@Get`, `@Post`, `@Injectable`, etc.), Next.js page exports, Jest/Vitest top-level test registrations.

**Files to change**:
- `codegraph/parsers/typescript.py` — add `_get_ts_decorators` helper; call `_is_entry_point_ts` in `_handle_class`, `_handle_method`, `_handle_function_decl`; add file-path check for Next.js pages.

**Files to add**:
- `tests/fixtures/framework_entrypoints/nestjs_controller.ts`
- `tests/fixtures/framework_entrypoints/nextjs_page.tsx`
- Additional assertions in `tests/test_dead_code_entrypoints.py`.

**Estimate**: 1 day.

---

### Phase D3 — Config-driven custom patterns

**Scope**: Let users declare custom decorator patterns, name globs, and file-path globs in `.codegraph.yml` under the `dead_code` key.

**Files to change**:
- `codegraph/config.py` — finalize `DeadCodeConfig` schema.
- `codegraph/graph/builder.py` — pass `cfg.dead_code` to extractors.
- `codegraph/parsers/python.py` and `codegraph/parsers/typescript.py` — accept and merge user patterns.

**Files to add**:
- `tests/test_dead_code_config.py` — test that a custom decorator declared in config suppresses the false positive.

**Estimate**: 0.5 days.
