"""Audience-aware cell values.

A second, orthogonal axis to :class:`~asyoulikeit.Importance`:

- ``Importance`` decides *whether* a value, column, or row appears.
- ``Audience`` decides *how* a value that does appear is rendered.

Formatters already split into "for humans" (``display``) and "for machines"
(``tsv``, ``json``). This module turns that split — previously only prose in
the docstrings — into a value the framework can read: every
:class:`~asyoulikeit.Formatter` declares an :class:`Audience`, and a cell can
carry both a machine and a human representation via :class:`ByAudience`.

The producing command stays audience-agnostic — it tags a cell once and never
branches on which formatter ``--as`` will pick::

    table.add_row(
        user=u.full_id,
        quota=ByAudience(machine=u.free_space, human=human_bytes(u.free_space)),
    )

:func:`format_as` knows the chosen formatter, hence its ``audience``, so it
collapses every ``ByAudience`` to the matching representation *before* calling
``format()``. No formatter implementation has to know ``ByAudience`` exists:
``json`` then serialises ``1048576`` as a real number, ``tsv`` stringifies it
to ``"1048576"``, and ``display`` shows ``"1.0 MiB"`` — all from one tagged
cell.

A ``ByAudience`` is honoured anywhere a human-vs-machine string can
legitimately differ: cell values (table rows, tree nodes, scalar values) and
the surrounding metadata — a content ``title`` or ``description`` and a column
``label``. A plain string in any of those positions is returned unchanged.

The collapse is shallow: a ``ByAudience`` that *is* a value is unwrapped; a
``ByAudience`` nested inside a list or dict cell is left alone (the machine
formatters would serialise the container as-is anyway).
"""

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from asyoulikeit.content import ReportContent
from asyoulikeit.scalar_data import ScalarContent
from asyoulikeit.tabular_data import Report, Reports, TableContent
from asyoulikeit.tree_data import Node, TreeContent


class Audience(Enum):
    """The reader a formatter's output is aimed at.

    A binary split is enough for the three shipped formatters — both machine
    formatters are happy with one raw Python value (JSON serialises it
    natively, TSV stringifies it via ``str()``). The enum can grow later if a
    real need for finer granularity appears.
    """

    HUMAN = "human"      # display
    MACHINE = "machine"  # tsv, json


@dataclass(frozen=True)
class ByAudience:
    """A cell value carrying both a machine and a human representation.

    Drop one into any cell; :func:`format_as` collapses it to the single
    representation matching the chosen formatter's :class:`Audience` before the
    formatter runs.

    Attributes:
        machine: The raw / canonical value — e.g. ``1048576``. JSON serialises
            it natively; TSV stringifies it to ``"1048576"``.
        human: The friendly value — e.g. ``"1.0 MiB"`` — shown by ``display``.
    """

    machine: Any
    human: Any

    def for_audience(self, audience: Audience) -> Any:
        """Return the representation matching ``audience``."""
        return self.human if audience is Audience.HUMAN else self.machine


def _resolve_value(value: Any, audience: Audience) -> Any:
    """Collapse a single cell value for ``audience``.

    A :class:`ByAudience` is unwrapped to its matching representation; any
    other value is returned unchanged.
    """
    if isinstance(value, ByAudience):
        return value.for_audience(audience)
    return value


def _resolve_table(data: TableContent, audience: Audience) -> TableContent:
    resolved = TableContent(
        title=_resolve_value(data.title, audience),
        description=_resolve_value(data.description, audience),
        present_transposed=data.present_transposed,
    )
    for col in data.columns:
        resolved.add_column(
            key=col.key,
            label=_resolve_value(col.label, audience),
            header=col.header,
            importance=col.importance,
            omit_if_empty_for=col.omit_if_empty_for,
        )
    for row, importance in zip(data.rows, data.row_importances):
        resolved.add_row(
            _importance=importance,
            **{key: _resolve_value(value, audience) for key, value in row.items()},
        )
    return resolved


def _resolve_tree(data: TreeContent, audience: Audience) -> TreeContent:
    resolved = TreeContent(
        title=_resolve_value(data.title, audience),
        description=_resolve_value(data.description, audience),
    )
    for col in data.columns:
        resolved.add_column(
            key=col.key,
            label=_resolve_value(col.label, audience),
            header=col.header,
            importance=col.importance,
        )

    def collapse(values) -> dict:
        return {key: _resolve_value(value, audience) for key, value in values.items()}

    def copy_children(source: Node, target: Node) -> None:
        for child in source.children:
            new_child = target.add_child(
                _importance=child.importance, **collapse(child.values)
            )
            copy_children(child, new_child)

    for root in data.roots:
        new_root = resolved.add_root(
            _importance=root.importance, **collapse(root.values)
        )
        copy_children(root, new_root)
    return resolved


