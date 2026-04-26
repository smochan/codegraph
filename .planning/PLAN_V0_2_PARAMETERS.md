# v0.2 Parameter Capture & Argument-Level Data Flow

## 1. Why

Today every `CALLS` edge in the graph is opaque: it tells us "function A calls
function B" but not what data crossed the boundary. The user feedback on the
0.1.0 release was clear:

> "I can see which functions call which. I want to see *what data* is flowing —
> argument names, types, the actual payload at each hop."

v0.2 closes that gap. We extend the schema so every call edge carries the
positional and keyword arguments at the call site as text, and every
function/method node carries its parameter list (name + annotation text +
default text). This unlocks:

- 3D edge labels that read `(user_id, role)` instead of just `→`.
- Cross-stack tracing (DF0–DF4) that shows the request body shape flowing from
  React → fetch → FastAPI handler → service → SQLAlchemy.
- An MCP `dataflow_trace` tool whose output is dense enough for an LLM to reason
  about how a value mutates through a chain.

This is **text-only capture**. No type inference, no flow analysis. We record
what the source code literally says. Inference is a v0.3 problem.

---

## 2. Data Model — Schema Extension

No new `NodeKind` or `EdgeKind` values. Everything fits in `metadata`.

### 2.1 `Edge.metadata` additions (CALLS edges only)

| Key      | Type                | Meaning |
|----------|---------------------|---------|
| `args`   | `list[str]`         | Positional argument expression text at the call site, in order. Each element is the source-text of one positional argument, normalized (see §3). |
| `kwargs` | `dict[str, str]`    | Keyword argument expression text, keyed by parameter name. Values are normalized expression text. |

Existing edge metadata (`line`, `target_name`, etc.) is preserved. `args` and
`kwargs` are both optional — old edges remain valid; new edges populate both.

### 2.2 `Node.metadata` additions (FUNCTION / METHOD / CLASS-init nodes)

| Key       | Type                                                                              | Meaning |
|-----------|-----------------------------------------------------------------------------------|---------|
| `params`  | `list[{name: str, type: str \| None, default: str \| None}]`                      | Parameter list from the def signature, in declaration order. Each entry has the param name, the annotation text (or `None` if absent), and the default expression text (or `None` if absent). |
| `returns` | `str \| None`                                                                     | Return-type annotation text. `None` when no annotation is present. |

For CLASS nodes we attach `params` derived from the `__init__` (Python) or
`constructor` (TS) signature, so callers of `Foo(...)` see the right shape.

### 2.3 Worked example

Source:

```python
def login(user_id: int, role: str = "user") -> Token:
    return issue_token(user_id, role=role)
```

Resulting graph:

```
Node FUNCTION login:
  metadata.params  = [
    {"name": "user_id", "type": "int", "default": null},
    {"name": "role",    "type": "str", "default": "\"user\""}
  ]
  metadata.returns = "Token"

Edge CALLS login -> issue_token:
  metadata.args   = ["user_id"]
  metadata.kwargs = {"role": "role"}
```

---

## 3. Parser Work

### 3.1 Python (`codegraph/parsers/python.py`)

**Argument capture — extending the existing call walker.**

When walking a `call` AST node, descend into the `argument_list` child and
process each child:

| Tree-sitter node type            | Handling |
|----------------------------------|----------|
| `identifier`                     | Capture the identifier text verbatim. Append to `args`. |
| `string` / `concatenated_string` | Capture the raw source text including quotes. Append to `args`. |
| `integer` / `float`              | Capture the numeric literal text. Append to `args`. |
| `true` / `false` / `none`        | Capture the keyword text (`"True"`, `"False"`, `"None"`). Append to `args`. |
| `attribute`                      | Capture the full source-text span (e.g. `"self.user.id"`). Append to `args`. |
| `subscript`                      | Capture the full source-text span (e.g. `"users[0]"`). Append to `args`. |
| `keyword_argument`               | Read child `name` (identifier) and `value`. Apply the same rules to `value`. Insert into `kwargs`. |
| anything else (binary_op, lambda, list/dict/set comp, walrus, conditional, …) | Insert the literal placeholder `"<expr>"`. Append to `args` or `kwargs[name]`. |

`*args` and `**kwargs` unpacking spread are recorded as the placeholder
`"*expr"` / `"**expr"` so they don't pollute `args`/`kwargs` ordering.

**Parameter capture — new walk in the function-definition handler.**

For every `function_definition` and `async_function_definition`, walk the
`parameters` child. Each child is one of:

| Tree-sitter node type                        | Captured |
|----------------------------------------------|----------|
| `identifier`                                 | `{name: <text>, type: null, default: null}` |
| `typed_parameter`                            | `name = identifier text`, `type = annotation text`, `default = null` |
| `default_parameter`                          | `name = identifier text`, `type = null`, `default = value source-text` |
| `typed_default_parameter`                    | `name = identifier text`, `type = annotation text`, `default = value source-text` |
| `list_splat_pattern` (`*args`)               | `{name: "*" + ident, type: null, default: null}` |
| `dictionary_splat_pattern` (`**kwargs`)      | `{name: "**" + ident, type: null, default: null}` |

