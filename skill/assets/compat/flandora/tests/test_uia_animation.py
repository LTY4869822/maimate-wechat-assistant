"""动态 GIF 不经过会扁平化成位图的 SetImage 通道。"""

import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flandora.uia_sender import UiaSender, _is_image_summary


def test_animated_gif_uses_original_file_drop_without_reencoding(tmp_path, monkeypatch):
    path = tmp_path / "animated.gif"
    Image.new("RGB", (8, 8), "red").save(
        path, save_all=True, append_images=[Image.new("RGB", (8, 8), "blue")], duration=100, loop=0
    )
    original = path.read_bytes()
    sender = object.__new__(UiaSender)
    calls = []
    monkeypatch.setattr(sender, "_copy_file_to_clipboard", lambda p: calls.append(p) or True)
    monkeypatch.setattr(
        sender, "_run_powershell", lambda *_: (_ for _ in ()).throw(AssertionError("No SetImage"))
    )
    assert sender._copy_image_to_clipboard(str(path)) is True
    assert calls == [str(path)]
    assert path.read_bytes() == original


def test_single_frame_gif_keeps_static_image_channel(tmp_path, monkeypatch):
    path = tmp_path / "static.gif"
    Image.new("RGB", (8, 8), "red").save(path)
    sender = object.__new__(UiaSender)
    scripts = []
    monkeypatch.setattr(sender, "_run_powershell", lambda script: scripts.append(script) or True)
    assert sender._copy_image_to_clipboard(str(path)) is True
    assert "SetImage" in scripts[0]


def test_invalid_gif_is_a_failure_not_a_static_fallback(tmp_path):
    path = tmp_path / "broken.gif"
    path.write_bytes(b"not a gif")
    sender = object.__new__(UiaSender)
    assert sender._copy_image_to_clipboard(str(path)) is False
    assert "无法读取" in sender._last_error


def test_animation_summary_is_accepted_but_file_card_is_not():
    assert _is_image_summary("[动画表情]")
    assert not _is_image_summary("[文件] animation.gif")
