# Architecture: v0.2 Cross-Stack Data Flow Tracing

## Wedge

Existing tools (GitNexus, code-review-graph, Sourcegraph, RepoMapper) stop at
function-level call edges within a single language. They cannot answer: "a user
clicks Submit on the Login form — trace it through fetch → API route → handler →
service → SQLAlchemy session → Postgres → back through serializer → response →
React state update." This plan closes that gap for the FastAPI + React/Next.js +
SQLAlchemy stack only.

v0.2 also closes two related gaps from the 0.1.0 user feedback:

- **Argument-level data flow.** CALLS edges today have no payload. v0.2 carries
  positional args, kwargs, and parameter lists along every edge and node.
  Detailed spec in [`PLAN_V0_2_PARAMETERS.md`](./PLAN_V0_2_PARAMETERS.md).
- **Service / component classification.** The dashboard picker today shows a
  flat list of FUNCTION nodes. v0.2 tags every FUNCTION/METHOD/CLASS with a
  `metadata.role` of HANDLER, SERVICE, COMPONENT, or REPO so the picker
  reflects how engineers actually navigate code.

---

## 1. Conceptual Model

### 1.1 New NodeKind values

Add these to `codegraph/graph/schema.py` `NodeKind` enum:

| Constant     | Meaning |
|--------------|---------|
| `ROUTE`      | An HTTP endpoint declared with a FastAPI decorator or Next.js API route file. Carries `method` (GET/POST/…) and `path` (normalized template). |
| `FETCH_CALL` | A frontend `fetch()` / `axios.*()` call site. Carries `method`, `path` (raw), `path_normalized`, `confidence`. |
| `TABLE`      | A Postgres/SQLite table derived from a SQLAlchemy `__tablename__`. |
| `MODEL`      | A SQLAlchemy ORM model class (maps 1:1 to a TABLE; they are different nodes so model code and DB schema can be queried independently). |
| `COMPONENT`  | A React/Next.js component function or class that returns JSX. Identified by capitalized identifier + JSX return. |
| `HANDLER`    | The Python function directly decorated by a FastAPI route decorator. Subtype of existing FUNCTION — represented as a FUNCTION node with `metadata.is_handler = True` and a HANDLES edge into it; no new kind needed unless queries become unwieldy. Decision: keep as FUNCTION for backward compat, use metadata flag to avoid breaking existing analysis. HANDLER node kind is exposed as a virtual kind in query output but stored as FUNCTION. |
| `SERVICE`    | A Python function or method identified heuristically as a service-layer call (called from a handler, not itself a handler, calls ORM methods). Stored as FUNCTION with `metadata.is_service = True`. Same reasoning as HANDLER. |

Storing HANDLER and SERVICE as FUNCTION-with-metadata preserves backward
compatibility with all existing `NodeKind.FUNCTION` queries. The dataflow
extractor tags them; the trace query filters by the metadata flag.

### 1.2 New EdgeKind values

Add to `EdgeKind` enum:

| Constant        | Direction | Meaning |
|-----------------|-----------|---------|
| `HANDLES`       | ROUTE → FUNCTION (handler) | The route delegates to this handler. |
| `READS_FROM`    | FUNCTION → TABLE | Handler/service reads rows from this table (SELECT context). |
| `WRITES_TO`     | FUNCTION → TABLE | Handler/service writes to this table (INSERT/UPDATE/DELETE context). |
| `RENDERS`       | COMPONENT → FETCH_CALL | The component contains this fetch call (static scope link). |
| `TRIGGERED_BY`  | FETCH_CALL → COMPONENT | The fetch call is inside an event handler (`onClick`, `onSubmit`, `useEffect`) in this component. Inverse of RENDERS for the event-scoped case. |
| `MATCHES`       | FETCH_CALL → ROUTE | Cross-stack stitch: frontend call matched to backend route. Carries `confidence` float in metadata. |
| `HAS_MODEL`     | TABLE → MODEL | ORM model that maps to this table. |

Existing `READS` and `WRITES` in the current schema are kept for variable-level
semantics. The new `READS_FROM` / `WRITES_TO` are table-level data-flow edges.

### 1.3 Schema diff vs current `codegraph/graph/schema.py`

```python
# NodeKind additions
ROUTE      = "ROUTE"
FETCH_CALL = "FETCH_CALL"
TABLE      = "TABLE"
MODEL      = "MODEL"
COMPONENT  = "COMPONENT"

# EdgeKind additions
HANDLES     = "HANDLES"
READS_FROM  = "READS_FROM"
WRITES_TO   = "WRITES_TO"
RENDERS     = "RENDERS"
TRIGGERED_BY = "TRIGGERED_BY"
MATCHES     = "MATCHES"
HAS_MODEL   = "HAS_MODEL"
```

No changes to the `Node` or `Edge` Pydantic models. All new semantics fit in the
existing `metadata: dict[str, Any]` field. The `make_node_id` function is reused
unchanged; the new kinds participate in its hash automatically.

### 1.4 Parameter / argument metadata (DF0)

Per [`PLAN_V0_2_PARAMETERS.md`](./PLAN_V0_2_PARAMETERS.md), DF0 lands these
metadata fields ahead of every other phase:

- `Edge.metadata.args: list[str]` on CALLS edges
- `Edge.metadata.kwargs: dict[str, str]` on CALLS edges
- `Node.metadata.params: list[{name, type, default}]` on FUNCTION/METHOD/CLASS
- `Node.metadata.returns: str | None` on FUNCTION/METHOD

DF1 (FastAPI), DF2 (React), DF3 (stitcher), and DF4 (dashboard) all consume
these. Without DF0 the rest of v0.2 still works structurally but the user-visible
"argument-level data flow" claim does not hold.

### 1.5 Role classification metadata (DF1.5)

DF1.5 adds a single `metadata.role` field on FUNCTION / METHOD / CLASS nodes
with one of these values (or absent):

| Role        | Detection summary |
|-------------|-------------------|
| `HANDLER`   | FastAPI/Flask route decorator, NestJS `@Controller` method, or Next.js `app/route.ts` default export. |
| `SERVICE`   | Class whose name ends in `Service` and constructor takes a repo/db dep, or class with `@Injectable()` (NestJS). |
| `COMPONENT` | Function returning JSX (Capitalized name + `<Capitalized` body), or class extending `React.Component`. |
| `REPO`      | Class whose name ends in `Repository`, or whose methods access a SQL session / ORM model. |

Detection rules in full are in §2.4. The role tag drives:

- HLD picker grouping ("Handlers", "Services", "Components", "Repositories")
- Dashboard Sankey lane assignment (DF4)
- MCP `find_symbol` filtering by role

---

## 2. Extractor Design

