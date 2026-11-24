"""Deterministic SFML 4.34 code generation for the workshop IR.

The generator is intentionally tiny and predictable: the same :class:`Project`
always produces byte-identical text (LF only, UTF-8 at write time, no
timestamp, no random data).  Everything the UI edits lives in
``core.model``; this module is the only place that turns it into SFML.

Grammar notes (verified against the bundled official 4.34 ANTLR parser):
  * clause order inside an I/O statement is fixed:
    ``input <qty> retain <n> <resource> <with/without> from "label" <side>``;
  * only one ``with``/``without`` clause is allowed per resource limit, so a
    take that has both filters is emitted as
    ``with (<with>) and (not (<without>))`` -- a single equivalent tag filter;
  * ``FORGET`` is the clear statement;
  * ``IF`` wraps the batch statements with one ``END``;
  * labels are always quoted and embedded ``"`` characters are escaped.
"""
from __future__ import annotations

from functools import lru_cache
import re

from .model import (
    DEFAULT_PROFILE,
    PROFILES,
    SIDE_TO_SFML,
    Batch,
    Project,
    Send,
    Take,
    Task,
)

INDENT = "    "

#: Character budget for a compiled SFML program (SFM 4.34.0 / PRD FR-11).
#: The upstream changelog says "about 32,300"; the checked source constant is
#: 32,600.  PRD pins the conservative 32,367 used by the product.
PROGRAM_CHAR_LIMIT = 32367

#: Resource-type prefix used when the user leaves a typed resource ID alone.
#: ``fe`` is the official shorthand for ``forge_energy``; chemicals use
#: ``chemical`` on MC 1.21.x builds and ``gas`` on older builds.
_TYPE_PREFIX = {
    "流体": "fluid",
    "能量": "fe",
}

_CHEMICAL_TYPES = {"化学品"}

#: First segment of a resource ID that denotes a resource *type* rather than a
#: namespace.  If present, the ID is emitted verbatim.
_RESOURCE_TYPE_TOKENS = {
    "item",
    "fluid",
    "fe",
    "rf",
    "energy",
    "power",
    "forge_energy",
    "mekanism_energy",
    "chemical",
    "gas",
    "infusion",
    "slurry",
    "pigment",
    "redstone",
}

_BARE_FILTER_RE = re.compile(r"^[A-Za-z0-9_*:./\-]+$")
_FILTER_KEYWORDS_RE = re.compile(r"\b(?:tag|not|and|or)\b", re.IGNORECASE)
#: Characters that can never appear in a single-line with/without clause.
_FILTER_BAD_CHARS_RE = re.compile(r'[\r\n{};",]')
#: One identifier segment of a resource ID (wildcards allowed for matching).
_RESOURCE_TOKEN_RE = re.compile(
    r'^(?:[A-Za-z0-9_*][A-Za-z0-9_*.\-]*(?::[A-Za-z0-9_*.\-]*){0,3}'
    r'|"(?:\\"|[^"])*")$'
)
_QUOTED_RESOURCE_RE = re.compile(r'^"(?:\\"|[^"])*"$')


def side_suffix(side: str) -> str:
    """Return the SFML side qualifier for a model side name.

    ``默认面`` (and any unknown/empty value) maps to ``""`` so that no side
    keyword is written; the remaining model values map to the exact keywords
    from ``model.SIDE_TO_SFML`` (e.g. ``每个面`` -> ``"each side"``).
    """
    return SIDE_TO_SFML.get((side or "").strip(), "")


def _quote(text: str) -> str:
    """Quote an SFML string.

    Embedded double quotes are written as ``\\"`` (the only escape the 4.34
    lexer defines).  A trailing backslash would escape the closing quote, so
    it is dropped; control characters are folded to spaces.  Labels containing
    those characters are reported as blockers by ``core.validate``, so this
    lossy fallback only keeps the generated program parseable.
    """
    text = str(text).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    if text.endswith("\\"):
        text = text.rstrip("\\")
    return '"' + text.replace('"', '\\"') + '"'


def _condition_expr(condition: str) -> str:
    """Normalise ``Batch.condition`` into a bare SFML boolean expression.

    Accepts either the expression alone (``"仓库" has > 100``) or a pasted
    full statement (``if ... then``).  Returns ``""`` when nothing is left, in
    which case no ``IF`` is emitted.
    """
    expr = (condition or "").strip()
    if not expr:
        return ""
    if expr.lower().startswith("if "):
        expr = expr[3:].strip()
    if expr.lower().endswith(" then"):
        expr = expr[: -len(" then")].strip()
    return expr


@lru_cache(maxsize=128)
def condition_is_valid(condition: str) -> bool:
    """Return whether *condition* normalises to a parseable 4.34 boolexpr.

    Empty text is valid (no ``IF`` emitted).  Invalid conditions are omitted
    from the generated program and reported as blockers by ``core.validate``.
    """
    expression = _condition_expr(condition)
    if not expression:
        return True
    if len(expression) > 1200 or "\n" in expression or "\r" in expression:
        return False
    from sfm_workshop.grammar import parse_sfml

    probe = (
        "every 20 ticks do\n"
        f"    if {expression} then\n"
        "    end\n"
        "end\n"
    )
    return not parse_sfml(probe)


