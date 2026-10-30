"""查询命中后停止读取无关聊天分支，保留顺序、预算与实时摘要校验。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flandora.uia_sender import UiaSender


class Node:
    def __init__(self, name, cls="", children=(), fail=False):
        self.Name = name
        self.ClassName = cls
        self.children = list(children)
        self.fail = fail
        self.expanded = 0

    def GetChildren(self):  # noqa: N802
        self.expanded += 1
        if self.fail:
            raise RuntimeError("control disappeared")
        return self.children


def sender(root):
    instance = object.__new__(UiaSender)
    instance._window = root
    return instance


def test_find_stops_before_expanding_target_or_unrelated_history():
    target = Node("input", UiaSender.INPUT_FIELD_CLASS)
    history = Node("history", children=[Node("message") for _ in range(100)])
    root = Node("window", children=[target, history])
    assert sender(root)._find_by_class(UiaSender.INPUT_FIELD_CLASS) is target
    assert target.expanded == history.expanded == 0


def test_find_keeps_breadth_first_priority():
    deep = Node("deep", "wanted")
    shallow = Node("shallow", "wanted")
    root = Node("window", children=[Node("branch", children=[deep]), shallow])
    assert sender(root)._find_by_class("wanted") is shallow


def test_complete_walk_keeps_order_and_survives_disappeared_branch():
    child = Node("child")
    root = Node("root", children=[Node("gone", fail=True), Node("branch", children=[child])])
    assert [(d, n.Name) for d, n in sender(root)._walk()] == [
        (0, "root"),
        (1, "gone"),
        (1, "branch"),
        (2, "child"),
    ]


def test_walk_still_obeys_node_and_depth_limits():
    root = Node("root", children=[Node("a", children=[Node("deep")]), Node("b")])
    instance = sender(root)
    instance.WALK_MAX_NODES = 2
    assert [n.Name for _, n in instance._walk()] == ["root", "a"]
    instance.WALK_MAX_NODES = 100
    instance.WALK_MAX_DEPTH = 1
    assert [n.Name for _, n in instance._walk()] == ["root", "a", "b"]


def test_summary_is_live_and_stops_at_matching_session():
    cell = Node("test group\nold text\nnow", UiaSender.SESSION_CELL_CLASS)
    history = Node("history", children=[Node("message")])
    instance = sender(Node("window", children=[cell, history]))
    assert instance._session_summary("test group") == "old text"
    cell.Name = "test group\nnew text\nnow"
    assert instance._session_summary("test group") == "new text"
    assert history.expanded == 0
