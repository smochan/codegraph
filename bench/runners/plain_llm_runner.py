"""Plain-LLM control runner.

Hands the LLM only the diff (no graph context) and asks for code-review
findings as JSON. Establishes the floor: "what does a generic LLM see?"

Defaults to Gemini Flash 2.5 (cheap, JSON-friendly, key in central store).
Override via BENCH_LLM_PROVIDER=gemini|openai and BENCH_LLM_MODEL=<name>.

Cost model: prompt+completion priced via _PRICE_PER_MTOK_USD. Cached responses
keyed by sha256(prompt+model) are read from .llm_cache/ so re-runs are free.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bench.query_types import QueryResult, QuerySpec, approx_tokens, matches
from bench.types import (
    CommitTarget,
    Finding,
    PassAResult,
    PassBResult,
    RunMetrics,
)

_QUESTION_FOR_KIND = {
    "find_symbol": "Where is the function or class `{target}` defined? Return the qualified name and file path.",
    "callers": "Which functions in this codebase call `{target}`? Return qualified names.",
    "subgraph": "What does `{target}` directly call or depend on? Return qualified names.",
    "untested": "List at least 10 functions that appear to have no tests covering them.",
    "cycles": "Are there any import cycles or circular call chains visible in this code? Describe them.",
}

_DEFAULT_PROVIDER = "gemini"
_DEFAULT_MODEL = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
}

_PRICE_PER_MTOK_USD = {
    # Approximate $/M-token. Update before publishing real numbers.
    "gemini-2.5-flash": {"in": 0.075, "out": 0.30},
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
}

_PROMPT_TEMPLATE = """You are reviewing one commit on an open-source project.

The commit subject is:
{title}

The full diff is below. Identify any code-quality, correctness, or safety issues
that a senior engineer would flag in code review. Return a JSON object with one key,
"findings", whose value is a list of objects with fields:
  file (string), line_start (int|null), line_end (int|null),
  severity ("info"|"low"|"medium"|"high"|"critical"),
  title (string, <= 80 chars), body (string).

Return ONLY JSON. If no issues, return {{"findings": []}}.

