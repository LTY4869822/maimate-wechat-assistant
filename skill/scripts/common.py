"""Small, dependency-free helpers shared by the resumable installer and manager."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def digest(path: Path, normalize: bool = False) -> str:
    if normalize:
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run(args: list[str], cwd: Path | None = None) -> None:
    # No shell expansion, hidden helpers, or secrets in command arguments.
    env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    subprocess.run([str(a) for a in args], cwd=cwd, env=env, check=True)


def safe_member(name: str) -> Path:
    if "\\" in name or ":" in name:
        raise ValueError("Archive contains a non-portable path")
    value = PurePosixPath(name)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError("Archive path escapes its destination")
    return Path(*value.parts)


def extract(archive: Path, destination: Path, prefix: str | None = None) -> None:
    with zipfile.ZipFile(archive) as z:
        members = []
        for item in z.infolist():
            relative = safe_member(item.filename)
            if stat.S_ISLNK(item.external_attr >> 16):
                # MaiBot publishes CLAUDE.md -> AGENTS.md. Copy a safe, same-archive
                # regular-file alias instead of creating a filesystem symlink.
                alias = safe_member(z.read(item).decode("utf-8"))
                target_name = (relative.parent / alias).as_posix()
                if prefix and not target_name.startswith(prefix + "/"):
                    raise ValueError("Archive alias escapes its component")
                try:
                    source_item = z.getinfo(target_name)
                except KeyError as exc:
                    raise ValueError("Archive alias points to a missing file") from exc
                if source_item.is_dir() or stat.S_ISLNK(
                    source_item.external_attr >> 16
                ):
                    raise ValueError(
                        "Archive alias must point directly to a regular file"
                    )
            else:
                source_item = item
            if prefix:
                try:
                    relative = relative.relative_to(Path(prefix))
                except ValueError:
                    continue
            members.append((source_item, relative))
        for item, relative in members:
            target = destination / relative
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Archive destination is outside the installation")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + ".extract-part")
                with z.open(item) as source, temporary.open("wb") as output:
                    shutil.copyfileobj(source, output)
                temporary.replace(target)


def download(source: dict, cache: Path, offline: bool = False) -> Path:
    target = cache / source["archive"]
    expected = source.get("sha256")
    if target.exists():
        if expected and digest(target) != expected:
            raise ValueError(
                f"Cached checksum mismatch: {target.name}; preserve it for diagnosis"
            )
        return target
    if offline:
        raise FileNotFoundError(f"Offline cache is missing {target.name}")
    cache.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    for attempt in range(3):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "wechat-group-assistant/1.0"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            request = urllib.request.Request(source["url"], headers=headers)
            with urllib.request.urlopen(request, timeout=45) as response:
                append = offset > 0 and response.status == 206
                if append and not response.headers.get("Content-Range", "").startswith(
                    f"bytes {offset}-"
                ):
                    raise ValueError("Download returned an unexpected range")
                size = offset if append else 0
                checkpoint = size
                with partial.open("ab" if append else "wb") as output:
                    while block := response.read(1024 * 1024):
                        output.write(block)
                        size += len(block)
                        if size - checkpoint >= 16 * 1024 * 1024:
                            print(
                                f"Downloading {target.name}: {size // 1048576} MiB",
                                flush=True,
                            )
                            checkpoint = size
            if expected and digest(partial) != expected:
                raise ValueError(f"Official SHA-256 mismatch for {target.name}")
            if not zipfile.is_zipfile(partial):
                raise ValueError(f"Download is not a ZIP archive: {target.name}")
            partial.replace(target)
            return target
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(1 + attempt)
    raise RuntimeError("Download did not complete")


def free_port(preferred: int, reserved: set[int]) -> int:
    for port in range(preferred, preferred + 200):
        if port in reserved:
            continue
        try:
            with socket.socket() as listener:
                if os.name == "nt":
                    listener.setsockopt(
                        socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1
                    )
                listener.bind(("127.0.0.1", port))
            reserved.add(port)
            return port
        except OSError:
            continue
    raise RuntimeError(f"No free loopback port near {preferred}")


def apply_compatibility(assets: Path, manifest: dict, roots: dict[str, Path]) -> None:
    # Validate every source and target before making any changes.
    pending = []
    for entry in manifest["compatibility_files"]:
        source = assets / "compat" / entry["component"] / safe_member(entry["path"])
        target = roots[entry["component"]] / safe_member(entry["path"])
        if digest(source, normalize=True) != entry["sha256"]:
            raise ValueError(f"Skill compatibility payload changed: {entry['path']}")
        current = digest(target, normalize=True) if target.is_file() else None
        if current == entry["sha256"]:
            continue
        if current != entry["base_sha256"]:
            raise ValueError(
                f"Unrecognized source version; refusing to overwrite {entry['path']}"
            )
        pending.append((source, target))
    for source, target in pending:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def state_for(root: Path) -> dict:
    state = read_json(root / "installation.json")
    if state.get("managed_by") != "wechat-group-assistant":
        raise ValueError(
            "This is not a managed installation; inspect and migrate it first"
        )
    return state
