from sfm_workshop.core.codegen import generate_project
from sfm_workshop.core.importer import import_sfml
from sfm_workshop.core.model import Batch, Project, SIDE_TO_SFML, Send, Take, Task


def test_relative_and_world_face_tokens():
    assert SIDE_TO_SFML["上面"] == "top side"
    assert SIDE_TO_SFML["下面"] == "bottom side"
    assert SIDE_TO_SFML["前面"] == "front side"
    assert SIDE_TO_SFML["后面"] == "back side"
    assert SIDE_TO_SFML["左面"] == "left side"
    assert SIDE_TO_SFML["右面"] == "right side"
    assert SIDE_TO_SFML["东面"] == "east side"
    assert SIDE_TO_SFML["西面"] == "west side"
    assert SIDE_TO_SFML["南面"] == "south side"
    assert SIDE_TO_SFML["北面"] == "north side"



def _project():
    p = Project(name="Import roundtrip", profile_id="1.21.1-neoforge")
    t = Task(name="Two batches")
    t.batches = [
        Batch(
            take=Take(source="原料箱", side="上面", quantity=8, retain=2),
            sends=[Send(target="熔炉", side="前面"), Send(target="熔炉", side="下面", retain=1)],
            clear=True,
        ),
        Batch(
            take=Take(source="煤炭箱", side="默认面", quantity=1),
            sends=[Send(target="熔炉", side="左面", retain=1)],
            clear=True,
            condition="redstone ge 1",
        ),
    ]
    p.tasks = [t]
    p.active_task_id = t.id
    return p


def test_import_generated_sfml_roundtrip():
    source = _project()
    code = generate_project(source)
    result = import_sfml(code, "1.21.1-neoforge", "Imported")
    assert result.project.name == "Import roundtrip"
    assert len(result.project.tasks) == 1
    assert len(result.project.tasks[0].batches) == 2
    assert result.project.tasks[0].batches[0].take.source == "原料箱"
    assert result.project.tasks[0].batches[0].take.side == "上面"
    assert result.project.tasks[0].batches[0].sends[0].side == "前面"
    assert result.project.tasks[0].batches[1].condition == "redstone ge 1"
    assert generate_project(result.project) == code


def test_import_rejects_invalid_sfml():
    try:
        import_sfml("hello world", "1.21.1-neoforge")
    except ValueError as exc:
        assert "语法" in str(exc)
    else:
        raise AssertionError("invalid SFML should not import")
