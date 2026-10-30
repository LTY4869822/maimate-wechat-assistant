from pathlib import Path
import asyncio
import importlib
import sys
import types

from maibot_sdk import PluginContext, PluginPaths
import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "local_wechat_tools_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
plugin_module = importlib.import_module(PACKAGE + ".plugin")
query_module = importlib.import_module(PACKAGE + ".group_query")


def make_plugin(tmp_path):
    plugin = plugin_module.create_plugin()
    plugin._set_context(
        PluginContext(
            plugin_id="local.wechat-group-tools",
            paths=PluginPaths(data_dir=tmp_path, runtime_dir=tmp_path / "runtime"),
        )
    )
    plugin.set_plugin_config(
        {
            "plugin": {"config_version": "1.0.0", "enabled": True},
            "bridge": {"token": "test-token"},
            "groups": {"allowed_group_ids": ["12345"]},
        }
    )
    return plugin


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"platform": "qq", "group_id": "12345"},
        {"platform": "wechat", "group_id": "99999"},
        {"platform": "wechat"},
    ],
)
def test_unapproved_context_never_queries(tmp_path, monkeypatch, context):
    async def forbidden(*_args):
        raise AssertionError("An unapproved context must not reach the bridge")

    monkeypatch.setattr(plugin_module, "query_group_info", forbidden)
    result = asyncio.run(make_plugin(tmp_path).current_group_info(**context))
    assert result["success"] is False


def test_group_size_is_returned_from_bridge_not_history(tmp_path, monkeypatch):
    async def query(port, token, group):
        assert port == 7999 and token == "test-token" and group == "12345"
        return {"group_id": group, "group_name": "测试群", "member_count": 17}

    monkeypatch.setattr(plugin_module, "query_group_info", query)
    result = asyncio.run(make_plugin(tmp_path).current_group_info(platform="wechat", group_id="12345"))
    assert result["success"] is True
    assert result["data"]["member_count"] == 17
    assert "17" in result["content"]


def test_query_failure_does_not_invent_a_count(tmp_path, monkeypatch):
    async def query(*_args):
        raise query_module.GroupQueryError("群资料尚未同步")

    monkeypatch.setattr(plugin_module, "query_group_info", query)
    result = asyncio.run(make_plugin(tmp_path).current_group_info(platform="wechat", group_id="12345"))
    assert result == {"success": False, "content": "群资料尚未同步"}


def test_seed_import_uses_host_api_and_reports_results(tmp_path):
    seed = tmp_path / "starter_emoji"
    seed.mkdir()
    (seed / "one.png").write_bytes(b"test-image")
    (seed / "ignored.txt").write_text("not an image")
    calls = []

    async def register(data):
        calls.append(data)
        return {"success": True}

    plugin = make_plugin(tmp_path)
    # The SDK context is retained; replace only the public emoji API method.
    plugin.ctx.emoji.register_emoji = register
    asyncio.run(plugin._import_emoji_library())
    assert len(calls) == 1
    assert '"imported": 1' in (tmp_path / "emoji-import-status.json").read_text(encoding="utf-8")


def test_unload_cancels_the_owned_import_task(tmp_path, monkeypatch):
    async def run():
        plugin = make_plugin(tmp_path)
        started = asyncio.Event()

        async def import_library():
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(plugin, "_import_emoji_library", import_library)
        await plugin.on_load()
        await started.wait()
        task = plugin._import_task
        await plugin.on_unload()
        assert task.cancelled()
        assert plugin._import_task is None

    asyncio.run(run())


@pytest.mark.parametrize("count", [None, True, 0, -1, "12"])
def test_bridge_missing_or_invalid_count_is_not_reported_as_real(monkeypatch, count):
    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def send(self, payload):
            import json

            self.echo = json.loads(payload)["echo"]

        def __aiter__(self):
            return self.events()

        async def events(self):
            yield '{"post_type":"meta_event"}'
            import json

            yield json.dumps({"echo": self.echo, "retcode": 0, "data": {"member_count": count}})

    monkeypatch.setattr(query_module.websockets, "connect", lambda *_args, **_kwargs: Connection())
    with pytest.raises(query_module.GroupQueryError):
        asyncio.run(query_module.query_group_info(7999, "test-token", "12345"))