### 2.1 FastAPI Route Extractor (`codegraph/dataflow/extractors/fastapi.py`)

**Goal**: find every `@app.get(...)`, `@router.post(...)`, etc. and emit a ROUTE
node plus a HANDLES edge to the handler FUNCTION node.

**Entry point**: `FastAPIExtractor.extract(nodes, edges, src, rel, tree_root)`
called with the already-parsed tree-sitter tree from the existing Python pass.
This avoids parsing twice. The Python extractor already captures decorators into
`metadata["decorators"]` on each FUNCTION node — the FastAPI extractor receives
the full node list from the Python pass and post-processes it.

**Tree-sitter node types involved**:

```
decorated_definition
  decorator                    ← child type "decorator"
    "@"
    call                       ← child type "call"
      function: attribute      ← child type "attribute"
        object: identifier     ← "app" or "router" variable name
        attribute: identifier  ← "get" | "post" | "put" | "delete" | "patch"
      arguments: argument_list
        string                 ← the path literal e.g. "/users/{id}"
        keyword_argument       ← e.g. response_model=UserOut
  function_definition          ← the handler
```

**Algorithm** (post-process on FUNCTION nodes with decorators):

1. For each FUNCTION/METHOD node where `metadata["decorators"]` is non-empty:
   a. For each decorator string, apply regex:
      `re\.search(r'@(\w+)\.(get|post|put|delete|patch|head|options)\s*\(', dec)`
   b. If matched: capture `router_var` (group 1), `method` (group 2).
   c. Extract path from the decorator string with:
      `re\.search(r'["\']([^"\']+)["\']', dec)` → group 1 is the raw path.
   d. Normalize path: replace `{param_name}` → `{param}` (canonical form).
   e. Create ROUTE node with:
      - `kind = NodeKind.ROUTE`
      - `name = f"{method.upper()} {normalized_path}"`
      - `qualname = f"route:{method.upper()}:{normalized_path}:{rel}"`
      - `metadata = {"method": method.upper(), "path": normalized_path, "raw_path": raw_path, "router_var": router_var, "file": rel}`
   f. Emit HANDLES edge: `src=route_id, dst=function_node_id`.
   g. **DF0 integration:** the handler's `metadata.params` (already populated
      by DF0 parser work) is the request-shape contract. Copy a summary of it
      onto the HANDLES edge as `metadata.handler_params` so downstream stitcher
      can match by argument shape.
   h. **DF1.5 integration:** tag the handler FUNCTION node with
      `metadata.role = "HANDLER"`.

**Argument propagation onto handler→service CALLS edges:** no extra work here.
DF0 already populates `args` / `kwargs` on every CALLS edge globally; FastAPI
extractor consumes that data, it does not produce it.

**Next.js API route support** (stretch for v0.2 — see risk section):

Files at `pages/api/**.ts` or `app/api/**/route.ts` export named HTTP handlers.
The TS extractor already captures exported functions. The FastAPI extractor does
not handle these; a separate Next.js extractor is deferred to v0.3.

### 2.2 SQLAlchemy Extractor (`codegraph/dataflow/extractors/sqlalchemy.py`)

**Goal**: find ORM MODEL classes, extract TABLE nodes, and emit READS_FROM /
WRITES_TO edges from handler/service functions to those tables.

**Part A — Model and Table extraction**:

SQLAlchemy models subclass `Base`, `DeclarativeBase`, or use `DeclarativeMeta`.
Post-process CLASS nodes:

1. For each CLASS node: check if any INHERITS edge points to a name matching
   `Base`, `DeclarativeBase`, or a user-defined base (heuristic: name ends in
   `Base` or is `Model`).
2. Walk the class body for `__tablename__` assignment:
   - Tree-sitter node: `expression_statement > assignment` where left side
     `identifier` text is `__tablename__` and right side is a `string`.
   - [TODO verify: assignment node in tree-sitter Python — field names are
     `left` and `right`; type is `assignment`]
3. For `Mapped[...]` / `Column(...)` attributes at class body level, these are
   columns — no separate node needed for v0.2; capture in MODEL metadata.
4. Emit:
   - MODEL node (the CLASS id is reused; tag `metadata["is_orm_model"] = True`
     and `metadata["tablename"] = value`).
   - TABLE node: `kind=NodeKind.TABLE, name=tablename, qualname=f"table:{tablename}"`.
   - HAS_MODEL edge: `src=table_id, dst=class_id`.
5. **DF1.5:** if the surrounding CLASS is itself a repository (name ends in
   `Repository` or methods touch this MODEL via session), tag
   `metadata.role = "REPO"`. Otherwise it is a plain MODEL.

**Part B — READS_FROM / WRITES_TO edges**:

For each FUNCTION/METHOD node, scan its CALLS edges for patterns that indicate
DB operations. Three detection strategies, applied in order:

Strategy 1 — `session.execute(select(Model))` / `session.execute(insert(Model))`:

The existing `_collect_calls` in python.py captures CALLS edges with
`target_name` = `"session.execute"` etc. Post-process: when a CALLS edge has
`target_name` matching `r'(session|db|conn)\.(execute|add|delete|query|get)'`:

- Walk the call's AST arguments. The first argument to `execute()` is often a
  `select(...)`, `insert(...)`, `update(...)`, `delete(...)` call.
- Tree-sitter: the `call` node's `arguments` field contains `argument_list`
  whose first child is itself a `call` whose `function` text is `select` /
  `insert` / `update` / `delete`.
- Extract the model name from the inner call's first argument (an `identifier`).
- Resolve model name to a TABLE node via the MODEL registry built in Part A.
- Emit `READS_FROM` if outer verb is select/get/query, `WRITES_TO` if
  insert/update/delete/add.

Strategy 2 — `Model.query.filter(...)` (legacy SQLAlchemy style):

CALLS edges where `target_name` matches `r'^(\w+)\.query\b'`. Group 1 is the
model class name. Always READS_FROM.

Strategy 3 — Implicit from `session.add(instance)` / `session.delete(instance)`:

CALLS edges where target is `session.add` → WRITES_TO (model inferred from
argument type annotation if present; fall back to `unresolved_table`). DF0's
`args` payload on the call edge is what carries the instance variable name
here, making "which value got written" answerable.

**Limitation**: ORM lazy loading (accessing a relationship attribute) produces no
explicit call site. This is documented as out of scope for v0.2 (see risk
section).

### 2.3 React/Next.js FETCH_CALL Extractor (`codegraph/dataflow/extractors/react.py`)

**Goal**: find COMPONENT nodes, identify fetch calls inside them, tag event
handler context.

**Part A — Component detection**:

Post-process FUNCTION nodes from the TypeScript extractor:

