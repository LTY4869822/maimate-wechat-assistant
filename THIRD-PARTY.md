# 许可与来源

本整合包是开源软件及运行资源的合集，不改变原项目许可。新增安装脚本及原创群工具/动态图按skill/LICENSE提供；其他部分保留各自版权、许可和例外条款。

- MaiBot1.3.16：GPL-3.0；原始完整源码在sources/MaiBot-source.zip，完整许可在licenses/MaiBot-GPL-3.0.txt。
- Flandora1.0.0：MIT；原始完整源码、官方发行包均在sources，本地修改源码及逐文件指纹在skill/assets/compat与versions.json。
- MaiBot-Flandora-Adapter1.0.0：AGPL-3.0-or-later；原始发布源码包与所有修改源码均随包，许可在skill/assets/compat/adapter/LICENSE。
- simp-skill情话素材：MIT；原文、来源及许可保存在skill/assets/wechat-group-tools/third_party/simp-skill。
- CPython3.12.8/3.13.15：原始运行时许可保存在runtimes和licenses；核心源码归档在sources/runtime-source。运行时剔除了制作者的site-packages、Scripts、安装日志和字节码，只保留公开标准库与运行文件。
- uv0.12.5：Apache-2.0或MIT双许可；两份原文及源码归档随包。
- FFmpeg及共享DLL：沿用Flandora官方固定的BtbN LGPL共享构建；许可、FFmpeg对应提交源码、BtbN对应构建脚本归档随包。FFmpeg及DLL保持独立文件，允许按适用许可替换；没有静态并入新增程序。
- Python依赖：wheel自身保留全部原始dist-info/许可；另在licenses/dependencies提取可获得的许可原文，并保存PyPI提供的依赖源码归档。dependency-inventory.json逐项记录版本、wheel SHA、原始来源和许可位置。

未打入腾讯微信客户端、任何微信账号、登录数据库、用户聊天数据或模型服务。微信和模型服务有各自使用条款，安装者自行操作和授权。

sources中的原始源包加skill/assets/compat中的修改源码共同描述当前工作版本；安装不依赖这些来源URL继续存在。请随分享完整保留本文件、许可、源码和资源。
