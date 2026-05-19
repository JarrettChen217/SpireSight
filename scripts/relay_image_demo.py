"""Verify that image input still hits the relay's fast path.

Generates a small synthetic PNG (mimicking a tiny SpireSight-style HUD),
sends it via Responses API + streaming, and times TTFT/total. Runs a
text-only call first as a warm baseline.
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


def make_test_png() -> bytes:
    img = Image.new("RGB", (480, 240), color=(20, 20, 40))
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 460, 80], fill=(80, 30, 30), outline=(200, 200, 200))
    d.text((30, 35), "HP: 35 / 80   GOLD: 142", fill=(255, 240, 220))
    d.rectangle([20, 100, 220, 220], fill=(40, 60, 90), outline=(180, 180, 180))
    d.text((35, 150), "Strike  (6 dmg)", fill=(255, 255, 255))
    d.rectangle([260, 100, 460, 220], fill=(60, 40, 90), outline=(180, 180, 180))
    d.text((275, 150), "Defend  (5 block)", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def stream_once(label: str, content: list) -> None:
    print(f"\n--- {label} ---")
    t0 = time.monotonic()
    ttft = None
    with client.responses.stream(
        model=MODEL,
        input=[{"role": "user", "content": content}],
    ) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                if ttft is None:
                    ttft = time.monotonic() - t0
                print(event.delta, end="", flush=True)
        final = stream.get_final_response()
        usage = final.usage
    total = time.monotonic() - t0
    ttft_s = f"{ttft:.2f}s" if ttft is not None else "n/a"
    in_tok = usage.input_tokens if usage else 0
    out_tok = usage.output_tokens if usage else 0
    print(f"\n[ttft={ttft_s}  total={total:.2f}s  in_tokens={in_tok}  out_tokens={out_tok}]")


# 1) Warm baseline: text only
stream_once("text only (warm-up)", [
    {"type": "input_text", "text": "Reply in one sentence: what is 2+2?"},
])

# 2) Image input
png = make_test_png()
b64 = base64.b64encode(png).decode()
print(f"\n(test PNG size: {len(png)} bytes, base64 {len(b64)} chars)")
stream_once("text + image", [
    {"type": "input_text",
     "text": "Briefly describe this game HUD in 2 sentences (HP, gold, available cards)."},
    {"type": "input_image", "image_url": f"data:image/png;base64,{b64}"},
])
