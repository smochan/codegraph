# PLAN_RESOLVER.md — Cross-File Resolution Fix Plan

**Status:** Draft  
**Target:** Reduce unresolved-edge rate from 61% → <25%  
**Scope:** `codegraph/resolve/calls.py`, `codegraph/parsers/python.py`, `codegraph/parsers/typescript.py`

---

## 1. Current Resolution Flow

### How unresolved edges are created

**`codegraph/parsers/python.py`**

| Location | What happens |
|---|---|
| `_collect_calls` line 329 | Every `call` node emits `dst="unresolved::<full_text_of_function_expression>"` — includes dotted chains like `self.foo.bar`, `obj.method`, `module.func` |
| `_handle_import` line 353 | `import os` or `import a.b` emits `dst="unresolved::os"` / `dst="unresolved::a.b"` |
| `_handle_import_from` line 377 | `from models import Dog` emits `dst="unresolved::models"` — **only the module**, not the imported names `Dog` or `Cat` |
| `_handle_class` line 222 | Base class like `class Dog(Animal)` emits `dst="unresolved::Animal"` via INHERITS edge |

**`codegraph/parsers/typescript.py`**

| Location | What happens |
|---|---|
| `_collect_calls` line 428 | Every `call_expression` emits `dst="unresolved::<full_text>"` including `this.foo`, `obj.method(...)`, chained calls |
| `_handle_import` line 162 | `import { foo } from './utils'` emits `dst="unresolved::./utils"` — only the path string, not the named imports |
| `_handle_class` line 222/237 | INHERITS and IMPLEMENTS edges target `dst="unresolved::<ClassName>"` |

**`codegraph/resolve/calls.py`**

The post-build resolver `resolve_unresolved_edges` (line 182) iterates all edges whose `dst` starts with `unresolved::` and calls `_resolve_target` (line 74) with 7 heuristics in priority order:

1. `self.X` → look up sibling method on enclosing class qualname (line 91-101)
2. Exact qualname match (line 103-107)
3. Same-module prefix: `<src_module>.<target>` (line 109-114)
4. Through IMPORTS bindings: map alias → qualname, then look up (line 116-130)
5. Module-by-qualname (for IMPORTS edges) (line 132-135)
6. Suffix match: any qualname ending with `.target` — only if unique (line 137-143)
7. Bare-name match across full graph — only if globally unique (line 145-149)

**`_build_import_bindings`** (line 154): For each IMPORTS edge from a MODULE node, takes `target_name` from edge metadata, strips leading `./` and `.`, replaces `/` with `.`, maps `leaf → normalized` and `normalized → normalized`. This is the only source of import alias data for the resolver.

**`codegraph/graph/store_networkx.py` line 18**: `to_digraph` calls `g.add_edge(edge.src, edge.dst, ...)`. When `edge.dst` is `"unresolved::something"`, NetworkX auto-creates a phantom node with no attributes. `metrics.py:29` then labels these nodes `kind="UNKNOWN"`. The 872 "UNKNOWN nodes" are phantom nodes, not a separate NodeKind — they are a symptom of unresolved edges, not a separate bug.

---

## 2. Categorization of Unresolved Cases

### Category A — Dotted attribute calls (est. 35-40% of unresolved edges)

**Example:** `Dog.fetch` calls `self.speak()` (python_sample/models.py:24), `Greeter.render` calls `this.props.firstName` and `formatName(...)` (ts_sample/Component.tsx:11).

**How created:** `_collect_calls` extracts the full text of the function expression including attribute chains. `self.speak` is handled by resolver heuristic 1. But `obj.method` where `obj` is a local variable, and `this.props.X` chains, fall through to heuristic 7 (bare-name) which only fires if globally unique.

**Unresolved when:** `self.foo.bar()` — heuristic 1 only strips one level of `self.`, so `self.foo.bar` becomes target `foo.bar`, not `ClassName.bar`. Also `module.Class.method()` — the head `module` resolves through imports but the full `module.Class.method` chain is not walked.