Diff:
```
{diff}
```
"""


class PlainLLMRunner:
    name = "plain-llm"

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.provider = os.environ.get("BENCH_LLM_PROVIDER", _DEFAULT_PROVIDER).lower()
        self.model = os.environ.get(
            "BENCH_LLM_MODEL",
            _DEFAULT_MODEL.get(self.provider, _DEFAULT_MODEL[_DEFAULT_PROVIDER]),
        )
        self._cache_dir = cache_dir or Path("bench/.llm_cache")
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def review_diff(self, target: CommitTarget, budget_usd: float) -> PassAResult:
        start = time.monotonic()
        prompt = _PROMPT_TEMPLATE.format(
            title=target.pr_title or "(no subject)",
            diff=target.diff[:200_000],  # hard cap to keep cost bounded
        )
        cache_key = hashlib.sha256(
            f"{self.provider}:{self.model}\n{prompt}".encode()
        ).hexdigest()
        cache_path = self._cache_dir / f"{cache_key}.json"

        if cache_path.exists():
            payload = json.loads(cache_path.read_text())
            cached = True
        else:
            payload = self._call_llm(prompt)
            cache_path.write_text(json.dumps(payload))
            cached = False

        findings = self._parse(payload)
        task_seconds = time.monotonic() - start
        cost = 0.0 if cached else self._estimate_cost(payload)
        return PassAResult(
            tool=f"{self.name} ({self.model})",
            repo=target.repo_name,
            commit_sha=target.commit_sha,
            findings=findings,
            metrics=RunMetrics(
                setup_seconds=0.0,
                task_seconds=round(task_seconds, 3),
                tokens_in=payload.get("usage", {}).get("input_tokens", 0),
                tokens_out=payload.get("usage", {}).get("output_tokens", 0),
                cost_usd=round(cost, 4),
            ),
        )

    def reproduce_work(self, target: CommitTarget, budget_usd: float) -> PassBResult:
        raise NotImplementedError("Pass B for plain-llm deferred to v2")

    # --- Pass Q ---------------------------------------------------------

    def query(self, spec: QuerySpec, repo: Path, *, prebuilt: bool = False) -> QueryResult:
        # Plain-LLM has no graph. Fair baseline: hand it the question + a grep dump
        # of the most likely candidate files so it has a fighting chance.
        question = _QUESTION_FOR_KIND.get(spec.kind, "What does `{target}` do?")
        if spec.target:
            question = question.format(target=spec.target)
        context = self._gather_context(spec, repo)

        prompt = (
            f"You're answering a question about a Python codebase. "
            f"Return ONLY a JSON object with one key, `answer`, whose value is a list "
            f"of strings (qualified names, file paths, or short factual statements). "
            f"If you cannot answer, return `{{\"answer\": []}}`.\n\n"
            f"Question: {question}\n\n"
            f"Candidate files (grep-filtered):\n```\n{context}\n```\n"
        )
        cache_key = hashlib.sha256(
            f"{self.provider}:{self.model}\n{prompt}".encode()
        ).hexdigest()
        cache_path = self._cache_dir / f"q_{cache_key}.json"

        task_start = time.monotonic()
        if cache_path.exists():
            payload = json.loads(cache_path.read_text())
            cached = True
        else:
            try:
                payload = self._call_llm(prompt)
            except RuntimeError as exc:
                return QueryResult(
                    tool=f"{self.name} ({self.model})",
                    query_id=spec.id,
                    repo_name=spec.repo_name,
                    failed=True,
                    failure_reason=str(exc),
                )
            cache_path.write_text(json.dumps(payload))
            cached = False
        latency = time.monotonic() - task_start

        text = payload.get("text", "")
        items = self._parse_answer(text)
        cost = 0.0 if cached else self._estimate_cost(payload)
        return QueryResult(
            tool=f"{self.name} ({self.model})",
            query_id=spec.id,
            repo_name=spec.repo_name,
            items=items,
            raw_text=context + "\n---\n" + text,  # include the context so token count reflects what the LLM actually saw
            correct=matches(spec, items, text),
            latency_seconds=round(latency, 4),
            setup_seconds=0.0,  # no setup — but the GREP CONTEXT IS the hidden cost
            tokens_returned=approx_tokens(context) + approx_tokens(text),
            cost_usd=round(cost, 4),
        )

    @staticmethod
    def _gather_context(spec: QuerySpec, repo: Path) -> str:
        """Return up to ~3000 lines of grep-style context."""
        if spec.target:
            res = subprocess.run(
                ["grep", "-rn", "--include=*.py", "-w", spec.target, str(repo)],
                check=False, capture_output=True, text=True, timeout=15,
            )
            out = res.stdout
        else:
            # untested / cycles — no specific symbol; dump test + import patterns.
            res = subprocess.run(
                ["grep", "-rEn", "--include=*.py",
                 r"(^def |^class |^from |^import )", str(repo)],
                check=False, capture_output=True, text=True, timeout=15,
            )
            out = res.stdout
        lines = out.splitlines()[:3000]
        return "\n".join(lines)

    @staticmethod
    def _parse_answer(text: str) -> list[str]:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[len("json"):]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return [text[:500]]
        return [str(x) for x in data.get("answer", [])]

    def _call_llm(self, prompt: str) -> dict:
        if self.provider == "gemini":
            return self._call_gemini(prompt)
        if self.provider == "openai":
            return self._call_openai(prompt)
        raise RuntimeError(f"unknown BENCH_LLM_PROVIDER: {self.provider!r}")

    def _call_gemini(self, prompt: str) -> dict:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY missing — run `seedenv .` to populate from the central store"
            )
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={api_key}"
        )
        body = json.dumps({
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": 2048,
            },
        }).encode()
        req = Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
        except HTTPError as e:
            raise RuntimeError(f"gemini HTTP {e.code}: {e.read().decode()[:200]}") from e
        text = ""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                text += part.get("text", "")
        usage = data.get("usageMetadata", {})
        return {
            "text": text,
            "usage": {
                "input_tokens": usage.get("promptTokenCount", 0),
                "output_tokens": usage.get("candidatesTokenCount", 0),
            },
        }

    def _call_openai(self, prompt: str) -> dict:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY missing — run `seedenv .`")
        url = "https://api.openai.com/v1/chat/completions"
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "max_tokens": 2048,
        }).encode()
        req = Request(
            url, data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
        except HTTPError as e:
            raise RuntimeError(f"openai HTTP {e.code}: {e.read().decode()[:200]}") from e
        return {
            "text": data["choices"][0]["message"]["content"],
            "usage": {
                "input_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                "output_tokens": data.get("usage", {}).get("completion_tokens", 0),
            },
        }

    def _estimate_cost(self, payload: dict) -> float:
        usage = payload.get("usage", {})
        prices = _PRICE_PER_MTOK_USD.get(self.model, {"in": 0.0, "out": 0.0})
        return (
            usage.get("input_tokens", 0) / 1_000_000 * prices["in"]
            + usage.get("output_tokens", 0) / 1_000_000 * prices["out"]
        )

    @staticmethod
    def _parse(payload: dict) -> list[Finding]:
        text = payload.get("text", "").strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[len("json"):]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        out: list[Finding] = []
        for item in data.get("findings", []):
            sev = str(item.get("severity", "info")).lower()
            if sev not in {"info", "low", "medium", "high", "critical"}:
                sev = "info"
            out.append(Finding(
                file=str(item.get("file", "")),
                line_start=item.get("line_start"),
                line_end=item.get("line_end"),
                severity=sev,  # type: ignore[arg-type]
                title=str(item.get("title", ""))[:120],
                body=str(item.get("body", "")),
                tool="plain-llm",
                raw=item,
            ))
        return out
