# 新机器安装

这是标准在线模式的说明。若用户要求不访问上游、使用完整离线包，先读 [offline.md](offline.md)，不要运行下面的下载流程。

验证基线（2026-10-29）：Windows x64，微信4.1.15.56，MaiBot1.3.16，SDK2.16.0，Dashboard1.9.10，maim-message0.6.8，Flandora/适配器1.0.0；Python分别3.12.8、3.13.15。源码和依赖见 `assets/versions.json` 与约束文件。这是带本地兼容修复的组合，不代表未来微信版本均兼容。

## 自动准备

选独立目录，例如用户本地应用数据下 `WeChatGroupAssistant`。先 `setup.py --root <root> --plan`，再 `prepare`。脚本下载固定提交源码、校验官方发行包 SHA-256、检查补丁指纹、安装两套独立环境、补齐官方 ffmpeg/取钥器、生成随机令牌和空闲回环端口、初始化配置及启动入口。初始群/私聊全拦截。重跑复用令牌和端口，不重置配置。

`--cache <dir>` 可复用下载，`--offline` 只用完整缓存。网络失败保留部分文件，重跑续传。解压拒绝越界路径，不创建文件系统符号链接；上游安全的同包文件别名复制为普通文件。需要约186MiB发行包及 Python/依赖、几GB磁盘空间。保持 TLS 校验，不修改系统代理/证书/防火墙来凑成功。

`uv` 缺失可用 `python -m pip install --user uv==0.12.5`；Python缺失先用宿主提供的运行时，否则代理从官方渠道安装。源码下载无需Git。

## 本人节点

打开新部署 Flandora 面板，阅读声明，按取钥向导先开始取钥，再扫码/手机确认。小号先加入目标群；切换账号需新的账号专属数据库口令。

部署目录「配置模型密钥」入口遮挡录入 DeepSeek Key，可修改模型标识；展示 MaiBot EULA/隐私原文，只有本人勾选同意才生成确认标记。保存后启动 MaiBot；程序运行中保存用本机热更新接口。

群名确定后 `manage.py bind --group-name <精确群名>`。同名多个补 `--group-id`，不能挑第一项。脚本从当前wxid找到登录标记和数据目录，通过目录联接固定小号范围，不复制微信数据库。无法唯一定位时需要 `--account-data` 与 `--login-dir`，不猜另一账号目录。用户要主动话题才加 `--proactive`。

## 模型与来源

DeepSeek Flash 的可用性、视觉、Search & Fetch 以实测为准；这些仍消耗用户模型账户用量，不宣称所有能力免费。固定模型下线时查官方模型列表，再明确选择和测试兼容模型，不能把404隐藏为成功。

- [MaiBot](https://github.com/Mai-with-u/MaiBot)：GPL-3.0。
- [Flandora](https://github.com/OMSociety/Flandora)：MIT。
- [MaiBot-Flandora-Adapter](https://github.com/OMSociety/MaiBot-Flandora-Adapter)：AGPL-3.0-or-later。
- [simp-skill](https://github.com/BeamusWayne/simp-skill)：MIT；风格素材保留原文、许可和来源。

兼容源码及许可随包提供。公开面板静态文件取自同版本产物，不含运行配置。勿自动同意条款，勿自动产生不在用户意图内的新付费服务。
