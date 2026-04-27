# Benchmarking codegraph against LLM-only / embedding-only baselines

## 1. Top recommendation (one sentence)

Run **SWE-bench Lite (300 issues, Python)** with the **Agentless** harness in two configurations — (a) Agentless baseline, (b) Agentless + codegraph-MCP — and target a **+2 to +4 absolute resolve-rate gain**, matching or beating the published RepoGraph result of +2.34% on the same cell ([RepoGraph, ICLR 2025](https://arxiv.org/html/2410.14684v1)).

Why this cell: RepoGraph already proved that a tree-sitter call/reference graph plugged into Agentless's localization step measurably moves the needle. Codegraph is **structurally a superset** of RepoGraph (CALLS + IMPORTS + INHERITS + signatures + roles + cycles + dead-code), so we have a defensible "improved structural retriever" story rather than competing on raw model quality.

## 2. Survey of candidate benchmarks

| Benchmark | Scope | Metric | Size | Run cost | codegraph signal? | URL |
|---|---|---|---|---|---|---|
| **SWE-bench Lite** | real GH issues, Py | resolve-rate (test pass) | 300 | local Docker + ~$30–80 in API | **High** — proven by RepoGraph | [swebench.com](https://www.swebench.com/lite.html) |
| SWE-bench Verified | filtered Py | resolve-rate | 500 | $100–300 in API | High, but more contaminated | [swebench.com/verified](https://www.swebench.com/verified.html) |
| SWE-bench Multilingual | 9 languages | resolve-rate | 300 | $50–150 | High for TS slice; Py+TS is exactly our parser coverage | [swebench.com/multilingual](https://www.swebench.com/multilingual.html) |
| SWE-Bench Pro / Live | newer, decontaminated | resolve-rate | 500 / rolling | $$$ | High, but contam-resistant — better headline | [swebench-live](https://swe-bench-live.github.io/) |
| **CrossCodeEval** | cross-file completion Py/Java/TS/C# | EM, Edit-Sim, ID-F1 | 9,928 | local, no agent loop, cheap | **High** — TS+Py overlap our parsers; cross-file is the exact thing call graph fixes | [crosscodeeval.github.io](https://crosscodeeval.github.io/) |
| RepoBench-R / -P | retrieval & line completion | acc@k, EM | 12k+ | local, cheap | High for -R (retrieval) | [arxiv 2306.03091](https://arxiv.org/abs/2306.03091) |
| CodeRAG-Bench | retrieval+gen mix | pass@1, recall@k | 9k tasks | medium | Medium — mostly file-level | [code-rag-bench.github.io](https://code-rag-bench.github.io/) |
| LongCodeArena | long-context QA | varied | smaller | medium | Medium | n/a |
| LiveCodeBench | competitive programming | pass | rolling | cheap | **None** (no repo) | – |
| HumanEval / MBPP | algorithmic | pass@1 | 164 / 974 | cheap | **None** | – |
| CodeXGLUE | mixed older | mixed | varied | cheap | Low | – |

Prior art that already does roughly what we want (must read before claiming novelty):
- **RepoGraph** ([arxiv 2410.14684](https://arxiv.org/html/2410.14684v1), [github](https://github.com/ozyyshr/RepoGraph)) — tree-sitter, line-level def/ref, +2.34% on Agentless+GPT-4o, +2.66% on RAG+GPT-4. Direct comparator.
- **CodexGraph** ([NAACL 2025](https://aclanthology.org/2025.naacl-long.7.pdf)) — Neo4j-backed graph, agent issues queries.
- **CGM (Code Graph Model)** ([arxiv 2505.16901](https://arxiv.org/pdf/2505.16901)) — fuses graph into model attention, 43% on SWE-bench Lite with Qwen2.5-72B.
- **RANGER** (Sep 2025) — graph KG for RepoBench retrieval, Acc@5 = 0.5471.
- **Agentless** ([arxiv 2407.01489](https://arxiv.org/abs/2407.01489)) — the harness itself, MIT-licensed.

## 3. Detailed methodology — SWE-bench Lite + Agentless + codegraph-MCP

**Setup**
1. Clone `Agentless` and `SWE-bench` Lite; verify Docker harness reproducibility on 5 instances.
2. Stand up local LLM pipe — Claude Sonnet 4.6 via API (best-known 60%+ on Lite). Set seed, `temperature=0`, top_p=1, fixed-prompt template.
3. Build codegraph index per-repo at the patch-base commit; expose `find_symbol`, `callers`, `callees`, `subgraph`, `blast_radius`, `cycles` via MCP (already done).

**Baseline (B0)**: vanilla Agentless + Sonnet 4.6 on 300 Lite tasks, 3 seeds. Record resolve-rate, p@k localization, mean prompt tokens, $ cost.

**Treatment (T1) — codegraph at localization**: replace Agentless's BM25 + class/function-list step with codegraph queries. Same model, same temperature, same retries. Localization prompt receives: file list + `subgraph` of likely-touched symbols (depth=2) + `signatures` for each + `callers`/`callees`.

**Treatment (T2) — codegraph at repair**: T1 plus `blast_radius` injected into repair prompt to surface call sites needing co-edit.

**Treatment (T3) — RepoGraph reproduction**: re-run RepoGraph context for an apples-to-apples third arm. This is the critical cell — it isolates "is codegraph better than RepoGraph specifically?" versus "is graph context useful at all?".

**Eval**: SWE-bench official harness, three independent seeds, McNemar's test on per-instance pass/fail between B0/T1/T2/T3.

**Reproducibility**: pin Sonnet snapshot, log every prompt+completion, ship a single `run.sh`.

**Cost & wall-clock**: ~300 tasks × 4 arms × 3 seeds = 3,600 runs. At ~$0.10–0.25/task with caching, **~$400–900 total**. Wall-clock ~24–48h on one workstation with parallel Docker.

**A winning result** = T1 or T2 strictly dominates B0 by ≥ +2.5% absolute resolve-rate **and** beats T3 by ≥ +1% (the codegraph-specific delta — driven by signatures/role classification/cycles that RepoGraph lacks). Sub-claim: localization recall@5 jumps ≥ +5pp.

## 4. Second recommendation — fast sanity-check

**CrossCodeEval (Python + TypeScript slices)**. ~3k tasks, no agent loop, runs in hours, costs <$50. Compare three retrievers feeding the same model: (a) BM25, (b) embeddings (CodeBERT/Voyage), (c) codegraph `callers`/`callees` + `signatures`. Metric: Edit-Sim and Identifier-F1. This validates the retrieval thesis before burning Lite budget. ([cceval repo](https://github.com/amazon-science/cceval))

## 5. Honest caveats

- **Not novel vs. RepoGraph** unless we beat T3. The RepoGraph paper cleanly establishes the "tree-sitter graph helps Agentless" claim; we're claiming a better graph, not the first one. Frame the paper accordingly.
- **Contamination**: SWE-bench Verified/Lite overlap Sonnet/GPT pretraining; absolute resolve numbers are inflated 3–6× for known repos ([Dissecting SWE-Bench, arxiv 2506.17208](https://arxiv.org/html/2506.17208v2)). For headline credibility, replicate on **SWE-bench-Live** afterwards.
- **HumanEval/MBPP/LiveCodeBench**: codegraph adds zero. Skip.
- **TypeScript story is weaker**: most published structural-retrieval baselines are Python-only. SWE-bench Multilingual has a TS slice — but smaller signal, smaller leaderboard.
- **MCP plumbing risk**: an MCP-tool-call agent loop introduces extra failure modes (tool-call format errors). Best to ship a deterministic non-agentic pipeline that calls codegraph as a Python library for the actual paper run, and keep the MCP demo for the README.
- **Engineering effort** to plug into Agentless: ~2–3 days. Plug into the official mini-SWE-agent harness: another 1–2.

---

**Bottom line**: SWE-bench Lite + Agentless is the obvious target — well-trodden, reproducible, has a direct comparator (RepoGraph) that we can plausibly beat because codegraph carries strictly more signal (signatures, roles, cycles, dead-code, blast-radius). CrossCodeEval is the cheap pre-flight.
