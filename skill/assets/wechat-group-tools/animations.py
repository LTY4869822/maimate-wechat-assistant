"""只从宿主已注册表情中筛选真实多帧 GIF，按情绪挑选后走 SDK 发送。"""

from hashlib import sha256
from io import BytesIO
from typing import Any, Dict, List

import asyncio
import base64
import json
import re

from PIL import Image


def animated_candidates(emojis: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    candidates = []
    for entry in emojis[:64]:
        encoded = str(entry.get("base64") or "")
        if len(encoded) > 7 * 1024 * 1024:
            continue
        try:
            data = base64.b64decode(encoded, validate=True)
            if not data.startswith((b"GIF87a", b"GIF89a")):
                continue
            with Image.open(BytesIO(data)) as image:
                if image.format != "GIF" or image.n_frames < 2:
                    continue
            candidates.append(
                {
                    "base64": encoded,
                    "description": str(entry.get("description") or entry.get("emotion") or "动态表情"),
                    "hash": sha256(data).hexdigest(),
                }
            )
        except (ValueError, OSError):
            continue
    return candidates


async def send_dynamic(owner: Any, emotion: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    group = str(kwargs.get("group_id") or "")
    if (
        not owner.config.plugin.enabled
        or kwargs.get("platform") != "wechat"
        or group not in owner.config.groups.allowed_group_ids
    ):
        return {"success": False, "content": "只能给当前已授权微信群发送动态表情。"}
    await owner.behavior.resolve_sessions()
    stream_id = owner.behavior.sessions.get(group)
    if not stream_id or stream_id != str(kwargs.get("stream_id") or kwargs.get("chat_id") or ""):
        return {"success": False, "content": "没有找到当前小号对应的真实群会话。"}
    emojis = await owner.ctx.emoji.get_all()
    if not isinstance(emojis, list):
        return {"success": False, "content": "读取宿主表情库失败。"}
    candidates = await asyncio.to_thread(animated_candidates, emojis)
    if not candidates:
        return {"success": False, "content": "当前表情库没有已注册的多帧 GIF，不能把静态图片假称为动图。"}
    last_hash = owner.behavior.record(group).get("last_dynamic_hash")
    fresh = [entry for entry in candidates if entry["hash"] != last_hash]
    if fresh:
        candidates = fresh
    labels = [{"index": i, "description": entry["description"]} for i, entry in enumerate(candidates)]
    result = await owner.ctx.llm.generate(
        "从候选动态表情中选最贴合聊天语境与情绪的一张。只输出 index 数字，不加解释。\n"
        + "语境与情绪："
        + emotion[:240]
        + "\n候选："
        + json.dumps(labels, ensure_ascii=False),
        task_name="replyer",
        max_tokens=32,
        temperature=0.1,
    )
    answer = str(result.get("response") or "").strip()
    if not result.get("success") or not re.fullmatch(r"\d+", answer) or int(answer) >= len(candidates):
        return {"success": False, "content": "动态表情选择没有返回有效序号，本次未发送。"}
    chosen = candidates[int(answer)]
    sent = await owner.ctx.send.emoji(chosen["base64"], stream_id, return_details=True)
    if not isinstance(sent, dict) or not sent.get("sent"):
        return {"success": False, "content": "动态 GIF 已选出，但微信投递失败，不能声称已发送。"}
    async with owner.behavior.lock:
        owner.behavior.record(group)["last_dynamic_hash"] = chosen["hash"]
        await owner.behavior.save()
    owner.ctx.logger.info(f"动态 GIF 已投递：group={group} description={chosen['description']}")
    return {
        "success": True,
        "content": "已发送一张保留原始帧的动态 GIF。",
        "data": {"description": chosen["description"], "message_id": sent.get("message_id")},
    }
