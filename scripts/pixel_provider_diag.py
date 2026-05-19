"""Time the PixelApiProvider end-to-end exactly as SpireSight uses it.

Compares two paths so we can tell whether slowness is in our provider or in the relay:
  1. Bare openai SDK call (same as relay_minimal_demo.py — should be ~1-2s TTFT)
  2. PixelApiProvider.fetch_remote_models()
  3. PixelApiProvider.stream() with empty system, plain text user input
  4. PixelApiProvider.stream() with non-empty system + JSON mode (closer to SpireSight)
"""
import json as _json
import os
import time

from openai import OpenAI

from spiresight.config.schema import ProviderConfig
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.pixel_api_provider import PixelApiProvider

API_KEY = os.environ["PIXEL_API_KEY"]
MODEL = "gpt-5.5"


def section(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


# 1. Baseline: bare SDK, same call shape as minimal_demo
section("1) bare openai SDK responses.stream  (baseline — should match demo)")
client = OpenAI(base_url="http://pixel.try-chatapi.com/v1", api_key=API_KEY)
t0 = time.monotonic()
ttft = None
with client.responses.stream(model=MODEL, input="Reply in one sentence: what is asyncio?") as s:
    for ev in s:
        if getattr(ev, "type", "") == "response.output_text.delta":
            if ttft is None:
                ttft = time.monotonic() - t0
print(f"  ttft={ttft:.2f}s  total={time.monotonic() - t0:.2f}s")


# 2. PixelApiProvider model fetch
section("2) PixelApiProvider.fetch_remote_models()")
provider = PixelApiProvider(
    ProviderConfig(api_key=API_KEY),
    ProviderOptions(),
)
t0 = time.monotonic()
models = provider.fetch_remote_models()
print(f"  total={time.monotonic() - t0:.2f}s  models={len(models)}")


# 3. PixelApiProvider stream — empty system, plain text
section("3) PixelApiProvider.stream  (empty system, text only)")
t0 = time.monotonic()
ttft = None
for chunk in provider.stream(model=MODEL, system="", user_text="Reply in one sentence: what is asyncio?"):
    if chunk.text_delta:
        if ttft is None:
            ttft = time.monotonic() - t0
print(f"  ttft={ttft:.2f}s  total={time.monotonic() - t0:.2f}s")


SYSTEM = (
    "You are an expert Slay the Spire II strategist. Reply with a JSON object "
    "with one key 'advice' whose value is a one-sentence string."
)
USER = "My HP is 35/80 and I have Strike and Defend in hand vs a Slime. What should I play?"


def run_responses_call(label: str, *, instructions=None, json_mode=False) -> None:
    print(f"\n--- {label} ---")
    kwargs = {"model": MODEL, "input": USER}
    if instructions is not None:
        kwargs["instructions"] = instructions
    if json_mode:
        kwargs["text"] = {"format": {"type": "json_object"}}
    t0 = time.monotonic()
    ttft = None
    try:
        with client.responses.stream(**kwargs) as s:
            for ev in s:
                if getattr(ev, "type", "") == "response.output_text.delta":
                    if ttft is None:
                        ttft = time.monotonic() - t0
        print(f"  OK   ttft={ttft:.2f}s  total={time.monotonic()-t0:.2f}s")
    except Exception as e:
        print(f"  FAIL ({type(e).__name__}): {str(e)[:120]}")


# 4. Isolate the JSON+system 502 — vary one axis at a time
section("4) isolate the JSON+system failure")
run_responses_call("4a baseline: no instructions, no json")
run_responses_call("4b instructions only (no json)", instructions=SYSTEM)
run_responses_call("4c json only (no instructions)", json_mode=True)
run_responses_call("4d both instructions + json (= SpireSight shape)", instructions=SYSTEM, json_mode=True)


# 5. Find a working JSON path
section("5) try alternative JSON strategies")

def try_call(label: str, model: str, **kw) -> None:
    print(f"\n--- {label}  model={model} ---")
    kwargs = {"model": model, "input": USER, **kw}
    t0 = time.monotonic()
    ttft = None
    try:
        with client.responses.stream(**kwargs) as s:
            for ev in s:
                if getattr(ev, "type", "") == "response.output_text.delta":
                    if ttft is None:
                        ttft = time.monotonic() - t0
        print(f"  OK   ttft={ttft:.2f}s  total={time.monotonic()-t0:.2f}s")
    except Exception as e:
        print(f"  FAIL ({type(e).__name__}): {str(e)[:120]}")


# 7. Hypothesis: the relay routes to the fast path only when `reasoning=` is present
section("7) hypothesis test — does `reasoning` parameter trigger the fast path?")

def time_call(label: str, **kw) -> None:
    t0 = time.monotonic()
    ttft = None
    try:
        with client.responses.stream(**kw) as s:
            for ev in s:
                if getattr(ev, "type", "") == "response.output_text.delta":
                    if ttft is None:
                        ttft = time.monotonic() - t0
        ttft_s = f"{ttft:.2f}s" if ttft is not None else "n/a"
        print(f"  {label:<48} ttft={ttft_s:>8}  total={time.monotonic()-t0:.2f}s")
    except Exception as e:
        print(f"  {label:<48} FAIL: {str(e)[:80]}")

# Same simple shape as #1, with vs without reasoning
COMMON = dict(model=MODEL, input="Reply in one sentence: what is asyncio?")
time_call("7a no reasoning (control, == #1)",         **COMMON)
time_call("7b with reasoning effort=low",             **COMMON, reasoning={"effort": "low"})
time_call("7c with reasoning effort=high",            **COMMON, reasoning={"effort": "high"})
time_call("7d run 7b again to rule out warmup",       **COMMON, reasoning={"effort": "low"})
time_call("7e no reasoning again (rule out warmup)",  **COMMON)


# 6. Verify the fixed PixelApiProvider with SpireSight-shape call
section("6) FIXED PixelApiProvider with system + JSON mode")
t0 = time.monotonic()
ttft = None
parts = []
for chunk in provider.stream(
    model=MODEL, system=SYSTEM, user_text=USER, json_mode=True,
):
    if chunk.text_delta:
        if ttft is None:
            ttft = time.monotonic() - t0
        parts.append(chunk.text_delta)
text = "".join(parts)
try:
    _json.loads(text)
    json_ok = "YES"
except Exception:
    json_ok = "NO"
print(f"  ttft={ttft:.2f}s  total={time.monotonic()-t0:.2f}s  json_valid={json_ok}")
print(f"  output: {text[:200]}")


# 5a: json_object on the mini model (worked in earlier probe)
try_call("5a json_object on gpt-5.4-mini",
         model="gpt-5.4-mini",
         text={"format": {"type": "json_object"}})

# 5b: json_schema on gpt-5.5 — stricter format
try_call("5b json_schema on gpt-5.5",
         model="gpt-5.5",
         text={"format": {
             "type": "json_schema",
             "name": "advice",
             "schema": {
                 "type": "object",
                 "properties": {"advice": {"type": "string"}},
                 "required": ["advice"],
                 "additionalProperties": False,
             },
             "strict": True,
         }})

# 5c: no format, just rely on prompt to produce JSON
try_call("5c no format, prompt-only JSON on gpt-5.5",
         model="gpt-5.5",
         instructions="You MUST reply with exactly: "
                      '{"advice": "<one sentence>"}  with no other text.')
