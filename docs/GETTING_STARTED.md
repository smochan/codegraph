# Getting started

One-page guide for cloning `codegraph`, getting it running, and pointing it
at a repo. If anything is unclear, the README and `CONTRIBUTING.md` go
deeper.

---

## 1. Clone and install

```bash
git clone https://github.com/smochan/codegraph.git
cd codegraph

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Optional: enable the embedding layer (`semantic_search` / `hybrid_search`
MCP tools, `codegraph embed` CLI):

```bash
pip install -e ".[embed]"
```

This pulls in `sentence-transformers` and `lancedb` (~150 MB). Skip if you
don't need it — codegraph works fully without it.

## 2. Run against your project

From any repo's root:

```bash
codegraph init                # interactive setup (one-time)
codegraph build --no-incremental
codegraph analyze
codegraph serve               # web dashboard at http://127.0.0.1:8765
```

The first build parses every file with tree-sitter; subsequent runs are
incremental.

## 3. Try the cross-stack demo

```bash
codegraph build --no-incremental --root examples/cross-stack-demo
codegraph analyze
codegraph dataflow trace "GET /api/users/{user_id}"
```

You should see a chain like:

```
Flow trace from: GET /api/users/{user_id}  (confidence: 1.00)

  [backend] backend/api/routes/users.py:17  backend.api.routes.users.get_user  HANDLER
              GET /api/users/{user_id}
              args: (user_id)
   ↓
  [backend] backend/api/routes/users.py:10  backend.api.routes.users._get_service
   ↓
  [backend] backend/services/user_service.py:5  backend.services.user_service.UserService  SERVICE
```

Or run `codegraph serve` and open the **Architecture** tab → click any
endpoint → **Learn Mode** → Phase 4 shows the same chain visually with
the `user_id` parameter highlighted as it travels through every hop.

## 4. Use with an AI client (Claude Code, Cursor, Codex, …)

Each MCP-compatible client reads codegraph the same way; only the config
file format differs. See the README's
[Use with MCP-compatible AI clients](../README.md#use-with-mcp-compatible-ai-clients)
section for exact JSON / TOML per client.

Once connected, you can ask:

> *"Trace what happens when a user clicks the button that fetches `/api/users/42`."*
>
> *"Which functions have the highest blast radius in the auth module?"*
>
> *"List the HANDLER nodes that don't have tests."*
>
> *"Are there any import cycles in this PR?"*

## 5. Contribute

Read [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — covers the local pre-PR
review script, what CI checks, commit / PR conventions, and the merge
process. Branch protection on `main` means every change goes through a PR.

The dogfood loop: every PR opened against `main` runs `codegraph review`
on itself and posts the diff as a sticky comment. Run
`./scripts/test-pr-review-locally.sh` before pushing to see the exact
review locally.
