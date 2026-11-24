from pathlib import Path

from sfm_workshop.core.workspaces import Workspace, group_projects


def test_group_projects_by_workspace(tmp_path):
    ws1 = tmp_path / "AlphaWorkspace"
    ws2 = tmp_path / "BetaWorkspace"
    ws1.mkdir()
    ws2.mkdir()
    p1 = ws1 / "a.sfmproj"
    p2 = ws2 / "b.sfmproj"
    p1.write_text("{}", encoding="utf-8")
    p2.write_text("{}", encoding="utf-8")
    groups = group_projects(
        [
            {"name": "A", "path": str(p1), "at": "2026-01-01T00:00:00"},
            {"name": "B", "path": str(p2), "at": "2026-01-02T00:00:00"},
        ],
        [
            Workspace("a", "Alpha", str(ws1), True),
            Workspace("b", "Beta", str(ws2)),
        ],
        current_name="A",
        current_path=str(p1),
    )
    assert [g["name"] for g in groups] == ["Alpha", "Beta"]
    assert groups[0]["projects"][0]["name"] == "A"
    assert groups[0]["projects"][0]["current"] is True
    assert groups[1]["projects"][0]["name"] == "B"


def test_group_unsaved_project_in_default(tmp_path):
    ws = tmp_path / "Default"
    ws.mkdir()
    groups = group_projects(
        [],
        [Workspace("default", "默认工作区", str(ws), True)],
        current_name="未保存工程",
        current_path="",
    )
    assert len(groups) == 1
    assert groups[0]["projects"][0]["name"] == "未保存工程"


def test_group_nests_child_workspace_and_keeps_one_session_per_file(tmp_path):
    parent = tmp_path / "Factory"
    child = parent / "Sub"
    child.mkdir(parents=True)
    from sfm_workshop.core.model import new_blank_project
    from sfm_workshop.core.storage import save_project

    save_project(new_blank_project("Parent Code"), parent / "parent.sfmproj")
    save_project(new_blank_project("Child Code"), child / "child.sfmproj")
    groups = group_projects(
        [],
        [
            Workspace("parent", "Factory", str(parent), True),
            Workspace("child", "Sub", str(child)),
        ],
        current_path=str(parent / "parent.sfmproj"),
    )
    by_id = {g["id"]: g for g in groups}
    assert by_id["parent"]["parent_path"] == ""
    assert by_id["child"]["parent_path"] == str(parent.resolve())
    assert [p["name"] for p in by_id["parent"]["projects"]] == ["Parent Code"]
    assert [p["name"] for p in by_id["child"]["projects"]] == ["Child Code"]
    assert by_id["parent"]["projects"][0]["current"] is True


def test_current_selection_does_not_reorder_sessions(tmp_path):
    workspace = tmp_path / "Workspace"
    workspace.mkdir()
    older = workspace / "older.sfmproj"
    newer = workspace / "newer.sfmproj"
    older.write_text("{}", encoding="utf-8")
    newer.write_text("{}", encoding="utf-8")
    groups = group_projects(
        [
            {"name": "Older", "path": str(older), "at": "2026-01-01T00:00:00"},
            {"name": "Newer", "path": str(newer), "at": "2026-01-02T00:00:00"},
        ],
        [Workspace("ws", "Workspace", str(workspace), True)],
        current_path=str(older),
    )
    names = [p["name"] for p in groups[0]["projects"]]
    assert names == ["Newer", "Older"]
    assert groups[0]["projects"][1]["current"] is True