1. A node is a COMPONENT if:
   - Its `name` starts with an uppercase letter, AND
   - Its body contains a `jsx_element` or `jsx_self_closing_element` tree-sitter
     node anywhere in its subtree.
   - [Tree-sitter TSX grammar: `jsx_element`, `jsx_self_closing_element` are the
     node types for `<Foo>` and `<Foo />`]
2. Tag `metadata["is_component"] = True` AND `metadata.role = "COMPONENT"`
   (DF1.5). Emit a COMPONENT node reusing the FUNCTION node id (same strategy
   as HANDLER — backward compatible). Alternatively emit a new COMPONENT node
   with a DEFINED_IN edge to the FUNCTION. Decision: new separate node to
   make graph traversal explicit. COMPONENT node id =
   `make_node_id(NodeKind.COMPONENT, qualname, rel)`. Emit a `DEFINED_IN`
   edge from COMPONENT → FUNCTION.

**Part B — FETCH_CALL detection**:

Walk the body of each COMPONENT function (and any nested arrow functions within
event handlers). Look for `call_expression` nodes where:

Pattern 1 — `fetch(url, opts)`:
```
call_expression
  function: identifier  text == "fetch"
  arguments: arguments
    [0]: string | template_string | identifier
    [1]: object       ← request init: { method, body, headers, ... }
```
[Tree-sitter TS: `call_expression` has field `function` and `arguments`;
argument list type is `arguments`]

Pattern 2 — `axios.get(url)` / `axios.post(url, data)`:
```
call_expression
  function: member_expression
    object: identifier   text == "axios"
    property: property_identifier  text in {get, post, put, delete, patch}
  arguments: arguments
    [0]: string | template_string
    [1]: object | identifier   ← request body / config
```

**DF0 integration (request-body capture):** the second argument's source-text
(an object literal in most fetch/axios cases) is captured into the FETCH_CALL
node's `metadata.args` per DF0 rules. The stitcher (DF3) then parses the
top-level keys of that object literal into a synthetic `body_keys: list[str]`
on the FETCH_CALL node so it can match against handler `params` shape.

Pattern 3 — custom hook calls like `useFetch("/api/users")`, `useQuery(...)`:
Deferred to v0.3. Too many variations to handle safely without false positives.

**URL extraction from the first argument**:

- `string` node: strip quotes → literal path.
- `template_string` node: reconstruct with param placeholders.
  Walk children; `template_substitution` nodes become `{param}` in the
  normalized form. E.g. `` `/users/${userId}` `` → `/users/{param}`.
  [Tree-sitter TS: `template_string` children include `string_fragment` and
  `template_substitution`]
- `identifier` (variable): mark `path_source = "variable"`, `path = null`,
  `confidence = 0.3`. Emit node but skip matching.

**Part C — Event handler context**:

For each FETCH_CALL, determine whether it is inside:
- An `onClick` / `onSubmit` / `onChange` JSX attribute handler:
  Walk ancestor nodes. If the containing function is an arrow function assigned
  to a JSX attribute (`jsx_attribute` with `property_identifier` text matching
  `on[A-Z]\w+`), tag `metadata["event"] = "onClick"` etc.
  [Tree-sitter TSX: `jsx_attribute`, `jsx_expression`]
- A `useEffect` call: if the FETCH_CALL's ancestor `call_expression` has
  `function.text == "useEffect"`, tag `metadata["event"] = "useEffect"`.

Emit edges:
- RENDERS: `src=component_id, dst=fetch_call_id`
- TRIGGERED_BY: if event context found, `src=fetch_call_id, dst=component_id`
  with `metadata["event"] = event_name`.

### 2.4 Role Classification Extractor — DF1.5 (`codegraph/dataflow/extractors/roles.py`)

A single post-pass that runs after FastAPI / SQLAlchemy / React extractors and
walks every FUNCTION / METHOD / CLASS node, emitting `metadata.role` based on
the rules below. It is its own pass (not folded into the others) because the
detection logic mixes signals from multiple extractors.

**HANDLER**

- Python: function with a decorator string matching the FastAPI/Flask regex
  used in §2.1, or matching `@app\.route\(`, `@blueprint\.route\(`.
- TypeScript: method on a class decorated with `@Controller(...)` (NestJS
  convention), OR a default-exported function from a file matching
  `app/**/route.ts` or `app/**/route.tsx`.
- Already covered by the FastAPI extractor for the Python case; this pass
  generalizes to Flask and Nest.

**SERVICE**

- Python: CLASS whose name ends with `Service` AND whose `__init__` parameter
  list (from DF0 `params`) includes a parameter whose annotation text
  references `Repo`, `Repository`, `Session`, `DB`, or whose name ends in
  `_repo` / `_db`. Methods on that class also inherit `role = "SERVICE"`.
- TypeScript: class decorated with `@Injectable(...)` (NestJS).

**COMPONENT**

- Already tagged by the React extractor (§2.3 Part A). The roles pass leaves
  these alone.
- Class components: TS class whose `extends_clause` references
  `React.Component` or `Component` (after import resolution by name match).

**REPO**

- Python: CLASS whose name ends with `Repository` OR whose methods emit a
  `READS_FROM` / `WRITES_TO` edge produced by the SQLAlchemy extractor (§2.2).
- TypeScript: class decorated with `@EntityRepository(...)` or whose methods
  call a TypeORM `Repository<T>`-typed dependency.

**Conflict resolution**

A node can match more than one rule (e.g. a `UserService` class containing a
method that also reads a table). Apply this priority order, first match wins:
`HANDLER > COMPONENT > SERVICE > REPO`. The node still ends up taggable as
`is_handler`, `is_service`, etc. via the existing boolean flags; `role` is the
single canonical label for UI grouping.

**Effort:** see §9 DF1.5.

---

## 3. Matching Algorithm

File: `codegraph/dataflow/stitcher.py`, function `stitch_fetch_to_routes`.

**Input**: the full graph post-extraction, containing ROUTE nodes and FETCH_CALL
nodes.

**Step 1 — Path normalization**

Apply to both ROUTE paths and FETCH_CALL paths before comparison.

Normalize function `normalize_path(raw: str) -> str`:

```
1. Strip leading/trailing whitespace and trailing slash (unless root "/").
2. Remove base URL prefix if present:
   - If path starts with "http", extract path component only (urllib.parse.urlparse).
   - If path starts with "/api" and router mounts at "/", keep as-is.
3. Replace path parameter variants:
   - FastAPI: {user_id} → {param}
   - Express-style colon params: :userId → {param}
   - Template literal params already normalized to {param} by extractor.
4. Lowercase the result.
```

Examples:
- `/users/{user_id}` → `/users/{param}`
- `/users/:id` → `/users/{param}`
- `/users/${userId}` (already converted) → `/users/{param}`
- `https://api.example.com/users/123` → skip (literal ID, not a param; no match)

