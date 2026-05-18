import pytest
from dataclasses import FrozenInstanceError

from spiresight.core.messages import Message


def test_message_creation():
    m = Message(role="user", text="hello")
    assert m.role == "user"
    assert m.text == "hello"
    assert m.image_png is None


def test_message_with_image():
    img = b"\x89PNG\r\n\x1a\n"
    m = Message(role="user", text="look", image_png=img)
    assert m.image_png == img
    assert m.role == "user"


def test_message_assistant():
    m = Message(role="assistant", text="ok")
    assert m.role == "assistant"
    assert m.image_png is None


def test_message_immutable():
    m = Message(role="user", text="hi")
    with pytest.raises(FrozenInstanceError):
        m.text = "nope"


def test_message_equality():
    a = Message(role="user", text="hi")
    b = Message(role="user", text="hi")
    assert a == b
    assert hash(a) == hash(b)
