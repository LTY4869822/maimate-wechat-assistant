"""COM 初始化：线程池里发消息的线程必须先接上 COM，才拿得到微信窗口。

uiautomation 的每次控件调用都走 COM。发消息跑在线程池的工作线程上，这些线程从没
初始化过 COM，`ControlFromHandle` 会直接报「尚未调用 CoInitialize」——真机上表现为
文字发送一律失败。这里只验「每个线程初始化一次」这件事，不启动微信。
"""

from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flandora import uia_sender  # noqa: E402


class _FakeOle:
    def __init__(self):
        self.calls: list[tuple] = []

    def CoInitializeEx(self, *args):  # noqa: N802 - 名字要与被替身的 API 一致
        self.calls.append(args)
        return 0


class _FakeWindll:
    def __init__(self, ole):
        self.ole32 = ole


class _FakeCtypes:
    def __init__(self, ole):
        self.windll = _FakeWindll(ole)


def test_ensure_com_initializes_once_per_thread(monkeypatch):
    ole = _FakeOle()
    monkeypatch.setattr(uia_sender, "ctypes", _FakeCtypes(ole))
    monkeypatch.setattr(uia_sender, "_com_ready", threading.local())

    uia_sender.ensure_com()
    uia_sender.ensure_com()

    assert ole.calls == [(None, 0x2)], ole.calls


def test_ensure_com_runs_again_on_another_thread(monkeypatch):
    ole = _FakeOle()
    monkeypatch.setattr(uia_sender, "ctypes", _FakeCtypes(ole))
    monkeypatch.setattr(uia_sender, "_com_ready", threading.local())

    uia_sender.ensure_com()
    worker = threading.Thread(target=uia_sender.ensure_com)
    worker.start()
    worker.join()

    assert len(ole.calls) == 2, ole.calls


def test_ensure_com_survives_a_refused_apartment(monkeypatch):
    """线程已经是 MTA 时 CoInitializeEx 回 RPC_E_CHANGED_MODE，不该抛错也不该重试。"""

    class _RefusingOle(_FakeOle):
        def CoInitializeEx(self, *args):  # noqa: N802
            self.calls.append(args)
            return -2147417850  # 0x80010106

    ole = _RefusingOle()
    monkeypatch.setattr(uia_sender, "ctypes", _FakeCtypes(ole))
    monkeypatch.setattr(uia_sender, "_com_ready", threading.local())

    uia_sender.ensure_com()
    uia_sender.ensure_com()

    assert len(ole.calls) == 1, ole.calls


def test_initial_window_binding_joins_desktop_before_initializing_com(monkeypatch):
    calls = []
    sender = object.__new__(uia_sender.UiaSender)
    sender._window = None
    monkeypatch.setattr(sender, "_join_wechat_desktop", lambda: calls.append("desktop"))
    monkeypatch.setattr(uia_sender, "ensure_com", lambda: calls.append("com"))
    monkeypatch.setattr(sender, "_find_window", lambda: calls.append("bind"))
    monkeypatch.setitem(sys.modules, "uiautomation", types.SimpleNamespace())
    sender._init()
    assert calls == ["desktop", "com", "bind"]


def test_window_status_initializes_and_releases_com_in_request_thread(monkeypatch):
    from flandora.win32 import windows

    calls = []

    class Initializer:
        def __enter__(self):
            calls.append("init")

        def __exit__(self, *_args):
            calls.append("release")

    control = types.SimpleNamespace(Exists=lambda _timeout: True)
    auto = types.SimpleNamespace(
        UIAutomationInitializerInThread=Initializer,
        ControlFromHandle=lambda _hwnd: control,
    )
    monkeypatch.setitem(sys.modules, "uiautomation", auto)
    monkeypatch.setattr(windows, "state_of", lambda _control: "chat")
    assert windows.state_from_handle(42) == "chat"
    assert calls == ["init", "release"]