**Root cause in resolver:** `_resolve_target` line 97-101: strips `self.` then does a single-level lookup `class_qual + "." + rest`. If `rest` itself is dotted (e.g. `foo.bar`), it looks up `ClassName.foo.bar` which does not exist as a qualname.

### Category B — Python relative imports (est. 15-20% of unresolved edges)

**Example:** `from . import utils`, `from ..pkg import helpers`, `from .models import Animal`.

**How created:** `_handle_import_from` (python.py line 362-384): when `child.type == "relative_import"`, it captures the raw text including leading dots (e.g. `". "` or `"..pkg"`). This becomes `target_name` in edge metadata.

**`_build_import_bindings`** (calls.py line 172-173): `normalized = target.replace("\\", "/").lstrip("./")`. For `from . import utils` the module_name captured is just `"."` (only dots, no name), so after `lstrip("./")` it becomes empty string — the binding is skipped (line 175: `if not normalized: continue`). For `from .models import Dog`, the module_name captured is `"."` (just the relative_import node), not `".models"`.

**Root cause in python.py:** `_handle_import_from` (line 362-384) only captures the `relative_import` or `dotted_name` as the module name, losing the actual module part and never capturing the individual imported names (`Dog`, `Cat`). A `from .models import Dog` statement should produce `target_name="<resolved_package>.models"` and bind `Dog` as an alias.

**Root cause in resolver:** `_build_import_bindings` discards empty normalized targets but does not use file path + relative level to resolve the actual module qualname.

### Category C — TS path aliases via tsconfig (est. 5-10% of unresolved edges)

**Example:** `import { foo } from '@/utils'`, `import bar from '~/lib/bar'`.

**How created:** `_handle_import` emits `dst="unresolved::@/utils"`. `_build_import_bindings` normalizes by stripping `./`, so `@/utils` becomes `@/utils` (the `@` is not stripped). The resolver heuristics never match.

**Root cause:** No tsconfig.json parsing. No `@` or `~` prefix handling in `_build_import_bindings`.

### Category D — Named imports not tracked (est. 20-25% of unresolved edges)

**Example:** `from models import Cat, Dog` in python_sample/utils.py. `import { formatName } from './utils'` in ts_sample/Component.tsx.

**How created (Python):** `_handle_import_from` (python.py line 362-384) only emits ONE IMPORTS edge for the source module, ignoring the individual names. When later code calls `Dog(name)`, the resolver sees target `Dog`, checks import bindings for `src_module`, finds binding `models → models`, tries `models.Dog` — this would work IF the qualname is `models.Dog`. But the fixture uses `from models import Cat, Dog` with relative-path module. The module qualname in the graph is `pkg.models` (from the repo root), not `models`.

**How created (TS):** `_handle_import` (typescript.py line 147-169) captures only the source path `'./utils'`, not the named imports `{ formatName }`. Resolver gets `target_name="./utils"`, `_build_import_bindings` maps `utils → utils`. When `formatName(...)` is called, target is `formatName`, binding lookup finds nothing for key `formatName` (only `utils` is bound).

**Root cause:** Both parsers need to also store the imported names (named imports) in the binding so `formatName` resolves to `utils.formatName`.

### Category E — Decorator calls (est. 3-5% of unresolved edges)

**Example:** `@dataclass`, `@property`, `@staticmethod`, `@pytest.mark.parametrize`.

**How created:** Decorators are captured as text by `_get_function_decorators` (python.py line 49) and stored in `metadata["decorators"]` but NOT emitted as CALLS edges. However, `_visit_block` also processes `decorated_definition` nodes (python.py line 134-151) and calls `_handle_function`, which calls `_collect_calls` on the body. The body walker does not walk the decorator nodes themselves for call edges.