Annotation text is the source-text span of the annotation node (preserves
generics like `dict[str, list[int]]`).

For the `returns` field, look for the `return_type` field on the
`function_definition` node and capture its source-text span (or `None`).

For CLASS nodes, look up the `__init__` method (skip `self`) and copy its
`params` onto the class node so call sites that look like `Foo(...)` resolve to
a meaningful parameter list.

### 3.2 TypeScript / JavaScript (`codegraph/parsers/typescript.py`)

**Argument capture — extending the existing call walker.**

Under `call_expression` walk the `arguments` child. Children are positional;
keyword arguments don't exist in TS. Object-literal first arguments are common
(`fetch(url, { method: "POST", body })`) — those are captured as a single
positional `args[1]` with the full source-text. (Per-property destructuring of
the options object is deferred — see §7.)

| Tree-sitter node type                                      | Handling |
|------------------------------------------------------------|----------|
| `identifier`                                               | Verbatim text. |
| `string` / `template_string`                               | Source text including quotes / backticks. |
| `number` / `true` / `false` / `null` / `undefined`         | Verbatim. |
| `member_expression`                                        | Full source-text span (`"this.user.id"`). |
| `subscript_expression`                                     | Full source-text span. |
| `object` / `array`                                         | Full source-text span (kept for fetch-body shape detection in DF stitcher). |
| spread (`...x`)                                            | Placeholder `"...expr"`. |
| anything else                                              | Placeholder `"<expr>"`. |

Since TS callers don't carry parameter names, `kwargs` is always `{}` for TS
edges. (DF3 stitcher reconstructs a synthetic kwargs map from object-literal
keys; that lives in DF land, not the parser.)

**Parameter capture.**

Under `function_declaration`, `function_expression`, `arrow_function`,
`method_definition`, walk the `formal_parameters` (TS) / `parameter_list` (JS)
child. Each parameter is one of `required_parameter`, `optional_parameter`,
`rest_parameter`. For each:

- `name` = source-text of the binding pattern (identifier, object pattern, or
  array pattern — kept as-is)
- `type` = source-text of `type_annotation` (strip the leading `:`) or `null`
- `default` = source-text of the initializer (after `=`) or `null`

For `returns`, capture the source-text of the function's `return_type`
annotation (after `:`) or `null`. JS files (no annotations) always have
`type = null` and `returns = null`.

For CLASS nodes, copy the `constructor` method's params onto the class node so
`new Foo(...)` resolves correctly.

---

## 4. Type Capture Is Text-Only

We record annotations as **strings** taken verbatim from the source. We do not:

- Resolve `User` to an import — it stays the literal text `"User"`.
- Run Mypy, Pyright, ts-morph, or the TS compiler.
- Infer types for unannotated parameters.
- Normalize `Optional[str]` vs `str | None` vs `Union[str, None]`.

This keeps the v0.2 parser pass deterministic, fast, and free of new
dependencies. The downstream consumers (3D edge labels, MCP, HLD) display the
text as-is. Type inference is a v0.3 concern and explicitly out of scope here.

---

## 5. Visualization Changes

### 5.1 3D Focus-Mode View

- **Edge label (default state, edge expanded):** `arg_names` joined with `, `.
  Example: `(user_id, role)`. Computed from `edge.metadata.args` (positional
  expressions, which for the common identifier case are the names) plus the
  keys of `edge.metadata.kwargs`.
- **Edge tooltip (hover):** full breakdown — positional list with index, kwargs
  list with name/value, and the resolved param list from the destination node
  with type annotations. This is where the "data flow" claim is visibly true.
- **Empty fallback:** if `args` and `kwargs` are both empty/missing, render the
  edge as today (no label).

### 5.2 HLD JSON Payload

Every symbol entry gains:

```json
{
  "params": [{"name": "user_id", "type": "int", "default": null}, ...],
  "returns": "Token | None"
}
```

Every call edge entry gains:

```json
{
  "args": ["user_id"],
  "kwargs": {"role": "role"}
}
```

Backward compatibility: consumers must treat both fields as optional. No
existing field is renamed or removed.

### 5.3 MCP `dataflow_trace` Tool

The hop list returned by `dataflow_trace` includes `params` on every node and
`args`/`kwargs` on every edge. The shape of one hop:

```json
{
  "layer": "Service",
  "kind": "FUNCTION",
  "name": "authenticate_user",
  "file": "backend/services/auth.py",
  "line": 34,
  "params": [
    {"name": "username", "type": "str", "default": null},
    {"name": "password", "type": "str", "default": null}
  ],
  "returns": "User | None",
  "edge_to_next": {
    "kind": "CALLS",
    "args": ["username"],
    "kwargs": {"password": "password"}
  }
}
```

