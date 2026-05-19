"""Probe a third-party OpenAI-compatible relay (or the official API).

Three modes:
  default    — sanity-check 5 endpoints on one target
  --bench    — sweep reasoning_effort levels on one target
  --compare  — run a fixed matrix: relay chat/responses + official chat,
               sweeping efforts, then print a single combined table

Examples:
    # Full comparison: relay (chat + responses) vs official, sweeping efforts
    python scripts/probe_openai_relay.py --compare \\
        --relay-key sk-RELAY... \\
        --official-key sk-OFFICIAL...

    # Sanity-check the relay only
    python scripts/probe_openai_relay.py --api-key sk-RELAY...

    # Bench a single target
    python scripts/probe_openai_relay.py --bench --api-key sk-RELAY...
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from dataclasses import dataclass

import httpx
from openai import OpenAI


def make_client(api_key: str, base_url: str, timeout: float, *,
                no_gzip: bool = False, extra_headers: dict | None = None) -> OpenAI:
    """Build an OpenAI client with optional Accept-Encoding override.

    Setting `Accept-Encoding: identity` disables gzip — useful for diagnosing
    relays that buffer entire SSE streams behind a gzip transform.
    """
    headers: dict = {}
    if no_gzip:
        headers["Accept-Encoding"] = "identity"
    if extra_headers:
        headers.update(extra_headers)
    http_client = httpx.Client(timeout=timeout, headers=headers) if headers else None
    kwargs: dict = dict(api_key=api_key, base_url=base_url,
                        timeout=timeout, max_retries=0)
    if http_client is not None:
        kwargs["http_client"] = http_client
    return OpenAI(**kwargs)


BENCH_PROMPT = (
    "In 5 short bullet points, explain the practical differences between "
    "Python's asyncio and threading for I/O-bound work. Keep each bullet "
    "to one sentence."
)

JSON_PROMPT = (
    "Compare Python's asyncio and threading for I/O-bound work. "
    "Reply with a JSON object containing exactly these fields: "
    "{\"summary\": <one-sentence string>, "
    "\"recommendation\": <one of: \"asyncio\", \"threading\", \"depends\">, "
    "\"reasons\": <array of 2-3 short strings>}. "
    "Return ONLY the JSON object, no prose."
)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# ---------- sanity probes ----------

def probe_models(client: OpenAI) -> None:
    section("GET /v1/models")
    try:
        resp = client.models.list()
        ids = [m.id for m in resp.data]
        print(f"OK — {len(ids)} models")
        for mid in ids[:20]:
            print(f"  - {mid}")
        if len(ids) > 20:
            print(f"  ... ({len(ids) - 20} more)")
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")


def probe_chat_completions(client: OpenAI, model: str, stream: bool, effort: str | None) -> None:
    section(f"POST /v1/chat/completions (stream={stream}, effort={effort}) model={model}")
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a terse assistant."},
            {"role": "user", "content": "Reply with exactly: pong"},
        ],
    }
    if effort:
        kwargs["reasoning_effort"] = effort
    try:
        if stream:
            with client.chat.completions.create(**kwargs, stream=True,
                                                stream_options={"include_usage": True}) as s:
                parts: list[str] = []
                usage = None
                for ev in s:
                    if getattr(ev, "usage", None):
                        usage = ev.usage
                    for ch in (ev.choices or []):
                        if ch.delta and ch.delta.content:
                            parts.append(ch.delta.content)
                print(f"OK — text={''.join(parts)!r} usage={usage}")
        else:
            r = client.chat.completions.create(**kwargs)
            msg = r.choices[0].message.content if r.choices else None
            print(f"OK — text={msg!r} usage={r.usage}")
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")


def probe_responses(client: OpenAI, model: str, stream: bool, effort: str | None) -> None:
    section(f"POST /v1/responses (stream={stream}, effort={effort}) model={model}")
    kwargs = {
        "model": model,
        "input": "Reply with exactly: pong",
        "instructions": "You are a terse assistant.",
    }
    if effort:
        kwargs["reasoning"] = {"effort": effort}
    try:
        if stream:
            parts: list[str] = []
            with client.responses.stream(**kwargs) as s:
                for ev in s:
                    if getattr(ev, "type", "") == "response.output_text.delta":
                        parts.append(ev.delta)
                final = s.get_final_response()
            print(f"OK — output_text={''.join(parts)!r} usage={final.usage}")
        else:
            r = client.responses.create(**kwargs)
            print(f"OK — output_text={r.output_text!r} usage={r.usage}")
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        traceback.print_exc(limit=2)


# ---------- benchmark ----------

@dataclass
class BenchResult:
    effort: str
    ttft_s: float | None
    total_s: float
    output_tokens: int
    reasoning_tokens: int  # responses API only; 0 otherwise
    text_chars: int
    json_valid: bool | None = None  # None when json_mode wasn't requested
    error: str | None = None

    def tps(self) -> float:
        if not self.output_tokens or self.total_s <= 0:
            return 0.0
        return self.output_tokens / self.total_s


def bench_chat(client: OpenAI, model: str, effort: str, prompt: str,
               json_mode: bool = False) -> BenchResult:
    import json as _json
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if effort != "default":
        kwargs["reasoning_effort"] = effort
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    t0 = time.monotonic()
    ttft: float | None = None
    output_tokens = 0
    parts: list[str] = []
    try:
        with client.chat.completions.create(**kwargs) as s:
            for ev in s:
                if getattr(ev, "usage", None):
                    output_tokens = ev.usage.completion_tokens or 0
                for ch in (ev.choices or []):
                    if ch.delta and ch.delta.content:
                        if ttft is None:
                            ttft = time.monotonic() - t0
                        parts.append(ch.delta.content)
    except Exception as exc:
        return BenchResult(effort, ttft, time.monotonic() - t0, 0, 0, 0,
                           json_valid=(False if json_mode else None),
                           error=f"{type(exc).__name__}: {exc}")
    text = "".join(parts)
    json_valid: bool | None = None
    if json_mode:
        try:
            _json.loads(text)
            json_valid = True
        except Exception:
            json_valid = False
    return BenchResult(effort, ttft, time.monotonic() - t0, output_tokens, 0,
                       len(text), json_valid=json_valid)


def bench_responses(client: OpenAI, model: str, effort: str, prompt: str,
                    json_mode: bool = False) -> BenchResult:
    import json as _json
    kwargs: dict = {"model": model, "input": prompt}
    if effort != "default":
        kwargs["reasoning"] = {"effort": effort}
    if json_mode:
        kwargs["text"] = {"format": {"type": "json_object"}}
    t0 = time.monotonic()
    ttft: float | None = None
    output_tokens = 0
    reasoning_tokens = 0
    parts: list[str] = []
    try:
        with client.responses.stream(**kwargs) as s:
            for ev in s:
                if getattr(ev, "type", "") == "response.output_text.delta":
                    if ttft is None:
                        ttft = time.monotonic() - t0
                    parts.append(ev.delta)
            final = s.get_final_response()
            if final.usage:
                output_tokens = final.usage.output_tokens or 0
                details = getattr(final.usage, "output_tokens_details", None)
                if details is not None:
                    reasoning_tokens = getattr(details, "reasoning_tokens", 0) or 0
    except Exception as exc:
        return BenchResult(effort, ttft, time.monotonic() - t0, 0, 0, 0,
                           json_valid=(False if json_mode else None),
                           error=f"{type(exc).__name__}: {exc}")
    text = "".join(parts)
    json_valid: bool | None = None
    if json_mode:
        try:
            _json.loads(text)
            json_valid = True
        except Exception:
            json_valid = False
    return BenchResult(effort, ttft, time.monotonic() - t0, output_tokens, reasoning_tokens,
                       len(text), json_valid=json_valid)


def run_bench(client: OpenAI, model: str, endpoint: str, efforts: list[str], prompt: str) -> None:
    section(f"BENCH endpoint={endpoint} model={model} efforts={efforts}")
    print(f"prompt = {prompt!r}\n")
    runner = bench_chat if endpoint == "chat" else bench_responses
    results: list[BenchResult] = []
    for eff in efforts:
        print(f"  → running effort={eff} ...", flush=True)
        r = runner(client, model, eff, prompt)
        results.append(r)
        if r.error:
            print(f"    FAIL: {r.error}")
        else:
            ttft = f"{r.ttft_s*1000:.0f}ms" if r.ttft_s is not None else "n/a"
            print(f"    OK   ttft={ttft}  total={r.total_s:.2f}s  "
                  f"out_tokens={r.output_tokens} (reasoning={r.reasoning_tokens})  "
                  f"chars={r.text_chars}  tok/s={r.tps():.1f}")

    # Summary table
    print("\n  Summary:")
    print(f"  {'effort':<10} {'ttft':>8} {'total':>8} {'out_tok':>8} {'reason_tok':>11} {'chars':>7} {'tok/s':>7}")
    print(f"  {'-'*10} {'-'*8:>8} {'-'*8:>8} {'-'*8:>8} {'-'*11:>11} {'-'*7:>7} {'-'*7:>7}")
    for r in results:
        if r.error:
            print(f"  {r.effort:<10} {'ERROR':>8}  {r.error[:60]}")
            continue
        ttft = f"{r.ttft_s*1000:.0f}ms" if r.ttft_s is not None else "n/a"
        print(f"  {r.effort:<10} {ttft:>8} {r.total_s:>7.2f}s "
              f"{r.output_tokens:>8} {r.reasoning_tokens:>11} {r.text_chars:>7} {r.tps():>7.1f}")


# ---------- raw httpx probe (bypass openai SDK) ----------

HEADER_PROFILES: dict[str, dict[str, str]] = {
    # ---- baselines from last run ----
    "python-openai": {
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "User-Agent": "OpenAI/Python 2.37.0",
        "X-Stainless-Lang": "python",
        "X-Stainless-Package-Version": "2.37.0",
        "X-Stainless-OS": "MacOS",
        "X-Stainless-Arch": "arm64",
        "X-Stainless-Runtime": "CPython",
        "X-Stainless-Runtime-Version": "3.12",
        "X-Stainless-Async": "false",
        "X-Stainless-Retry-Count": "0",
        "X-Stainless-Read-Timeout": "120",
    },
    "minimal": {  # fast in last run
        "Accept": "*/*",
    },

    # ---- isolate User-Agent variable (keep Accept: */* fixed) ----
    "ua-openai": {
        "Accept": "*/*",
        "User-Agent": "OpenAI/Python 2.37.0",
    },
    "ua-aisdk": {
        "Accept": "*/*",
        "User-Agent": "ai-sdk/provider-utils/3.0.0 node",
    },
    "ua-chrome": {  # Electron-style UA, what Cherry Studio actually sends
        "Accept": "*/*",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "cherry-studio/1.7.0 Chrome/130.0.0.0 Electron/33.0.0 Safari/537.36",
    },
    "ua-curl": {
        "Accept": "*/*",
        "User-Agent": "curl/8.7.1",
    },

    # ---- isolate Accept variable (keep httpx default UA fixed) ----
    "accept-json": {
        "Accept": "application/json",
    },
    "accept-sse": {
        "Accept": "text/event-stream",
    },

    # ---- isolate Accept-Encoding ----
    "ae-br-zstd": {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
    },

    # ---- isolate X-Stainless-* ----
    "xstainless": {
        "Accept": "*/*",
        "X-Stainless-Lang": "python",
        "X-Stainless-Package-Version": "2.37.0",
    },
}


def raw_probe_chat(base_url: str, api_key: str, model: str, profile_name: str,
                   prompt: str, timeout: float, json_mode: bool = False) -> BenchResult:
    """Direct httpx call to /v1/chat/completions, bypassing openai SDK entirely."""
    import json as _json
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **HEADER_PROFILES[profile_name],
    }
    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    url = base_url.rstrip("/") + "/chat/completions"
    t0 = time.monotonic()
    ttft: float | None = None
    output_tokens = 0
    parts: list[str] = []
    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", url, headers=headers,
                               content=_json.dumps(body)) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(data)
                    except Exception:
                        continue
                    if "usage" in chunk and chunk["usage"]:
                        output_tokens = chunk["usage"].get("completion_tokens", 0) or 0
                    for ch in chunk.get("choices", []):
                        delta = ch.get("delta", {})
                        text = delta.get("content")
                        if text:
                            if ttft is None:
                                ttft = time.monotonic() - t0
                            parts.append(text)
    except Exception as exc:
        return BenchResult(profile_name, ttft, time.monotonic() - t0, 0, 0, 0,
                           json_valid=(False if json_mode else None),
                           error=f"{type(exc).__name__}: {exc}")
    text = "".join(parts)
    json_valid: bool | None = None
    if json_mode:
        try:
            _json.loads(text)
            json_valid = True
        except Exception:
            json_valid = False
    return BenchResult(profile_name, ttft, time.monotonic() - t0, output_tokens, 0,
                       len(text), json_valid=json_valid)


def run_raw_probe(args) -> None:
    section(f"RAW HTTPX PROBE  base={args.base_url}  model={args.model}")
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    print(f"profiles = {profiles}")
    print(f"json_mode = {args.json_mode}\n")

    results: list[BenchResult] = []
    prompt = JSON_PROMPT if args.json_mode else args.prompt
    for prof in profiles:
        if prof not in HEADER_PROFILES:
            print(f"  ! unknown profile {prof!r} — skipping")
            continue
        print(f"  → profile={prof} ...", flush=True)
        r = raw_probe_chat(args.base_url, args.api_key, args.model, prof,
                           prompt, args.timeout, json_mode=args.json_mode)
        results.append(r)
        if r.error:
            print(f"    FAIL: {r.error}")
        else:
            ttft = f"{r.ttft_s*1000:.0f}ms" if r.ttft_s is not None else "n/a"
            print(f"    OK   ttft={ttft}  total={r.total_s:.2f}s  "
                  f"out={r.output_tokens}  tok/s={r.tps():.1f}")

    print("\n  Summary:")
    print(f"  {'profile':<16} {'ttft':>10} {'total':>10} {'out':>5} {'tok/s':>7}")
    print("  " + "-" * 58)
    for r in results:
        if r.error:
            print(f"  {r.effort:<16}  ERROR: {r.error[:60]}")
            continue
        ttft = f"{r.ttft_s*1000:.0f}ms" if r.ttft_s is not None else "n/a"
        print(f"  {r.effort:<16} {ttft:>10} {r.total_s:>9.2f}s {r.output_tokens:>5} {r.tps():>7.1f}")


# ---------- compare matrix ----------

RELAY_BASE_DEFAULT = "https://pixel.try-chatapi.com/v1"
OFFICIAL_BASE_DEFAULT = "https://api.openai.com/v1"


def run_compare(args) -> None:
    efforts = [e.strip() for e in args.efforts.split(",") if e.strip()]
    modes: list[str] = []
    if not args.skip_text:
        modes.append("text")
    if not args.skip_json:
        modes.append("json")
    if not modes:
        print("ERROR: both text and json skipped — nothing to do", file=sys.stderr)
        sys.exit(2)

    # (target_label, base_url, key, model)
    matrix: list[tuple[str, str, str, str]] = []
    if args.relay_key:
        matrix.append(("relay",    args.relay_base_url,    args.relay_key,    args.relay_model))
    if args.official_key:
        matrix.append(("official", args.official_base_url, args.official_key, args.official_model))

    if not matrix:
        print("ERROR: no targets — pass --relay-key and/or --official-key", file=sys.stderr)
        sys.exit(2)

    endpoints: list[str] = []
    if args.endpoint == "both":
        endpoints = ["chat", "responses"]
    else:
        endpoints = [args.endpoint]

    print(f"endpoints = {endpoints}")
    print(f"modes = {modes}")
    print(f"efforts = {efforts}\n")

    # (target, model, endpoint, mode, result)
    all_rows: list[tuple[str, str, str, str, BenchResult]] = []

    for target, base, key, model in matrix:
        section(f"{target}  model={model}  base={base}  no_gzip={args.no_gzip}")
        client = make_client(api_key=key, base_url=base, timeout=args.timeout,
                             no_gzip=args.no_gzip)
        for endpoint in endpoints:
            runner = bench_chat if endpoint == "chat" else bench_responses
            for mode in modes:
                prompt = JSON_PROMPT if mode == "json" else args.prompt
                json_mode = (mode == "json")
                for eff in efforts:
                    print(f"  → endpoint={endpoint} mode={mode} effort={eff} ...", flush=True)
                    r = runner(client, model, eff, prompt, json_mode=json_mode)
                    all_rows.append((target, model, endpoint, mode, r))
                    if r.error:
                        print(f"    FAIL: {r.error}")
                    else:
                        ttft = f"{r.ttft_s*1000:.0f}ms" if r.ttft_s is not None else "n/a"
                        jv = "" if r.json_valid is None else f" json_valid={r.json_valid}"
                        print(f"    OK   ttft={ttft}  total={r.total_s:.2f}s  "
                              f"out={r.output_tokens}  tok/s={r.tps():.1f}{jv}")

    section("COMBINED SUMMARY")
    header = f"  {'target':<10} {'model':<14} {'ep':<10} {'mode':<5} {'effort':<9} {'ttft':>8} {'total':>8} {'out':>5} {'tok/s':>7} {'json_ok':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for target, model, endpoint, mode, r in all_rows:
        if r.error:
            print(f"  {target:<10} {model:<14} {endpoint:<10} {mode:<5} {r.effort:<9}  ERROR: {r.error[:60]}")
            continue
        ttft = f"{r.ttft_s*1000:.0f}ms" if r.ttft_s is not None else "n/a"
        jv = "-" if r.json_valid is None else ("YES" if r.json_valid else "NO")
        print(f"  {target:<10} {model:<14} {endpoint:<10} {mode:<5} {r.effort:<9} {ttft:>8} "
              f"{r.total_s:>7.2f}s {r.output_tokens:>5} {r.tps():>7.1f} {jv:>8}")


# ---------- main ----------

def main() -> int:
    ap = argparse.ArgumentParser()

    # single-target (sanity + --bench) flags
    ap.add_argument("--base-url", default=RELAY_BASE_DEFAULT)
    ap.add_argument("--model", default="gpt-5.4")
    ap.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY"))
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--skip", default="",
                    help="Sanity mode: skip probes: models,chat,chat-stream,responses,responses-stream")
    ap.add_argument("--effort", default=None,
                    help="Sanity mode: pass reasoning_effort (minimal/low/medium/high)")
    ap.add_argument("--bench", action="store_true",
                    help="Run benchmark sweep instead of sanity probes")
    ap.add_argument("--endpoint", choices=["chat", "responses", "both"], default="chat",
                    help="Bench/compare: which API to call (default: chat; 'both' tests chat then responses)")

    # shared
    ap.add_argument("--efforts", default="default",
                    help="Bench/compare: comma list of effort levels "
                         "('default' = unset). Examples: 'default' or 'default,minimal,high'")
    ap.add_argument("--prompt", default=BENCH_PROMPT)

    # --compare matrix flags
    ap.add_argument("--compare", action="store_true",
                    help="Run the comparison matrix (relay vs official, text + JSON)")
    ap.add_argument("--relay-key", default=None,
                    help="Compare: API key for the relay")
    ap.add_argument("--relay-base-url", default=RELAY_BASE_DEFAULT)
    ap.add_argument("--relay-model", default="gpt-5.4-mini",
                    help="Compare: relay model id (default: gpt-5.4-mini)")
    ap.add_argument("--official-key", default=os.environ.get("OPENAI_API_KEY"),
                    help="Compare: API key for official OpenAI (default: $OPENAI_API_KEY)")
    ap.add_argument("--official-base-url", default=OFFICIAL_BASE_DEFAULT)
    ap.add_argument("--official-model", default="gpt-5.5")
    ap.add_argument("--skip-text", action="store_true", help="Compare: skip plain-text run")
    ap.add_argument("--skip-json", action="store_true", help="Compare: skip JSON-mode run")
    ap.add_argument("--no-gzip", action="store_true",
                    help="Send Accept-Encoding: identity to disable gzip "
                         "(diagnose relays that buffer behind a gzip transform)")

    # --raw-probe (bypass openai SDK, compare HTTP header profiles)
    ap.add_argument("--raw-probe", action="store_true",
                    help="Bypass openai SDK; call /v1/chat/completions with httpx directly, "
                         "sweeping HTTP header profiles to find what triggers fast streaming")
    ap.add_argument("--profiles", default="python-openai,vercel-fetch,minimal,sse-accept",
                    help="Raw probe: comma-separated header profile names "
                         "(python-openai, vercel-fetch, minimal, sse-accept)")
    ap.add_argument("--json-mode", action="store_true",
                    help="Raw probe: also enable response_format=json_object")

    args = ap.parse_args()

    if args.raw_probe:
        run_raw_probe(args)
        return 0

    if args.compare:
        run_compare(args)
        return 0

    if not args.api_key:
        print("ERROR: no API key (set $OPENAI_API_KEY or pass --api-key)", file=sys.stderr)
        return 2

    print(f"base_url = {args.base_url}")
    print(f"model    = {args.model}")
    print(f"key      = {args.api_key[:6]}…{args.api_key[-4:]} (len={len(args.api_key)})")

    client = make_client(api_key=args.api_key, base_url=args.base_url,
                         timeout=args.timeout, no_gzip=args.no_gzip)

    if args.bench:
        efforts = [e.strip() for e in args.efforts.split(",") if e.strip()]
        run_bench(client, args.model, args.endpoint, efforts, args.prompt)
        return 0

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    if "models" not in skip:
        probe_models(client)
    if "chat" not in skip:
        probe_chat_completions(client, args.model, False, args.effort)
    if "chat-stream" not in skip:
        probe_chat_completions(client, args.model, True, args.effort)
    if "responses" not in skip:
        probe_responses(client, args.model, False, args.effort)
    if "responses-stream" not in skip:
        probe_responses(client, args.model, True, args.effort)
    return 0


if __name__ == "__main__":
    sys.exit(main())
