"""Onboarding invariants with fake installations; no services or message sending."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_entry as entry  # noqa: E402


def fake_install(root, key="", terms=False, binding=False):
    state = {
        "initialized": True,
        "ports": {"bridge_web": 4999},
        "model_configured": bool(key and terms),
    }
    if binding:
        state["binding"] = {
            "account_id": "private-account",
            "group_id": "private-group",
            "group_name": "用户原来的群",
        }
    root.mkdir(exist_ok=True)
    (root / "installation.json").write_text(json.dumps(state))
    for name in ("MaiBot/.venv/Scripts/python.exe", "assistant_setup/manage.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    model = root / "MaiBot/config/model_config.toml"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(
        '[[api_providers]]\nname="DeepSeek"\napi_key=' + json.dumps(key) + "\n"
    )
    for doc, marker in (
        ("EULA.md", "eula.confirmed"),
        ("PRIVACY.md", "privacy.confirmed"),
    ):
        (root / "MaiBot" / doc).write_text("test terms")
        if terms:
            (root / "MaiBot" / marker).write_text(
                hashlib.md5(b"test terms").hexdigest()
            )
    return state


def flags(login=False, connected=False):
    return {
        "bridge_reachable": True,
        "wechat_login_ready": login,
        "onebot_connected": connected,
    }


@pytest.mark.parametrize("host", entry.HOSTS)
def test_readonly_status_does_not_create_installation(tmp_path, host):
    report = entry.status_report(tmp_path / "missing", host)
    assert report["phase"] == "installation_required"
    assert not (tmp_path / "missing").exists()


def test_key_and_terms_are_verified_from_actual_files(tmp_path, monkeypatch):
    state = fake_install(tmp_path, key="test-private-credential")
    state["model_configured"] = True
    (tmp_path / "installation.json").write_text(json.dumps(state))
    monkeypatch.setattr(entry, "bridge_flags", lambda _: flags(True, True))
    assert (
        entry.status_report(tmp_path, "generic")["phase"]
        == "awaiting_model_key_and_terms"
    )
    (tmp_path / "MaiBot/eula.confirmed").write_text("obsolete approval")
    assert entry.model_ready(tmp_path) == (True, False)


@pytest.mark.parametrize("key", ["", "YOUR_API_KEY", "<paste-key>", "change_me"])
def test_placeholder_key_does_not_advance_onboarding(tmp_path, key):
    fake_install(tmp_path, key=key, terms=True)
    assert not entry.model_ready(tmp_path)[0]


def test_status_and_journal_never_expose_keys_or_binding_ids(tmp_path, monkeypatch):
    fake_install(tmp_path, key="private-unit-test-key", terms=True, binding=True)
    monkeypatch.setattr(entry, "bridge_flags", lambda _: flags(True, True))
    report = entry.status_report(tmp_path, "doubao")
    entry.persist_phase(tmp_path, report)
    serialized = json.dumps(report) + (tmp_path / "agent-onboarding.json").read_text()
    assert all(
        value not in serialized
        for value in ("private-unit-test-key", "private-account", "private-group")
    )
    assert report["phase"] == "awaiting_message_acceptance"
    assert report["delivery_verified"] is False


def test_nonlocal_host_is_rejected_before_any_install_write(tmp_path, monkeypatch):
    monkeypatch.setattr(
        entry,
        "capabilities",
        lambda: {"windows": False, "x64_python": True, "interactive_session": False},
    )
    monkeypatch.setattr(
        entry, "prepare", lambda *_: pytest.fail("must not install in a cloud sandbox")
    )
    with pytest.raises(RuntimeError):
        entry.onboard(tmp_path, tmp_path / "app", "doubao")
    assert list(tmp_path.iterdir()) == []


def test_first_onboard_prepares_then_waits_for_own_credentials(tmp_path, monkeypatch):
    root = tmp_path / "app"
    monkeypatch.setattr(entry, "require_local_windows", lambda: None)
    monkeypatch.setattr(entry, "prepare", lambda *_: fake_install(root))
    monkeypatch.setattr(entry, "bridge_flags", lambda _: flags())
    windows = []
    monkeypatch.setattr(entry, "show_gui", lambda *_: windows.append("credentials"))
    monkeypatch.setattr(
        entry, "execute", lambda *_: pytest.fail("no service before user's key/terms")
    )
    result = entry.onboard(tmp_path, root, "workbuddy")
    assert windows == ["credentials"]
    assert result["phase"] == "awaiting_model_key_and_terms"


def test_login_wait_preserves_all_existing_config_bytes(tmp_path, monkeypatch):
    fake_install(tmp_path, key="private-test-key", terms=True)
    marker = tmp_path / "user-preferences.json"
    marker.write_text('{"custom_proactive": 127, "mode": "custom"}')
    before = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    monkeypatch.setattr(entry, "require_local_windows", lambda: None)
    monkeypatch.setattr(entry, "bridge_flags", lambda _: flags(False, True))
    monkeypatch.setattr(
        entry,
        "execute",
        lambda *_: pytest.fail("existing connected services must not restart"),
    )
    monkeypatch.setattr(
        entry, "show_gui", lambda *_: pytest.fail("no second credentials window")
    )
    result = entry.onboard(tmp_path, tmp_path, "doubao", no_browser=True)
    assert result["phase"] == "awaiting_wechat_login"
    assert all((tmp_path / p).read_bytes() == data for p, data in before.items())


def test_ready_login_opens_picker_without_guessing_group(tmp_path, monkeypatch):
    fake_install(tmp_path, key="private-test-key", terms=True)
    monkeypatch.setattr(entry, "require_local_windows", lambda: None)
    monkeypatch.setattr(entry, "bridge_flags", lambda _: flags(True, True))
    monkeypatch.setattr(
        entry, "execute", lambda *_: pytest.fail("must not bind an invented group")
    )
    opened = []
    monkeypatch.setattr(entry, "show_gui", lambda _, command: opened.append(command))
    result = entry.onboard(tmp_path, tmp_path, "generic")
    assert opened == ["bind-window"]
    assert result["phase"] == "awaiting_group_selection"


def test_authorized_group_binding_preserves_default_proactive_choice(
    tmp_path, monkeypatch
):
    fake_install(tmp_path, key="private-test-key", terms=True)
    monkeypatch.setattr(entry, "require_local_windows", lambda: None)
    monkeypatch.setattr(entry, "bridge_flags", lambda _: flags(True, True))
    calls = []

    def execute(arguments, _root):
        calls.append([str(x) for x in arguments])
        if "bind" in arguments:
            state = entry.load_json(tmp_path / "installation.json")
            state["binding"] = {
                "account_id": "fake-current",
                "group_id": "fake-selected",
            }
            (tmp_path / "installation.json").write_text(json.dumps(state))

    monkeypatch.setattr(entry, "execute", execute)
    result = entry.onboard(
        tmp_path, tmp_path, "workbuddy", group_name="用户明确选择的群"
    )
    assert result["phase"] == "awaiting_message_acceptance"
    assert calls[0][-3:] == ["bind", "--group-name", "用户明确选择的群"]
    assert calls[1][-2:] == ["verify", "--live"]
    assert "--proactive" not in calls[0] and "--no-proactive" not in calls[0]


def test_missing_bundle_never_falls_back_to_downloading(tmp_path, monkeypatch):
    monkeypatch.setattr(
        entry, "execute", lambda *_: pytest.fail("missing payload cannot execute")
    )
    with pytest.raises(FileNotFoundError):
        entry.prepare(tmp_path, tmp_path / "app")
    assert list(tmp_path.iterdir()) == []


def test_existing_installation_can_resume_without_original_bundle(tmp_path):
    fake_install(tmp_path)
    assert entry.root_for(tmp_path, None) == tmp_path
    assert entry.bundle_for(tmp_path) is None


def test_loopback_probe_disables_proxies_and_filters_account_fields(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, limit):
            return json.dumps(
                {
                    "self": {"wxid": "private-wxid"},
                    "inbound": {"ready": True},
                    "ob": {"connected": True},
                }
            ).encode()

    class Opener:
        def open(self, url, timeout):
            assert url == "http://127.0.0.1:4999/api/status"
            return Response()

    def build(handler):
        assert handler.proxies == {}
        return Opener()

    monkeypatch.setattr(entry.urllib.request, "build_opener", build)
    result = entry.bridge_flags({"ports": {"bridge_web": 4999}})
    assert result == flags(True, True)
    assert "private-wxid" not in json.dumps(result)


@pytest.mark.parametrize("terms", [True, False])
def test_interrupted_credential_save_repairs_only_a_valid_confirmation(tmp_path, terms):
    state = fake_install(tmp_path, key="private-test-key", terms=terms)
    state.update(model_configured=False, custom_preference=127)
    (tmp_path / "installation.json").write_text(json.dumps(state))
    key_before = (tmp_path / "MaiBot/config/model_config.toml").read_bytes()
    entry.reconcile_model_marker(tmp_path)
    after = entry.load_json(tmp_path / "installation.json")
    assert after["model_configured"] is terms
    assert after["custom_preference"] == 127
    assert (tmp_path / "MaiBot/config/model_config.toml").read_bytes() == key_before


def test_explicit_new_group_is_applied_even_when_already_bound(tmp_path, monkeypatch):
    fake_install(tmp_path, key="private-test-key", terms=True, binding=True)
    monkeypatch.setattr(entry, "require_local_windows", lambda: None)
    monkeypatch.setattr(entry, "bridge_flags", lambda _: flags(True, True))
    calls = []
    monkeypatch.setattr(
        entry, "execute", lambda args, _: calls.append([str(x) for x in args])
    )
    entry.onboard(tmp_path, tmp_path, "doubao", group_name="用户重新指定的群")
    assert calls[0][-3:] == ["bind", "--group-name", "用户重新指定的群"]


def test_proactive_change_checks_account_and_keeps_exact_group(tmp_path, monkeypatch):
    fake_install(tmp_path, key="private-test-key", terms=True, binding=True)
    monkeypatch.setattr(entry, "require_local_windows", lambda: None)
    monkeypatch.setattr(entry, "bridge_flags", lambda _: flags(True, True))
    calls = []
    monkeypatch.setattr(
        entry, "execute", lambda args, _: calls.append([str(x) for x in args])
    )
    entry.onboard(tmp_path, tmp_path, "workbuddy", proactive=True)
    assert calls[0][-2:] == ["verify", "--live"]
    assert calls[1][-6:] == [
        "bind",
        "--group-name",
        "用户原来的群",
        "--group-id",
        "private-group",
        "--proactive",
    ]


def test_first_start_opens_only_one_login_panel(tmp_path, monkeypatch):
    import webbrowser

    fake_install(tmp_path, key="private-test-key", terms=True)
    monkeypatch.setattr(entry, "require_local_windows", lambda: None)
    responses = iter(
        [{**flags(False, False), "bridge_reachable": False}, flags(False, True)]
    )
    monkeypatch.setattr(entry, "bridge_flags", lambda _: next(responses))
    monkeypatch.setattr(
        webbrowser,
        "open",
        lambda *_: pytest.fail("manage.start already opens the panel"),
    )
    commands = []
    monkeypatch.setattr(
        entry, "execute", lambda args, _: commands.append([str(x) for x in args])
    )
    result = entry.onboard(tmp_path, tmp_path, "generic")
    assert result["phase"] == "awaiting_wechat_login"
    assert commands[0][-1] == "start"