**Step 2 — Exact match by (method, normalized_path)**

Build a dict `route_index: dict[tuple[str,str], list[str]]` mapping
`(method, normalized_path)` → list of ROUTE node ids.

For each FETCH_CALL node:
- Get its `method` and `path_normalized` from metadata.
- Look up `route_index[(method, path_normalized)]`.
- If 1 match: emit MATCHES edge, `confidence = 1.0`.
- If multiple matches (same path, different files): emit all, `confidence = 0.9`,
  `metadata["ambiguous"] = True`.

**Step 2b — Argument-shape tiebreaker (DF0 + DF3 integration)**

When Step 2 yields multiple candidate ROUTEs for the same `(method, path)`,
reduce ambiguity by comparing argument shape:

1. From the FETCH_CALL: read `metadata.body_keys` (the top-level keys of the
   request-init object literal, parsed by DF3 from DF0's `args` payload).
2. From each candidate ROUTE: read its handler's `metadata.params` (excluding
   `self`, dependency-injected `Depends(...)` params, and path params already
   bound by the URL).
3. Score = size of intersection between `body_keys` and remaining param names.
4. Pick the highest-scoring ROUTE; record the others as `metadata["alternatives"]`.

If `body_keys` is empty (GET request, identifier-only fetch arg), skip the
tiebreaker and accept the ambiguous match as today.

**Step 3 — Fuzzy fallback for prefix mismatches**

Frontend apps often call `/api/users` while the FastAPI router is mounted at
`/users` (with a Next.js rewrite of `/api/*` → `/*`), or vice versa.

If no exact match:
- Strip common prefix segments one at a time from the FETCH_CALL path and retry.
  Specifically, strip `/api`, `/v1`, `/v2` prefixes.
- If still no match, try stripping the first path segment entirely.
- If match found: emit MATCHES edge, `confidence = 0.7`,
  `metadata["matched_via"] = "prefix_strip"`.

**Step 4 — No-match logging**

FETCH_CALLs with no MATCHES edge are recorded in a `dataflow_unmatched` metadata
key on the graph object (stored as graph-level metadata in SQLite via
`store.set_meta`). This powers the success metric measurement.

**Confidence score semantics**:

| Score | Meaning |
|-------|---------|
| 1.0   | Exact (method, normalized_path) match, single candidate or shape-tiebroken |
| 0.9   | Exact match but multiple backend routes with same path, no shape tiebreak |
| 0.7   | Prefix-stripped match |
| 0.3   | Path is a variable (unresolvable statically) |

---

## 4. Pipeline Integration

### 4.1 Where in the build pipeline

Current `GraphBuilder.build()` in `codegraph/graph/builder.py` runs:

```
walk files
  → per-file extractor (PythonExtractor / TypeScriptExtractor)
  → store.upsert_nodes / upsert_edges
→ resolve_unresolved_edges   ← existing cross-file name resolution
```

**DF0 (parameter capture)** is implemented in the per-file extractors
themselves (`codegraph/parsers/python.py`, `codegraph/parsers/typescript.py`)
— see [`PLAN_V0_2_PARAMETERS.md`](./PLAN_V0_2_PARAMETERS.md) §3. So by the time
`run_dataflow_pass` runs, every CALLS edge already carries `args`/`kwargs` and
every FUNCTION/METHOD/CLASS node already carries `params`/`returns`.

New stage inserted **after** `resolve_unresolved_edges`:

```python
# codegraph/graph/builder.py  (addition to build() method)
try:
    from codegraph.dataflow.pipeline import run_dataflow_pass
    df_stats = run_dataflow_pass(self._store, self._repo_root)
    self._store.set_meta("last_dataflow", json.dumps(df_stats))
except Exception as exc:
    logger.warning("dataflow pass failed: %s", exc)
    stats.errors.append(f"dataflow: {exc}")
```

The dataflow pass is defensive: if it raises, the build still succeeds.

### 4.2 `codegraph/dataflow/pipeline.py`

```python
def run_dataflow_pass(store: SQLiteGraphStore, repo_root: Path) -> dict:
    from codegraph.graph.store_networkx import to_digraph
    from codegraph.dataflow.extractors.fastapi import FastAPIExtractor
    from codegraph.dataflow.extractors.sqlalchemy import SQLAlchemyExtractor
    from codegraph.dataflow.extractors.react import ReactExtractor
    from codegraph.dataflow.extractors.roles import RoleClassifier
    from codegraph.dataflow.stitcher import stitch_fetch_to_routes

    g = to_digraph(store)

    fastapi_nodes, fastapi_edges = FastAPIExtractor().extract(g)
    store.upsert_nodes(fastapi_nodes)
    store.upsert_edges(fastapi_edges)

    sqla_nodes, sqla_edges = SQLAlchemyExtractor().extract(g, store)
    store.upsert_nodes(sqla_nodes)
    store.upsert_edges(sqla_edges)

    react_nodes, react_edges = ReactExtractor().extract(g)
    store.upsert_nodes(react_nodes)
    store.upsert_edges(react_edges)

    # DF1.5 — runs after the three extractors above so it can read their tags.
    role_node_updates = RoleClassifier().classify(store)
    store.upsert_nodes(role_node_updates)

    # Reload graph with new nodes before stitching
    g2 = to_digraph(store)
    stitch_edges = stitch_fetch_to_routes(g2)
    store.upsert_edges(stitch_edges)

    return {
        "routes": len([n for n in fastapi_nodes if n.kind == NodeKind.ROUTE]),
        "fetch_calls": len([n for n in react_nodes if n.kind == NodeKind.FETCH_CALL]),
        "tables": len([n for n in sqla_nodes if n.kind == NodeKind.TABLE]),
        "matches": len(stitch_edges),
        "roles": {
            "handler":   sum(1 for n in role_node_updates if n.metadata.get("role") == "HANDLER"),
            "service":   sum(1 for n in role_node_updates if n.metadata.get("role") == "SERVICE"),
            "component": sum(1 for n in role_node_updates if n.metadata.get("role") == "COMPONENT"),
            "repo":      sum(1 for n in role_node_updates if n.metadata.get("role") == "REPO"),
        },
    }
```

### 4.3 File structure

```
codegraph/
  dataflow/
    __init__.py
    pipeline.py               ← orchestrator (as above)
    stitcher.py               ← URL matching, MATCHES edge emission
    extractors/
      __init__.py
      fastapi.py              ← ROUTE + HANDLES
      sqlalchemy.py           ← MODEL, TABLE, READS_FROM, WRITES_TO
      react.py                ← COMPONENT, FETCH_CALL, RENDERS, TRIGGERED_BY
      roles.py                ← DF1.5 — metadata.role classification
```

Each extractor exposes a single class with one public method:

