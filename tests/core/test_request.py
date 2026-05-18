from spiresight.core.request import QuickActionRequest, FollowUpRequest


def test_quick_action_request():
    req = QuickActionRequest(
        prompt_id="combat_advice",
        custom_text="",
        include_screenshot=True,
    )
    assert req.prompt_id == "combat_advice"
    assert req.custom_text == ""
    assert req.include_screenshot is True


def test_quick_action_request_immutable():
    req = QuickActionRequest(prompt_id="x", custom_text="", include_screenshot=False)
    try:
        req.prompt_id = "y"  # type: ignore[misc]
        assert False
    except Exception:
        pass


def test_follow_up_request():
    req = FollowUpRequest(user_text="what about defense?")
    assert req.user_text == "what about defense?"
    assert req.include_screenshot is False
    assert req.recapture is False


def test_follow_up_request_recapture():
    req = FollowUpRequest(user_text="look again", recapture=True)
    assert req.recapture is True
    assert req.include_screenshot is False


def test_follow_up_request_with_screenshot():
    req = FollowUpRequest(user_text="check this", include_screenshot=True, recapture=True)
    assert req.include_screenshot is True
    assert req.recapture is True
