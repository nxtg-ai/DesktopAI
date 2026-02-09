import base64
from datetime import datetime, timezone

from app.desktop_context import DesktopContext, _MAX_UIA_SUMMARY_LEN
from app.schemas import UiaElement, UiaSnapshot, WindowEvent


def _make_event(**kwargs):
    defaults = dict(
        type="foreground",
        hwnd="0x1234",
        title="Test Window",
        process_exe="test.exe",
        pid=100,
        timestamp=datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        source="collector",
    )
    defaults.update(kwargs)
    return WindowEvent(**defaults)


def test_from_event_basic_fields():
    event = _make_event(title="Outlook - Inbox", process_exe="outlook.exe")
    ctx = DesktopContext.from_event(event)
    assert ctx is not None
    assert ctx.window_title == "Outlook - Inbox"
    assert ctx.process_exe == "outlook.exe"
    assert ctx.timestamp == event.timestamp


def test_from_event_none_returns_none():
    assert DesktopContext.from_event(None) is None


def test_from_event_with_uia_snapshot():
    uia = UiaSnapshot(
        focused_name="Reply Button",
        control_type="Button",
        document_text="Hello world",
    )
    event = _make_event(uia=uia)
    ctx = DesktopContext.from_event(event)
    assert ctx is not None
    assert "Reply Button" in ctx.uia_summary
    assert "Button" in ctx.uia_summary
    assert "Hello world" in ctx.uia_summary


def test_from_event_without_uia_has_empty_summary():
    event = _make_event(uia=None)
    ctx = DesktopContext.from_event(event)
    assert ctx is not None
    assert ctx.uia_summary == ""


def test_from_event_with_screenshot():
    raw = b"fake-jpeg-data"
    b64 = base64.b64encode(raw).decode()
    event = _make_event()
    # WindowEvent uses extra="allow", so we can set screenshot_b64 dynamically
    event.screenshot_b64 = b64  # type: ignore[attr-defined]
    ctx = DesktopContext.from_event(event)
    assert ctx is not None
    assert ctx.screenshot_b64 == b64
    assert ctx.get_screenshot_bytes() == raw


def test_from_event_without_screenshot():
    event = _make_event()
    ctx = DesktopContext.from_event(event)
    assert ctx is not None
    assert ctx.screenshot_b64 is None
    assert ctx.get_screenshot_bytes() is None


def test_uia_summary_truncated_when_too_long():
    long_text = "x" * 5000
    uia = UiaSnapshot(focused_name=long_text)
    event = _make_event(uia=uia)
    ctx = DesktopContext.from_event(event)
    assert ctx is not None
    assert len(ctx.uia_summary) <= _MAX_UIA_SUMMARY_LEN
    assert ctx.uia_summary.endswith("...")


def test_to_llm_prompt_includes_fields():
    uia = UiaSnapshot(focused_name="Send", control_type="Button")
    event = _make_event(title="Outlook", process_exe="outlook.exe", uia=uia)
    ctx = DesktopContext.from_event(event)
    assert ctx is not None
    prompt = ctx.to_llm_prompt()
    assert "Window: Outlook" in prompt
    assert "Process: outlook.exe" in prompt
    assert "UI Elements:" in prompt
    assert "Send" in prompt


def test_to_llm_prompt_screenshot_indicator():
    raw = b"data"
    b64 = base64.b64encode(raw).decode()
    event = _make_event()
    event.screenshot_b64 = b64  # type: ignore[attr-defined]
    ctx = DesktopContext.from_event(event)
    assert ctx is not None
    prompt = ctx.to_llm_prompt()
    assert "[Screenshot available]" in prompt


def test_uia_tree_elements_in_summary():
    tree = [
        UiaElement(
            name="Send",
            control_type="Button",
            children=[
                UiaElement(name="Icon", control_type="Image"),
            ],
        ),
        UiaElement(name="To", control_type="Edit", value="user@example.com"),
    ]
    uia = UiaSnapshot(window_tree=tree)
    event = _make_event(uia=uia)
    ctx = DesktopContext.from_event(event)
    assert ctx is not None
    assert 'Button "Send"' in ctx.uia_summary
    assert 'Image "Icon"' in ctx.uia_summary
    assert "val=user@example.com" in ctx.uia_summary
