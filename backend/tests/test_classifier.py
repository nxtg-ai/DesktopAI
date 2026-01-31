import asyncio
from datetime import datetime, timezone

from app.classifier import ActivityClassifier
from app.schemas import WindowEvent


def test_classifier_rules_coding():
    classifier = ActivityClassifier(None, default_category="docs", use_ollama=False)
    event = WindowEvent(
        type="foreground",
        hwnd="0x1",
        title="main.rs - Visual Studio Code",
        process_exe="C:\\Program Files\\Microsoft VS Code\\Code.exe",
        pid=123,
        timestamp=datetime.now(timezone.utc),
        source="test",
    )
    result = asyncio.run(classifier.classify(event))
    assert result.category == "coding"


def test_classifier_rules_terminal():
    classifier = ActivityClassifier(None, default_category="docs", use_ollama=False)
    event = WindowEvent(
        type="foreground",
        hwnd="0x2",
        title="Windows PowerShell",
        process_exe="C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
        pid=456,
        timestamp=datetime.now(timezone.utc),
        source="test",
    )
    result = asyncio.run(classifier.classify(event))
    assert result.category == "terminal"
