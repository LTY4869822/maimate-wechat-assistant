from datetime import datetime
from types import SimpleNamespace

import asyncio
import importlib

import pytest
from test_tools import PACKAGE, make_plugin

behavior = importlib.import_module(PACKAGE + ".behavior")


def configured_plugin(tmp_path, proactive=False):
    plugin = make_plugin(tmp_path)
    plugin.set_plugin_config(
        {
            "plugin": {"config_version": "1.0.0", "enabled": True},
            "groups": {"allowed_group_ids": ["12345"], "bot_account_id": "1001"},
            "proactive": {"enabled": proactive},
        }
    )

    async def stream(*_args, **_kwargs):
        # Multiple accounts can have the same group; never take the first group-ID match.
        return [
            {"session_id": "old-account-session", "account_id": "old-account", "group_id": "12345"},
            {"session_id": "real-session", "account_id": "1001", "group_id": "12345"},
        ]

    plugin.ctx.chat.get_group_streams = stream

    async def recent(*_args, **_kwargs):
        return []

    plugin.ctx.message.get_recent = recent
    return plugin


def message(text="启动高情商模式", at="1001", account="1001", group="12345"):
    raw = [{"type": "text", "data": text}]
    if at is not None:
        raw.insert(0, {"type": "at", "data": {"target_user_id": at}})
    return {
        "platform": "wechat",
        "account_id": account,
        "session_id": "real-session",
        "message_info": {"group_info": {"group_id": group}, "user_info": {"user_id": "2002"}},
        "raw_message": raw,
    }


@pytest.mark.parametrize(
    "text,at,expected",
    [
        ("启动高情商模式", "1001", True),
        ("关闭高情商模式", "1001", False),
        ("启动高情商模式", None, None),
        ("启动高情商模式", "2002", None),
        ("他说启动高情商模式", "1001", None),
        ("关闭高情商模式吗", "1001", None),
    ],
)
def test_mode_requires_exact_phrase_and_real_at(text, at, expected):
    assert behavior.parse_mode_command(message(text, at), "1001") is expected


def test_mode_is_saved_in_group_state_and_off_does_not_leave_history_active(tmp_path):
    async def run():
        plugin = configured_plugin(tmp_path)
        acknowledgements = []

        async def send(text, stream_id, **_kwargs):
            acknowledgements.append((text, stream_id))
            return {"sent": True, "message_id": "9001"}

        plugin.ctx.send.text = send
        assert (await plugin.behavior.receive(message()))["action"] == "abort"
        assert "当前已开启" in plugin.behavior.mode_prompt("real-session")
        restarted = configured_plugin(tmp_path)
        await restarted.behavior.load()
        assert "当前已开启" in restarted.behavior.mode_prompt("real-session")
        plugin.ctx.send.text = send
        await plugin.behavior.receive(message("关闭高情商模式"))
        assert "当前关闭" in plugin.behavior.mode_prompt("real-session")
        assert len(acknowledgements) == 2
        assert plugin.behavior.mode_prompt("unrelated-session") == ""

    asyncio.run(run())


@pytest.mark.parametrize("change", [{"account": "different-account"}, {"group": "99999"}])
def test_mode_does_not_touch_unapproved_account_or_group(tmp_path, change):
    async def run():
        plugin = configured_plugin(tmp_path)
        assert await plugin.behavior.receive(message(**change)) == {"action": "continue"}
        assert plugin.behavior.state == {"groups": {}}
        assert not plugin.behavior.path.exists()

    asyncio.run(run())


def test_planner_and_replyer_get_current_mode_without_mutating_other_items(tmp_path):
    plugin = configured_plugin(tmp_path)
    plugin.behavior.sessions["12345"] = "real-session"
    plugin.behavior.record("12345")["eq_mode"] = True
    original = {"item_type": "UserMessageItem", "parts": [{"type": "text", "text": "hello"}]}
    result = plugin.behavior.planner({"session_id": "real-session", "items": [original]})
    assert result["modified_kwargs"]["items"][1] == original
    assert result["modified_kwargs"]["items"][0]["item_type"] == "SystemMessageItem"
    assert original["parts"][0]["text"] == "hello"
    reply = plugin.behavior.replyer({"session_id": "real-session", "extra_prompt": "original"})
    assert reply["modified_kwargs"]["extra_prompt"].startswith("original\n")
    assert "夸张土味" in reply["modified_kwargs"]["extra_prompt"]
    assert plugin.behavior.planner({"session_id": "another"}) == {"action": "continue"}


def stamp(hour=12):
    return datetime(2026, 10, 29, hour, tzinfo=behavior.SHANGHAI).timestamp()


@pytest.mark.parametrize(
    "hour,activity_age,count,due,expected",
    [
        (12, 601, 0, -1, True),
        (8, 601, 0, -1, False),
        (23, 601, 0, -1, False),
        (12, 599, 0, -1, False),
        (12, 601, 4, -1, False),
        (12, 601, 0, 10, False),
    ],
)
def test_proactive_gates_quiet_hours_idle_limit_and_interval(hour, activity_age, count, due, expected):
    cfg = SimpleNamespace(enabled=True, start_hour=9, end_hour=23, daily_limit=4, idle_minutes=10)
    now = stamp(hour)
    record = {"date": "2026-10-29", "count": count, "next_due": now + due}
    assert behavior.may_trigger(cfg, record, now, now - activity_age) is expected


