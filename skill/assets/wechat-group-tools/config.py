"""本机微信群能力配置；群查询默认关闭，按明确的群 ID 放行。"""

from typing import List

from maibot_sdk import Field, PluginConfigBase


class PluginSection(PluginConfigBase):
    config_version: str = Field(default="1.0.0", description="配置结构版本")
    enabled: bool = Field(default=True, description="启用本机微信群能力")


class BridgeSection(PluginConfigBase):
    port: int = Field(default=7999, ge=1, le=65535, description="本机 Flandora OneBot 端口")
    token: str = Field(default="", description="本机 Flandora 访问令牌")


class GroupSection(PluginConfigBase):
    allowed_group_ids: List[str] = Field(
        default_factory=list, description="允许查询资料的群 ID；空列表不放行"
    )
    bot_account_id: str = Field(default="", description="机器人小号 ID；主动聊天和模式指令只接受此账号")


class ProactiveSection(PluginConfigBase):
    enabled: bool = Field(default=False, description="允许按冷场与频率限制主动开话题")
    start_hour: int = Field(default=9, ge=0, le=23)
    end_hour: int = Field(default=23, ge=1, le=24)
    idle_minutes: int = Field(default=10, ge=5, le=120)
    interval_min_minutes: int = Field(default=60, ge=20, le=360)
    interval_max_minutes: int = Field(default=90, ge=20, le=720)
    daily_limit: int = Field(default=4, ge=1, le=12)


class EmojiSection(PluginConfigBase):
    import_starter_emoji: bool = Field(default=True, description="加载插件数据目录中选定的群表情")
    max_import_count: int = Field(default=12, ge=1, le=32, description="单次最多导入数量")


class Settings(PluginConfigBase):
    plugin: PluginSection = Field(default_factory=PluginSection)
    bridge: BridgeSection = Field(default_factory=BridgeSection)
    groups: GroupSection = Field(default_factory=GroupSection)
    emoji: EmojiSection = Field(default_factory=EmojiSection)
    proactive: ProactiveSection = Field(default_factory=ProactiveSection)
