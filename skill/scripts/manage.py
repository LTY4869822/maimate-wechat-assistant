"""Local configuration, account binding and read-only verification for this installation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from common import digest, read_json, state_for, write_json


def resource(name: str) -> Path:
    bundled = Path(__file__).resolve().parents[1] / "assets" / name
    return bundled if bundled.is_file() else Path(__file__).with_name(name)


def backup(path: Path, root: Path) -> None:
    if path.is_file():
        target = (
            root
            / "backups"
            / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            / path.relative_to(root)
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def write_toml(path: Path, data: dict, root: Path) -> None:
    import tomlkit

    backup(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(tomlkit.dumps(data), encoding="utf-8")
    temporary.replace(path)


def credentials(root: Path, create: bool = False) -> dict:
    path = root / "local-credentials.json"
    if path.exists():
        return read_json(path)
    if not create:
        raise FileNotFoundError(
            "Local credentials are missing; restore this installation's backup"
        )
    data = {
        "bridge_token": secrets.token_urlsafe(32),
        "webui_token": "MaiBot!Aa-" + secrets.token_urlsafe(32),
    }
    write_json(path, data)
    return data


def bot_session(root: Path):
    import requests

    state = state_for(root)
    s = requests.Session()
    s.trust_env = False
    base = f"http://127.0.0.1:{state['ports']['bot_web']}/api/webui"
    response = s.post(
        base + "/auth/verify",
        json={"token": credentials(root)["webui_token"]},
        timeout=10,
    )
    response.raise_for_status()
    return s, base


def bridge_base(root: Path) -> str:
    return f"http://127.0.0.1:{state_for(root)['ports']['bridge_web']}"


def detect_wechat() -> str:
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = Path(os.environ.get(variable, "C:/__not_found__"))
        for relative in ("Tencent/Weixin/Weixin.exe", "Tencent/WeChat/WeChat.exe"):
            candidate = base / relative
            if candidate.is_file():
                return str(candidate)
    return ""


def initialize(root: Path) -> None:
    import tomlkit

    state = state_for(root)
    if state.get("initialized"):
        print("Existing configuration preserved.")
        return
    ports, keys = state["ports"], credentials(root, create=True)
    write_json(
        root / "Flandora-source/data/config.json",
        {
            "ob_server_host": "127.0.0.1",
            "ob_server_port": ports["onebot"],
            "ob_server_token": keys["bridge_token"],
            "ob_message_format": "array",
            "ob_networks": [],
            "isolated_desktop": True,
            "allow_foreground_steal": True,
            "web_port": ports["bridge_web"],
            "web_bind_host": "127.0.0.1",
            "wechat_exe": detect_wechat(),
            "wx_backfill_seconds": 0,
        },
    )
    bot_path = root / "MaiBot/config/bot_config.toml"
    config = tomlkit.loads(bot_path.read_text(encoding="utf-8"))
    config["http"].update(host=["127.0.0.1"], port=ports["bot_web"])
    config["maim_message"].update(
        ws_server_host="127.0.0.1",
        ws_server_port=ports["bot_legacy"],
        auth_token=[keys["bridge_token"]],
        enable_api_server=False,
    )
    config["bot"].update(
        platform="wechat", nickname="麦麦", alias_names=["小麦", "麦麦"]
    )
    config["personality"].update(
        personality="你叫麦麦，是群里的聊天伙伴。温和幽默，熟悉后轻松接梗，不编造真实生活经历。",
        behavior_style="不必等待@：看到相关闲聊、问题和玩笑可以自然接话。被点名时优先回应。看气氛，不抢每句话，没话可说就安静。",
        reply_style="自然中文口语，通常一两句。少套话，不用客服口吻，不重复群友原话。",
        multiple_probability=0.0,
    )
    config["chat"]["reply_timing"].update(
        talk_value=1.0,
        inevitable_at_reply=True,
        private_reply_paused=True,
        message_debounce_mode="off",
    )
    config["response_post_process"]["typing_speed"] = 0.0
    config["response_splitter"]["max_split_num"] = 1
    config["telemetry"]["enable"] = False
    config["debug"]["enable_console_input"] = False
    write_toml(bot_path, config, root)
    write_toml(
        root / "MaiBot/config/model_config.toml",
        read_json(resource("model-config.template.json")),
        root,
    )
    write_toml(
        root / "MaiBot/config/adapter_policy.toml",
        {
            "defaults": {
                "group": {"default_action": "block"},
                "private": {"default_action": "block"},
            }
        },
        root,
    )
    write_toml(
        root / "MaiBot/plugins/flandora-adapter/config.toml",
        {
            "plugin": {"enabled": True, "config_version": "1.0.0"},
            "client": {
                "server": "127.0.0.1",
                "port": ports["onebot"],
                "token": keys["bridge_token"],
                "reconnect_delay_sec": 5.0,
                "max_reconnect_delay_sec": 60.0,
                "heartbeat_interval_sec": 30.0,
                "action_timeout_sec": 30.0,
                "attachment_max_mb": 20,
            },
            "filters": {
                "ignore_self_message": True,
                "ban_user_id": [],
                "ban_group_id": [],
                "quote_wakes": True,
            },
            "notice": {
                "enable_group_recall": True,
                "enable_friend_recall": True,
                "enable_poke": True,
            },
            "debug": {"log_raw_events": False},
        },
        root,
    )
    write_toml(
        root / "MaiBot/plugins/wechat-group-tools/config.toml",
        {
            "plugin": {"config_version": "1.0.0", "enabled": True},
            "bridge": {"port": ports["onebot"], "token": keys["bridge_token"]},
            "groups": {"allowed_group_ids": [], "bot_account_id": ""},
            "proactive": {"enabled": False},
            "emoji": {"import_starter_emoji": True, "max_import_count": 12},
        },
        root,
    )
    seed = root / "MaiBot/data/plugins/local.wechat-group-tools/starter_emoji"
    shutil.copytree(root / "starter-emoji", seed, dirs_exist_ok=True)
    write_json(
        root / "MaiBot/data/webui.json",
        {
            "access_token": keys["webui_token"],
            "token_source": "configured",
            "first_setup_completed": False,
        },
    )
    for command, filename in (
        ("start", "启动群聊助手.cmd"),
        ("credentials", "配置模型密钥.cmd"),
        ("bind-window", "选择群聊.cmd"),
        ("verify --live", "检查群聊助手.cmd"),
    ):
        content = (
            '@echo off\nchcp 65001 >nul\ncd /d "%~dp0"\nset "PYTHONUTF8=1"\n'
            '"MaiBot\\.venv\\Scripts\\python.exe" "assistant_setup\\manage.py" --root "%CD%" '
            + command
            + "\nif errorlevel 1 pause\n"
        )
        (root / filename).write_text(content, encoding="utf-8")
    (root / "FIRST-RUN.txt").write_text(
        f"1. 打开「配置模型密钥」，阅读条款并保存自己的DeepSeek Key。\n"
        f"2. 双击「启动群聊助手」，Flandora面板：http://127.0.0.1:{ports['bridge_web']}\n"
        f"3. 取钥向导先开始取钥，再用机器人小号扫码并手机确认；小号须已在目标群。\n"
        f"4. 双击「选择群聊.cmd」，读取小号群列表并保存；用另一账号测试实际回复。\n"
        f"5. MaiBot面板：http://127.0.0.1:{ports['bot_web']}\n"
        "电脑关机/休眠/微信退出后不能继续回复。不要把local-credentials.json或备份发给别人。\n",
        encoding="utf-8",
    )
    state["initialized"] = True
    (root / "继续自动配置.cmd").write_text(
        '@echo off\nchcp 65001 >nul\ncd /d "%~dp0"\n'
        'call "assistant_setup\\bootstrap.cmd" "%CD%" --host generic onboard\n'
        "if errorlevel 1 pause\n",
        encoding="utf-8",
    )
    write_json(root / "installation.json", state)
    print("Local configuration prepared; no chat has been authorized or sent.")


async def query_binding(
    root: Path, name: str, group_id: str | None
) -> tuple[dict, dict]:
    import websockets

    state = state_for(root)
    token = quote(credentials(root)["bridge_token"], safe="")
    async with websockets.connect(
        f"ws://127.0.0.1:{state['ports']['onebot']}/?access_token={token}",
        open_timeout=10,
    ) as connection:

        async def call(action: str):
            echo = "bind-" + secrets.token_hex(8)
            await connection.send(
                json.dumps({"action": action, "params": {}, "echo": echo})
            )
            async with asyncio.timeout(20):
                while True:
                    result = json.loads(await connection.recv())
                    if result.get("echo") == echo:
                        if result.get("retcode") != 0:
                            raise RuntimeError(f"Bridge action failed: {action}")
                        return result["data"]

        login = await call("get_login_info")
        groups = await call("get_group_list")
    if not str(login.get("user_id") or "") or not isinstance(groups, list):
        raise RuntimeError("Bridge did not identify the current account and groups")
    matches = [
        g
        for g in groups
        if str(g.get("group_name", "")).strip() == name
        and (group_id is None or str(g.get("group_id")) == group_id)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one exact group, found {len(matches)}; specify --group-id for duplicate names"
        )
    return login, matches[0]


def junction(link: Path, target: Path) -> None:
    target = target.resolve(strict=True)
    if link.exists():
        if link.resolve() != target:
            raise ValueError(
                "An existing account scope points elsewhere; nothing was replaced"
            )
        return
    link.parent.mkdir(parents=True, exist_ok=True)

    # PowerShell native filesystem operation, no cmd handoff and no recursive deletion.
    def ps_literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    script = (
        "New-Item -ItemType Junction -Path "
        + ps_literal(str(link))
        + " -Value "
        + ps_literal(str(target))
        + " | Out-Null"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if link.resolve() != target:
        raise RuntimeError("Account directory junction was not verified")


def account_scope(root: Path, wxid: str, args: argparse.Namespace) -> Path:
    if not wxid.startswith("wxid_") or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
        for c in wxid
    ):
        raise ValueError("Unexpected current account wxid")
    if args.account_data and args.login_dir:
        data_dir, login_dir = args.account_data.resolve(), args.login_dir.resolve()
    elif args.account_data or args.login_dir:
        raise ValueError("Provide both --account-data and --login-dir")
    else:
        probe = (
            "import sys,json;sys.path.insert(0,"
            + repr(str(root / "Flandora-source"))
            + ");"
            "from flandora.wechat_account import candidate_roots,list_accounts;"
            "a=[x for r in dict.fromkeys(candidate_roots()) for x in list_accounts(r) if x.wxid=="
            + repr(wxid)
            + "];"
            "print(json.dumps([{'data_dir':x.data_dir,'login_dir':x.login_dir} for x in a]))"
        )
        raw = subprocess.check_output(
            [str(root / "Flandora-source/.venv/Scripts/python.exe"), "-c", probe],
            text=True,
            encoding="utf-8",
        )
        candidates = list(
            {(x["data_dir"], x["login_dir"]) for x in json.loads(raw) if x["data_dir"]}
        )
        if len(candidates) != 1:
            raise ValueError(
                "Cannot uniquely locate the current account; provide --account-data and --login-dir"
            )
        data_dir, login_dir = map(Path, candidates[0])
    if login_dir.name != wxid or not (
        data_dir.name == wxid or data_dir.name.startswith(wxid + "_")
    ):
        raise ValueError("Account directories do not match the current logged-in wxid")
    if (
        not (login_dir / "key_info.db").is_file()
        or not (data_dir / "db_storage").is_dir()
    ):
        raise ValueError(
            "The selected login marker or WeChat database directory is missing"
        )
    scoped = root / "wechat-bot-data" / wxid
    junction(scoped / "all_users/login" / wxid, login_dir)
    junction(scoped / data_dir.name, data_dir)
    return scoped


def proactive_settings(existing: dict, enabled: bool | None) -> dict:
    result = dict(existing)
    for key, value in {
        "enabled": False,
        "start_hour": 9,
        "end_hour": 23,
        "idle_minutes": 10,
        "interval_min_minutes": 60,
        "interval_max_minutes": 90,
        "daily_limit": 4,
    }.items():
        result.setdefault(key, value)
    if enabled is not None:
        result["enabled"] = enabled
    return result


def bind(root: Path, args: argparse.Namespace) -> None:
    import requests
    import tomlkit

    login, group = asyncio.run(query_binding(root, args.group_name, args.group_id))
    s = requests.Session()
    s.trust_env = False
    response = s.get(bridge_base(root) + "/api/status", timeout=10)
    response.raise_for_status()
    status = response.json()
    wxid = str((status.get("self") or {}).get("wxid") or "")
    if not (status.get("window") or {}).get("hwnd"):
        raise RuntimeError("No current WeChat client window is bound")
    scoped = account_scope(root, wxid, args)
    response = s.put(
        bridge_base(root) + "/api/config",
        json={"wechat_files_root": str(scoped)},
        timeout=20,
    )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("Account scope was not saved")
    restart_required = response.json().get("restart_required", [])
    account_id, group_id = str(login["user_id"]), str(group["group_id"])
    write_toml(
        root / "MaiBot/config/adapter_policy.toml",
        {
            "defaults": {
                "group": {"default_action": "block"},
                "private": {"default_action": "block"},
            },
            "adapters": [
                {
                    "platform": "wechat",
                    "account_id": account_id,
                    "group": {"default_action": "block", "allow_ids": [group_id]},
                }
            ],
        },
        root,
    )
    path = root / "MaiBot/plugins/wechat-group-tools/config.toml"
    config = tomlkit.loads(path.read_text(encoding="utf-8"))
    config["groups"] = {"allowed_group_ids": [group_id], "bot_account_id": account_id}
    config["proactive"] = proactive_settings(
        config.get("proactive", {}), args.proactive
    )
    proactive = config["proactive"]["enabled"]
    write_toml(path, config, root)
    state = state_for(root)
    state.update(
        binding={
            "account_id": account_id,
            "wxid": wxid,
            "group_id": group_id,
            "group_name": args.group_name,
            "account_nickname": login.get("nickname", ""),
        },
        stage="bound_awaiting_live_chat_test",
    )
    write_json(root / "installation.json", state)
    # Reload only our independent plugin so a newly enabled proactive task starts.
    session, base = bot_session(root)
    current = session.get(base + "/plugins/config/local.wechat-group-tools", timeout=20)
    current.raise_for_status()
    enabled = current.json()["config"]["plugin"]["enabled"]
    if enabled:
        r = session.post(
            base + "/plugins/config/local.wechat-group-tools/toggle", timeout=30
        )
        r.raise_for_status()
        if r.json().get("enabled") is not False:
            raise RuntimeError(
                "Unexpected plugin reload state; inspect before toggling again"
            )
    r = session.post(
        base + "/plugins/config/local.wechat-group-tools/toggle", timeout=30
    )
    r.raise_for_status()
    if r.json().get("enabled") is not True:
        raise RuntimeError("Group plugin was not re-enabled")
    print(
        json.dumps(
            {
                "bound_group": args.group_name,
                "account_nickname": login.get("nickname", ""),
                "proactive": proactive,
                "bridge_restart_required": restart_required,
                "next": "Inspect the current client screen and test from another account; reload only the owned bridge if listed above.",
            },
            ensure_ascii=False,
        )
    )


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def port_belongs_to_installation(root: Path, port: int) -> bool:
    literal = "'" + str(root.resolve()).replace("'", "''") + "'"
    command = (
        "$taskIds = @(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort "
        + str(int(port))
        + " -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique);"
        "$taskOwned = $taskIds.Count -gt 0; foreach ($taskProcessId in $taskIds) {"
        "$taskProcess = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $taskProcessId);"
        "if (!$taskProcess.CommandLine -or $taskProcess.CommandLine.IndexOf("
        + literal
        + ", [StringComparison]::OrdinalIgnoreCase) -lt 0) {$taskOwned = $false}};"
        "Write-Output $taskOwned"
    )
    result = subprocess.check_output(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        text=True,
        encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.strip().lower() == "true"


def start(root: Path, open_browser: bool = True) -> None:
    state = state_for(root)
    if not state.get("model_configured"):
        raise RuntimeError(
            "Open the local credentials window and accept terms before starting MaiBot"
        )
    for filename in ("eula.confirmed", "privacy.confirmed"):
        if not (root / "MaiBot" / filename).is_file():
            raise RuntimeError("The user has not confirmed MaiBot terms")
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    tasks = [
        (
            "bridge",
            state["ports"]["bridge_web"],
            root / "Flandora-source",
            "manager/main.py",
        ),
        ("bot", state["ports"]["bot_web"], root / "MaiBot", "-c"),
    ]
    for _, port, _, _ in tasks:
        if port_open(port) and not port_belongs_to_installation(root, port):
            raise RuntimeError(f"端口{port}由其他程序占用，没有启动或关闭任何进程。")
    for name, port, directory, entry in tasks:
        if port_open(port):
            print(
                f"Port {port} already has a listener; no second {name} process was started."
            )
            continue
        python = directory / ".venv/Scripts/python.exe"
        args = [str(python), "-u", entry]
        if name == "bot":
            args.append(
                "from src.cli.tool import main;main(['run','--directory',"
                + repr(str(directory))
                + "])"
            )
        with (logs / (name + "-startup.log")).open("ab") as output:
            process = subprocess.Popen(
                args,
                cwd=directory,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1"),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        state.setdefault("launched_processes", {})[name] = process.pid
        write_json(root / "installation.json", state)
        print(f"Started {name}; startup log: {logs / (name + '-startup.log')}")
    if open_browser:
        import webbrowser

        deadline = time.monotonic() + 20
        while (
            not port_open(state["ports"]["bridge_web"]) and time.monotonic() < deadline
        ):
            time.sleep(0.25)
        if not port_open(state["ports"]["bridge_web"]):
            raise RuntimeError(
                "桥接页面尚未就绪，请查看安装目录logs/bridge-startup.log。"
            )
        webbrowser.open(bridge_base(root))


def save_model(root: Path, key: str, model_identifier: str, accepted: bool) -> None:
    if not accepted:
        raise ValueError("Read and accept the displayed terms before saving")
    import tomlkit

    path = root / "MaiBot/config/model_config.toml"
    config = tomlkit.loads(path.read_text(encoding="utf-8"))
    provider = next(p for p in config["api_providers"] if p["name"] == "DeepSeek")
    provider["api_key"] = key
    config["web"]["services"]["deepseek"]["api_key"] = key
    config["models"][0]["model_identifier"] = model_identifier
    if port_open(state_for(root)["ports"]["bot_web"]):
        session, base = bot_session(root)
        result = session.post(base + "/config/model", json=config.unwrap(), timeout=25)
        result.raise_for_status()
        if not result.json().get("success"):
            raise RuntimeError("Model configuration hot update was not confirmed")
    else:
        write_toml(path, config, root)
    for source, marker in (
        ("EULA.md", "eula.confirmed"),
        ("PRIVACY.md", "privacy.confirmed"),
    ):
        data = (root / "MaiBot" / source).read_text(encoding="utf-8")
        (root / "MaiBot" / marker).write_text(
            hashlib.md5(data.encode()).hexdigest(), encoding="utf-8"
        )
    state = state_for(root)
    state["model_configured"] = True
    write_json(root / "installation.json", state)
    webui = root / "MaiBot/data/webui.json"
    cfg = read_json(webui)
    cfg["first_setup_completed"] = True
    write_json(webui, cfg)


def credential_window(root: Path) -> None:
    import tkinter as tk
    from tkinter import messagebox
    import threading

    window = tk.Tk()
    window.title("微信群聊助手 · 模型配置")
    window.geometry("650x350")
    window.resizable(False, False)
    tk.Label(
        window,
        text="请输入自己的 DeepSeek API Key（只保存在本机）",
        font=("Microsoft YaHei UI", 12),
    ).pack(pady=(18, 8))
    entry = tk.Entry(window, show="*", width=62)
    entry.pack(pady=8)
    tk.Label(window, text="模型标识；默认使用已验证的Flash，供应商更新时可修改").pack()
    model = tk.Entry(window, width=40)
    model.insert(0, "deepseek-flash")
    model.pack(pady=5)
    links = tk.Frame(window)
    links.pack(pady=8)
    for label, document in (
        ("阅读MaiBot EULA", "EULA.md"),
        ("阅读隐私说明", "PRIVACY.md"),
    ):
        tk.Button(
            links,
            text=label,
            command=lambda name=document: os.startfile(root / "MaiBot" / name),
        ).pack(side=tk.LEFT, padx=8)
    accepted = tk.BooleanVar(value=False)
    tk.Checkbutton(
        window,
        text="我已阅读并同意上述条款；模型请求按我自己的API账户用量计费",
        variable=accepted,
    ).pack()
    status = tk.StringVar(
        value="不要把密钥发送到群聊；Flandora使用声明在其取钥向导单独确认。"
    )
    tk.Label(window, textvariable=status, wraplength=610).pack(pady=10)

    def save() -> None:
        key = entry.get().strip()
        identifier = model.get().strip()
        if (
            not key
            or any(c.isspace() for c in key)
            or not identifier
            or not accepted.get()
        ):
            messagebox.showinfo(
                "尚未完成", "请填入有效密钥和模型标识，并阅读/勾选条款。"
            )
            return
        button.config(state="disabled")
        status.set("正在保存并检查本机配置……")

        def done(error: str = "") -> None:
            button.config(state="normal")
            if error:
                status.set(error)
            else:
                entry.delete(0, tk.END)
                status.set("已保存。可以启动群聊助手；模型、视觉、搜索仍需实际测试。")
                messagebox.showinfo(
                    "已保存", "配置已保存；若已运行则已热更新。无需重新扫码。"
                )

        def work() -> None:
            try:
                save_model(root, key, identifier, True)
            except Exception as exc:
                error = (
                    "保存未确认成功："
                    + type(exc).__name__
                    + "；保持现有文件，检查本机服务后重试。"
                )
                window.after(0, lambda: done(error))
            else:
                window.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    button = tk.Button(window, text="保存配置", command=save, width=20)
    button.pack(pady=6)
    entry.focus_set()
    window.mainloop()


def verify(root: Path, live: bool) -> None:
    import tomllib

    state = state_for(root)
    keys = credentials(root)
    version = read_json(resource("versions.json"))
    for package, expected in (
        ("MaiBot", version["maibot"]),
        ("maibot-plugin-sdk", version["sdk"]),
        ("maibot-dashboard", version["dashboard"]),
        ("maim-message", version["maim_message"]),
    ):
        if importlib.metadata.version(package) != expected:
            raise ValueError("Installed version mismatch: " + package)
    bridge = read_json(root / "Flandora-source/data/config.json")
    adapter = tomllib.loads(
        (root / "MaiBot/plugins/flandora-adapter/config.toml").read_text(
            encoding="utf-8"
        )
    )
    if not (
        bridge["ob_server_token"] == adapter["client"]["token"] == keys["bridge_token"]
    ):
        raise ValueError("Bridge and adapter credentials differ")
    if (
        bridge["ob_server_host"] != "127.0.0.1"
        or bridge["web_bind_host"] != "127.0.0.1"
    ):
        raise ValueError("Unexpected non-loopback listener")
    policy = tomllib.loads(
        (root / "MaiBot/config/adapter_policy.toml").read_text(encoding="utf-8")
    )
    if policy["defaults"] != {
        "group": {"default_action": "block"},
        "private": {"default_action": "block"},
    }:
        raise ValueError("Default access is not blocked")
    binding = state.get("binding")
    entries = policy.get("adapters", [])
    if binding and entries != [
        {
            "platform": "wechat",
            "account_id": binding["account_id"],
            "group": {"default_action": "block", "allow_ids": [binding["group_id"]]},
        }
    ]:
        raise ValueError("Group/account access does not match the selected binding")
    for item in version["compatibility_files"]:
        base = root / (
            "Flandora-source"
            if item["component"] == "flandora"
            else "MaiBot/plugins/flandora-adapter"
        )
        if digest(base / item["path"], normalize=True) != item["sha256"]:
            raise ValueError("Compatibility file changed: " + item["path"])
    for name in (
        "tools/ffmpeg/ffmpeg.exe",
        "tools/Flandora-KeyTool.exe",
        "flandora/webui/dist/index.html",
    ):
        if not (root / "Flandora-source" / name).is_file():
            raise ValueError("Runtime asset is missing: " + name)
    for item in version["runtime_files"]:
        path = root / "Flandora-source" / item["path"]
        if (
            not path.is_file()
            or path.stat().st_size != item["size"]
            or digest(path) != item["sha256"]
        ):
            raise ValueError("Runtime asset integrity mismatch: " + item["path"])
    report = {
        "static_checks": "passed",
        "group_bound": bool(binding),
        "live_chat_delivery": "requires_phone_confirmation",
    }
    if live:
        import requests

        session = requests.Session()
        session.trust_env = False
        response = session.get(bridge_base(root) + "/api/status", timeout=10)
        response.raise_for_status()
        status = response.json()
        if binding and (status.get("self") or {}).get("wxid") != binding["wxid"]:
            raise ValueError("Live bridge account differs from the selected account")
        session, base = bot_session(root)
        response = session.get(base + "/plugins/installed", timeout=15)
        response.raise_for_status()
        data = response.json()
        data = data.get("data", data)
        plugins = data.get("plugins", []) if isinstance(data, dict) else data
        required = {"omsociety.flandora-adapter", "local.wechat-group-tools"}
        loaded = {p["id"] for p in plugins if p.get("loaded") and p.get("enabled")}
        if not required <= loaded:
            raise ValueError("One or more required plugins are not loaded")
        report.update(
            services_reachable=True,
            plugins_loaded=True,
            inbound_ready=bool((status.get("inbound") or {}).get("ready")),
            onebot_connected=bool((status.get("ob") or {}).get("connected")),
        )
        report["live_readiness"] = (
            "ready"
            if report["inbound_ready"] and report["onebot_connected"]
            else "not_ready"
        )
    write_json(root / "verification.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if live and report["live_readiness"] != "ready":
        raise RuntimeError(
            "Service status is reachable but inbound/OneBot is not ready"
        )


def binding_window(root: Path) -> None:
    import threading
    import tkinter as tk
    from tkinter import messagebox, ttk
    import websockets
    import tomlkit

    window = tk.Tk()
    window.title("微信群聊助手 · 选择账号与群聊")
    window.geometry("680x340")
    window.resizable(False, False)
    tk.Label(
        window,
        text="先在 Flandora 面板完成小号扫码，再读取群列表。",
        font=("Microsoft YaHei UI", 12),
    ).pack(pady=(18, 10))
    status = tk.StringVar(value="只会放行你选择的这个群，其他群和私聊继续拦截。")
    tk.Label(window, textvariable=status, wraplength=630).pack(pady=6)
    choices = ttk.Combobox(window, state="readonly", width=72)
    choices.pack(pady=10)
    current = tomlkit.loads(
        (root / "MaiBot/plugins/wechat-group-tools/config.toml").read_text(
            encoding="utf-8"
        )
    )
    current_proactive = proactive_settings(current.get("proactive", {}), None)
    proactive = tk.BooleanVar(value=bool(current_proactive["enabled"]))
    tk.Checkbutton(
        window,
        text=(
            f"允许主动开话题：{int(current_proactive['start_hour']):02d}–{int(current_proactive['end_hour']):02d}点、"
            f"冷场{current_proactive['idle_minutes']}分钟、每天最多{current_proactive['daily_limit']}次"
        ),
        variable=proactive,
    ).pack(pady=8)
    loaded: dict[str, dict] = {}

    async def read_groups():
        token = quote(credentials(root)["bridge_token"], safe="")
        port = state_for(root)["ports"]["onebot"]
        async with websockets.connect(
            f"ws://127.0.0.1:{port}/?access_token={token}", open_timeout=10
        ) as connection:
            results = []
            for action in ("get_login_info", "get_group_list"):
                echo = "picker-" + secrets.token_hex(6)
                await connection.send(
                    json.dumps({"action": action, "params": {}, "echo": echo})
                )
                async with asyncio.timeout(20):
                    while True:
                        response = json.loads(await connection.recv())
                        if response.get("echo") == echo:
                            if response.get("retcode") != 0:
                                raise RuntimeError("群列表暂不可用")
                            results.append(response["data"])
                            break
        return results

    def refresh() -> None:
        refresh_button.config(state="disabled")
        status.set("正在读取当前小号的群列表……")

        def work():
            try:
                login, groups = asyncio.run(read_groups())
                values = {
                    str(g.get("group_name", ""))
                    + "（"
                    + str(g.get("group_id", ""))
                    + "）": g
                    for g in groups
                }
            except Exception:
                window.after(
                    0,
                    lambda: (
                        refresh_button.config(state="normal"),
                        status.set(
                            "读取失败，请确认桥接已启动、扫码完成且小号已在群内。"
                        ),
                    ),
                )
            else:

                def ready():
                    loaded.clear()
                    loaded.update(values)
                    choices["values"] = list(values)
                    if values:
                        choices.current(0)
                    status.set(
                        "当前账号："
                        + str(login.get("nickname", ""))
                        + "；请核对后选择群聊。"
                    )
                    refresh_button.config(state="normal")

                window.after(0, ready)

        threading.Thread(target=work, daemon=True).start()

    def save() -> None:
        selected = loaded.get(choices.get())
        if selected is None:
            messagebox.showinfo("尚未选择", "请先读取群列表，再选择要启用的群。")
            return
        args = argparse.Namespace(
            group_name=str(selected["group_name"]),
            group_id=str(selected["group_id"]),
            proactive=proactive.get(),
            account_data=None,
            login_dir=None,
        )
        save_button.config(state="disabled")
        status.set("正在固定小号数据范围并保存群绑定……")

        def work():
            try:
                bind(root, args)
            except Exception:
                window.after(
                    0,
                    lambda: (
                        save_button.config(state="normal"),
                        status.set(
                            "绑定未确认成功，请保持窗口，查看本机日志；不要连续重复测试。"
                        ),
                    ),
                )
            else:

                def done():
                    status.set(
                        "已保存。请用另一个账号在群里 @小号说你好，核对实际回复。"
                    )
                    save_button.config(state="normal")
                    messagebox.showinfo(
                        "群已绑定", "账号与群白名单已保存。接下来需要实际群聊收发验收。"
                    )

                window.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    refresh_button = tk.Button(
        window, text="读取当前小号群列表", command=refresh, width=28
    )
    refresh_button.pack(pady=6)
    save_button = tk.Button(window, text="保存群绑定", command=save, width=28)
    save_button.pack(pady=6)
    window.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("initialize", "credentials", "bind-window"):
        sub.add_parser(command)
    starter = sub.add_parser("start")
    starter.add_argument("--no-browser", action="store_true")
    selection = sub.add_parser("bind")
    selection.add_argument("--group-name", required=True)
    selection.add_argument("--group-id")
    selection.add_argument(
        "--proactive", action=argparse.BooleanOptionalAction, default=None
    )
    selection.add_argument("--account-data", type=Path)
    selection.add_argument("--login-dir", type=Path)
    check = sub.add_parser("verify")
    check.add_argument("--live", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    state_for(root)
    if args.command == "initialize":
        initialize(root)
    elif args.command == "start":
        start(root, open_browser=not args.no_browser)
    elif args.command == "credentials":
        credential_window(root)
    elif args.command == "bind":
        bind(root, args)
    elif args.command == "bind-window":
        binding_window(root)
    else:
        verify(root, args.live)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # HTTP/SDK exceptions may include payloads; never echo their full representation.
        print(
            "Operation did not complete: "
            + type(exc).__name__
            + ". Check this installation's local logs; no automatic message retry was made.",
            file=sys.stderr,
        )
        raise SystemExit(1)
