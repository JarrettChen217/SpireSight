"""Minimal try-chatapi relay demo — streaming via Responses API, sweeping
reasoning effort levels.

Run:
    python scripts/relay_minimal_demo.py
"""
import os
import time
from openai import OpenAI

client = OpenAI(
    base_url="http://pixel.try-chatapi.com/v1",
    api_key=os.environ["PIXEL_API_KEY"],
)

PROMPT = "Write a 2-sentence bedtime story about a unicorn."
EFFORTS = ["minimal", "low", "medium", "high"]

for effort in EFFORTS:
    print(f"\n--- effort={effort} ---")
    t0 = time.monotonic()
    ttft = None
    reasoning_tokens = 0
    output_tokens = 0

    with client.responses.stream(
        model="gpt-5.5",
        input=PROMPT,
        reasoning={"effort": effort},
    ) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                if ttft is None:
                    ttft = time.monotonic() - t0
                print(event.delta, end="", flush=True)
        final = stream.get_final_response()
        if final.usage:
            output_tokens = final.usage.output_tokens or 0
            details = getattr(final.usage, "output_tokens_details", None)
            if details is not None:
                reasoning_tokens = getattr(details, "reasoning_tokens", 0) or 0

    total = time.monotonic() - t0
    ttft_s = f"{ttft:.2f}s" if ttft is not None else "n/a"
    print(f"\n[ttft={ttft_s}  total={total:.2f}s  "
          f"out_tokens={output_tokens}  reasoning_tokens={reasoning_tokens}]")
