"""本地库读取层：引用消息要带回被引消息的服务端号。

微信把引用塞在 appmsg 的 `<refermsg>` 里，`<svrid>` 就是被引消息的 `server_id`。
这是收件侧还原 `reply` 段的唯一依据，所以读取层必须把两者都带出来。
"""

import hashlib
import os
import sqlite3
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from flandora import wx_store  # noqa: E402

TALKER = "wxid_lisi"
QUOTE_SVID = "6961106450683539328"
APP_QUOTE = 57  # appmsg 的引用子类型（高位）
BASE_APPMSG = 49  # appmsg 基础类型（低位）

QUOTE_XML = (
    "<msg><appmsg><title>同意</title>"
    "<refermsg><chatusr>wxid_lisi</chatusr><displayname>李四</displayname>"
    f"<svrid>{QUOTE_SVID}</svrid><type>1</type><content>明天开会</content></refermsg>"
    "</appmsg></msg>"
)


def _build_db(work_dir: str) -> None:
    table = "Msg_" + hashlib.md5(TALKER.encode("utf-8")).hexdigest()
    con = sqlite3.connect(os.path.join(work_dir, "message_0.db"))
    try:
        con.execute("CREATE TABLE Name2Id (user_name TEXT)")
        con.execute("INSERT INTO Name2Id (user_name) VALUES (?)", (TALKER,))
        con.execute(
            f'CREATE TABLE "{table}" (local_id INTEGER PRIMARY KEY, server_id TEXT, '
            "local_type INTEGER, real_sender_id INTEGER, create_time INTEGER, message_content BLOB)"
        )
        con.execute(
            f'INSERT INTO "{table}" (local_id, server_id, local_type, real_sender_id, '
            "create_time, message_content) VALUES (?,?,?,?,?,?)",
            (5, "SN-PLAIN", 1, 1, 1720000000, "明天开会"),
        )
        con.execute(
            f'INSERT INTO "{table}" (local_id, server_id, local_type, real_sender_id, '
            "create_time, message_content) VALUES (?,?,?,?,?,?)",
            (6, "SN-QUOTE", (APP_QUOTE << 32) | BASE_APPMSG, 1, 1720000060, QUOTE_XML),
        )
        con.commit()
    finally:
        con.close()


def _store(tmp_path):
    store = wx_store.WxStore(
        data_dir=str(tmp_path), passphrase=b"", work_dir=str(tmp_path), my_wxid="wxid_self"
    )
    store._decrypted.add("message_0.db")
    return store


def test_quote_ref_extracts_server_id_and_sender():
    assert wx_store.quote_ref(QUOTE_XML) == {
        "server_id": QUOTE_SVID,
        "sender": "wxid_lisi",
        "name": "李四",
    }


def test_quote_ref_needs_svrid():
    assert wx_store.quote_ref("<msg><appmsg><title>x</title></appmsg></msg>") is None
    assert wx_store.quote_ref("") is None


def test_messages_carry_server_id_and_quote(tmp_path):
    _build_db(str(tmp_path))
    rows = _store(tmp_path).messages(TALKER)
    assert [r["local_id"] for r in rows] == [5, 6]
    assert rows[0]["server_id"] == "SN-PLAIN"
    assert rows[0]["quote"] == {}
    assert rows[0]["kind"] == "text"
    assert rows[1]["server_id"] == "SN-QUOTE"
    assert rows[1]["kind"] == "quote"
    assert rows[1]["text"] == "同意"
    assert rows[1]["quote"]["server_id"] == QUOTE_SVID
    assert rows[1]["quote"]["name"] == "李四"


def test_recent_messages_carry_server_id(tmp_path):
    _build_db(str(tmp_path))
    rows = _store(tmp_path).recent_messages(TALKER)
    assert [r["local_id"] for r in rows] == [5, 6]
    assert [r["server_id"] for r in rows] == ["SN-PLAIN", "SN-QUOTE"]


def test_group_existing_only_in_second_shard_is_read(tmp_path):
    _build_db(str(tmp_path))
    (tmp_path / "message_0.db").rename(tmp_path / "message_1.db")
    store = _store(tmp_path)
    store._decrypted = {"message_1.db"}
    assert [r["local_id"] for r in store.messages(TALKER)] == [5, 6]
    assert [r["local_id"] for r in store.recent_messages(TALKER, limit=1)] == [6]
    assert store.message_by_server(TALKER, "SN-PLAIN")["text"] == "明天开会"


def test_shards_use_their_own_sender_mapping_and_global_limit(tmp_path):
    _build_db(str(tmp_path))
    other = tmp_path / "other"
    other.mkdir()
    _build_db(str(other))
    (other / "message_0.db").rename(tmp_path / "message_1.db")
    table = wx_store.WxStore.table_for(TALKER)
    with sqlite3.connect(tmp_path / "message_1.db") as con:
        con.execute("UPDATE Name2Id SET user_name='wxid_other_sender'")
        con.execute(f"UPDATE \"{table}\" SET local_id=local_id+2, server_id=server_id||'-new'")
    store = _store(tmp_path)
    store._decrypted.add("message_1.db")
    rows = store.messages(TALKER, after_local_id=5, limit=2)
    assert [r["local_id"] for r in rows] == [6, 7]
    assert rows[1]["sender"] == "wxid_other_sender"
    assert [r["local_id"] for r in store.recent_messages(TALKER, limit=2)] == [7, 8]


def test_duplicate_rows_in_shards_are_returned_once(tmp_path):
    _build_db(str(tmp_path))
    import shutil

    shutil.copyfile(tmp_path / "message_0.db", tmp_path / "message_1.db")
    store = _store(tmp_path)
    store._decrypted.add("message_1.db")
    assert [r["local_id"] for r in store.messages(TALKER)] == [5, 6]


def test_quote_ref_takes_the_sender_from_either_field():
    """被引消息的发送者可能在 fromusr，也可能只在 chatusr：两个都认，fromusr 优先。"""
    group_quote = (
        "<msg><appmsg><refermsg><fromusr>wxid_self</fromusr>"
        "<chatusr>50071592949@chatroom</chatusr><displayname>芙兰朵露Flandre</displayname>"
        f"<svrid>{QUOTE_SVID}</svrid></refermsg></appmsg></msg>"
    )
    assert wx_store.quote_ref(group_quote)["sender"] == "wxid_self"

    only_fromusr = (
        "<msg><appmsg><refermsg><fromusr>wxid_zhangsan</fromusr>"
        f"<svrid>{QUOTE_SVID}</svrid></refermsg></appmsg></msg>"
    )
    assert wx_store.quote_ref(only_fromusr)["sender"] == "wxid_zhangsan"

    only_chatusr = (
        "<msg><appmsg><refermsg><chatusr>wxid_zhangsan</chatusr>"
        f"<svrid>{QUOTE_SVID}</svrid></refermsg></appmsg></msg>"
    )
    assert wx_store.quote_ref(only_chatusr)["sender"] == "wxid_zhangsan"