```python
class FastAPIExtractor:
    def extract(self, graph: nx.MultiDiGraph) -> tuple[list[Node], list[Edge]]: ...

class SQLAlchemyExtractor:
    def extract(self, graph: nx.MultiDiGraph, store: SQLiteGraphStore) -> tuple[list[Node], list[Edge]]: ...

class ReactExtractor:
    def extract(self, graph: nx.MultiDiGraph) -> tuple[list[Node], list[Edge]]: ...

class RoleClassifier:
    def classify(self, store: SQLiteGraphStore) -> list[Node]: ...
```

SQLAlchemyExtractor takes `store` because it needs to re-read the Python AST
source for certain call argument walks that were not captured in the graph.

---

## 5. CLI Surface

Add a `dataflow_app` Typer sub-app to `codegraph/cli.py`, mounted as
`codegraph dataflow`.

### 5.1 `codegraph dataflow trace --from SYMBOL --to SYMBOL`

```
codegraph dataflow trace --from "LoginForm" --to "users"
```

Implementation (`codegraph/dataflow/trace.py`, function `trace_path`):

1. Resolve `--from` to a COMPONENT or FETCH_CALL node (substring match on name).
2. Resolve `--to` to a TABLE node (substring match on `name`).
3. Run BFS/DFS on the graph following edges in this order:
   RENDERS → MATCHES → HANDLES → CALLS → READS_FROM/WRITES_TO
   and also: TRIGGERED_BY, HAS_MODEL.
4. Return the shortest path as an ordered list of (node, edge) pairs.
5. Output as a Rich table showing: Layer | Role | Kind | Name | Args | File:Line.
   The `Args` column joins `edge.metadata.args` and `kwargs.keys()` for the
   call edge leaving each hop (DF0). The `Role` column reads `metadata.role`
   (DF1.5).

Layers displayed:
```
UI Event      COMPONENT  LoginForm          (form fields)         frontend/LoginForm.tsx:45
Fetch Call    FETCH_CALL POST /api/login    {username, password}  frontend/LoginForm.tsx:52
Route Match   ROUTE      POST /auth/login                         backend/routes/auth.py:12
Handler       HANDLER    login_handler      (creds)               backend/routes/auth.py:15
Service       SERVICE    authenticate_user  (username, password)  backend/services/auth.py:34
DB Write      TABLE      users                                    (via SQLAlchemy session)
```

### 5.2 `codegraph dataflow visualize`

Generates a standalone HTML Sankey diagram (using existing pyvis/html infra).
Writes to `.codegraph/dataflow.html`. Reuses `codegraph/viz` render patterns.

### 5.3 `codegraph dataflow stats`

Prints a summary table: routes found, fetch calls found, tables found, matched
fetch calls, unmatched fetch calls, match rate %, role counts (HANDLER /
SERVICE / COMPONENT / REPO).

---

## 6. MCP Tool Surface

Add one new tool to `codegraph/mcp_server/server.py`:

### Tool: `dataflow_trace`

```json
{
  "name": "dataflow_trace",
  "description": "Trace the full cross-stack data flow path from a UI component or fetch call to a database table, or from a backend route back to the frontend components that call it. Returns an ordered chain: component → fetch → route → handler → service → table, with per-hop parameter and argument metadata.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "start": {
        "type": "string",
        "description": "Component name, fetch URL pattern, or route path to start from."
      },
      "direction": {
        "type": "string",
        "enum": ["forward", "backward", "both"],
        "default": "forward",
        "description": "forward = UI → DB, backward = DB → UI, both = full chain."
      },
      "limit": {
        "type": "integer",
        "default": 50,
        "description": "Max chain nodes to return."
      }
    },
    "required": ["start"]
  }
}
```

Implementation function `tool_dataflow_trace(graph, start, direction, limit)` in
`codegraph/mcp_server/server.py` (following existing tool function pattern).
Returns a list of dicts, each with `layer`, `role`, `kind`, `name`, `file`,
`line`, `params` (DF0), `returns` (DF0), and `edge_to_next` (containing `args`
and `kwargs` from DF0). See [`PLAN_V0_2_PARAMETERS.md`](./PLAN_V0_2_PARAMETERS.md)
§5.3 for the per-hop payload shape.

The single tool covers all three navigation directions so the AI assistant does
not need to know which end of the chain to start from.

---

## 7. Visualization: Data Flow Dashboard View

### 7.1 New page in the explore dashboard

Add `dataflow.html` to the explore output alongside the existing
`architecture.html`, `callgraph.html` files. Rendered by
`codegraph/viz/explore.py` (add `_render_dataflow_page` function).

### 7.2 Sankey diagram layout

Use D3 sankey (via CDN, loaded in the generated HTML) or fall back to a layered
force graph if D3 sankey adds too much weight.

Lanes are driven by `metadata.role` (DF1.5) with TABLE in its own terminal
lane:

```
[ Frontend ]    |  [ API Layer ]   |  [ Service Layer ]  |  [ Data ]
COMPONENT          ROUTE              SERVICE              MODEL
                   HANDLER                                  TABLE
                                                            REPO (left edge of Data lane)
```

Node color coding:
- COMPONENT: blue
- FETCH_CALL: teal
- ROUTE: orange
- HANDLER: yellow
- SERVICE: amber
- REPO: rose
- MODEL: purple
- TABLE: red

**Edge labels (DF0):** every Sankey link shows `arg_names` joined with `, ` —
the names from `edge.metadata.args` (positional, where the source-text is an
identifier) and the keys of `edge.metadata.kwargs`. When the edge is a
`MATCHES` link from FETCH_CALL → ROUTE, the label is the request `body_keys`
captured by the stitcher (DF3). Edge width encodes call frequency where
available (fall back to uniform).

