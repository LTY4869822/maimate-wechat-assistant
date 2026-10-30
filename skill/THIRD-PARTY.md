# 第三方归属

本包新增脚本、说明、群工具和原创动态表情按根目录 MIT 许可提供；不替换或覆盖第三方许可。

| 内容 | 来源与版本 | 许可及位置 |
| --- | --- | --- |
| Flandora 兼容源码和公开面板静态产物 | [OMSociety/Flandora](https://github.com/OMSociety/Flandora)，v1.0.0 / 5a58817f836f86e64a199f14bfcb74856388fa51 | MIT，`assets/compat/flandora/LICENSE` |
| 适配器贴纸识别修改及测试源码 | [OMSociety/MaiBot-Flandora-Adapter](https://github.com/OMSociety/MaiBot-Flandora-Adapter)，v1.0.0 | AGPL-3.0-or-later，`assets/compat/adapter/LICENSE`；此部分的修改也按相同许可提供 |
| 情话风格素材与原文 | [BeamusWayne/simp-skill](https://github.com/BeamusWayne/simp-skill) | MIT，`assets/wechat-group-tools/third_party/simp-skill/LICENSE`；来源记录同目录SOURCE.json |
| 运行时下载的 MaiBot | [Mai-with-u/MaiBot](https://github.com/Mai-with-u/MaiBot)，1.3.16 / fe88ec6b6053e40eaf430cb5ba7ed7e805add2cb | GPL-3.0，下载源码自带LICENSE；本包不重新分发其完整源码 |
| 运行时下载的 ffmpeg 与取钥器 | 上述 Flandora 官方 v1.0.0 发行包 | 发行包自带许可；安装时连同tools内的许可一起保存 |

Flandora 修改包括多消息库发现与WAL/SHM刷新、Windows COM/隔离桌面配对、发送控件搜索提前结束、动态GIF原文件投递及对应回归测试；没有语音扩展。适配器修改保留贴纸类型与宿主表情识别。逐文件原始/修改后指纹见 `assets/versions.json`；全部修改源码随包提供。

启动本 skill 不产生第三方服务授权；扫码登录、软件条款、模型Key和账户用量仍由安装者本人处理。
