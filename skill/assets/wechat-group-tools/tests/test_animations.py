from io import BytesIO

import asyncio
import base64
import importlib

from PIL import Image
import pytest
from test_tools import PACKAGE
from test_behavior import configured_plugin

animations = importlib.import_module(PACKAGE + ".animations")


def gif(animated=True):
    buffer = BytesIO()
    image = Image.new("RGB", (8, 8), "red")
    options = (
        {"save_all": True, "append_images": [Image.new("RGB", (8, 8), "blue")], "duration": 100}
        if animated
        else {}
    )
    image.save(buffer, format="GIF", **options)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_only_real_multiframe_gifs_are_dynamic_candidates():
    dynamic = gif()
    result = animations.animated_candidates(
        [
            {"base64": gif(False)},
            {"base64": "invalid-base64"},
            {"base64": dynamic, "description": "开心"},
        ]
    )
    assert len(result) == 1
    assert result[0]["base64"] == dynamic


@pytest.mark.parametrize("answer,expected", [("0", True), ("10", False), ("invalid", False)])
def test_dynamic_send_checks_model_choice_and_preserves_original_frames(tmp_path, answer, expected):
    async def run():
        plugin = configured_plugin(tmp_path)
        encoded = gif()
        sends = []

        async def all_emojis():
            return [{"base64": encoded, "description": "可爱,开心"}]

        async def choose(*_args, **_kwargs):
            return {"success": True, "response": answer}

        async def send(data, stream_id, **_kwargs):
            sends.append((data, stream_id))
            return {"sent": True, "message_id": "9002"}

        plugin.ctx.emoji.get_all = all_emojis
        plugin.ctx.llm.generate = choose
        plugin.ctx.send.emoji = send
        result = await animations.send_dynamic(
            plugin, "开心", {"platform": "wechat", "group_id": "12345", "stream_id": "real-session"}
        )
        assert result["success"] is expected
        assert sends == ([(encoded, "real-session")] if expected else [])

    asyncio.run(run())


def test_unapproved_dynamic_send_never_reads_library(tmp_path):
    plugin = configured_plugin(tmp_path)
    result = asyncio.run(animations.send_dynamic(plugin, "开心", {"platform": "wechat", "group_id": "other"}))
    assert result["success"] is False