def _normalise_filter(text: str, polarity: str = "with") -> str:
    """Normalise a with/without filter value into an SFML ``withClause``.

    * a matching leading ``with``/``without`` written by the user is stripped;
    * a mismatched prefix is kept so syntax validation rejects it instead of
      silently flipping ``without`` into ``with``;
    * a bare tag matcher (``forge:gems``, ``#c:ores``) keeps the ``#`` form or
      is prefixed with ``tag`` so it is a valid ``withClause``;
    * richer expressions (``(not #x) and #y``) are passed through.
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    expected = "with " if polarity == "with" else "without "
    wrong = "without " if polarity == "with" else "with "
    if lowered.startswith(expected):
        raw = raw[len(expected) :].strip()
    elif lowered.startswith(wrong):
        return raw  # mismatched prefix: validation will report it
    if not raw:
        return ""
    if "#" not in raw and "(" not in raw and not _FILTER_KEYWORDS_RE.search(raw):
        if _BARE_FILTER_RE.match(raw):
            raw = "tag " + raw
    return raw


def _filter_clause(take: Take) -> str:
    """Return ``with ...`` / ``without ...`` / combined clause (``""`` if none).

    Filters that do not parse as a 4.34 ``withClause`` are omitted from the
    generated program (the project validator reports them as blockers), so a
    typo cannot cascade into unrelated L0 syntax errors.
    """
    with_raw = (take.with_filter or "").strip()
    without_raw = (take.without_filter or "").strip()
    if not filter_is_valid(with_raw, "with") or not filter_is_valid(
        without_raw, "without"
    ):
        return ""
    with_expr = _normalise_filter(with_raw, "with")
    without_expr = _normalise_filter(without_raw, "without")
    if with_expr and without_expr:
        # One limit may only carry one with/without clause in the 4.34 grammar.
        return f"with ({with_expr}) and (not ({without_expr}))"
    if with_expr:
        return f"with {with_expr}"
    if without_expr:
        return f"without {without_expr}"
    return ""


@lru_cache(maxsize=256)
def filter_is_valid(text: str, polarity: str = "with") -> bool:
    """Return whether *text* normalises to a parseable 4.34 withClause.

    Empty text is valid (no filter).  A probe program is parsed with the
    bundled official grammar; results are cached by filter text because the
    UI regenerates code on every edit.
    """
    raw = (text or "").strip()
    if not raw:
        return True
    expression = _normalise_filter(raw, polarity)
    if not expression:
        return True
    if len(expression) > 800 or _FILTER_BAD_CHARS_RE.search(expression):
        return False
    from sfm_workshop.grammar import parse_sfml

    probe = (
        "every 20 ticks do\n"
        f"    input with {expression} from \"probe\"\n"
        "    forget\n"
        "end\n"
    )
    return not parse_sfml(probe)


def is_valid_resource_token(token: str) -> bool:
    """Return whether *token* is a legal SFML 4.34 resource ID (or ``""``)."""
    if not token:
        return True
    return bool(_RESOURCE_TOKEN_RE.match(token))


def is_quoted_resource_id(resource_id: str) -> bool:
    """Return whether the model resource ID is a quoted regular expression."""
    return bool(_QUOTED_RESOURCE_RE.match((resource_id or "").strip()))


def _chemical_prefix(profile_id: str) -> str:
    profile = PROFILES.get(profile_id) or PROFILES[DEFAULT_PROFILE]
    return "gas" if profile.mc.startswith("1.20") else "chemical"


def resource_token(take: Take, profile_id: str = DEFAULT_PROFILE) -> str:
    """Return the SFML resource token for a take (``""`` means items).

    * items with no ID emit nothing (SFM defaults to items);
    * an ID that already starts with a resource-type segment is kept as-is;
    * other IDs are prefixed with the type shorthand (``fluid:``, ``fe:``,
      ``chemical:``/``gas:``);
    * typed takes without an ID emit the wildcard form (``fluid::``, ``fe::``).
    """
    resource_type = (take.resource_type or "物品").strip() or "物品"
    raw = (take.resource_id or "").strip()

    if raw:
        first = raw.split(":", 1)[0].lower()
        if ":" in raw and first in _RESOURCE_TYPE_TOKENS:
            return raw
        if resource_type == "物品":
            return raw
        if resource_type in _CHEMICAL_TYPES:
            return f"{_chemical_prefix(profile_id)}:{raw}"
        prefix = _TYPE_PREFIX.get(resource_type)
        if prefix:
            return f"{prefix}:{raw}"
        # Unknown resource type: emit the raw id and let L1 report the type.
        return raw

    if resource_type == "物品":
        return ""
    if resource_type == "流体":
        return "fluid::"
    if resource_type == "能量":
        return "fe::"
    if resource_type in _CHEMICAL_TYPES:
        return f"{_chemical_prefix(profile_id)}::"
    return ""


def _wildcard_resource_token(take: Take, profile_id: str) -> str:
    """Type-only wildcard for a take whose explicit ID cannot be emitted."""
    resource_type = (take.resource_type or "物品").strip() or "物品"
    if resource_type == "流体":
        return "fluid::"
    if resource_type == "能量":
        return "fe::"
    if resource_type in _CHEMICAL_TYPES:
        return f"{_chemical_prefix(profile_id)}::"
    return ""


def _emitted_resource_token(take: Take, profile_id: str) -> str:
    """Resource token safe to place in a generated statement.

    Invalid IDs keep the take's type intent (wildcard form) or fall back to
    the item default, so the rest of the program still parses; ``validate``
    reports the invalid ID as a blocker so such code cannot be copied.
    """
    token = resource_token(take, profile_id)
    if token and not is_valid_resource_token(token):
        return _wildcard_resource_token(take, profile_id)
    return token


def _positive_int(value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _input_line(take: Take, profile_id: str) -> str:
    parts = ["input"]
    quantity = _positive_int(take.quantity)
    retain = _positive_int(take.retain)
    if quantity:
        parts.append(str(quantity))
    if retain:
        parts.extend(("retain", str(retain)))
    token = _emitted_resource_token(take, profile_id)
    if token:
        parts.append(token)
    clause = _filter_clause(take)
    if clause:
        parts.append(clause)
    parts.append("from")
    parts.append(_quote(take.source))
    side = side_suffix(take.side)
    if side:
        parts.append(side)
    return " ".join(parts)


def _output_line(send: Send) -> str:
    parts = ["output"]
    retain = _positive_int(send.retain)
    if retain:
        parts.extend(("retain", str(retain)))
    parts.append("to")
    parts.append(_quote(send.target))
    side = side_suffix(send.side)
    if side:
        parts.append(side)
    return " ".join(parts)


def _batch_lines(batch: Batch, profile_id: str) -> list[str]:
    """Return a batch's statements without indentation (may be empty)."""
    source = (batch.take.source or "").strip()
    targets = [send for send in batch.sends if (send.target or "").strip()]
    if not source and not targets:
        # Completely empty batches are skipped rather than emitting a lone
        # FORGET (an empty trigger is allowed by the grammar but useless).
        return []

    body: list[str] = []
    if source:
        body.append(_input_line(batch.take, profile_id))
    for send in targets:
        body.append(_output_line(send))
    if batch.clear:
        body.append("forget")

    condition = _condition_expr(batch.condition)
    if not body:
        return []
    if condition and condition_is_valid(batch.condition):
        return (
            [INDENT + f"if {condition} then"]
            + [INDENT * 2 + line for line in body]
            + [INDENT + "end"]
        )
    return [INDENT + line for line in body]


