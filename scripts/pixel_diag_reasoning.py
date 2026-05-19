"""Isolated hypothesis test: does the relay use the `reasoning=` parameter
to route to the fast path?

Skips all the slow setup probes — just the 5 head-to-head calls.
"""
import os
import time

from openai import OpenAI

client = OpenAI(
    base_url="http://pixel.try-chatapi.com/v1",
    api_key=os.environ["PIXEL_API_KEY"],
)

MODEL = "gpt-5.5"
COMMON = dict(model=MODEL, input="Reply in one sentence: what is asyncio?")


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
        print(f"  {label:<46} ttft={ttft_s:>8}  total={time.monotonic()-t0:.2f}s")
    except Exception as e:
        print(f"  {label:<46} FAIL: {str(e)[:80]}")


print("=== reasoning hypothesis test ===")
time_call("7a no reasoning (control)",          **COMMON)
time_call("7b with reasoning effort=low",       **COMMON, reasoning={"effort": "low"})
time_call("7c with reasoning effort=high",      **COMMON, reasoning={"effort": "high"})
time_call("7d run 7b again",                    **COMMON, reasoning={"effort": "low"})
time_call("7e no reasoning again (control)",    **COMMON)
