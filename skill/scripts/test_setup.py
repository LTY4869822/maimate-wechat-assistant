"""Offline invariants: no live services, credentials or real WeChat directories."""

import argparse
import hashlib
import importlib.util
import json
import socket
import stat
import sys
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import manage  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "assistant_installer_test", HERE / "setup.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_unmanaged_directory_is_never_initialized(tmp_path):
    (tmp_path / "keep.txt").write_text("original")
    with pytest.raises(ValueError):
        installer.new_state(tmp_path, {"skill_version": "test"})
    assert (tmp_path / "keep.txt").read_text() == "original"
    assert not (tmp_path / "installation.json").exists()


def test_resume_preserves_ports_and_credentials(tmp_path):
    a = installer.new_state(tmp_path, {"skill_version": "test"})
    first = manage.credentials(tmp_path, create=True)
    second = manage.credentials(tmp_path, create=True)
    assert first == second
    assert first["bridge_token"] != first["webui_token"]
    assert installer.new_state(tmp_path, {"skill_version": "test"}) == a
    assert len(set(a["ports"].values())) == 4


def test_missing_credentials_does_not_mutate_during_checks(tmp_path):
    with pytest.raises(FileNotFoundError):
        manage.credentials(tmp_path)
    assert not (tmp_path / "local-credentials.json").exists()


