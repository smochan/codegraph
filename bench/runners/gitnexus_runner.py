from __future__ import annotations

from bench.runners._excluded import ExcludedRunner


class GitNexusRunner(ExcludedRunner):
    name = "gitnexus"
    upstream_url = "https://github.com/abhigyanpatwari/GitNexus"
    reason = (
        "License blocker: GitNexus is licensed PolyForm Noncommercial 1.0.0. "
        "We do not benchmark or redistribute it from this MIT-licensed project to "
        "avoid ambiguity about commercial use. Revisit if upstream relicenses."
    )
