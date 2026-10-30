# 完整离线整合包

适用于用户要求保存源码和依赖、上游删除后仍可重装的情况。离线包同时是独立安装器，不要求接收者安装Codex或先装Python。

## 定位与执行

寻找用户提供的 `WeChatGroupAssistant-Offline-1.2.0.zip` 或解压目录；1.1.0完整包仍可由通用入口部署。优先使用 [agent-platforms.md](agent-platforms.md) 的自动发现、解压和续跑入口，不遍历个人微信数据。解压目录应有 `offline-manifest.json`、`offline_install.py`、`runtimes`、`wheelhouse`、`sources`、`locks`、`licenses` 和 `skill`。没有离线包时请用户提供其本地位置，不擅自切回上游下载。

双击「安装.cmd」，或自动执行：

```powershell
& "<bundle>/runtimes/python312/python.exe" -I -B "<bundle>/offline_install.py" --root "<root>"
```

`--verify-only` 只校验整合包。安装器在独立目录创建两套Python环境，使用空安装缓存、`uv --offline`、`--no-index`、包内wheelhouse和带SHA-256的完整锁文件，不调用GitHub/PyPI，也不安装语音。运行时Python复制进安装目录，安装后移动整合包不会破坏已安装环境。

不覆盖非本包管理的旧部署；旧在线版目录请换新位置后单独迁移，不复制旧微信密钥或账号。重跑保留已有模型Key、群绑定及行为状态。安装器不会自动启动微信、发消息、同意条款或调用模型。

## 本人设置

安装成功后按安装目录入口操作：

1. 「配置模型密钥.cmd」：遮挡录入自己的Key，阅读并同意MaiBot条款。
2. 「启动群聊助手.cmd」：启动本机MaiBot和桥接，面板地址见FIRST-RUN.txt。
3. 在Flandora取钥向导阅读声明，开始取钥，扫码并手机确认；小号已在目标群内。
4. 「选择群聊.cmd」：读取当前小号群列表，核对账号后选择群；可选主动话题。
5. 由另一账号发消息，按acceptance.md验收实际群回复、人数、动态GIF、新闻与情话开关。

需已安装兼容的官方Windows微信客户端。离线指安装和重装过程，不代表微信、模型API或新闻检索不需要网络，也不代表未来微信版本永远兼容。不要为了测试断网而关闭正在使用的电脑网络；可使用新目录、空缓存、禁外网测试守卫和UV离线模式验证安装。

## 归档与校验

`sources`保存主体源码、依赖源包、CPython/uv/FFmpeg源码与构建脚本；`wheelhouse`保存Windows对应安装轮；`dependency-inventory.json`记录版本、原始来源、SHA和许可位置。所有修改源码与第三方许可原文一并保留，不把合集重新许可为全部自研。

发生缺文件或校验不符时停止，恢复完整压缩包；离线安装不允许通过联网补缺来掩盖归档不完整。不要删除wheelhouse、sources、runtimes和licenses后再宣称此包仍可从零离线安装。