**Status:** This is NOT generating unresolved edges — decorators are stored in metadata only. Low priority. Skip.

### Category F — Instance method calls through variables (est. 10-15% of unresolved edges)

**Example:** `result = path.read_text()` (utils.py line 17), `dog = Dog("Rex"); dog.speak()` (test_models.py line 8-9).

**How created:** `_collect_calls` captures `path.read_text` as the full name. Target is `path.read_text`. The resolver: heuristic 1 fails (no `self.`), heuristic 2 fails (no qualname `path.read_text`), heuristic 3 fails, heuristic 4 fails (no `path` in import bindings), heuristic 6 fails (not unique), heuristic 7 — bare name `read_text` may be unique or not. These generally stay unresolved unless the class name happens to be globally unique.

**Root cause:** No type inference. Fixing fully requires data-flow analysis. Partial fix: for known local variable assignments of the form `x = ClassName(...)`, the first segment of the call could be resolved.

---

## 3. Proposed Fixes, Ordered by ROI

### Fix R1a — Track named imports in Python (Category D, Python side)

**File:** `codegraph/parsers/python.py`  
**Function:** `_handle_import_from` (line 362-384)  
**Change:** After capturing the module name, iterate children again to find `import_from_names` / `dotted_name` / `identifier` children that represent the imported names. Emit an additional edge per name with `metadata={"target_name": "<module>.<name>", "imported_name": "<name>"}`.

Pseudo-diff:
```
# current: emits one edge with target_name = module string
# new: also walk the `name` children
for child in node.children:
    if child.type in ("import_list", "import_from_names"):
        for name_child in child.children:
            if name_child.type in ("identifier", "dotted_name"):
                name = node_text(name_child, src)
                edges.append(Edge(
                    src=parent_id,
                    dst=f"unresolved::{module_name}.{name}",
                    kind=EdgeKind.IMPORTS,
                    file=rel, line=...,
                    metadata={"target_name": f"{module_name}.{name}", "imported_name": name},
                ))
```

Also update `_build_import_bindings` in `calls.py`: when `metadata["imported_name"]` is present, also bind `imported_name → full_qualname` in the module's bindings dict so the resolver can find `Dog` → `models.Dog`.

**Estimated ROI:** Resolves the named-import → call chain for all `from X import Y; Y()` patterns. Est. 20-25% of unresolved edges.

### Fix R1b — Track named imports in TypeScript (Category D, TS side)

**File:** `codegraph/parsers/typescript.py`  
**Function:** `_handle_import` (line 147-169)  
**Change:** After extracting the source string, walk the `import_clause` / `named_imports` / `import_specifier` children to extract individual imported names. For each name, emit an additional IMPORTS edge with `metadata={"target_name": "<source>.<name>", "imported_name": "<name>"}`.

Pseudo-diff:
```
# walk named imports
clause = node.child_by_field_name("import_clause") or ...
for specifier in named_import_children(clause):
    name = node_text(specifier, src)
    edges.append(Edge(
        src=parent_id,
        dst=f"unresolved::{source}.{name}",
        kind=EdgeKind.IMPORTS, ...,
        metadata={"source": source, "target_name": f"{source}.{name}", "imported_name": name},
    ))
```

**Estimated ROI:** Resolves `formatName(...)` → `ts_sample.utils.formatName` pattern. Est. 10-15% of TS unresolved edges.

### Fix R1c — Fix relative import resolution in Python (Category B)

**File:** `codegraph/parsers/python.py`  
**Function:** `_handle_import_from` (line 362-384)  
**Change:** When `child.type == "relative_import"`, count the dots to get `level`, and find the subsequent `dotted_name` sibling to get the relative module name. Compute absolute module qualname from `rel` (current file) + `level` (dots) + relative module name.

**File:** `codegraph/resolve/calls.py`  
**Function:** `_build_import_bindings` (line 154-179)  
**Change:** If target starts with `.` after lstrip-check fails, fall back to using the edge `file` attribute to compute the containing package qualname, then resolve the relative path.