def test_proactive_tick_reserves_once_and_does_not_duplicate_on_restart(tmp_path, monkeypatch):
    async def run():
        plugin = configured_plugin(tmp_path, proactive=True)
        now = stamp()
        monkeypatch.setattr(behavior.time, "time", lambda: now)
        plugin.behavior.activity["12345"] = now - 700
        plugin.behavior.record("12345")["next_due"] = now - 1
        calls = []

        async def trigger(stream_id, intent, **kwargs):
            calls.append((stream_id, intent, kwargs))
            return {"success": True, "accepted": True}

        plugin.ctx.maisaka.proactive.trigger = trigger
        await plugin.behavior.tick(now)
        await plugin.behavior.tick(now + 60)
        assert len(calls) == 1
        assert calls[0][0] == "real-session"
        assert plugin.behavior.record("12345")["count"] == 1
        restarted = configured_plugin(tmp_path)
        await restarted.behavior.load()
        assert restarted.behavior.record("12345")["count"] == 1
        assert restarted.behavior.record("12345")["next_due"] >= now + 3600

    asyncio.run(run())


def test_owned_proactive_loop_is_cancelled_on_unload(tmp_path):
    async def run():
        plugin = configured_plugin(tmp_path, proactive=True)
        await plugin.behavior.load()
        task = plugin.behavior.task
        assert task is not None
        await plugin.behavior.stop()
        assert task.cancelled()
        assert plugin.behavior.task is None

    asyncio.run(run())


def test_loaded_skill_overrides_tone_after_existing_system_prompt(tmp_path):
    async def run():
        plugin = configured_plugin(tmp_path)
        await plugin.behavior.load()
        plugin.behavior.record("12345")["eq_mode"] = True
        result = plugin.behavior.planner(
            {
                "session_id": "real-session",
                "items": [
                    {
                        "item_type": "SystemMessageItem",
                        "parts": [{"type": "text", "text": "original persona"}],
                    },
                    {"item_type": "UserMessageItem", "parts": [{"type": "text", "text": "你在干嘛"}]},
                ],
            }
        )
        items = result["modified_kwargs"]["items"]
        assert items[0]["parts"][0]["text"] == "original persona"
        assert "开口就撩" in items[1]["parts"][0]["text"]
        assert "直接以麦麦的身份" in items[1]["parts"][0]["text"]
        assert "name: maimai" not in items[1]["parts"][0]["text"]
        assert items[2]["item_type"] == "UserMessageItem"

    asyncio.run(run())


def test_first_proactive_due_waits_for_idle_but_not_an_extra_hour(tmp_path, monkeypatch):
    async def run():
        now = stamp()
        monkeypatch.setattr(behavior.time, "time", lambda: now)
        plugin = configured_plugin(tmp_path, proactive=True)
        await plugin.behavior.load()
        assert plugin.behavior.record("12345")["next_due"] == now + 600
        assert not behavior.may_trigger(
            plugin.config.proactive, plugin.behavior.record("12345"), now + 599, now
        )
        await plugin.behavior.stop()

    asyncio.run(run())


def test_restart_restores_real_human_activity_instead_of_delaying_again(tmp_path, monkeypatch):
    async def run():
        now = stamp()
        monkeypatch.setattr(behavior.time, "time", lambda: now)
        plugin = configured_plugin(tmp_path, proactive=True)

        async def recent(*_args, **_kwargs):
            item = message("普通聊天", at=None)
            item["timestamp"] = str(now - 1200)
            return [item]

        plugin.ctx.message.get_recent = recent
        await plugin.behavior.load()
        assert plugin.behavior.activity["12345"] == now - 1200
        assert behavior.may_trigger(plugin.config.proactive, plugin.behavior.record("12345"), now, now - 1200)
        await plugin.behavior.stop()

    asyncio.run(run())


def test_replyer_gets_system_style_without_planner_tool_instructions(tmp_path):
    async def run():
        plugin = configured_plugin(tmp_path)
        await plugin.behavior.load()
        plugin.behavior.record("12345")["eq_mode"] = True
        result = plugin.behavior.model_request({"session_id": "real-session", "items": []})
        text = result["modified_kwargs"]["items"][0]["parts"][0]["text"]
        assert "开口就撩" in text
        assert "原始来源网址" in text
        assert "tool_search(query=" not in text

    asyncio.run(run())


@pytest.mark.parametrize(
    "text,at,expected",
    [
        ("你在干嘛？", "1001", True),
        ("麦麦，你现在在干什么呀", None, True),
        ("你在忙什么呢", None, True),
        ("你在干嘛", "other-member", False),
        ("你在干嘛，帮我查一下新闻", "1001", False),
    ],
)
def test_activity_greeting_does_not_swallow_other_requests(text, at, expected):
    assert behavior.is_activity_greeting(message(text, at), "1001") is expected


def test_activity_greeting_replies_thinking_of_you_only_while_mode_is_on(tmp_path):
    async def run():
        plugin = configured_plugin(tmp_path)
        replies = []

        async def send(text, stream_id, **_kwargs):
            replies.append((text, stream_id))
            return {"sent": True, "message_id": "9003"}

        plugin.ctx.send.text = send
        assert await plugin.behavior.receive(message("你在干嘛")) == {"action": "continue"}
        assert replies == []
        plugin.behavior.record("12345")["eq_mode"] = True
        for _ in range(2):
            assert await plugin.behavior.receive(message("你在干嘛")) == {"action": "abort"}
        assert replies[0] == ("在想你呀。", "real-session")
        assert all("在想你" in text for text, _ in replies)
        assert replies[0] != replies[1]

    asyncio.run(run())