def _resolve_scalar(data: ScalarContent, audience: Audience) -> ScalarContent:
    return ScalarContent(
        value=_resolve_value(data.value, audience),
        title=_resolve_value(data.title, audience),
        description=_resolve_value(data.description, audience),
    )


def _resolve_content(data: ReportContent, audience: Audience) -> ReportContent:
    if isinstance(data, TableContent):
        return _resolve_table(data, audience)
    if isinstance(data, TreeContent):
        return _resolve_tree(data, audience)
    if isinstance(data, ScalarContent):
        return _resolve_scalar(data, audience)
    # An unknown content kind passes through untouched — the formatter owns
    # the "I can't render this" error, not the resolver.
    return data


def resolve_audience(reports: Reports, audience: Audience) -> Reports:
    """Collapse every ``ByAudience`` cell in ``reports`` for ``audience``.

    Walks each report's content (table rows, tree nodes, or scalar value) and
    replaces each :class:`ByAudience` with the representation matching
    ``audience``, returning a new :class:`Reports`. The parallel ``styles``
    table is audience-invariant and left untouched (same object).

    Args:
        reports: The reports to resolve.
        audience: The audience of the formatter about to render them.

    Returns:
        A new :class:`Reports` with every ``ByAudience`` collapsed. Reports
        carrying no ``ByAudience`` cells are equivalent to the originals.
    """
    return Reports(
        {
            name: replace(report, data=_resolve_content(report.data, audience))
            for name, report in reports.items()
        }
    )


def _cell_is_empty(value: Any) -> bool:
    """Whether a cell counts as empty for column-omission purposes.

    Empty means *absent text*: ``None`` or the empty string. Other falsy
    values — ``0``, ``False``, an empty list — are real data and keep a column
    alive. Whitespace-only strings are content, not emptiness. The value is
    assumed already collapsed for the target audience.
    """
    return value is None or value == ""


def _prune_table(data: TableContent, audience: Audience) -> TableContent:
    droppable = {
        col.key
        for col in data.columns
        if not col.header
        and audience in col.omit_if_empty_for
        and all(_cell_is_empty(row.get(col.key)) for row in data.rows)
    }
    if not droppable:
        return data

    kept = [col for col in data.columns if col.key not in droppable]
    pruned = TableContent(
        title=data.title,
        description=data.description,
        present_transposed=data.present_transposed,
    )
    for col in kept:
        pruned.add_column(
            key=col.key,
            label=col.label,
            header=col.header,
            importance=col.importance,
            omit_if_empty_for=col.omit_if_empty_for,
        )
    for row, importance in zip(data.rows, data.row_importances):
        pruned.add_row(
            _importance=importance,
            **{col.key: row[col.key] for col in kept},
        )
    return pruned


def prune_empty_columns(reports: Reports, audience: Audience) -> Reports:
    """Drop columns that are empty for ``audience`` and opted in to omission.

    A column declared with ``omit_if_empty_for`` containing ``audience`` is
    dropped when every one of its data cells is empty (``None`` or ``""``).
    This lets a provably-empty column vanish for humans (legibility, and not
    spending terminal width on a dead column) while machine formatters keep it
    as part of a stable schema.

    Intended to run *after* :func:`resolve_audience`, so emptiness is evaluated
    on already-collapsed values — a column that is empty for one audience but
    not another (``ByAudience(machine=x, human="")``) is then handled
    per-audience for free. Like ``resolve_audience``, this only takes effect via
    :func:`~asyoulikeit.format_as`; calling a formatter's ``format()`` directly
    bypasses it.

    Scope and floor:

    - Tables only. Tree and scalar content pass through unchanged.
    - Header columns are never dropped, so a table that has one always keeps at
      least its row-label column. Emptiness is judged on data cells alone; a
      column's label never keeps it alive.
    - Emptiness is judged over *all* data rows, independent of the detail-level
      row filtering a formatter applies afterwards. A column with data only in
      ``DETAIL`` rows therefore survives even when those rows are hidden under
      ``--essential`` — the conservative direction (keep rather than drop).

    Args:
        reports: The reports to prune (typically already audience-resolved).
        audience: The audience of the formatter about to render them.

    Returns:
        A new :class:`Reports` with empty opted-in columns dropped, or the same
        object when nothing changed.
    """
    pruned = {}
    changed = False
    for name, report in reports.items():
        data = report.data
        if isinstance(data, TableContent):
            new_data = _prune_table(data, audience)
            if new_data is not data:
                pruned[name] = replace(report, data=new_data)
                changed = True
                continue
        pruned[name] = report
    return Reports(pruned) if changed else reports