Pseudo-diff (parsers/python.py):
```
# inside _handle_import_from when relative_import child found:
dots = node_text(relative_import_child, src).count(".")
pkg_parts = _file_to_qualname(rel).split(".")[:-dots]  # go up `dots` levels
rel_module_name = node_text(next_dotted_name_sibling, src) if sibling else ""
abs_module = ".".join(pkg_parts + ([rel_module_name] if rel_module_name else []))
# emit edge with target_name = abs_module
```

**Estimated ROI:** Resolves `from . import X` and `from .module import Y` patterns. Est. 10-15% of unresolved edges on typical packages.

### Fix R1d — Deepen self.foo.bar resolution (Category A)

**File:** `codegraph/resolve/calls.py`  
**Function:** `_resolve_target` (line 74-151)  
**Change:** At heuristic 1 (line 91-101), after stripping `self.`, if `rest` contains a dot, split on the first dot: `method_name = rest.split(".")[0]`. Look up `class_qual.method_name` to find if it's a known attribute/method. If not resolvable to an in-graph node, set `target = method_name` (just the first segment) and fall through to remaining heuristics instead of dropping to bare-name.

This is a safe narrowing: for `self.foo.bar()` we at least resolve to the method `foo` if `bar` is too ambiguous.

**Estimated ROI:** Reduces dangling `self.X.Y` calls. Est. 5-8% of unresolved edges.

### Fix R2a — Resolve TS relative import paths to module nodes (Category C partial)

**File:** `codegraph/resolve/calls.py`  
**Function:** `_build_import_bindings` (line 154-179)  
**Change:** When `target_name` starts with `./` or `../`, use the edge `file` attribute to compute the absolute module qualname. Normalize `./utils` relative to `ts_sample/Component.tsx` → `ts_sample.utils`. Then bind both `utils` and `ts_sample.utils` in the module's bindings.

Pseudo-diff:
```
# in _build_import_bindings, before lstrip:
if target.startswith("./") or target.startswith("../"):
    if edge.file:
        from_pkg = edge.file.replace("/", ".").rsplit(".", 1)[0]  # strip extension
        from_dir = ".".join(from_pkg.split(".")[:-1])
        abs_module = _resolve_relative_path(from_dir, target)
        leaf = abs_module.rsplit(".", 1)[-1]
        bindings[src_node.id][leaf] = abs_module
        bindings[src_node.id][abs_module] = abs_module
        continue
```

Add helper `_resolve_relative_path(from_dir: str, rel_path: str) -> str` that handles `./X` → `from_dir.X` and `../X` → parent-of-from_dir.X.

**Estimated ROI:** Resolves same-package TS imports like `from './utils'`. Est. 8-12% of TS unresolved edges.

### Fix R2b — TS path alias support via tsconfig (Category C)

**File:** `codegraph/graph/builder.py`  
**New function:** `_load_tsconfig_paths(repo_root: Path) -> dict[str, str]`  
Parse `tsconfig.json` at repo root (and any `tsconfig.*.json`). Extract `compilerOptions.paths`. Map each alias pattern (e.g. `@/*`) to its first target path (e.g. `./src/*`). Store as `{alias_prefix: resolved_prefix}`.

**File:** `codegraph/graph/builder.py`, `build()` method  
Pass tsconfig paths into `resolve_unresolved_edges` as an optional kwarg.

**File:** `codegraph/resolve/calls.py`  
**Function:** `_build_import_bindings`  
Accept `path_aliases: dict[str, str]` kwarg. For each import target that matches an alias prefix, rewrite to the resolved path before normalization.

**Estimated ROI:** Resolves `@/X`, `~/X`, `#X` style imports. Only applies to TS repos using path aliases. Est. 5-10% of TS unresolved edges in affected repos. Medium effort.