@pytest.mark.parametrize(
    "path",
    ["../escape.txt", "folder/../../escape", "/absolute", "C:/drive", "a\\..\\bad"],
)
def test_unsafe_archive_cannot_write_anything(tmp_path, path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("safe.txt", "safe")
        z.writestr(path, "bad")
    target = tmp_path / "extract"
    with pytest.raises(ValueError):
        common.extract(archive, target)
    assert not target.exists()


def test_source_mismatch_prevents_all_compatibility_writes(tmp_path):
    assets = tmp_path / "assets"
    root = tmp_path / "repo"
    root.mkdir()
    entries = []
    for name in ("one.py", "two.py"):
        p = assets / "compat/flandora" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("new")
        (root / name).write_text("base" if name == "one.py" else "changed by owner")
        entries.append(
            {
                "component": "flandora",
                "path": name,
                "base_sha256": hashlib.sha256(b"base").hexdigest(),
                "sha256": common.digest(p),
            }
        )
    with pytest.raises(ValueError):
        common.apply_compatibility(
            assets, {"compatibility_files": entries}, {"flandora": root}
        )
    assert (root / "one.py").read_text() == "base"
    assert (root / "two.py").read_text() == "changed by owner"


def test_safe_internal_archive_alias_is_a_regular_file(tmp_path):
    archive = tmp_path / "aliases.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("project/AGENTS.md", "public instructions")
        alias = zipfile.ZipInfo("project/CLAUDE.md")
        alias.create_system = 3
        alias.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(alias, "AGENTS.md")
    target = tmp_path / "extract"
    common.extract(archive, target, "project")
    assert (target / "CLAUDE.md").read_text() == "public instructions"
    assert not (target / "CLAUDE.md").is_symlink()


def test_interrupted_archive_recovers_without_publishing_partial_files(
    tmp_path, monkeypatch
):
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("project/plugin.py", "complete" * 500)
    target = tmp_path / "adapter"
    copy = common.shutil.copyfileobj

    def interrupt(source, output):
        output.write(source.read(3))
        raise OSError("simulated interrupted extraction")

    monkeypatch.setattr(common.shutil, "copyfileobj", interrupt)
    with pytest.raises(OSError):
        installer.install_archive(archive, target, "project", "test-source")
    assert not target.exists()
    monkeypatch.setattr(common.shutil, "copyfileobj", copy)
    installer.install_archive(archive, target, "project", "test-source")
    assert (target / "plugin.py").read_text() == "complete" * 500
    installer.install_archive(archive, target, "project", "test-source")
    assert (target / "plugin.py").stat().st_size == 4000


def test_group_resolution_rejects_duplicates_and_other_groups(tmp_path, monkeypatch):
    import websockets

    installer.new_state(tmp_path, {"skill_version": "test"})
    manage.credentials(tmp_path, create=True)

    class FakeConnection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def send(self, data):
            self.request = json.loads(data)

        async def recv(self):
            data = (
                {"user_id": "fake-account"}
                if self.request["action"] == "get_login_info"
                else [
                    {"group_name": "测试群", "group_id": "111"},
                    {"group_name": "测试群", "group_id": "222"},
                ]
            )
            return json.dumps(
                {"echo": self.request["echo"], "retcode": 0, "data": data}
            )

    monkeypatch.setattr(
        websockets, "connect", lambda *_args, **_kwargs: FakeConnection()
    )
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(manage.query_binding(tmp_path, "测试群", None))
    _, selected = asyncio.run(manage.query_binding(tmp_path, "测试群", "222"))
    assert selected["group_id"] == "222"
    with pytest.raises(ValueError):
        asyncio.run(manage.query_binding(tmp_path, "其他群", "222"))


def test_account_scope_never_includes_another_account(tmp_path, monkeypatch):
    # Use directory markers rather than Windows junctions so this check is portable.
    def fake_link(link, target):
        link.mkdir(parents=True, exist_ok=True)
        (link / "fake-target.txt").write_text(str(target))

    monkeypatch.setattr(manage, "junction", fake_link)
    scopes = []
    for wxid in ("wxid_first", "wxid_second"):
        data = tmp_path / "fake-wechat" / (wxid + "_test")
        login = tmp_path / "fake-wechat/all_users/login" / wxid
        (data / "db_storage").mkdir(parents=True)
        login.mkdir(parents=True)
        (login / "key_info.db").write_bytes(b"fake-marker")
        args = argparse.Namespace(account_data=data, login_dir=login)
        scopes.append(manage.account_scope(tmp_path / "app", wxid, args))
    assert scopes[0] != scopes[1]
    assert [p.name for p in (scopes[1] / "all_users/login").iterdir()] == [
        "wxid_second"
    ]


def test_resource_paths_work_before_runtime_copy():
    assert manage.resource("versions.json").is_file()
    template = common.read_json(manage.resource("model-config.template.json"))
    assert all(not p.get("api_key") for p in template["api_providers"])
    assert not template["web"]["services"]["deepseek"]["api_key"]


def test_occupied_port_is_skipped():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        occupied = listener.getsockname()[1]
        assert common.free_port(occupied, set()) != occupied


@pytest.mark.parametrize("enabled", [None, True, False])
def test_rebinding_preserves_custom_proactive_frequency(enabled):
    original = {
        "enabled": True,
        "start_hour": 13,
        "end_hour": 20,
        "idle_minutes": 22,
        "interval_min_minutes": 150,
        "interval_max_minutes": 180,
        "daily_limit": 1,
    }
    result = manage.proactive_settings(original, enabled)
    assert result == {
        **original,
        "enabled": original["enabled"] if enabled is None else enabled,
    }
    assert original["enabled"] is True


@pytest.mark.parametrize("open_browser", [True, False])
def test_start_opens_owned_panel_without_duplicate_processes(
    tmp_path, monkeypatch, open_browser
):
    import webbrowser

    state = installer.new_state(tmp_path, {"skill_version": "test"})
    state["model_configured"] = True
    common.write_json(tmp_path / "installation.json", state)
    (tmp_path / "MaiBot").mkdir()
    for name in ("eula.confirmed", "privacy.confirmed"):
        (tmp_path / "MaiBot" / name).write_text("fake unit-test marker")
    monkeypatch.setattr(manage, "port_open", lambda _port: True)
    monkeypatch.setattr(manage, "port_belongs_to_installation", lambda *_args: True)
    monkeypatch.setattr(
        manage.subprocess,
        "Popen",
        lambda *_a, **_k: pytest.fail("already running; no new processes"),
    )
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    manage.start(tmp_path, open_browser=open_browser)
    assert opened == ([manage.bridge_base(tmp_path)] if open_browser else [])


def test_start_refuses_a_foreign_listener_without_starting_processes(
    tmp_path, monkeypatch
):
    state = installer.new_state(tmp_path, {"skill_version": "test"})
    state["model_configured"] = True
    common.write_json(tmp_path / "installation.json", state)
    (tmp_path / "MaiBot").mkdir()
    for name in ("eula.confirmed", "privacy.confirmed"):
        (tmp_path / "MaiBot" / name).write_text("fake unit-test marker")
    monkeypatch.setattr(manage, "port_open", lambda _port: True)
    monkeypatch.setattr(manage, "port_belongs_to_installation", lambda *_args: False)
    monkeypatch.setattr(
        manage.subprocess,
        "Popen",
        lambda *_a, **_k: pytest.fail("foreign port must not launch anything"),
    )
    with pytest.raises(RuntimeError, match="其他程序"):
        manage.start(tmp_path)
