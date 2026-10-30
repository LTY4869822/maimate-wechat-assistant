"""通过本机 OneBot 连接查询一个群；不包含任何发送动作。"""

from typing import Any, Dict
from urllib.parse import quote
from uuid import uuid4

import asyncio
import json

import websockets


class GroupQueryError(Exception):
    """群资料尚不可用，调用方应如实报告。"""


async def query_group_info(port: int, token: str, group_id: str) -> Dict[str, Any]:
    if not group_id.isdecimal():
        raise GroupQueryError("群 ID 格式无效")
    echo = "group-info-" + uuid4().hex
    uri = f"ws://127.0.0.1:{port}/?access_token={quote(token, safe='')}"
    async with asyncio.timeout(8):
        async with websockets.connect(
            uri, open_timeout=5, close_timeout=1, max_size=24 * 1024 * 1024
        ) as connection:
            await connection.send(
                json.dumps({"action": "get_group_info", "params": {"group_id": int(group_id)}, "echo": echo})
            )
            async for raw in connection:
                response = json.loads(raw)
                if response.get("echo") != echo:
                    continue
                if response.get("retcode") != 0:
                    raise GroupQueryError("微信本地群资料查询失败")
                data = response.get("data")
                if not isinstance(data, dict):
                    raise GroupQueryError("微信本地群资料为空")
                count = data.get("member_count")
                if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                    raise GroupQueryError("当前本地群资料没有完整的成员数量")
                return {
                    "group_id": group_id,
                    "group_name": str(data.get("group_name") or ""),
                    "member_count": count,
                }
    raise GroupQueryError("群资料连接已关闭")
