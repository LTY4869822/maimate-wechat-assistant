"""微信群实际资料工具与本机选定表情导入，不修改 MaiBot 主程序。"""

from datetime import datetime
from typing import Any, ClassVar, Dict, Optional

import asyncio
import base64
import json

from maibot_sdk import HookHandler, MaiBotPlugin, Tool

from .config import Settings
from .behavior import GroupBehavior
from .animations import send_dynamic
from .group_query import GroupQueryError, query_group_info


class WechatGroupTools(MaiBotPlugin):
    config_model: ClassVar[type[Settings]] = Settings

    def __init__(self) -> None:
        super().__init__()
        self._import_task: Optional[asyncio.Task[None]] = None
        self.behavior = GroupBehavior(self)

    async def on_load(self) -> None:
        if not self.config.plugin.enabled:
            return
        self.ctx.logger.info("微信群资料工具已加载")
        await self.behavior.load()
        if self.config.emoji.import_starter_emoji:
            self._import_task = asyncio.create_task(self._import_emoji_library())

    async def on_unload(self) -> None:
        await self.behavior.stop()
        if self._import_task is not None:
            self._import_task.cancel()
            try:
                await self._import_task
            except asyncio.CancelledError:
                pass
            self._import_task = None

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        del version
        if scope == "self":
            self.set_plugin_config(config_data)

    @HookHandler("chat.receive.after_process", timeout_ms=20000)
    async def receive_group_message(self, message: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        del kwargs
        return await self.behavior.receive(message)

    @HookHandler("maisaka.planner.before_request")
    async def group_planner_style(self, **kwargs: Any) -> Dict[str, Any]:
        return self.behavior.planner(kwargs)

    @HookHandler("maisaka.replyer.before_request")
    async def group_replyer_style(self, **kwargs: Any) -> Dict[str, Any]:
        return self.behavior.replyer(kwargs)

    @HookHandler("maisaka.replyer.before_model_request")
    async def group_replyer_system_style(self, **kwargs: Any) -> Dict[str, Any]:
        return self.behavior.model_request(kwargs)

    @Tool(
        "send_dynamic_emoji",
        description="按聊天语境发送一张真正的动态 GIF 表情。有人要动态表情或一般表情包时优先使用；只从已注册的多帧 GIF 中挑选，避免连续重复同一张。",
        parameters={
            "emotion": {
                "type": "string",
                "description": "当前聊天语境与想表达的情绪，例如开心卖萌、无语吐槽",
                "maxLength": 240,
            }
        },
        platforms="wechat",
        chat_scope="group",
    )
    async def dynamic_emoji(self, emotion: str = "贴合当前聊天", **kwargs: Any) -> Dict[str, Any]:
        return await send_dynamic(self, emotion, kwargs)

    @Tool(
        "wechat_group_info",
        description="查询当前微信群的实际群名和成员总数。有人问群里多少人、几位群友时必须先查这个工具；人数来自微信本地群资料，包含机器人小号，不凭聊天记录估计。",
        parameters=[],
        platforms="wechat",
        chat_scope="group",
    )
    async def current_group_info(self, **kwargs: Any) -> Dict[str, Any]:
        platform = str(kwargs.get("platform") or "").strip().lower()
        group_id = str(kwargs.get("group_id") or "").strip()
        if not self.config.plugin.enabled or platform != "wechat" or not group_id:
            return {"success": False, "content": "只能在已授权的微信群会话中查询群资料。"}
        if group_id not in self.config.groups.allowed_group_ids:
            return {"success": False, "content": "当前群未授权群资料查询。"}
        if not self.config.bridge.token:
            return {"success": False, "content": "本机群查询连接尚未配置。"}
        try:
            data = await query_group_info(self.config.bridge.port, self.config.bridge.token, group_id)
        except GroupQueryError as exc:
            return {"success": False, "content": str(exc)}
        except Exception as exc:
            self.ctx.logger.warning(f"群资料连接失败：{type(exc).__name__}")
            return {"success": False, "content": "暂时无法连接本机微信群资料，请稍后再试；不要估计人数。"}
        name = data["group_name"] or "当前微信群"
        return {
            "success": True,
            "content": f"刚查询到【{name}】共有 {data['member_count']} 位成员，包含麦麦当前使用的小号。",
            "data": {**data, "queried_at": datetime.now().isoformat(timespec="seconds")},
        }

    async def _import_emoji_library(self) -> None:
        status: Dict[str, Any] = {"completed": False, "imported": 0, "failed": 0}
        try:
            seed_dir = self.ctx.paths.data_dir / "starter_emoji"
            if not seed_dir.is_dir():
                status["completed"] = True
                return
            files = [
                p
                for p in seed_dir.iterdir()
                if p.is_file() and p.suffix.lower() in {".png", ".gif", ".jpg", ".jpeg", ".webp"}
            ]
            for path in sorted(files)[: self.config.emoji.max_import_count]:
                data = await asyncio.to_thread(path.read_bytes)
                if not data or len(data) > 5 * 1024 * 1024:
                    status["failed"] += 1
                    continue
                result = await self.ctx.emoji.register_emoji(base64.b64encode(data).decode("ascii"))
                if isinstance(result, dict) and result.get("success"):
                    status["imported"] += 1
                else:
                    status["failed"] += 1
            status["completed"] = True
            self.ctx.logger.info(f"本机群表情导入完成：可用 {status['imported']}，失败 {status['failed']}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status["error_type"] = type(exc).__name__
            self.ctx.logger.warning(f"表情导入未完成：{type(exc).__name__}")
        finally:
            self.ctx.paths.data_dir.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                (self.ctx.paths.data_dir / "emoji-import-status.json").write_text,
                json.dumps(status, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


def create_plugin() -> MaiBotPlugin:
    return WechatGroupTools()
