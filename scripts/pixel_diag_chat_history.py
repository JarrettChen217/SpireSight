"""Reproduce the chat-history (messages=[...]) path that SpireSight's
main menu chat uses. Suspected slow path: structured assistant turns with
`type: output_text`.
"""
import os
import base64
import io
import time

from openai import OpenAI
from PIL import Image, ImageDraw

client = OpenAI(
    base_url="http://pixel.try-chatapi.com/v1",
    api_key=os.environ["PIXEL_API_KEY"],
)

MODEL = "gpt-5.5"
SYSTEM = "You are a Slay the Spire II strategist. Respond conversationally in 1-2 sentences."


def make_png() -> bytes:
    img = Image.new("RGB", (240, 120), (20, 20, 40))
    d = ImageDraw.Draw(img)
    d.text((20, 20), "HP 35/80   Strike   Defend", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


PNG_B64 = base64.b64encode(make_png()).decode()
IMAGE_DATA_URL = f"data:image/png;base64,{PNG_B64}"


def time_call(label: str, **kwargs) -> None:
    t0 = time.monotonic()
    ttft = None
    try:
        with client.responses.stream(**kwargs) as s:
            for ev in s:
                if getattr(ev, "type", "") == "response.output_text.delta":
                    if ttft is None:
                        ttft = time.monotonic() - t0
        ttft_s = f"{ttft:.2f}s" if ttft is not None else "n/a"
        print(f"  {label:<58} ttft={ttft_s:>9}  total={time.monotonic()-t0:.2f}s")
    except Exception as e:
        print(f"  {label:<58} FAIL: {str(e)[:80]}")


# Warm
time_call("WARMUP", model=MODEL, input="hi")
print()

USER_TEXT = "Given my hand, what should I play?"
ASSISTANT_PRIOR = "You should focus on defense at low HP. Play Defend if you're being attacked."
USER_FOLLOWUP = "What if it's not attacking?"

# ── Variant 1: provider's current format (output_text in assistant content)
print("--- assistant content as `output_text` (provider's current format) ---")
time_call("1a) single user, no image, no history",
          model=MODEL, instructions=SYSTEM,
          input=[{"role": "user", "content": [{"type": "input_text", "text": USER_TEXT}]}])

time_call("1b) 2-turn history, no image (chat shape)",
          model=MODEL, instructions=SYSTEM,
          input=[
              {"role": "user", "content": [{"type": "input_text", "text": USER_TEXT}]},
              {"role": "assistant", "content": [{"type": "output_text", "text": ASSISTANT_PRIOR}]},
              {"role": "user", "content": [{"type": "input_text", "text": USER_FOLLOWUP}]},
          ])

time_call("1c) 2-turn history + image on first user",
          model=MODEL, instructions=SYSTEM,
          input=[
              {"role": "user", "content": [
                  {"type": "input_text", "text": USER_TEXT},
                  {"type": "input_image", "image_url": IMAGE_DATA_URL},
              ]},
              {"role": "assistant", "content": [{"type": "output_text", "text": ASSISTANT_PRIOR}]},
              {"role": "user", "content": [{"type": "input_text", "text": USER_FOLLOWUP}]},
          ])

print()

# ── Variant 2: assistant content as plain string (OpenAI's documented shape)
print("--- assistant content as plain string (try this fix) ---")
time_call("2a) 2-turn history, no image",
          model=MODEL, instructions=SYSTEM,
          input=[
              {"role": "user", "content": [{"type": "input_text", "text": USER_TEXT}]},
              {"role": "assistant", "content": ASSISTANT_PRIOR},
              {"role": "user", "content": [{"type": "input_text", "text": USER_FOLLOWUP}]},
          ])

time_call("2b) 2-turn history + image on first user",
          model=MODEL, instructions=SYSTEM,
          input=[
              {"role": "user", "content": [
                  {"type": "input_text", "text": USER_TEXT},
                  {"type": "input_image", "image_url": IMAGE_DATA_URL},
              ]},
              {"role": "assistant", "content": ASSISTANT_PRIOR},
              {"role": "user", "content": [{"type": "input_text", "text": USER_FOLLOWUP}]},
          ])

print()

# ── Variant 3: all roles use simple string content (cleanest possible)
print("--- all string content (no parts list when avoidable) ---")
time_call("3a) 2-turn history, all strings, no image",
          model=MODEL, instructions=SYSTEM,
          input=[
              {"role": "user", "content": USER_TEXT},
              {"role": "assistant", "content": ASSISTANT_PRIOR},
              {"role": "user", "content": USER_FOLLOWUP},
          ])