def _task_header(task: Task) -> str:
    if (task.trigger_kind or "timer").strip().lower() == "pulse":
        return "every redstone pulse do"
    interval = _positive_int(task.interval) or 1
    unit = (task.unit or "TICKS").strip().upper()
    unit_word = "seconds" if unit == "SECONDS" else "ticks"
    return f"every {interval} {unit_word} do"


def generate_task(task: Task, profile_id: str = DEFAULT_PROFILE) -> str:
    """Generate one ``every ... do ... end`` trigger block.

    ``profile_id`` only selects the chemical resource prefix on 1.20.x
    profiles; it is optional so the contract signature keeps working.
    Returns ``""`` for a task with no effective statement (no source, no send
    target), which lets :func:`generate_project` skip empty tasks.
    """
    body: list[str] = []
    for batch in task.batches:
        body.extend(_batch_lines(batch, profile_id))
    if not body:
        return ""
    return "\n".join([_task_header(task), *body, "end"]) + "\n"


def task_blocks(project: Project) -> list[tuple[Task, str]]:
    """Return ``(task, generated block)`` for every task that will be emitted."""
    blocks: list[tuple[Task, str]] = []
    for task in project.tasks:
        if not task.enabled:
            continue
        text = generate_task(task, project.profile_id)
        if text:
            blocks.append((task, text))
    return blocks


def generate_project(project: Project) -> str:
    """Generate a complete SFML program for *project*.

    The program is deterministic: tasks keep model order, blank lines only
    separate trigger blocks, and the text always ends with a single ``\\n``
    (``""`` only when there is neither a name nor any emitted task).
    Disabled tasks and tasks without statements are skipped.
    """
    lines: list[str] = []
    name = (project.name or "").strip()
    if name:
        lines.append("name " + _quote(name))

    emitted_any = False
    for _task, block in task_blocks(project):
        if emitted_any:
            lines.append("")
        lines.extend(block.rstrip("\n").split("\n"))
        emitted_any = True

    if not lines:
        return ""
    return "\n".join(lines) + "\n"


__all__ = [
    "INDENT",
    "PROGRAM_CHAR_LIMIT",
    "condition_is_valid",
    "filter_is_valid",
    "generate_project",
    "generate_task",
    "is_quoted_resource_id",
    "is_valid_resource_token",
    "resource_token",
    "side_suffix",
    "task_blocks",
]
