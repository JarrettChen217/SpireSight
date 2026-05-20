from __future__ import annotations

from spiresight.core.message_composer import apply_image_policy
from spiresight.core.messages import Message


def test_latest_only_strips_history_images():
    history = (
        Message(role="user", text="q1", image_png=b"OLD"),
        Message(role="assistant", text="a1"),
    )
    user = Message(role="user", text="q2", image_png=b"OLD")
    out = apply_image_policy("latest_only", history, user)
    assert out[0].image_png is None
    assert out[-1].image_png == b"OLD"


def test_once_only_keeps_first_image_only():
    history = (
        Message(role="user", text="q1", image_png=b"IMG"),
        Message(role="assistant", text="a1"),
    )
    user = Message(role="user", text="q2", image_png=b"IMG")
    out = apply_image_policy("once_only", history, user)
    assert out[0].image_png == b"IMG"
    assert out[-1].image_png is None


def test_never_strips_all_images():
    history = (Message(role="user", text="q1", image_png=b"X"),)
    user = Message(role="user", text="q2", image_png=b"X")
    out = apply_image_policy("never", history, user)
    assert all(m.image_png is None for m in out)
