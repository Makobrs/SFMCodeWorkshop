from __future__ import annotations

import json
from pathlib import Path

import pytest

import sfm_workshop
from sfm_workshop.core import codegen, storage, templates
from sfm_workshop.core.model import Task
from sfm_workshop.core.validate import validate_project
from sfm_workshop.grammar import parse_sfml

EXPECTED_PRESET_FILES = {
    "01-furnace.sfmproj",
    "02-fuel.sfmproj",
    "03-tree-farm.sfmproj",
    "04-bee-sorting.sfmproj",
    "05-ore-sorting.sfmproj",
    "06-fluid.sfmproj",
    "07-energy.sfmproj",
    "08-redstone.sfmproj",
}

BUILTIN_KEYS = [
    "furnace",
    "fuel",
    "tree-farm",
    "bee-sorting",
    "ore-sorting",
    "fluid",
    "energy",
    "redstone",
]

BUILTIN_NAMES = [
    "熔炉自动线",
    "燃料补给",
    "树场收集",
    "蜂箱分类",
    "矿物分拣",
    "流体转运",
    "能量传输",
    "红石脉冲",
]


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Keep preset writes and user templates inside the test directory."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(storage, "resource_root", lambda: tmp_path / "resources")
    return tmp_path


def test_committed_preset_files_exist_in_package():
    root = (
        Path(sfm_workshop.__file__).resolve().parent
        / "resources"
        / "templates"
        / "presets"
    )
    names = {path.name for path in root.glob("*.sfmproj")}
    assert names == EXPECTED_PRESET_FILES
    assert templates.BLANK_FILENAME not in names


def test_list_templates_has_eight_presets_and_blank():
    infos = templates.list_templates()
    assert [info.name for info in infos[:8]] == BUILTIN_NAMES
    assert [info.key for info in infos[:8]] == BUILTIN_KEYS
    assert all(info.builtin and info.path is not None and info.path.exists() for info in infos[:8])
    assert all(info.path.parent == storage.presets_templates_dir() for info in infos[:8])
    blank = infos[8]
    assert blank.key == "blank"
    assert not blank.builtin  # blank lives in the user dir and is editable
    assert blank.path is not None and blank.path.exists()
    assert blank.path.parent == storage.user_templates_dir()
    assert blank.path.name == templates.BLANK_FILENAME
    assert not (storage.presets_templates_dir() / templates.BLANK_FILENAME).exists()


def test_every_builtin_template_parses_and_validates():
    for key in [*BUILTIN_KEYS, "blank"]:
        project = templates.load_template(key)
        code = codegen.generate_project(project)
        assert parse_sfml(code) == [], (key, code)
        result = validate_project(project)
        assert not result.blocked, (key, [i.message for i in result.issues if i.level == "block"])
        assert result.syntax_errors == []


def test_preset_files_are_deterministic_json():
    templates.ensure_builtin_templates()
    presets = storage.presets_templates_dir()
    files = sorted(presets.glob("*.sfmproj"))
    assert len(files) == 8
    snapshot = {path.name: path.read_bytes() for path in files}
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == 1
        assert data["name"] in BUILTIN_NAMES
        assert isinstance(data["tasks"], list)
        assert data["template_key"]
        assert b"\r\n" not in path.read_bytes()

    for path in files:
        path.unlink()
    templates.ensure_builtin_templates()
    for path in files:
        assert path.read_bytes() == snapshot[path.name], path.name


def test_missing_preset_is_rebuilt_from_definition():
    templates.ensure_builtin_templates()
    presets = storage.presets_templates_dir()
    path = presets / "01-furnace.sfmproj"
    path.unlink()
    info = next(i for i in templates.list_templates() if i.key == "furnace")
    assert info.path is not None and info.path.exists()
    project = templates.load_template("furnace")
    assert project.name == "熔炉自动线"


def test_corrupt_preset_is_rebuilt():
    presets = storage.presets_templates_dir()
    path = presets / "03-tree-farm.sfmproj"
    path.write_text("{not json", encoding="utf-8")
    project = templates.load_template("tree-farm")
    assert project.name == "树场收集"
    assert json.loads(path.read_text(encoding="utf-8"))["name"] == "树场收集"


def test_blank_template_has_labels_but_no_tasks():
    project = templates.load_template("blank")
    assert project.tasks == []
    assert [label.name for label in project.labels] == ["原料箱", "熔炉", "成品箱"]
    assert project.template_key == "blank"
    assert codegen.generate_project(project) == 'name "未命名工程"\n'
    assert parse_sfml(codegen.generate_project(project)) == []


