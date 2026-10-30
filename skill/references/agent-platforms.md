# Agent 通用接入与自动配置

## 导入

通用技能 ZIP 的根目录直接是 `SKILL.md`，另有 `scripts/`、`references/`、`assets/` 和可选 `agents/openai.yaml`。后者仅为 Codex 显示信息，其他宿主无需读取。没有 WorkBuddy/豆包专属私有 SDK，也不假设宿主工具名或技能安装目录。

- WorkBuddy Windows：专家·技能·连接器 → 技能 → 添加技能 → 上传技能，选通用小 ZIP，启用后在本机工作区提出部署请求。[官方技能说明](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)。将离线包放在工作区或传其本地路径；资料库上传不等于本机文件可用。
- 豆包工作/有技能功能的电脑版：在当前版本的技能管理入口上传同一 ZIP；若界面提供「技能·连接器·伙伴 → 新建 → 上传技能」，使用此入口。选择能访问运行微信的这台 Windows 电脑的任务。入口与授权以当前客户端实际界面为准，不假设网页版或手机聊天端具有本机执行能力。
- 其他支持 Agent Skills 的本机 Agent：导入 ZIP 或完整技能文件夹，保留所有附带文件。[开放结构规范](https://agentskills.io/specification)。仅粘贴 SKILL.md 会丢失执行脚本和兼容资源。

导入不会自动同意条款、开始扫码或发送群消息。首次对话可直接说：

> 使用微信群聊助手技能，在本机自动完成离线安装和配置。完整离线包在「我提供的本地路径」。保留已有数据，需要填写密钥、扫码或选群时再叫我。

小技能包负责发现和操作；完整离线包保存全部 Python、wheel、源码和资源，必须一并交给接收者。无需把近900MB离线包上传到技能导入器。环境受限时请求授权本机目录或切换本地任务，不改系统安全策略或擅自安装远程控制组件。

## 自动入口

使用宿主自带终端工具，以 PowerShell 运行脚本（当前终端已是PowerShell时直接用 `&`；其他终端可以 `powershell.exe -NoProfile -File`）：

```powershell
& "<skill>/scripts/bootstrap.ps1" -Agent doubao -ResourcePath "<完整离线ZIP或解压目录>" -Root "<安装目录>" -Action Doctor
& "<skill>/scripts/bootstrap.ps1" -Agent doubao -ResourcePath "<完整离线ZIP或解压目录>" -Root "<安装目录>" -Action Onboard
```

`ResourcePath` 可省略：在当前工作区及其 deliverables、技能相邻目录、下载、桌面中有限查找。也可由使用者设置 `WECHAT_ASSISTANT_BUNDLE`。优先续用已有标准安装或显式 `Root`；不搜索微信数据。默认新安装位置为当前用户本地应用数据目录的 WeChatGroupAssistant，`Root` 在整个流程保持一致。

`-Probe` 仅报告发现的资源，不解压、不安装、不启动。Doctor 检查本机能力与状态，不启动服务；若资源还是ZIP，它会准备解压副本。Onboard 使用包内 Python，离线安装后分阶段续跑，停止在真正需要本人参与的位置。配置窗口重复调用会复用仍存活的本安装窗口。

若 `.ps1` 被宿主或执行策略阻止，使用本机文件工具解压完整 ZIP，再通过无需PS脚本的入口执行同一 Python 流程：

```powershell
& "<skill>/scripts/bootstrap.cmd" "<解压后的完整离线包或已有安装目录>" --host doubao --root "<安装目录>" doctor
& "<skill>/scripts/bootstrap.cmd" "<解压后的完整离线包或已有安装目录>" --host doubao --root "<安装目录>" onboard
```

也可直接调用 `<resource>/runtimes/python312/python.exe -I -X utf8 -B <skill>/scripts/agent_entry.py <resource> --host generic --root <root> onboard`。对已安装目录，Python在 `MaiBot/.venv/Scripts/python.exe`。不使用 ExecutionPolicy Bypass，不修改系统Python、PATH或全局技能配置。

## 阶段与续跑

| phase | Agent 下一步 |
|---|---|
| installation_required | 自动执行 Onboard 完成包校验和离线准备 |
| awaiting_model_key_and_terms | 本机已弹出遮挡输入窗口；请用户保存并阅读条款，再续跑 |
| awaiting_wechat_login | 打开本安装 Flandora 面板；本人扫码和手机确认后续跑 |
| awaiting_group_selection | 本机已弹出群选择窗口；选择后续跑，或使用用户已经明确的 GroupName |
| services_not_ready | 检查本安装的启动状态与日志，不能冒称已完成 |
| awaiting_message_acceptance | 执行只读 Verify，再由另一账号做群内实际验收 |

用户已经指定群名时，可在 Onboard 加 `-GroupName "用户选择的群"`；同名多个群会要求区分，不猜群ID。`-Proactive preserve` 默认保留现有开关和频率，`on`/`off` 只用于用户明确要求。`-NoBrowser` 供无需自动打开面板的场景。

`-Action Status` 输出经过筛选的状态，不显示 Key、令牌或群成员；`-Action Verify -Live` 只读核对账号、插件和连接，不调用模型或发群消息。命令退出码非0就检查错误，不把它当成功。Doctor码20表示缺少本机 Windows 交互环境；bootstrap.cmd码18表示缺少包内Python。

`agent-onboarding.json` 仅保存技能版本、宿主与阶段。密钥、群绑定、情话模式和主动话题状态继续由本机安装原有文件保存。切换 Agent 不需要重建机器人，也不共享前一位使用者的账号。
