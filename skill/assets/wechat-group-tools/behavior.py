"""按群持久化模式与有频率限制的主动任务，只使用宿主公开能力。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

import asyncio
import json
import random
import re
import time

SHANGHAI = timezone(timedelta(hours=8))
EQ_ON = (
    "本群高情商模式当前已开启。先理解并接住对方情绪，再温暖、体贴、有分寸地回应；"
    "多用具体真诚的肯定，适度幽默，偶尔自然穿插情话或土味情话，不要每句强行撩人。"
    "对方表达拒绝、尴尬或不适就立即收敛；群友可能年龄不同，只使用清爽、不露骨的日常情话。"
    "认真问题先给有用答案，事实与新闻照实核查，不为哄人编造。日常回复保持简短自然。"
)
EQ_OFF = "本群高情商模式当前关闭，恢复原本自然聊天风格；历史里的开启指令不代表当前仍开启。"
PLANNER_OPERATIONS = (
    "需要发表情包时优先使用 send_dynamic_emoji；如果它不在当前工具列表，先调用 "
    "tool_search(query='send_dynamic_emoji') 发现它，再调用发送，不能只用文字声称已经发出。"
    "询问新闻、近期事件、最新进展时先 web_search，必要时 web_fetch 核对权威正文；"
    "争议与负面传闻不要把单一不可靠摘要当结论。"
)
NEWS_REPLY_GUIDE = (
    "本次若回答新闻或近期事件，只能依据实际联网结果，不凭旧知识补造细节。"
    "必须把真正参考的1到2条原始来源网址写在回复末尾，不能因为闲聊口吻就省略来源；"
    "能确认事件日期或报道日期时写清，未经确认的传闻明确说尚未确认。"
)
THINKING_OF_YOU_REPLIES = (
    "在想你呀。",
    "在想你，刚好你就来找我了。",
    "本来在想你，现在在陪你。",
)


def is_activity_greeting(message: Dict[str, Any], bot_id: str) -> bool:
    segments = message.get("raw_message") or []
    ats = [part for part in segments if part.get("type") == "at"]
    if ats and not any(str((part.get("data") or {}).get("target_user_id")) == bot_id for part in ats):
        return False
    text = "".join(
        part["data"] if isinstance(part.get("data"), str) else str((part.get("data") or {}).get("text", ""))
        for part in segments
        if part.get("type") == "text"
    )
    text = re.sub(r"[\s，,。.!！?？~～]", "", text)
    return (
        re.fullmatch(
            r"(?:麦麦|小麦)?你?(?:现在|这会儿)?在?(?:干嘛|干吗|干啥|干什么|做什么|忙啥|忙什么)(?:呢|呀|啊)?",
            text,
        )
        is not None
    )


def allowed_message(message: Dict[str, Any], groups: list[str], bot_id: str) -> Optional[str]:
    if not bot_id or message.get("platform") != "wechat" or str(message.get("account_id")) != bot_id:
        return None
    info = message.get("message_info") or {}
    group = str((info.get("group_info") or {}).get("group_id") or "")
    user = str((info.get("user_info") or {}).get("user_id") or "")
    if group not in groups or user == bot_id or message.get("is_notify"):
        return None
    return group


def parse_mode_command(message: Dict[str, Any], bot_id: str) -> Optional[bool]:
    """必须存在真正指向小号的 @ 段；引用、名字文本与 @ 其他成员均不算。"""
    segments = message.get("raw_message") or []
    ats = [part for part in segments if part.get("type") == "at"]
    if not any(str((part.get("data") or {}).get("target_user_id")) == bot_id for part in ats):
        return None
    text_parts = []
    for part in segments:
        if part.get("type") != "text":
            continue
        data = part.get("data", "")
        text_parts.append(data if isinstance(data, str) else str(data.get("text", "")))
    match = re.fullmatch(r"\s*(启动|开启|关闭)高情商模式[！!。]?\s*", "".join(text_parts))
    return match.group(1) != "关闭" if match else None


def may_trigger(config: Any, record: Dict[str, Any], now: float, last_activity: float) -> bool:
    local = datetime.fromtimestamp(now, SHANGHAI)
    if not config.enabled or not config.start_hour <= local.hour < config.end_hour:
        return False
    count = record.get("count", 0) if record.get("date") == local.date().isoformat() else 0
    return (
        count < config.daily_limit
        and now >= record.get("next_due", now + 1)
        and now - last_activity >= config.idle_minutes * 60
    )


class GroupBehavior:
    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.state: Dict[str, Any] = {"groups": {}}
        self.sessions: Dict[str, str] = {}
        self.activity: Dict[str, float] = {}
        self.task: Optional[asyncio.Task[None]] = None
        self.lock = asyncio.Lock()
        self.sweet_prompt = EQ_ON

    @property
    def path(self) -> Path:
        return self.owner.ctx.paths.data_dir / "group-behavior-state.json"

    def record(self, group: str) -> Dict[str, Any]:
        return self.state["groups"].setdefault(group, {"eq_mode": False})

    def next_interval(self) -> int:
        cfg = self.owner.config.proactive
        if cfg.interval_max_minutes < cfg.interval_min_minutes:
            raise ValueError("主动聊天最大间隔不能小于最小间隔")
        return random.randint(cfg.interval_min_minutes, cfg.interval_max_minutes) * 60

    async def save(self) -> None:
        text = json.dumps(self.state, ensure_ascii=False, indent=2)

        def write() -> None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(self.path)

        await asyncio.to_thread(write)

    async def resolve_sessions(self) -> None:
        cfg = self.owner.config.groups
        if not cfg.bot_account_id:
            return
        streams = await self.owner.ctx.chat.get_group_streams(platform="wechat")
        if not isinstance(streams, list):
            raise ValueError("宿主没有返回有效群会话列表")
        for group in cfg.allowed_group_ids:
            stream = next(
                (
                    item
                    for item in streams
                    if str(item.get("group_id")) == group
                    and str(item.get("account_id")) == cfg.bot_account_id
                ),
                None,
            )
            if stream is not None:
                self.sessions[group] = str(stream.get("session_id") or "")
            else:
                self.sessions.pop(group, None)

    async def load(self) -> None:
        skill_path = Path(__file__).parent / "skills" / "sweet-talk" / "SKILL.md"
        skill = await asyncio.to_thread(skill_path.read_text, encoding="utf-8")
        self.sweet_prompt = re.sub(r"\A---\n.*?\n---\n", "", skill, count=1, flags=re.S).strip()
        self.owner.ctx.logger.info("群风格技能已加载：maimai-sweet-talk")
        if await asyncio.to_thread(self.path.exists):
            self.state = json.loads(await asyncio.to_thread(self.path.read_text, encoding="utf-8"))
            if not isinstance(self.state.get("groups"), dict):
                raise ValueError("群模式状态文件格式无效")
        now = time.time()
        await self.resolve_sessions()
        for group in self.owner.config.groups.allowed_group_ids:
            rec = self.record(group)
            last_activity = rec.get("last_human_activity")
            if self.owner.config.proactive.enabled and self.sessions.get(group):
                messages = await self.owner.ctx.message.get_recent(self.sessions[group], limit=20)
                if not isinstance(messages, list):
                    raise ValueError("宿主没有返回有效的最近消息列表")
                for message in messages:
                    if (
                        allowed_message(
                            message,
                            self.owner.config.groups.allowed_group_ids,
                            self.owner.config.groups.bot_account_id,
                        )
                        != group
                    ):
                        continue
                    try:
                        timestamp = min(now, float(message["timestamp"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    last_activity = max(last_activity or 0, timestamp)
            self.activity[group] = now if last_activity is None else min(now, last_activity)
            rec["last_human_activity"] = self.activity[group]
            first_due = self.activity[group] + self.owner.config.proactive.idle_minutes * 60
            if not rec.get("last_attempt"):
                rec["next_due"] = min(rec.get("next_due", first_due), first_due)
            else:
                rec.setdefault("next_due", now + self.next_interval())
            if self.owner.config.proactive.enabled:
                self.owner.ctx.logger.info(
                    f"主动聊天状态：group={group} idle_seconds={int(now - self.activity[group])} session_ready={bool(self.sessions.get(group))}"
                )
        if self.owner.config.proactive.enabled:
            await self.save()
            self.task = asyncio.create_task(self.loop())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        if self.state["groups"]:
            async with self.lock:
                await self.save()

    async def receive(self, message: Dict[str, Any]) -> Dict[str, Any]:
        if not self.owner.config.plugin.enabled:
            return {"action": "continue"}
        cfg = self.owner.config.groups
        group = allowed_message(message, cfg.allowed_group_ids, cfg.bot_account_id)
        if group is None:
            return {"action": "continue"}
        stream_id = str(message.get("session_id") or "")
        if not stream_id:
            return {"action": "continue"}
        self.sessions[group] = stream_id
        self.activity[group] = time.time()
        self.record(group)["last_human_activity"] = self.activity[group]
        mode = parse_mode_command(message, cfg.bot_account_id)
        if mode is None:
            if self.record(group).get("eq_mode") and is_activity_greeting(message, cfg.bot_account_id):
                async with self.lock:
                    record = self.record(group)
                    index = int(record.get("activity_greeting_index", 0)) % len(THINKING_OF_YOU_REPLIES)
                    text = THINKING_OF_YOU_REPLIES[index]
                    record["activity_greeting_index"] = index + 1
                    await self.save()
                sent = await self.owner.ctx.send.text(text, stream_id, return_details=True)
                success = isinstance(sent, dict) and bool(sent.get("sent"))
                self.owner.ctx.logger.info(f"问候固定回复：group={group} sent={success}")
                return {"action": "abort"}
            return {"action": "continue"}
        async with self.lock:
            self.record(group)["eq_mode"] = mode
            await self.save()
        acknowledgement = (
            "高情商模式已启动～话会好好说，糖也给你们备上。" if mode else "高情商模式已关闭，恢复平时聊天。"
        )
        sent = await self.owner.ctx.send.text(acknowledgement, stream_id, return_details=True)
        if not isinstance(sent, dict) or not sent.get("sent"):
            self.owner.ctx.logger.warning("高情商模式已保存，但确认消息未能发出")
        self.owner.ctx.logger.info(f"群模式切换：group={group} eq_mode={mode}")
        return {"action": "abort"}

    def mode_prompt(self, session_id: str) -> str:
        group = next((g for g, s in self.sessions.items() if s == session_id), None)
        if group is None:
            return ""
        return self.sweet_prompt if self.record(group).get("eq_mode") else EQ_OFF

    def planner(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        return self.inject_system_style(kwargs, PLANNER_OPERATIONS)

    def model_request(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        return self.inject_system_style(kwargs, NEWS_REPLY_GUIDE)

    def inject_system_style(self, kwargs: Dict[str, Any], operational_rules: str) -> Dict[str, Any]:
        prompt = self.mode_prompt(str(kwargs.get("session_id") or ""))
        if not prompt:
            return {"action": "continue"}
        prompt += "\n" + operational_rules
        items = deepcopy(kwargs["items"])
        last_system = next(
            (i for i, item in enumerate(items) if item.get("item_type") != "SystemMessageItem"), len(items)
        )
        items.insert(
            last_system,
            {
                "item_type": "SystemMessageItem",
                "meta": {
                    "item_id": "group-mode-" + uuid4().hex,
                    "logical_turn_id": None,
                    "timestamp": datetime.now(SHANGHAI).isoformat(),
                },
                "parts": [{"type": "text", "text": prompt}],
            },
        )
        return {"action": "continue", "modified_kwargs": {**kwargs, "items": items}}

    def replyer(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self.mode_prompt(str(kwargs.get("session_id") or ""))
        if not prompt:
            return {"action": "continue"}
        if self.record(
            next(g for g, s in self.sessions.items() if s == str(kwargs.get("session_id") or ""))
        ).get("eq_mode"):
            prompt = "高情商模式已开启：本轮按系统中的夸张土味技能开口就撩，用情话梗和反转把对方逗笑；不要只给普通安慰。"
        return {
            "action": "continue",
            "modified_kwargs": {
                **kwargs,
                "extra_prompt": str(kwargs.get("extra_prompt") or "")
                + "\n"
                + prompt
                + "\n"
                + NEWS_REPLY_GUIDE,
            },
        }

    async def tick(self, now: Optional[float] = None) -> None:
        if not self.owner.config.plugin.enabled:
            return
        now = time.time() if now is None else now
        await self.resolve_sessions()
        for group, stream_id in list(self.sessions.items()):
            if group not in self.owner.config.groups.allowed_group_ids or not stream_id:
                continue
            async with self.lock:
                rec = self.record(group)
                if not may_trigger(self.owner.config.proactive, rec, now, self.activity.get(group, now)):
                    continue
                day = datetime.fromtimestamp(now, SHANGHAI).date().isoformat()
                rec["count"] = (rec.get("count", 0) if rec.get("date") == day else 0) + 1
                rec.update(date=day, next_due=now + self.next_interval(), last_attempt=now)
                # 先持久化额度，避免进程重启后重复触发或异常时每分钟重试刷屏。
                await self.save()
            result = await self.owner.ctx.maisaka.proactive.trigger(
                stream_id,
                "群里已经安静了一会儿。请你主动开一个轻松自然的新话题，像熟悉的群友一样发一两句，"
                "可以接最近的群聊内容、聊吃饭或日常小趣事。不要说是定时任务，不催人回复、不@全体。"
                "若聊到今天或最近的新闻必须先联网核实并给来源；不要重复你上次主动说过的话。"
                "若语境不适合开口就选择安静。",
                reason="已到主动聊天间隔，且群内冷场达到设定时长",
                metadata={"source": "local_group_proactive", "group_id": group},
            )
            self.owner.ctx.logger.info(f"主动话题任务：group={group} accepted={bool(result.get('success'))}")

    async def loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.owner.ctx.logger.warning(f"主动聊天检查失败：{type(exc).__name__}")
