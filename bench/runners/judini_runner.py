from __future__ import annotations

from bench.runners._excluded import ExcludedRunner


class JudiniRunner(ExcludedRunner):
    name = "judini-mcp-code-graph"
    upstream_url = "https://github.com/JudiniLabs/mcp-code-graph"
    reason = (
        "Different category: thin MCP client to the CodeGPT/DeepGraph hosted "
        "service. No diff-ingestion surface, no local graph build. Also stale "
        "(last release 2025-06). Not a peer for a local-graph benchmark."
    )
