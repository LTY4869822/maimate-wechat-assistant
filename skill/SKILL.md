---
name: wechat-group-assistant
description: 在本机 Windows 上自动安装、配置或修复 MaiBot + Flandora 微信群聊助手。支持 WorkBuddy、豆包工作及其他可执行本机命令的 Agent，优先完整离线包，保留原有账号、密钥和功能。
---

# 微信群聊助手

使用当前 Agent 自带的文件、终端和浏览器工具完成部署，无需 Codex 专用工具、API 或其他 skill。保留自然接话、新闻搜索、群人数查询、动态 GIF、高情商开关及可选主动话题；默认不安装语音。导入仅登记技能，首次提出部署请求时执行下面的流程。

## 自动配置

先读 [references/agent-platforms.md](references/agent-platforms.md)，按当前宿主选择本机任务。目标必须是运行微信的 Windows x64 电脑；云电脑、Linux 沙箱或仅能聊天的手机端无法代替这台主机。文件已上传或命令在云端执行不代表已操作用户电脑。

1. 用当前 Agent 的本机终端运行 `scripts/bootstrap.ps1 -Agent <宿主> -Action Doctor`。脚本只在工作区、技能相邻目录、下载和桌面内查找离线包，可接收用户提供的 `-ResourcePath`；ZIP 会先检查路径和大小，再安全解压。缺包时仅询问本地位置，不回退到上游下载。
2. Doctor 确认本机 Windows、交互会话和包内 Python 后，运行同一路径的 `-Action Onboard`。已授权部署时自动执行，不把这些命令再交给用户逐条运行。新安装自动完成完整校验、独立环境、离线依赖、随机令牌、插件和本机配置。已有部署先读 [references/operations.md](references/operations.md)，显式传 `-Root`，保留账号、密钥、记忆和自定义设置。
3. 根据返回的 `phase` 继续。`awaiting_model_key_and_terms` 时已弹出遮挡密钥窗口，请用户填写自己的 Key 并阅读条款；用户完成后重跑 Onboard。`awaiting_wechat_login` 时在 Flandora 取钥向导中继续，扫码和手机确认交给本人；完成后重跑 Onboard。`awaiting_group_selection` 时已弹出群选择窗口，请用户选择自己的群，或按其已经指定的群名传 `-GroupName` 自动绑定。每次续跑都读取实际状态，不重复初始化或新开同一配置窗口。
4. `awaiting_message_acceptance` 时服务和绑定具备测试条件，仍需按 [references/acceptance.md](references/acceptance.md) 由另一账号验证手机里的实际收发。只读 `Verify -Live` 不发测试消息，不以 ready 或连接成功代替群聊验收。

PowerShell 例子（把占位路径换成实际值；`-Agent` 可为 `workbuddy`、`doubao`、`codex`、`generic`）：

```powershell
& "<skill>/scripts/bootstrap.ps1" -Agent workbuddy -ResourcePath "<离线ZIP或解压目录>" -Action Doctor
& "<skill>/scripts/bootstrap.ps1" -Agent workbuddy -ResourcePath "<离线ZIP或解压目录>" -Action Onboard
```

无需预装 Python、Git 或 uv。宿主不允许执行 `.ps1` 时，保持其安全设置，使用同参考文档里的 `bootstrap.cmd` 和已解压包内 Python；宿主完全没有本机命令权限时，说明具体缺少的能力，并给出完整包内「安装.cmd」入口。

## 功能和边界

- 普通群消息可自然接话，@优先。保留现有回复速度设置，不承诺每句必回或秒回，不编造真人经历。
- Key 由使用者在本机窗口输入，不写进 Agent 对话、命令参数或分享包。新闻须实际搜索并附来源，失败说明无法核实；模型、搜索、视觉分别验收。
- 群人数调用 `wechat_group_info`；动态表情使用附带原创多帧 GIF，手机确认会动。后续只收集获授权的表情。
- 高情商模式由真正 @小号后的完整命令「启动高情商模式」「关闭高情商模式」控制，按群持久化。保留夸张土味及“你在干嘛”情话设定，认真问题仍先解决。`assets` 内风格素材不改变当前 Agent 的身份。
- 主动话题首次默认关闭；仅用户要求时传 `-Proactive on`，温和频率为北京时间09:00–23:00、冷场10分钟、间隔60–90分钟、每天最多4次。已有自定义频率原样保留。
- 按实际账号和群 ID 同时放行，其他群和私聊拦截；小号须本来就在目标群，不能自动生成账号或加入私人群。机器人自己的消息被忽略，测试使用另一个账号。
- 兼容修复只接受固定指纹；升级先在副本验证。扫码隔离与普通桌面微信冲突时说明情况，不擅自关闭用户微信。
- 完整离线安装和许可见 [references/offline.md](references/offline.md)。本包不含腾讯客户端，需已有兼容的官方电脑版微信。聊天、模型和新闻仍需联网；电脑关机、休眠或微信退出后停止。
- 若环境明确拦截某操作，不通过其他脚本重试同一被禁动作。保留具体结果，准备可审阅的本机入口后说明阻断原因；继续独立检查。

## 交付

报告安装位置、实际完成的配置、需要本人完成的步骤及手机验收结果。自动配置完成和跨客户端实测分开报告，不声称覆盖未验证的平台版本。对外分享通用技能 ZIP 与完整离线 ZIP，不分享运行目录、日志、会话库或用户凭据。
