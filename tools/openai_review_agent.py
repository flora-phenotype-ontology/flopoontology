#!/usr/bin/env python3
"""A reviewer on an OpenAI-compatible endpoint, callable like the Claude Code client.

``tools/llm_candidate_review.py`` runs ``<command> -p --model M --tools Read,Grep,Glob
--output-format json`` with the prompt on stdin and reads one JSON envelope. This script takes the
same call and answers it with a model served by vLLM (``tools/orix/deepseek_flopo.sbatch``): a
tool loop over chat completions with the same three read-only tools, confined to the repository.

    OPENAI_BASE_URL=http://127.0.0.1:8499/v1 OPENAI_API_KEY_FILE=~/tmp/deepseek/key \
      python -m tools.llm_candidate_review run --command tools/openai_review_agent.py \
        --model deepseek-v4.1-flash --out curation/deepseek-review-2026-11-27 --workers 16
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("REVIEW_ROOT") or Path.cwd()).resolve()  # the checkout the reviewer may read
MAX_TURNS = 40
MAX_OUTPUT = 24_000  # characters of one tool result

SYSTEM = (
    "You are a careful reviewer working in the FLOPO repository (a plant phenotype ontology and "
    "its annotation pipeline). You can read the repository with the tools Read, Grep and Glob; "
    "paths are relative to the repository root. Look terms up before you name them: never cite an "
    "identifier you have not seen in a file. Large ontology files must be searched with Grep, not "
    "read whole. When you are done, give the final answer exactly in the format the task asks for."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "Read", "description": "Read a text file of the repository (a line range for large files).",
        "parameters": {"type": "object", "properties": {
            "file_path": {"type": "string"}, "offset": {"type": "integer", "description": "first line, from 1"},
            "limit": {"type": "integer", "description": "number of lines (default 400)"}},
            "required": ["file_path"]}}},
    {"type": "function", "function": {
        "name": "Grep", "description": "Search file contents with a regular expression (ripgrep). Returns matching lines with file and line number.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string", "description": "file or directory (default: repository root)"},
            "glob": {"type": "string", "description": "only files matching this glob, e.g. *.tsv"},
            "ignore_case": {"type": "boolean"}, "context": {"type": "integer", "description": "lines of context"},
            "max_results": {"type": "integer", "description": "default 80"}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "Glob", "description": "List files matching a glob pattern, e.g. config/*.tsv or docs/odp/*.md.",
        "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}}},
]


def _inside(path: str) -> Path:
    target = (ROOT / path).resolve() if not os.path.isabs(path) else Path(path).resolve()
    if ROOT != target and ROOT not in target.parents:
        raise ValueError("path is outside the repository")
    return target


def _read(file_path: str, offset: int = 1, limit: int = 400) -> str:
    path = _inside(file_path)
    if not path.is_file():
        return f"no such file: {file_path}"
    out, size = [], 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, 1):
            if number < max(1, offset):
                continue
            if number >= max(1, offset) + limit or size > MAX_OUTPUT:
                out.append(f"... (more lines; read on with offset={number})")
                break
            line = line.rstrip("\n")[:1200]
            out.append(f"{number}\t{line}")
            size += len(line)
    return "\n".join(out) or "(empty)"


def _grep(pattern: str, path: str = ".", glob: str = "", ignore_case: bool = False, context: int = 0,
          max_results: int = 80) -> str:
    target = _inside(path)
    command = ["rg", "--line-number", "--no-heading", "--color", "never", "--max-columns", "600",
               "--max-columns-preview", "--max-count", str(max(1, max_results))]
    if ignore_case:
        command.append("-i")
    if context:
        command += ["-C", str(min(int(context), 5))]
    if glob:
        command += ["--glob", glob]
    for skip in ("local-corpora", ".git", "*.jsonl", "hs_err_*", "replay_*", "deepseek-review-*"):
        command += ["--glob", f"!{skip}"]
    command += ["--", pattern, str(target)]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        return "search timed out; narrow the path or the pattern"
    lines = done.stdout.replace(str(ROOT) + "/", "").splitlines()
    text = "\n".join(lines[: max(1, max_results)])
    if len(lines) > max_results:
        text += f"\n... ({len(lines) - max_results} more lines; narrow the search)"
    return text[:MAX_OUTPUT] or (done.stderr.strip()[:400] or "no match")


def _glob(pattern: str) -> str:
    names = sorted(str(p.relative_to(ROOT)) for p in ROOT.glob(pattern)
                   if not any(part in {".git", "local-corpora"} for part in p.parts))
    if not names and "/" not in pattern:
        names = sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if fnmatch.fnmatch(p.name, pattern))[:300]
    return "\n".join(names[:300]) or "no file matches"


def _call(name: str, arguments: str) -> str:
    try:
        args = json.loads(arguments or "{}")
        if name == "Read":
            return _read(str(args["file_path"]), int(args.get("offset") or 1), int(args.get("limit") or 400))
        if name == "Grep":
            return _grep(str(args["pattern"]), str(args.get("path") or "."), str(args.get("glob") or ""),
                         bool(args.get("ignore_case")), int(args.get("context") or 0), int(args.get("max_results") or 80))
        if name == "Glob":
            return _glob(str(args["pattern"]))
        return f"unknown tool {name}"
    except Exception as exc:  # noqa: BLE001  (the model reads the error and corrects the call)
        return f"error: {type(exc).__name__}: {exc}"


_DSML_INVOKE = re.compile(r"<｜DSML｜\s*invoke name=\"([^\"]+)\">(.*?)</｜DSML｜\s*invoke>", re.S)
_DSML_PARAM = re.compile(r"<｜DSML｜\s*parameter name=\"([^\"]+)\" string=\"(true|false)\">(.*?)</｜DSML｜\s*parameter>", re.S)


def _dsml_calls(content: str) -> list[dict]:
    """Tool calls the server's parser left in the text (DeepSeek's own markup), as OpenAI calls."""

    calls = []
    for number, (name, body) in enumerate(_DSML_INVOKE.findall(content or "")):
        args = {}
        for key, is_string, value in _DSML_PARAM.findall(body):
            if is_string == "true":
                args[key] = value
            else:
                try:
                    args[key] = json.loads(value)
                except json.JSONDecodeError:
                    args[key] = value
        calls.append({"id": f"dsml-{int(time.time() * 1000)}-{number}", "type": "function",
                      "function": {"name": name, "arguments": json.dumps(args)}})
    return calls


def _post(base: str, key: str, payload: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    last = ""
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:500]}"
            if exc.code < 500 and exc.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(last)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-p", action="store_true")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "deepseek-v4.1-flash"))
    parser.add_argument("--tools", default="Read,Grep,Glob")
    parser.add_argument("--output-format", default="json")
    args = parser.parse_args(argv)
    base = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8499/v1")
    key_file = os.environ.get("OPENAI_API_KEY_FILE")
    key = Path(key_file).expanduser().read_text().strip() if key_file else os.environ.get("OPENAI_API_KEY", "")
    allowed = set(args.tools.split(","))
    tools = [t for t in TOOLS if t["function"]["name"] in allowed]
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": sys.stdin.read()}]
    started = time.time()
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    envelope: dict = {"is_error": False, "subtype": "success", "modelUsage": {args.model: usage}, "total_cost_usd": 0.0}
    turns = 0
    try:
        while True:
            turns += 1
            payload = {"model": args.model, "messages": messages, "max_tokens": int(os.environ.get("OPENAI_MAX_TOKENS", "32000")),
                       "temperature": float(os.environ.get("OPENAI_TEMPERATURE", "1.0"))}
            if tools and turns < MAX_TURNS:
                payload["tools"] = tools
            if turns > MAX_TURNS + 3:
                raise RuntimeError("no final answer after the lookup limit")
            answer = _post(base, key, payload, timeout=1800)
            for name in usage:
                usage[name] += int((answer.get("usage") or {}).get(name) or 0)
            choice = answer["choices"][0]
            message = choice["message"]
            calls = message.get("tool_calls") or []
            if not calls and "｜DSML｜" in (message.get("content") or ""):
                calls = _dsml_calls(message["content"])
                message["content"] = _DSML_INVOKE.split(message["content"])[0] if calls else message["content"]
            if calls and turns >= MAX_TURNS:
                messages.append({"role": "user", "content": "No more lookups: give the final answer now, in the format the task asks for."})
                continue
            if not calls:
                if choice.get("finish_reason") == "length":
                    raise RuntimeError("the answer was cut off at the token limit")
                envelope["result"] = message.get("content") or ""
                break
            messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
            for call in calls:
                function = call.get("function") or {}
                messages.append({"role": "tool", "tool_call_id": call.get("id"),
                                 "content": _call(str(function.get("name")), function.get("arguments") or "{}")})
    except Exception as exc:  # noqa: BLE001
        envelope.update({"is_error": True, "subtype": "error", "result": f"{type(exc).__name__}: {exc}"})
    envelope.update({"num_turns": turns, "duration_ms": int((time.time() - started) * 1000)})
    if not re.search(r"\S", str(envelope.get("result") or "")) and not envelope["is_error"]:
        envelope.update({"is_error": True, "subtype": "error", "result": "empty answer"})
    print(json.dumps(envelope, ensure_ascii=False))
    sys.exit(1 if envelope["is_error"] else 0)


if __name__ == "__main__":
    main()
