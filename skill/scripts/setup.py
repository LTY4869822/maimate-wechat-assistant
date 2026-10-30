"""Prepare a pinned, isolated Windows installation without sending chat messages."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from common import (
    apply_compatibility,
    digest,
    download,
    extract,
    free_port,
    read_json,
    run,
    state_for,
    write_json,
)

SKILL = Path(__file__).resolve().parents[1]
ASSETS = SKILL / "assets"


def ensure_uv(offline: bool = False) -> str:
    candidates = [
        shutil.which("uv"),
        str(Path.home() / ".local/bin/uv.exe"),
        str(Path(sys.executable).parent / "uv.exe"),
        str(
            Path.home()
            / "AppData/Roaming/Python"
            / f"Python{sys.version_info.major}{sys.version_info.minor}"
            / "Scripts/uv.exe"
        ),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    if offline:
        raise RuntimeError("uv is missing; offline installation cannot bootstrap it")
    version = read_json(ASSETS / "versions.json")["uv"]
    run([sys.executable, "-m", "pip", "install", "--user", "uv==" + version])
    found = subprocess.check_output(
        [sys.executable, "-c", "import uv;print(uv.find_uv_bin())"], text=True
    ).strip()
    if not Path(found).is_file():
        raise RuntimeError("uv was installed but its executable was not found")
    return found


def new_state(root: Path, manifest: dict) -> dict:
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise ValueError("Choose a dedicated application directory")
    if (root / "installation.json").exists():
        return state_for(root)
    if root.exists() and any(root.iterdir()):
        raise ValueError("Refusing to initialize a non-empty unmanaged directory")
    root.mkdir(parents=True, exist_ok=True)
    used: set[int] = set()
    state = {
        "managed_by": "wechat-group-assistant",
        "skill_version": manifest["skill_version"],
        "stage": "created",
        "ports": {
            name: free_port(port, used)
            for name, port in (
                ("bridge_web", 4950),
                ("onebot", 7999),
                ("bot_web", 8001),
                ("bot_legacy", 8002),
            )
        },
    }
    write_json(root / "installation.json", state)
    return state


def install_archive(
    archive: Path, destination: Path, prefix: str, identity: str
) -> None:
    marker = ".assistant-archive.json"
    if destination.exists():
        if (
            not (destination / marker).is_file()
            or read_json(destination / marker).get("identity") != identity
        ):
            raise RuntimeError(
                f"Source directory is unmanaged or has another version: {destination}"
            )
        return
    stage = destination.with_name(destination.name + ".extracting")
    if stage.exists() and (
        not (stage / marker).is_file()
        or read_json(stage / marker).get("identity") != identity
    ):
        raise RuntimeError(f"Inspect the unrelated staging directory: {stage}")
    stage.mkdir(parents=True, exist_ok=True)
    write_json(stage / marker, {"identity": identity})
    extract(archive, stage, prefix)
    stage.rename(destination)


def materialize(root: Path, cache: Path, manifest: dict, offline: bool) -> None:
    bot, bridge = root / "MaiBot", root / "Flandora-source"
    for key, destination in (("maibot", bot), ("flandora", bridge)):
        source = manifest["sources"][key]
        archive = download(source, cache, offline)
        with zipfile.ZipFile(archive) as z:
            prefixes = {name.split("/")[0] for name in z.namelist() if name}
        expected = ("MaiBot-" if key == "maibot" else "Flandora-") + source["commit"]
        if prefixes != {expected}:
            raise ValueError(f"Unexpected source archive identity for {key}")
        install_archive(archive, destination, expected, source["commit"])
    adapter = bot / "plugins/flandora-adapter"
    adapter_source = manifest["sources"]["adapter"]
    install_archive(
        download(adapter_source, cache, offline),
        adapter,
        "flandora-adapter",
        adapter_source["sha256"],
    )
    apply_compatibility(ASSETS, manifest, {"flandora": bridge, "adapter": adapter})
    portable = download(manifest["sources"]["portable"], cache, offline)
    # Use only public runtime tools, not the original portable executables or user data.
    with zipfile.ZipFile(portable) as z:
        expected_files = {x["path"]: x for x in manifest["runtime_files"]}
        for info in z.infolist():
            if info.is_dir() or not info.filename.startswith("Flandora-v1.0.0/tools/"):
                continue
            relative = Path(*info.filename.split("/")[1:])
            target = bridge / relative
            expected = expected_files[relative.as_posix()]
            if (
                target.is_file()
                and target.stat().st_size == expected["size"]
                and digest(target) == expected["sha256"]
            ):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".install-part")
            with z.open(info) as source, temporary.open("wb") as output:
                shutil.copyfileobj(source, output)
            if digest(temporary) != expected["sha256"]:
                raise ValueError(f"Runtime file integrity mismatch: {relative}")
            temporary.replace(target)
    plugin = bot / "plugins/wechat-group-tools"
    if not plugin.exists():
        stage = plugin.with_name(plugin.name + ".extracting")
        shutil.copytree(ASSETS / "wechat-group-tools", stage, dirs_exist_ok=True)
        stage.rename(plugin)
    runtime = root / "assistant_setup"
    runtime.mkdir(exist_ok=True)
    for name in (
        "common.py",
        "manage.py",
        "agent_entry.py",
        "bootstrap.cmd",
        "bootstrap.ps1",
    ):
        shutil.copy2(SKILL / "scripts" / name, runtime / name)
    for name in ("model-config.template.json", "versions.json"):
        shutil.copy2(ASSETS / name, runtime / name)
    shutil.copytree(
        ASSETS / "starter-emoji", root / "starter-emoji", dirs_exist_ok=True
    )


def prepare(args: argparse.Namespace, manifest: dict) -> None:
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise RuntimeError(
            "This installer requires 64-bit Windows; --plan remains available elsewhere"
        )
    root = args.root.resolve()
    state = new_state(root, manifest)
    cache = (args.cache or root / "downloads").resolve()
    materialize(root, cache, manifest, args.offline)
    state["stage"] = "sources_prepared"
    write_json(root / "installation.json", state)
    uv = ensure_uv(args.offline)
    for directory, version in (
        ("MaiBot", manifest["python_bot"]),
        ("Flandora-source", manifest["python_bridge"]),
    ):
        env = root / directory / ".venv"
        if not (env / "Scripts/python.exe").is_file():
            if env.exists():
                raise RuntimeError(
                    f"Incomplete environment preserved for inspection: {env}"
                )
            if not args.offline:
                run([uv, "python", "install", version])
            run([uv, "venv", "--python", version, str(env)])
    bot_python = root / "MaiBot/.venv/Scripts/python.exe"
    bridge_python = root / "Flandora-source/.venv/Scripts/python.exe"
    extra = ["--offline"] if args.offline else []
    run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(bot_python),
            "-e",
            str(root / "MaiBot"),
            "-c",
            str(ASSETS / "maibot-constraints.txt"),
            "pytest==9.1.1",
            *extra,
        ]
    )
    run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(bridge_python),
            "-r",
            str(root / "Flandora-source/flandora/requirements.txt"),
            "-r",
            str(root / "Flandora-source/manager/requirements.txt"),
            "-c",
            str(ASSETS / "flandora-constraints.txt"),
            "pytest==9.1.1",
            "ruff==0.17.2",
            *extra,
        ]
    )
    run(
        [
            str(bot_python),
            "-c",
            "from src.cli.tool import main;main(['init','--directory',"
            + repr(str(root / "MaiBot"))
            + "])",
        ]
    )
    run(
        [
            str(bot_python),
            str(root / "assistant_setup/manage.py"),
            "--root",
            str(root),
            "initialize",
        ]
    )
    state = state_for(root)
    state["stage"] = "prepared_awaiting_credentials_and_login"
    write_json(root / "installation.json", state)
    print(
        "Prepared. Follow FIRST-RUN.txt for model credentials, terms, login and group binding."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("command", nargs="?", choices=["prepare"], default="prepare")
    args = parser.parse_args()
    manifest = read_json(ASSETS / "versions.json")
    if args.plan:
        print(json_plan(args.root, manifest))
    else:
        prepare(args, manifest)


def json_plan(root: Path, manifest: dict) -> str:
    import json

    return json.dumps(
        {
            "root": str(root.resolve()),
            "platform_required": "Windows x64",
            "versions": {
                k: manifest[k]
                for k in (
                    "maibot",
                    "sdk",
                    "dashboard",
                    "python_bot",
                    "python_bridge",
                    "wechat_tested",
                )
            },
            "downloads": {k: v["url"] for k, v in manifest["sources"].items()},
            "voice": False,
            "default_access": "block_all_until_exact_account_and_group_are_selected",
            "human_steps": [
                "accept terms",
                "enter own model key",
                "scan and confirm WeChat login",
                "select group",
                "verify from another account",
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Setup stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