This payload is dense enough for an LLM to reason about whether a parameter is
forwarded, dropped, or transformed at each hop — without needing follow-up
queries.

---

## 6. Test Plan

Fixtures live under `tests/fixtures/parameters_sample/` (Python + TS). Test
files live alongside the existing parser tests.

### Required cases

1. **Positional only** — `foo(a, b)` → `args=["a","b"]`, `kwargs={}`.
2. **Kwargs only** — `foo(a=1, b="x")` → `args=[]`, `kwargs={"a":"1","b":"\"x\""}`.
3. **Mixed** — `foo(user, role=r)` → `args=["user"]`, `kwargs={"role":"r"}`.
4. **Complex expression reduced** — `foo(a + b, [x for x in xs])` →
   `args=["<expr>", "<expr>"]`.
5. **Type-annotated params** — `def f(x: int, y: list[str]) -> bool` →
   `params = [{name:"x",type:"int",...},{name:"y",type:"list[str]",...}]`,
   `returns="bool"`.
6. **Default values** — `def f(x: int = 5, y="abc")` → defaults captured as
   `"5"` and `"\"abc\""`.
7. **Missing annotation** — `def f(x)` → `params[0].type is None`.
8. **No return annotation** — `def f(x): ...` → `returns is None`.
9. **TS required+optional+rest** — `function f(a: number, b?: string, ...rest: number[])`
   covers all three TS parameter kinds.
10. **TS arrow function with destructured object param** — `({ id, name }: Props) => ...`
    captures `name` as the source-text of the binding pattern.
11. **CLASS init copy** — `class User: def __init__(self, id: int)` →
    `User` node carries `params=[{name:"id",type:"int",...}]` (self elided).

Each case asserts shape against a known-good golden dict.

---

## 7. Out of Scope (Defer to v0.3+)

The following are deliberately excluded from v0.2:

- **Return-value tracing.** We capture `returns` annotation text; we do not
  follow how a return value flows into the next call's argument.
- **Mutation tracking.** No analysis of `x.field = ...` or `dict[key] = ...`
  effects on argument shape.
- **Flow-sensitive analysis.** We do not branch on control flow; an argument
  passed inside an `if` is recorded the same as one passed unconditionally.
- **Generic-parameter resolution.** `List[T]` stays as the literal string
  `"List[T]"`; we do not bind `T` to a concrete type.
- **Async-task argument tracing.** `asyncio.create_task(coro(x))`,
  `loop.run_in_executor(...)`, and `Promise.all([...])` are recorded as a
  normal call to the outer function; the inner coroutine's argument flow is
  not reconstructed.
- **Object-literal destructuring for fetch options.** TS `fetch(url, { body })`
  records the options object as one positional `args[1]`; reconstructing it
  into synthetic kwargs is a DF3 (stitcher) concern, not a parser concern.
- **Type inference.** Unannotated params stay `type=null`. Mypy/Pyright/TSC
  integration is v0.3.

---

## 8. Effort Estimate

| Workstream                                | Days |
|-------------------------------------------|------|
| Parser extensions — Python + TS           | 4    |
| Schema + serialization (store, JSON I/O)  | 1    |
| HLD payload extension                     | 1    |
| MCP `dataflow_trace` tool extension       | 1    |
| 3D view edge-label rendering + tooltip    | 2    |
| Tests + fixtures (cases §6.1–§6.11)       | 1    |
| **Total**                                 | **10** |

---

## 9. Ship vs Defer

| Capability                                         | v0.2 | Deferred |
|----------------------------------------------------|:----:|:--------:|
| Positional args text on CALLS edges                | ✅   |          |
| Keyword args text on CALLS edges                   | ✅   |          |
| Param list (name + annotation + default) on nodes  | ✅   |          |
| Return-type annotation text on nodes               | ✅   |          |
| Class init params copied onto CLASS node           | ✅   |          |
| Complex expressions reduced to `<expr>` placeholder| ✅   |          |
| 3D edge labels showing arg names                   | ✅   |          |
| Hover tooltip with full args + types               | ✅   |          |
| HLD JSON includes `params`/`args`/`kwargs`         | ✅   |          |
| MCP `dataflow_trace` returns per-hop payload       | ✅   |          |
| Type **inference** (Mypy/Pyright/TSC)              |      | v0.3     |
| Return-value flow tracing                          |      | v0.3     |
| Mutation tracking                                  |      | v0.3     |
| Flow-sensitive (branch-aware) argument tracking    |      | v0.3     |
| Generic-parameter resolution                       |      | v0.3     |
| Async-task / Promise.all argument tracing          |      | v0.3     |
| Object-literal destructuring → synthetic kwargs    |      | DF3 / v0.3 |