### Fix R3 — Partial type inference for variable-bound calls (Category F)

**File:** `codegraph/parsers/python.py`  
**New helper:** `_collect_assignments(body, src) -> dict[str, str]`  
Walk a function body for `assignment` nodes of the form `name = CallExpr(...)`. For each, record `{local_var_name: constructor_name}`. Pass this mapping into `_collect_calls`.

**File:** `codegraph/parsers/python.py`  
**Function:** `_collect_calls` (line 309-336)  
When a call target starts with `known_local.`, replace `known_local` with `constructor_name` before emitting the unresolved edge.

**Estimated ROI:** Resolves `dog = Dog("Rex"); dog.speak()` → `Dog.speak`. High LOC cost for moderate gain. Est. 5-8% when patterns are common. Defer to R3 phase.

---

## 4. Phased Plan

### Phase R1 — Quick wins (1 day)

**Goal:** Reduce unresolved rate from 61% → ~35%

| Task | File | Function | LOC estimate |
|---|---|---|---|
| R1a: Python named imports tracking | `parsers/python.py` | `_handle_import_from` | ~20 |
| R1a cont.: bindings update | `resolve/calls.py` | `_build_import_bindings` | ~10 |
| R1b: TS named imports tracking | `parsers/typescript.py` | `_handle_import` | ~25 |
| R1c: Python relative import resolution | `parsers/python.py` | `_handle_import_from` | ~25 |
| R1d: Deepen self.X.Y resolution | `resolve/calls.py` | `_resolve_target` heuristic 1 | ~10 |

**Total R1:** ~90 LOC of changes

**Acceptance gate:** `store.count_unresolved_edges() / store.count_edges() < 0.35` on `codegraph`'s own graph.

### Phase R2 — Medium work (1 day)

**Goal:** Reduce unresolved rate from ~35% → ~20%

| Task | File | Function | LOC estimate |
|---|---|---|---|
| R2a: TS relative path resolution | `resolve/calls.py` | `_build_import_bindings` + new `_resolve_relative_path` | ~40 |
| R2b: tsconfig path alias parsing | `graph/builder.py` + `resolve/calls.py` | `_load_tsconfig_paths`, `resolve_unresolved_edges` | ~60 |

**Total R2:** ~100 LOC of changes

**Acceptance gate:** `< 0.25` unresolved rate on `codegraph`'s own graph.

### Phase R3 — Hard cases (deferred / 1+ day)

**Goal:** Reduce from ~20% → <15%

| Task | File | Complexity |
|---|---|---|
| R3a: Variable-bound call resolution | `parsers/python.py`, `resolve/calls.py` | High — requires local scope tracking |
| R3b: Cross-package import chains | `resolve/calls.py` | High — multi-hop resolution |
| R3c: TS re-export tracking (`export { X } from './y'`) | `parsers/typescript.py`, `_handle_import` | Medium |
| R3d: TS `export_statement` with source string | `parsers/typescript.py`, `_visit` line 126 | Medium — currently export_statement only recurses into decls, not re-export strings |

---

## 5. Verification Strategy

### Existing tests that cover the regression surface

| Test file | Coverage |
|---|---|
| `tests/test_resolve.py` | `resolve_unresolved_edges`, self-method resolution, imported-call resolution, idempotency |
| `tests/test_extractor_python.py` | Import edges, CALLS edges, INHERITS edges |
| `tests/test_extractor_typescript.py` | Import edges, CALLS edges, INHERITS edges |
| `tests/test_builder.py` | Full build pipeline, incremental build |

### New tests to add

**`tests/test_resolve.py` additions:**

