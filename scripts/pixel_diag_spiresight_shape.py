"""Reproduce SpireSight's real production call shape against the relay,
WITHOUT going through PixelApiProvider — just bare openai SDK.

Goal: find out which variable in (image / system / json_schema) drives the
slow path. Each variant adds one piece.
"""
import os
import base64
import io
import time

from openai import OpenAI
from PIL import Image, ImageDraw

from spiresight.config.schema import ProviderConfig
from spiresight.llm.provider import ProviderOptions
from spiresight.llm.providers.pixel_api_provider import PixelApiProvider

client = OpenAI(
    base_url="http://pixel.try-chatapi.com/v1",
    api_key=os.environ["PIXEL_API_KEY"],
)

MODEL = "gpt-5.5"
SYSTEM = (
    "You are an expert Slay the Spire II strategist. Reply with a JSON object "
    "with one key 'advice' whose value is a one-sentence string."
)
USER_TEXT = "What should I do this turn?"

SCHEMA = {
    "type": "json_schema",
    "name": "response",
    "schema": {"type": "object", "additionalProperties": True},
    "strict": False,
}


def make_png() -> bytes:
    img = Image.new("RGB", (480, 240), (20, 20, 40))
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


PNG_B64 = base64.b64encode(make_png()).decode()
IMAGE_DATA_URL = f"data:image/png;base64,{PNG_B64}"

STRUCTURED_INPUT_WITH_IMAGE = [{
    "role": "user",
    "content": [
        {"type": "input_text", "text": USER_TEXT},
        {"type": "input_image", "image_url": IMAGE_DATA_URL},
    ],
}]

STRUCTURED_INPUT_TEXT_ONLY = [{
    "role": "user",
    "content": [{"type": "input_text", "text": USER_TEXT}],
}]


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
        print(f"  {label:<60} ttft={ttft_s:>9}  total={time.monotonic()-t0:.2f}s")
    except Exception as e:
        print(f"  {label:<60} FAIL: {str(e)[:80]}")


print("=== SpireSight-shape reproduction ===")
print(f"image: {len(PNG_B64)} chars base64\n")

# Warm the connection (cold start would skew first result)
time_call("WARMUP plain string input",
          model=MODEL, input="warmup ping")

print()

# Variants — add one variable at a time
time_call("A) string input only (baseline)",
          model=MODEL, input=USER_TEXT)

time_call("B) string input + system instructions",
          model=MODEL, input=USER_TEXT, instructions=SYSTEM)

time_call("C) string input + json_schema",
          model=MODEL, input=USER_TEXT, text={"format": SCHEMA})

time_call("D) string input + system + json_schema",
          model=MODEL, input=USER_TEXT, instructions=SYSTEM, text={"format": SCHEMA})

time_call("E) structured input (no image), plain",
          model=MODEL, input=STRUCTURED_INPUT_TEXT_ONLY)

time_call("F) structured input + system + json_schema (no image)",
          model=MODEL, input=STRUCTURED_INPUT_TEXT_ONLY, instructions=SYSTEM, text={"format": SCHEMA})

time_call("G) image input only (no system, no json)",
          model=MODEL, input=STRUCTURED_INPUT_WITH_IMAGE)

time_call("H) image + system (no json)",
          model=MODEL, input=STRUCTURED_INPUT_WITH_IMAGE, instructions=SYSTEM)

time_call("I) image + json_schema (no system)",
          model=MODEL, input=STRUCTURED_INPUT_WITH_IMAGE, text={"format": SCHEMA})

time_call("J) image + system + json_schema (FULL SPIRESIGHT SHAPE)",
          model=MODEL, input=STRUCTURED_INPUT_WITH_IMAGE, instructions=SYSTEM, text={"format": SCHEMA})


# Now run the SAME shape via PixelApiProvider to compare apples-to-apples
print("\n--- via PixelApiProvider (same call, but through our wrapper) ---")

provider = PixelApiProvider(
    ProviderConfig(api_key=os.environ["PIXEL_API_KEY"]),
    ProviderOptions(),
)


def time_provider(label: str, **kw) -> None:
    t0 = time.monotonic()
    ttft = None
    try:
        for chunk in provider.stream(**kw):
            if chunk.text_delta and ttft is None:
                ttft = time.monotonic() - t0
        ttft_s = f"{ttft:.2f}s" if ttft is not None else "n/a"
        print(f"  {label:<60} ttft={ttft_s:>9}  total={time.monotonic()-t0:.2f}s")
    except Exception as e:
        print(f"  {label:<60} FAIL: {str(e)[:80]}")


PNG_BYTES = make_png()
time_provider("K) provider: text only (no system)",
              model=MODEL, system="", user_text=USER_TEXT)
time_provider("L) provider: text + system",
              model=MODEL, system=SYSTEM, user_text=USER_TEXT)
time_provider("M) provider: text + system + json",
              model=MODEL, system=SYSTEM, user_text=USER_TEXT, json_mode=True)
time_provider("N) provider: image + system + json (SpireSight shape)",
              model=MODEL, system=SYSTEM, user_text=USER_TEXT, images=[PNG_BYTES], json_mode=True)