def test_load_by_key_filename_and_path(tmp_path):
    by_key = templates.load_template("furnace")
    by_filename = templates.load_template("01-furnace")
    by_path = templates.load_template(str(storage.presets_templates_dir() / "01-furnace.sfmproj"))

    assert by_key.name == by_filename.name == by_path.name == "熔炉自动线"
    assert by_key.template_key == by_filename.template_key == by_path.template_key == "furnace"
    # Every load is a new document.
    assert len({by_key.id, by_filename.id, by_path.id}) == 3


def test_load_template_profile_override():
    project = templates.load_template("furnace", "1.20.1-forge")
    assert project.profile_id == "1.20.1-forge"
    assert project.profile.mc == "1.20.1"

    fallback = templates.load_template("furnace", "9.9.9-unknown")
    assert fallback.profile_id == "1.21.1-neoforge"


def test_load_missing_template_raises():
    with pytest.raises(FileNotFoundError):
        templates.load_template("does-not-exist")


def test_load_does_not_modify_preset_file():
    templates.ensure_builtin_templates()
    presets = storage.presets_templates_dir()
    path = presets / "02-fuel.sfmproj"
    before = path.read_bytes()
    templates.load_template("fuel")
    assert path.read_bytes() == before


def test_save_template_roundtrip(tmp_path):
    project = templates.blank_project("1.20.1-forge")
    project.name = "我的模板"
    project.tasks = [Task(name="自定义任务")]
    project.tasks[0].batches[0].take.source = "原料箱"
    project.tasks[0].batches[0].sends[0].target = "熔炉"
    project.active_task_id = project.tasks[0].id

    target = tmp_path / "我的模板.sfmproj"
    saved = templates.save_template(project, target)
    assert saved == target and saved.exists()

    loaded = templates.load_template(str(saved))
    assert loaded.name == "我的模板"
    assert loaded.profile_id == "1.20.1-forge"
    assert loaded.tasks and loaded.tasks[0].batches[0].take.source == "原料箱"


def test_save_template_adds_extension(tmp_path):
    saved = templates.save_template(templates.blank_project(), tmp_path / "无后缀")
    assert saved.suffix == ".sfmproj"
    assert saved.exists()


def test_save_template_rejects_presets(tmp_path):
    project = templates.blank_project()
    with pytest.raises(ValueError):
        templates.save_template(project, storage.presets_templates_dir() / "hack.sfmproj")


def test_copy_template_to_user_is_a_copy():
    templates.ensure_builtin_templates()
    presets = storage.presets_templates_dir()
    source = presets / "02-fuel.sfmproj"
    before = source.read_bytes()

    copied = templates.copy_template_to_user("fuel")
    assert copied.parent == storage.user_templates_dir()
    assert copied.read_bytes() == before
    assert source.read_bytes() == before

    second = templates.copy_template_to_user("fuel")
    assert second != copied
    assert second.exists()


def test_copy_blank_returns_existing_blank():
    blank_path = storage.user_templates_dir() / templates.BLANK_FILENAME
    result = templates.copy_template_to_user("blank")
    assert result == blank_path
    assert result.exists()
    assert len(list(storage.user_templates_dir().glob("blank*.sfmproj"))) == 1


def test_user_template_is_discovered_and_editable(tmp_path):
    user_dir = storage.user_templates_dir()
    project = templates.blank_project()
    project.name = "自定义模板"
    path = templates.save_template(project, user_dir / "custom.sfmproj")

    infos = templates.list_templates()
    custom = [info for info in infos if info.key == "custom"]
    assert len(custom) == 1
    assert not custom[0].builtin
    assert custom[0].name == "自定义模板"
    assert custom[0].path == path

    loaded = templates.load_template("custom")
    assert loaded.name == "自定义模板"
    assert loaded.template_key == "custom"


def test_blank_project_is_writable_and_has_default_labels():
    first = templates.blank_project()
    second = templates.blank_project("1.20.1-forge")
    assert first.tasks == [] and second.tasks == []
    assert [label.name for label in first.labels] == ["原料箱", "熔炉", "成品箱"]
    assert first.profile_id == "1.21.1-neoforge"
    assert second.profile_id == "1.20.1-forge"
    assert first.id != second.id
    assert templates.blank_project("bogus").profile_id == "1.21.1-neoforge"


def test_ensure_builtin_templates_returns_all_nine_paths():
    paths = templates.ensure_builtin_templates()
    assert len(paths) == 9
    assert all(path.exists() for path in paths)