Clicking a Sankey link opens a side panel showing the **full payload schema**:
- Source: full `args` list and `kwargs` map (raw expression text).
- Destination: full `params` list with `name`, `type`, `default`.
- Diff: param names not covered by any arg/kwarg are flagged ("missing
  argument") and arg names not matched to a param are flagged ("extra
  argument") — useful for spotting drift between handler signatures and
  fetch payloads.

Clicking a node opens a detail panel showing file, line, qualname, role,
params, returns, and connected nodes.

### 7.3 Integration into `codegraph serve`

The existing web server in `codegraph/web/` serves the explore directory. The
`dataflow.html` page is included automatically once it lands in that directory.
No server-side changes needed beyond calling `_render_dataflow_page` from
`render_explore`.

---

## 8. Test Fixtures

### 8.1 Directory layout

```
tests/fixtures/dataflow_sample/
  backend/
    main.py                   ← FastAPI app instance, router include
    routes/
      auth.py                 ← @router.post("/login"), @router.get("/me")
      users.py                ← @router.get("/users/{id}"), @router.post("/users")
    services/
      auth_service.py         ← AuthService class — tagged role=SERVICE
      user_service.py         ← UserService class — tagged role=SERVICE
    repositories/
      user_repository.py      ← UserRepository class — tagged role=REPO
    models/
      user.py                 ← class User(Base): __tablename__ = "users"
      session.py              ← SessionLocal = sessionmaker(...)
  frontend/
    components/
      LoginForm.tsx           ← onClick → fetch POST /api/login
      UserProfile.tsx         ← useEffect → fetch GET /api/users/{id}
      UserList.tsx            ← onLoad → axios.get("/api/users")
    pages/
      index.tsx               ← renders LoginForm
      users/
        [id].tsx              ← renders UserProfile
```

### 8.2 Coverage requirements per extractor

**FastAPI extractor** (`test_dataflow_fastapi.py`):
- `@app.get("/path")` on a bare app
- `@router.post("/path/{id}")` on an APIRouter
- `response_model` keyword captured in metadata
- Multiple decorators on one function (should emit multiple ROUTE nodes)
- Handler node carries `metadata.role = "HANDLER"` (DF1.5)
- Handler node carries `metadata.params` from DF0

**SQLAlchemy extractor** (`test_dataflow_sqlalchemy.py`):
- `__tablename__` detection → TABLE node
- `session.execute(select(User))` → READS_FROM edge to "users" TABLE
- `session.execute(insert(User).values(...))` → WRITES_TO edge
- `session.add(user_instance)` → WRITES_TO edge (with unresolved model fallback)
  AND the call edge carries `metadata.args = ["user_instance"]` from DF0
- `User.query.filter(...)` → READS_FROM legacy-style
- A `UserRepository` class is tagged `metadata.role = "REPO"` (DF1.5)

**React extractor** (`test_dataflow_react.py`):
- Function component returning JSX → COMPONENT node, `metadata.role = "COMPONENT"`
- `fetch("/api/login", {method:"POST", body: JSON.stringify({username, password})})`
  → FETCH_CALL node, RENDERS edge, `metadata.body_keys = ["method","body"]`
- `axios.post("/api/users", {name, email})` → FETCH_CALL with
  `metadata.body_keys = ["name","email"]`
- Template URL: `fetch(\`/api/users/${id}\`)` → normalized `/api/users/{param}`
- onClick handler context → TRIGGERED_BY edge
- useEffect context → TRIGGERED_BY edge with event="useEffect"

**Stitcher** (`test_dataflow_stitcher.py`):
- Exact match: frontend POST /api/login → backend POST /login (after prefix strip)
  confidence 0.7
- Exact match no stripping: /users/{id} ↔ /users/{id} confidence 1.0
- Template vs template: /users/${id} normalized ≡ /users/{user_id} normalized
- Unmatched fetch: /api/nonexistent → no MATCHES edge, recorded in stats
- **Argument-shape tiebreaker:** two routes share `(POST, /users)`, only one
  has `params=[name,email]`; FETCH_CALL with `body_keys=[name,email]` matches
  it, the other becomes `metadata.alternatives`.

**Roles classifier** (`test_dataflow_roles.py`) — new in DF1.5:
- FastAPI handler → role=HANDLER
- `UserService` class with `def __init__(self, repo: UserRepository)` →
  role=SERVICE on class and methods
- React function component → role=COMPONENT (already tagged by react extractor;
  classifier leaves it alone)
- `class UserRepository` → role=REPO
- Conflict: `class UserService` whose method also writes to a table — role
  stays SERVICE per priority rules (HANDLER > COMPONENT > SERVICE > REPO).

**Integration** (`test_dataflow_integration.py`):
- Run `GraphBuilder.build()` on `tests/fixtures/dataflow_sample/`
- Assert ROUTE count >= 4
- Assert TABLE count >= 1 ("users")
- Assert MATCHES edges > 0
- Assert role counts: HANDLER >= 4, SERVICE >= 2, COMPONENT >= 3, REPO >= 1
- Assert trace from "LoginForm" to "users" returns a non-empty path with
  per-hop `args` populated on every CALLS edge

---

## 9. Phased Build Sequence

### DF0: Parameter capture (10 days) — depends on `PLAN_V0_2_PARAMETERS.md`

Detailed in [`PLAN_V0_2_PARAMETERS.md`](./PLAN_V0_2_PARAMETERS.md) §8. Summary:

- Days 1–4: Python + TS parser extensions for `args`, `kwargs`, `params`,
  `returns`.
- Day 5: schema + SQLite serialization changes.
- Day 6: HLD payload extension.
- Day 7: MCP `dataflow_trace` payload extension.
- Days 8–9: 3D edge-label rendering + hover tooltip.
- Day 10: tests + fixtures (cases §6.1–§6.11 of the parameters plan).

DF0 must land before DF1 because every downstream extractor reads its outputs.

### DF1: FastAPI route extractor + SQLAlchemy READS_FROM (3 days)

Day 1:
- Add new `NodeKind` and `EdgeKind` values to `codegraph/graph/schema.py`.
- Create `codegraph/dataflow/` package skeleton.
- Implement `FastAPIExtractor.extract()` (post-processes existing Python nodes,
  reads DF0 `params` to populate `HANDLES.metadata.handler_params`).
- Unit tests: `test_dataflow_fastapi.py` against `dataflow_sample/backend/routes/`.

Day 2:
- Implement `SQLAlchemyExtractor` Part A (MODEL/TABLE nodes).
- Implement `SQLAlchemyExtractor` Part B Strategy 1 (session.execute patterns).
- Unit tests: `test_dataflow_sqlalchemy.py`.

Day 3:
- SQLAlchemy Strategy 2 (legacy `.query`) and Strategy 3 (session.add/delete).
- Wire `pipeline.py` with FastAPI + SQLAlchemy passes only.
- Integration test: build against `dataflow_sample/`, assert ROUTE + TABLE nodes.

### DF1.5: Service / component classification (3 days)

Day 1:
- Implement `RoleClassifier.classify()` covering HANDLER + REPO detection
  (the cases that fall out of DF1's existing extractor signals).
- Wire into `pipeline.py` between extractors and stitcher.
- Unit tests for HANDLER and REPO rules.

Day 2:
- Add SERVICE detection (Python `*Service` classes with repo/db dependency,
  NestJS `@Injectable`).
- Add class-component COMPONENT detection (React class extending
  `React.Component`).
- Unit tests for SERVICE and class-COMPONENT rules.

Day 3:
- Conflict resolution priority order (`HANDLER > COMPONENT > SERVICE > REPO`).
- HLD picker grouping by role (read-only consumer change).
- MCP `find_symbol` filter parameter `role`.
- Final integration test: assert role counts on `dataflow_sample/`.

### DF2: React FETCH_CALL extractor (2 days)

Day 4:
- Implement `ReactExtractor` Part A (COMPONENT detection, sets role=COMPONENT).
- Implement fetch/axios pattern matching (Part B Patterns 1 and 2).
- Capture request-init object literal as DF0 `args[1]`; parse top-level keys
  into `metadata.body_keys` for stitcher consumption.
- Unit tests for component detection and fetch pattern matching.

Day 5:
- Event handler context detection (Part C): onClick/onSubmit/useEffect tagging.
- RENDERS and TRIGGERED_BY edge emission.
- Unit tests: event context cases.
- Add React pass to `pipeline.py`.

### DF3: Stitcher + URL matcher (2 days)

Day 6:
- Implement `normalize_path` with all four variants.
- Implement Steps 1-2 (exact matching), `stitch_fetch_to_routes`.
- Implement Step 2b (argument-shape tiebreaker) consuming `body_keys` from
  DF2 and `params` from DF0.
- Unit tests for normalizer edge cases, exact-match stitching, and shape
  tiebreaker.

Day 7:
- Implement Step 3 (prefix-strip fuzzy fallback).
- Wire stitcher into `pipeline.py` final step.
- End-to-end integration test on `dataflow_sample/`: assert MATCHES edges exist.

### DF4: CLI / MCP / dashboard surface (3 days)

Day 8:
- Implement `codegraph/dataflow/trace.py` BFS path finder.
- Add `codegraph dataflow trace` CLI command (renders Args + Role columns).
- Add `codegraph dataflow stats` CLI command (renders role counts).

Day 9:
- Add `dataflow_trace` MCP tool to `codegraph/mcp_server/server.py` (returns
  per-hop `params`, `args`, `kwargs` from DF0).
- Add `codegraph dataflow visualize` command (HTML Sankey).

Day 10:
- Integrate `_render_dataflow_page` into `codegraph/viz/explore.py`.
- Sankey link labels show `arg_names` (DF0).
- Click handler on a Sankey link opens the payload-schema side panel showing
  source `args`/`kwargs`, destination `params`, and a missing/extra diff.
- Run full end-to-end on `fastapi-react-template` reference repo (see §11).
- Fix any issues found. Write `CHANGELOG` entry.

**Stretch items** (do not block ship):
- Next.js `/app/api/route.ts` convention support.
- `useFetch` / `useQuery` hook detection.
- Confidence score displayed in `codegraph dataflow trace` output.

### Total effort

| Phase   | Description                              | Days |
|---------|------------------------------------------|-----:|
| DF0     | Parameter capture (parsers + UI + MCP)   | 10   |
| DF1     | FastAPI + SQLAlchemy extractors          |  3   |
| DF1.5   | Service / component classification       |  3   |
| DF2     | React FETCH_CALL extractor               |  2   |
| DF3     | Stitcher + URL matcher (incl. shape)     |  2   |
| DF4     | CLI / MCP / dashboard surface            |  3   |
| **Total** |                                        | **23** |

---

## 10. Risks and Scope Decisions

| Risk | In scope v0.2? | Mitigation / Decision |
|------|----------------|----------------------|
| Dynamic routes: `app.include_router(router, prefix=f"/{tenant}")` | Out | Document as known gap. Prefix must be a string literal to be captured. |
| Query builder patterns: `select(User).where(User.id == id)` with chained calls | Partial | Strategy 1 catches the outer `session.execute(select(Model))` call; chained `.where()` is ignored. Accuracy sufficient for route-to-table identification. |
| ORM lazy loading: `user.orders` attribute access emitting SELECT | Out | No call site exists statically. Document; note that eager-load patterns (`.options(joinedload(...))`) are also not captured. |
| Monorepo: separate `frontend/` and `backend/` roots | In | `run_dataflow_pass` operates on the full store built from both roots. Graph builder already handles multi-root; no change needed. |
| Next.js API routes (`app/api/**/route.ts`, `pages/api/**.ts`) | Out | Deferred to v0.3. These are pure TypeScript files with a different convention (exported `GET`, `POST` functions). A `NextJSRouteExtractor` in v0.3 will handle them. |
| TypeScript path aliases (`tsconfig paths: @/components → src/components`) | Out | URL strings are literals or templates; they do not go through TS module resolution. No impact on FETCH_CALL extraction. |
| `axios` instance with `baseURL` configuration | Partial | If the base URL is a string literal in the same file, the normalizer can strip it. If it comes from env var or a separate config file, the path remains unresolved. Document. |
| Multiple FastAPI `app` instances | In | Router variable name captured in ROUTE `metadata.router_var`; no disambiguation needed for v0.2 since we extract all decorated functions regardless of which app they belong to. |
| SQLAlchemy `async_sessionmaker` / `AsyncSession` | In | Same tree-sitter patterns apply. `await session.execute(select(Model))` — the `call` node structure is identical; `await` wraps the outer call but does not change argument positions. |
| Response serialization path (ORM → Pydantic schema → JSON) | Out | `response_model` is captured in ROUTE metadata but the serializer → response edge is not traced. The chain ends at TABLE. |
| Type **inference** for unannotated params | Out | DF0 captures annotation text only. Inference is v0.3 (see PLAN_V0_2_PARAMETERS §7). |
| Argument flow through `*args` / `**kwargs` spreads | Out | Parser records placeholders `*expr` / `**expr`; the actual value-flow is not reconstructed. |
| Role classification false positives (e.g. `*Service` class that isn't a service) | Accepted | Heuristics are documented; the role is metadata, not a hard constraint. Engineers can override via comment / config in v0.3. |

---

## 11. Success Metric

**Target**: on a real sample app, the trace from a frontend button to a DB table
is visible end-to-end, with >= 80% of legitimate fetch calls matched to their
backend route, **and every CALLS edge in the trace carries non-empty `args` or
`kwargs` metadata**.

### Reference repository

`github.com/tiangolo/full-stack-fastapi-template` (previously
`full-stack-fastapi-postgresql`). This repo contains:
- FastAPI backend with `APIRouter` routes
- React frontend with `fetch` calls to `/api/v1/*`
- SQLAlchemy models

### Measurement procedure

1. `git clone https://github.com/tiangolo/full-stack-fastapi-template`
2. `cd full-stack-fastapi-template && codegraph build`
3. `codegraph dataflow stats` → captures `fetch_calls_total`, `matched`, `unmatched`, role counts.
4. Manual audit: inspect the `unmatched` list. Mark each as:
   - True negative (dynamic/env URL, legitimately unresolvable)
   - False negative (should have matched, normalizer failed)
5. Adjusted match rate = `matched / (matched + false_negatives)`.

**Pass thresholds**:
- Adjusted match rate >= 80%.
- >= 95% of FUNCTION/METHOD nodes carry a non-empty `params` list (DF0
  coverage check).
- All four roles (HANDLER, SERVICE, COMPONENT, REPO) have at least one tagged
  node.

**Trace completeness check**:
- Run `codegraph dataflow trace --from "LoginPage" --to "user"` (or equivalent
  component and table names from that repo).
- Pass if the output chain contains at least one node from each layer:
  COMPONENT, FETCH_CALL, ROUTE, FUNCTION, TABLE.
- Pass if every CALLS edge in the chain has non-empty `args` or `kwargs`.

### Automated regression

Add `tests/test_dataflow_integration.py` which runs against
`tests/fixtures/dataflow_sample/` (controlled fixture, not the real repo) and
asserts:
- `match_rate = matched / total_fetch_calls >= 0.8`
- `trace("LoginForm", "users")` returns a path of length >= 3
- Every CALLS edge in that path has `args` or `kwargs` populated
- All four roles are represented in the fixture graph

The full-stack-fastapi-template measurement is a manual release gate, not a CI
check (it requires cloning an external repo).

---

## Files to Create

New source files, all under `/media/mochan/Files/projects/codegraph/`:

| File | Purpose | Phase |
|------|---------|-------|
| `codegraph/dataflow/__init__.py` | Package marker | DF1 |
| `codegraph/dataflow/pipeline.py` | Orchestrator: runs all three extractors then stitcher | DF1 |
| `codegraph/dataflow/extractors/__init__.py` | Package marker | DF1 |
| `codegraph/dataflow/extractors/fastapi.py` | ROUTE + HANDLES extraction | DF1 |
| `codegraph/dataflow/extractors/sqlalchemy.py` | MODEL, TABLE, READS_FROM, WRITES_TO | DF1 |
| `codegraph/dataflow/extractors/roles.py` | DF1.5 — role classification | DF1.5 |
| `codegraph/dataflow/extractors/react.py` | COMPONENT, FETCH_CALL, RENDERS, TRIGGERED_BY | DF2 |
| `codegraph/dataflow/stitcher.py` | URL normalization + MATCHES edge emission + shape tiebreaker | DF3 |
| `codegraph/dataflow/trace.py` | BFS path finder for CLI trace command | DF4 |
| `tests/fixtures/dataflow_sample/` | Fixture app (8 backend + 3 frontend files per §8) | DF1-2 |
| `tests/fixtures/parameters_sample/` | Parser-level parameter fixtures (Python + TS) | DF0 |
| `tests/test_dataflow_fastapi.py` | Unit tests for FastAPI extractor | DF1 |
| `tests/test_dataflow_sqlalchemy.py` | Unit tests for SQLAlchemy extractor | DF1 |
| `tests/test_dataflow_roles.py` | Unit tests for role classifier | DF1.5 |
| `tests/test_dataflow_react.py` | Unit tests for React extractor | DF2 |
| `tests/test_dataflow_stitcher.py` | Unit tests for URL matcher + shape tiebreaker | DF3 |
| `tests/test_dataflow_integration.py` | End-to-end build + trace on fixture | DF4 |
| `tests/test_parameters_python.py` | DF0 — Python parser parameter capture | DF0 |
| `tests/test_parameters_typescript.py` | DF0 — TS parser parameter capture | DF0 |

## Files to Modify

| File | Change | Phase |
|------|--------|-------|
| `codegraph/parsers/python.py` | DF0 — capture `args`/`kwargs` on call edges, `params`/`returns` on def nodes | DF0 |
| `codegraph/parsers/typescript.py` | DF0 — same capture for TS/JS call_expression and formal_parameters | DF0 |
| `codegraph/graph/schema.py` | Add 5 NodeKind values, 7 EdgeKind values; document new metadata keys | DF1 |
| `codegraph/graph/builder.py` | Call `run_dataflow_pass` after `resolve_unresolved_edges` | DF1 |
| `codegraph/cli.py` | Add `dataflow_app` Typer sub-app with `trace`, `visualize`, `stats` (Args + Role columns) | DF4 |
| `codegraph/mcp_server/server.py` | Add `tool_dataflow_trace` returning per-hop `params`/`args`; extend `find_symbol` with `role` filter | DF1.5 + DF4 |
| `codegraph/viz/explore.py` | Add `_render_dataflow_page` with Sankey arg-name labels and payload side panel | DF4 |
| `codegraph/web/3d/*` (HLD payload + edge label) | Surface DF0 `params`/`args`/`kwargs` in 3D view | DF0 |

---

## 12. Ship vs Defer

| Capability                                              | v0.2 | Deferred |
|---------------------------------------------------------|:----:|:--------:|
| DF0 — args/kwargs on CALLS edges                        | ✅   |          |
| DF0 — params/returns on FUNCTION/METHOD/CLASS           | ✅   |          |
| DF1 — FastAPI ROUTE + HANDLES extraction                | ✅   |          |
| DF1 — SQLAlchemy MODEL / TABLE / READS_FROM / WRITES_TO | ✅   |          |
| DF1.5 — HANDLER role tagging                            | ✅   |          |
| DF1.5 — SERVICE role tagging (incl. NestJS @Injectable) | ✅   |          |
| DF1.5 — COMPONENT role tagging (function + class)       | ✅   |          |
| DF1.5 — REPO role tagging                               | ✅   |          |
| DF2 — React fetch/axios FETCH_CALL extraction           | ✅   |          |
| DF2 — body_keys parsed from request-init object literal | ✅   |          |
| DF3 — URL exact + prefix-strip matching                 | ✅   |          |
| DF3 — argument-shape tiebreaker                         | ✅   |          |
| DF4 — `codegraph dataflow trace` CLI                    | ✅   |          |
| DF4 — Sankey dashboard with arg-name edge labels        | ✅   |          |
| DF4 — payload side panel with missing/extra arg diff    | ✅   |          |
| DF4 — MCP `dataflow_trace` tool with per-hop payload    | ✅   |          |
| Next.js `app/api/**/route.ts` extractor                 |      | v0.3     |
| `useFetch` / `useQuery` custom hook detection           |      | v0.3     |
| Type **inference** (Mypy/Pyright/TSC integration)       |      | v0.3     |
| Return-value flow tracing                               |      | v0.3     |
| Mutation tracking                                       |      | v0.3     |
| Flow-sensitive (branch-aware) argument tracking         |      | v0.3     |
| ORM lazy-load → SELECT edge inference                   |      | v0.3     |
| Pydantic serializer → response chain past TABLE         |      | v0.3     |
| Async-task / Promise.all argument tracing               |      | v0.3     |
| Role override config / comment annotation               |      | v0.3     |