1. `test_resolver_resolves_named_import_call` — Python: `from models import Dog; Dog("x")` → CALLS edge to `models.Dog` not `unresolved::Dog`.
2. `test_resolver_resolves_relative_import` — fixture with `from .models import Animal` in a sub-package, verify IMPORTS edge dst resolves to the sibling module.
3. `test_resolver_resolves_ts_relative_import` — TS: `import { formatName } from './utils'` then `formatName(...)` call resolves to `ts_sample.utils.formatName`.
4. `test_resolver_resolves_self_dotted_chain` — Python: `self.validator.validate()` → resolves at least to the `validator` method if `validate` is ambiguous.

**`tests/fixtures/` additions:**

- `tests/fixtures/py_relative_import/pkg/__init__.py` (empty)
- `tests/fixtures/py_relative_import/pkg/models.py` (class `Foo`)
- `tests/fixtures/py_relative_import/pkg/service.py` (`from .models import Foo; Foo()`)
- `tests/fixtures/ts_alias/tsconfig.json` (with `paths: { "@/*": ["./src/*"] }`)
- `tests/fixtures/ts_alias/src/utils.ts` (export function)
- `tests/fixtures/ts_alias/src/app.ts` (`import { fn } from '@/utils'`)

### Target unresolved-edge rates

| After phase | Target unresolved rate | Notes |
|---|---|---|
| Baseline | 61% | Current state |
| After R1 | < 35% | Named imports + relative imports + self chain |
| After R2 | < 25% | TS relative paths + tsconfig aliases |
| After R3 | < 15% | Variable binding + re-exports |

---

## 6. Risks

### Regression risks

- **R1a/R1b named import edges**: Adding extra IMPORTS edges per named import increases edge count. Analyses that aggregate by IMPORTS kind will see more edges — verify `test_analysis.py`, `test_review_rules.py`. The resolver idempotency test (`test_resolver_idempotent`) must still pass.
- **R1c relative import resolution**: The `_file_to_qualname` helper in `python.py` encodes the repo-relative path, but `_handle_import_from` only has `rel` (repo-relative). If the fixture is loaded with `repo_root=FIXTURE_DIR` (as in tests), the package prefix differs from loading with `repo_root=tests/fixtures`. Ensure test fixtures use consistent `repo_root`.
- **R2a relative TS path resolution**: `edge.file` is the file of the import statement, which is correct. But `_build_import_bindings` currently only receives `edges: list[Edge]` — the `file` field is present on Edge (schema.py line 55). Verify all IMPORTS edges have `file` set (they do — parsers set it to `rel`).
- **R1d self-chain**: Changing heuristic 1 to fall-through instead of dead-end could cause false-positive resolutions if a method name like `foo` exists in multiple classes. The suffix-uniqueness check (heuristic 6) provides a guard, but add a test to confirm no spurious CALLS edges appear.

### Hard cases to defer

- **stdlib / third-party imports**: `import os`, `from pathlib import Path` will never resolve to in-graph nodes. These will always be unresolved. Accepting ~10-15% permanent unresolved rate for external symbols is correct behavior. Do NOT create stub nodes for stdlib.
- **Dynamic calls**: `getattr(obj, method_name)()`, `func = locals()[name]()` — cannot resolve without runtime. Defer entirely.
- **Circular re-exports**: `a.py` re-exports from `b.py` which re-exports from `c.py`. Multi-hop chains require fixed-point iteration in `_build_import_bindings`. Defer to R3.
- **`__init__.py` aggregation**: A package `pkg/__init__.py` that does `from .models import Dog` makes `Dog` available as `pkg.Dog`. The resolver does not trace through `__init__` re-exports. This is a significant source of unresolved edges in well-structured Python packages. Partially addressed by R1c but full fix requires walking `__init__` IMPORTS chains. Defer to R3.

### What's hard

- tsconfig.json path alias parsing (R2b) requires JSON parsing with comment stripping (tsconfig allows JS comments) and glob pattern matching for multi-segment aliases.
- Variable-type inference (R3a) is a slippery slope — stopping at single-level assignments is safe, but any deeper analysis risks false positives and adds significant complexity.
