"""Provider-agnostic conversation message assembly for inference requests."""
from __future__ import annotations

from typing import Literal

from spiresight.core.messages import Message
from spiresight.core.request import FollowUpRequest
from spiresight.core.run_state import RunState

ImagePolicy = Literal["full", "latest_only", "once_only", "never"]


def resolve_follow_up_image(
    request: FollowUpRequest,
    history: tuple[Message, ...],
    *,
    capture_primary: bytes | None,
) -> bytes | None:
    if request.recapture:
        return capture_primary
    if not request.include_screenshot:
        return None
    for m in reversed(history):
        if m.role == "user" and m.image_png is not None:
            return m.image_png
    return None


def apply_image_policy(
    policy: ImagePolicy,
    history: tuple[Message, ...],
    user_msg: Message,
) -> tuple[Message, ...]:
    combined = (*history, user_msg)
    if policy == "full":
        return combined
    if policy == "never":
        return tuple(Message(role=m.role, text=m.text, image_png=None) for m in combined)
    if policy == "latest_only":
        stripped = tuple(
            Message(role=m.role, text=m.text, image_png=None) for m in history
        )
        return (*stripped, user_msg)
    first_image_idx = None
    for i, m in enumerate(combined):
        if m.role == "user" and m.image_png is not None:
            first_image_idx = i
            break
    out = []
    for i, m in enumerate(combined):
        keep = first_image_idx is not None and i == first_image_idx
        out.append(Message(role=m.role, text=m.text, image_png=m.image_png if keep else None))
    return tuple(out)


def compose_follow_up_system(base: str, run_state: RunState | None) -> str:
    if run_state is None:
        return base
    return f"{base}\n\n{run_state.to_prompt_block()}"
