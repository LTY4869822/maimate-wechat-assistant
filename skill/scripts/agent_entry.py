"""Host-neutral, resumable onboarding. No Agent SDK, downloads or message sending."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import struct
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path

VERSION = "1.2.0"
HOSTS = ("generic", "workbuddy", "doubao", "codex")


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Expected a local configuration object")
    return value


def capabilities() -> dict:
    windows = sys.platform == "win32"
    session = ctypes.c_ulong()
    interactive = bool(
        windows
        and ctypes.windll.kernel32.ProcessIdToSessionId(
            os.getpid(), ctypes.byref(session)
        )
        and session.value > 0
    )
    return {
        "windows": windows,
        "x64_python": struct.calcsize("P") == 8,
        "interactive_session": interactive,
        "python": sys.version.split()[0],
        "agent_sdk_required": False,
        "downloads_allowed": False,
    }


def require_local_windows() -> None:
    info = capabilities()
    if not all(info[k] for k in ("windows", "x64_python", "interactive_session")):
        raise RuntimeError("A local interactive Windows x64 task is required")


def root_for(resource: Path, requested: Path | None) -> Path:
    if requested is not None:
        return requested.expanduser().resolve()
    if (resource / "installation.json").is_file():
        return resource
    return (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "WeChatGroupAssistant"
    ).resolve()


def bundle_for(resource: Path) -> Path | None:
    for candidate in (resource, resource / "WeChatGroupAssistant-Offline-1.2.0"):
        if (candidate / "offline-manifest.json").is_file() and (
            candidate / "offline_install.py"
        ).is_file():
            return candidate
    return None


def child_environment() -> dict:
    environment = dict(
        os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1"
    )
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    return environment


def execute(args: list[str | Path], root: Path | None = None) -> None:
    subprocess.run(
        [str(x) for x in args], cwd=root, env=child_environment(), check=True
    )


def manage_args(root: Path, command: str, *options: str) -> list[str | Path]:
    python = root / "MaiBot/.venv/Scripts/python.exe"
    helper = root / "assistant_setup/manage.py"
    if not python.is_file() or not helper.is_file():
        raise FileNotFoundError(
            "The managed installation is incomplete; resume offline preparation"
        )
    return [python, "-B", helper, "--root", root, command, *options]


def model_ready(root: Path) -> tuple[bool, bool]:
    path = root / "MaiBot/config/model_config.toml"
    configured = False
    if path.is_file():
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        for provider in data.get("api_providers", []):
            if provider.get("name") != "DeepSeek":
                continue
            key = str(provider.get("api_key", "")).strip()
            configured = bool(
                key
                and key.lower()
                not in {
                    "your_api_key",
                    "your_deepseek_api_key",
                    "change_me",
                    "",
                    "none",
                }
                and "<" not in key
            )
    terms = True
    for document, marker in (
        ("EULA.md", "eula.confirmed"),
        ("PRIVACY.md", "privacy.confirmed"),
    ):
        text, confirmation = root / "MaiBot" / document, root / "MaiBot" / marker
        if not text.is_file() or not confirmation.is_file():
            terms = False
            continue
        expected = hashlib.md5(text.read_text(encoding="utf-8").encode()).hexdigest()
        terms = terms and confirmation.read_text(encoding="utf-8").strip() == expected
    return configured, bool(terms)


def bridge_flags(state: dict) -> dict:
    flags = {
        "bridge_reachable": False,
        "wechat_login_ready": False,
        "onebot_connected": False,
    }
    port = state.get("ports", {}).get("bridge_web")
    if not isinstance(port, int) or not 0 < port < 65536:
        return flags
    try:
        # Always loopback, with proxy inheritance disabled. Never return raw account/API responses.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/status", timeout=3) as response:
            raw = response.read(262145)
        if len(raw) > 262144:
            return flags
        status = json.loads(raw)
        flags.update(
            bridge_reachable=True,
            wechat_login_ready=bool(
                (status.get("self") or {}).get("wxid")
                and (status.get("inbound") or {}).get("ready")
            ),
            onebot_connected=bool((status.get("ob") or {}).get("connected")),
        )
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return flags


def status_report(root: Path, host: str, live: bool = True) -> dict:
    state = load_json(root / "installation.json")
    installed = bool(
        state.get("initialized")
        and (root / "MaiBot/.venv/Scripts/python.exe").is_file()
        and (root / "assistant_setup/manage.py").is_file()
    )
    key, terms = model_ready(root) if installed else (False, False)
    flags = (
        bridge_flags(state)
        if installed and live
        else {
            "bridge_reachable": False,
            "wechat_login_ready": False,
            "onebot_connected": False,
        }
    )
    bound = bool(
        state.get("binding", {}).get("account_id")
        and state.get("binding", {}).get("group_id")
    )
    if not installed:
        phase = "installation_required"
    elif not key or not terms:
        phase = "awaiting_model_key_and_terms"
    elif not flags["wechat_login_ready"]:
        phase = "awaiting_wechat_login"
    elif not bound:
        phase = "awaiting_group_selection"
    elif not flags["onebot_connected"]:
        phase = "services_not_ready"
    else:
        phase = "awaiting_message_acceptance"
    return {
        "skill_version": VERSION,
        "host": host,
        "installation": str(root),
        "phase": phase,
        "installed": installed,
        "model_key_present": key,
        "terms_confirmed": terms,
        "group_bound": bound,
        **flags,
        "delivery_verified": False,
        "note": "Actual replies must be confirmed in WeChat by another account; no messages were sent by this helper.",
    }


def persist_phase(root: Path, report: dict) -> None:
    if not (root / "installation.json").is_file():
        return
    path = root / "agent-onboarding.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {k: report[k] for k in ("skill_version", "host", "phase")},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def process_alive(pid: int, expected_python: Path) -> bool:
    if sys.platform != "win32" or not isinstance(pid, int) or pid <= 0:
        return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        buffer, size = ctypes.create_unicode_buffer(32768), ctypes.c_ulong(32768)
        return bool(
            kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
            and Path(buffer.value).resolve() == expected_python.resolve()
        )
    finally:
        kernel.CloseHandle(handle)


def reconcile_model_marker(root: Path) -> None:
    # Repair an interrupted save only when the actual Key and current terms are valid.
    key, terms = model_ready(root)
    if not key or not terms:
        return
    path = root / "installation.json"
    state = load_json(path)
    if state.get("model_configured"):
        return
    state["model_configured"] = True
    temporary = path.with_name("installation.agent.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def show_gui(root: Path, command: str) -> None:
    state_path = root / "agent-windows.json"
    opened = load_json(state_path)
    args = manage_args(root, command)
    if process_alive(opened.get(command, 0), Path(args[0])):
        return
    process = subprocess.Popen(
        [str(x) for x in args],
        cwd=root,
        env=child_environment(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    opened[command] = process.pid
    state_path.write_text(json.dumps(opened) + "\n", encoding="utf-8")


def prepare(resource: Path, root: Path) -> None:
    bundle = bundle_for(resource)
    if bundle is None:
        raise FileNotFoundError(
            "A complete local offline bundle is required for installation; there is no download fallback"
        )
    python = bundle / "runtimes/python312/python.exe"
    execute(
        [
            python,
            "-I",
            "-X",
            "utf8",
            "-B",
            bundle / "offline_install.py",
            "--root",
            root,
        ]
    )


def onboard(
    resource: Path,
    root: Path,
    host: str,
    group_name: str | None = None,
    proactive: bool | None = None,
    no_browser: bool = False,
) -> dict:
    require_local_windows()
    report = status_report(root, host)
    if not report["installed"]:
        prepare(resource, root)
        report = status_report(root, host)
        if not report["installed"]:
            raise RuntimeError(
                "Offline preparation did not produce a complete installation"
            )
    if not report["model_key_present"] or not report["terms_confirmed"]:
        show_gui(root, "credentials")
        persist_phase(root, report)
        return report
    reconcile_model_marker(root)
    started = False
    if not report["bridge_reachable"] or not report["onebot_connected"]:
        execute(
            manage_args(root, "start", *(["--no-browser"] if no_browser else [])), root
        )
        started = True
        report = status_report(root, host)
    if not report["wechat_login_ready"]:
        if report["bridge_reachable"] and not no_browser and not started:
            import webbrowser

            port = load_json(root / "installation.json")["ports"]["bridge_web"]
            webbrowser.open(f"http://127.0.0.1:{int(port)}")
        persist_phase(root, report)
        return report
    if group_name or (proactive is not None and report["group_bound"]):
        options = []
        if not group_name:
            # Verify the current account before changing the existing group's setting.
            execute(manage_args(root, "verify", "--live"), root)
            binding = load_json(root / "installation.json")["binding"]
            group_name = binding.get("group_name")
            if not group_name:
                raise ValueError(
                    "The current group name is missing; select the group again"
                )
            options = ["--group-id", str(binding["group_id"])]
        options = ["--group-name", group_name, *options]
        if proactive is not None:
            options.append("--proactive" if proactive else "--no-proactive")
        execute(manage_args(root, "bind", *options), root)
        report = status_report(root, host)
    elif not report["group_bound"]:
        show_gui(root, "bind-window")
    if report["phase"] == "awaiting_message_acceptance":
        execute(manage_args(root, "verify", "--live"), root)
    persist_phase(root, report)
    return report


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "resource",
        type=Path,
        help="Extracted offline bundle or existing managed installation",
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--host", choices=HOSTS, default="generic")
    parser.add_argument(
        "--group-name", help="Only a group explicitly selected by the current user"
    )
    parser.add_argument(
        "--proactive", action=argparse.BooleanOptionalAction, default=None
    )
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "command",
        choices=(
            "doctor",
            "prepare",
            "status",
            "onboard",
            "credentials",
            "start",
            "bind",
            "verify",
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Verify running services without sending messages",
    )
    args = parser.parse_args()
    resource = args.resource.expanduser().resolve()
    root = root_for(resource, args.root)
    if args.command == "doctor":
        info = capabilities()
        report = {
            "capabilities": info,
            "resource_is_bundle": bool(bundle_for(resource)),
            **status_report(root, args.host, live=False),
        }
        report["can_deploy_here"] = all(
            info[k] for k in ("windows", "x64_python", "interactive_session")
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["can_deploy_here"] else 20)
    if args.command == "status":
        report = status_report(root, args.host)
    else:
        require_local_windows()
        if args.command == "onboard":
            report = onboard(
                resource,
                root,
                args.host,
                args.group_name,
                args.proactive,
                args.no_browser,
            )
        else:
            if args.command == "prepare":
                prepare(resource, root)
            elif args.command in {"credentials", "bind"}:
                show_gui(
                    root,
                    "credentials" if args.command == "credentials" else "bind-window",
                )
            else:
                if args.command == "start":
                    reconcile_model_marker(root)
                options = ["--live"] if args.command == "verify" and args.live else []
                if args.command == "start" and args.no_browser:
                    options.append("--no-browser")
                execute(manage_args(root, args.command, *options), root)
            report = status_report(root, args.host)
            persist_phase(root, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Keep local account names, headers, keys and provider responses out of Agent transcripts.
        print(
            json.dumps(
                {
                    "error": type(exc).__name__,
                    "message": "Operation was not completed. Check local permissions and this installation; no online fallback or message retry was made.",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
