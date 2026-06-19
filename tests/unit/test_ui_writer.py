"""Unit tests for the Tk status writer adapter."""

from __future__ import annotations

import threading

from vaivox.application.ports import StatusLevel
from vaivox.infrastructure.ui.theme import TAG_BLACK, THEME_LIGHT
from vaivox.infrastructure.ui.writer import TkStatusWriter


class FakeInnerText:
    def __init__(self) -> None:
        self.states = []

    def configure(self, **kwargs) -> None:
        self.states.append(kwargs)


class FakeTextArea:
    def __init__(self) -> None:
        self.text = FakeInnerText()
        self.tags = []
        self.inserted = []
        self.deleted = []
        self.seen = []
        self.after_calls = []

    def tag_configure(self, tag, **kwargs) -> None:
        self.tags.append((tag, kwargs))

    def insert(self, index, text, tag) -> None:
        self.inserted.append((index, text, tag))

    def delete(self, start, end) -> None:
        self.deleted.append((start, end))

    def see(self, index) -> None:
        self.seen.append(index)

    def after(self, delay, callback, *args) -> None:
        self.after_calls.append((delay, callback, args))


def test_write_on_ui_thread_appends_immediately() -> None:
    text_area = FakeTextArea()
    writer = TkStatusWriter(THEME_LIGHT, text_area)

    writer.write("hello", TAG_BLACK)

    assert text_area.inserted == [("end", "hello\n", TAG_BLACK)]
    assert text_area.after_calls == []


def test_write_from_background_thread_is_marshaled_with_after() -> None:
    text_area = FakeTextArea()
    writer = TkStatusWriter(THEME_LIGHT, text_area)

    thread = threading.Thread(target=lambda: writer.write("background", TAG_BLACK))
    thread.start()
    thread.join(timeout=2)

    assert text_area.inserted == []
    assert len(text_area.after_calls) == 1
    delay, callback, args = text_area.after_calls[0]
    assert delay == 0

    callback(*args)

    assert text_area.inserted == [("end", "background\n", TAG_BLACK)]


def test_report_notifies_status_callback() -> None:
    text_area = FakeTextArea()
    statuses = []
    writer = TkStatusWriter(
        THEME_LIGHT,
        text_area,
        on_status=lambda message, level: statuses.append((message, level)),
    )

    writer.report("ready")

    assert statuses == [("ready", StatusLevel.INFO)]


def test_clear_empties_text_area() -> None:
    text_area = FakeTextArea()
    writer = TkStatusWriter(THEME_LIGHT, text_area)

    writer.clear()

    assert text_area.deleted == [("1.0", "end")]
