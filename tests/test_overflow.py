"""Tests for per-column overflow policy (issue #18).

Covers the schema field, the cell-budget elision arithmetic behind it, and
the two display paths that honour it — Rich-managed widths for a table,
formatter-managed widths for a tree — plus the guarantee that machine
formats are untouched by any of it.
"""

import json
import re

import pytest
from rich.cells import cell_len

from asyoulikeit import (
    Audience,
    ByAudience,
    Column,
    Overflow,
    Report,
    Reports,
    TableContent,
    TreeContent,
)
from asyoulikeit.audience import prune_empty_columns, resolve_audience
from asyoulikeit.formatter import format_as
from asyoulikeit.ext.formatters.display._elide import ELLIPSIS, elide


def strip_ansi_codes(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


ELIDING = [Overflow.ELIDE_START, Overflow.ELIDE_MIDDLE, Overflow.ELIDE_END]


class TestElide:
    """The cell-budget arithmetic, independent of any table."""

    def test_text_that_fits_is_returned_unchanged(self):
        for policy in ELIDING:
            assert elide("Dircopy267", 10, policy) == "Dircopy267"
            assert elide("Dircopy267", 40, policy) == "Dircopy267"

    def test_wrap_never_elides(self):
        # The wrapping policy is answered so callers needn't special-case it.
        assert elide("Dircopy267", 3, Overflow.WRAP) == "Dircopy267"

    def test_each_policy_keeps_the_end_it_advertises(self):
        assert elide("Dircopy267", 7, Overflow.ELIDE_END) == "Dircop" + ELLIPSIS
        assert elide("Dircopy267", 7, Overflow.ELIDE_START) == ELLIPSIS + "opy267"
        assert elide("Dircopy267", 7, Overflow.ELIDE_MIDDLE) == "Dir" + ELLIPSIS + "267"

    def test_middle_elision_discriminates_where_end_elision_cannot(self):
        # The motivating case: two names sharing a prefix and differing in
        # their tails. End-elision throws away exactly what tells them apart.
        a, b = "Dircopy267", "Dircopy254"
        assert elide(a, 8, Overflow.ELIDE_END) == elide(b, 8, Overflow.ELIDE_END)
        assert elide(a, 8, Overflow.ELIDE_MIDDLE) != elide(b, 8, Overflow.ELIDE_MIDDLE)

    def test_odd_cell_goes_to_the_head(self):
        # A value's opening is marginally more orienting than its close.
        assert elide("Dircopy267", 6, Overflow.ELIDE_MIDDLE) == "Dir" + ELLIPSIS + "67"

    def test_degrades_without_special_casing(self):
        # At two cells there is nothing left for a tail, so middle-elision
        # reads as end-elision; at one, every policy is a bare ellipsis.
        assert elide("Dircopy267", 2, Overflow.ELIDE_MIDDLE) == "D" + ELLIPSIS
        for policy in ELIDING:
            assert elide("Dircopy267", 1, policy) == ELLIPSIS
            assert elide("Dircopy267", 0, policy) == ""

    @pytest.mark.parametrize(
        "text",
        [
            "Dircopy267",
            "├── Copyf254",
            "日本語テキスト",          # every cluster two cells wide
            "a日b本c語d",              # mixed single- and double-width
        ],
    )
    @pytest.mark.parametrize("policy", ELIDING)
    def test_never_exceeds_its_budget_in_cells(self, text, policy):
        # The budget is terminal cells, not characters: a double-width
        # character simply does not go in when one cell is left.
        for width in range(0, cell_len(text) + 3):
            assert cell_len(elide(text, width, policy)) <= width

    def test_double_width_text_is_not_cut_mid_character(self):
        result = elide("日本語テキスト", 5, Overflow.ELIDE_MIDDLE)
        assert result == "日" + ELLIPSIS + "ト"


class TestOverflowSchema:
    """The policy is declared on the schema and survives the pipeline."""

    def test_default_is_wrap(self):
        assert Column(key="k", label="L").overflow == Overflow.WRAP
        table = TableContent().add_column("k", "L")
        assert table.columns[0].overflow == Overflow.WRAP

    def test_declared_on_table_columns(self):
        table = TableContent().add_column(
            "k", "L", overflow=Overflow.ELIDE_MIDDLE
        )
        assert table.columns[0].overflow == Overflow.ELIDE_MIDDLE

    def test_declared_on_tree_columns(self):
        tree = TreeContent().add_column(
            "k", "L", header=True, overflow=Overflow.ELIDE_START
        )
        assert tree.columns[0].overflow == Overflow.ELIDE_START

    def test_survives_audience_resolution_of_a_table(self):
        # Audience collapse rebuilds the schema column by column; a policy
        # dropped there would vanish before any formatter saw it.
        table = TableContent().add_column(
            "k", ByAudience(human="Label", machine="k"),
            overflow=Overflow.ELIDE_MIDDLE,
        )
        table.add_row(k="v")
        resolved = resolve_audience(
            Reports(r=Report(data=table)), Audience.HUMAN
        )
        assert resolved["r"].data.columns[0].overflow == Overflow.ELIDE_MIDDLE

    def test_survives_audience_resolution_of_a_tree(self):
        tree = TreeContent().add_column(
            "k", ByAudience(human="Label", machine="k"),
            header=True, overflow=Overflow.ELIDE_END,
        )
        tree.add_root(k="v")
        resolved = resolve_audience(
            Reports(r=Report(data=tree)), Audience.HUMAN
        )
        assert resolved["r"].data.columns[0].overflow == Overflow.ELIDE_END

    def test_survives_empty_column_pruning(self):
        table = TableContent().add_column(
            "k", "K", overflow=Overflow.ELIDE_MIDDLE
        )
        table.add_column("gone", "Gone", omit_if_empty_for={Audience.HUMAN})
        table.add_row(k="v", gone="")
        pruned = prune_empty_columns(
            Reports(r=Report(data=table)), Audience.HUMAN
        )
        kept = pruned["r"].data.columns
        assert [col.key for col in kept] == ["k"]
        assert kept[0].overflow == Overflow.ELIDE_MIDDLE


def _zip_listing(policy=Overflow.WRAP) -> TableContent:
    """The issue's motivating case: tree art laid into a flat table."""
    table = TableContent(title="M128Welc.zip")
    table.add_column("filename", "Filename", header=True, overflow=policy)
    table.add_column("load", "Load")
    table.add_column("length", "Length")
    for name, load, length in [
        ("UNCRUNCHED", "", ""),
        ("├── Copyf254", "0xFFFFFB3F", 14985),
        ("└── Dircopy267", "0xFFFFFB3F", 7935),
    ]:
        table.add_row(filename=name, load=load, length=length)
    return table


class TestDisplayTableOverflow:
    """On the table path Rich owns the widths, so elision happens at render time."""

    @staticmethod
    def _render(content, columns, monkeypatch):
        monkeypatch.setenv("COLUMNS", str(columns))
        monkeypatch.setenv("NO_COLOR", "1")
        return strip_ansi_codes(
            format_as(Reports(r=Report(data=content)), "display")
        )

    def test_wrapping_splits_an_atomic_value_across_rows(self, monkeypatch):
        # The behaviour being fixed, pinned here so the contrast is explicit:
        # the space in the tree prefix is a legal break opportunity, so the
        # connector and the name land on different lines.
        out = self._render(_zip_listing(), 36, monkeypatch)
        assert "├── Copyf254" not in out
        assert "Copyf254" in out

    @pytest.mark.parametrize("policy", ELIDING)
    def test_eliding_keeps_each_entry_on_one_row(self, monkeypatch, policy):
        out = self._render(_zip_listing(policy), 36, monkeypatch)
        assert "├── Copyf254" in out
        assert "└── Dircopy267" in out

    def test_elision_costs_nothing_when_everything_fits(self, monkeypatch):
        # A policy is a contingency, not a transformation: at a width where
        # nothing needs eliding the output is what wrapping would give.
        wide = 120
        wrapped = self._render(_zip_listing(), wide, monkeypatch)
        elided = self._render(
            _zip_listing(Overflow.ELIDE_MIDDLE), wide, monkeypatch
        )
        assert wrapped == elided

    def test_eliding_column_does_not_starve_its_neighbours(self, monkeypatch):
        # Marking a column no_wrap so Rich shrinks the others first protects
        # it absolutely unless it is also capped: without the ceiling the
        # filename column keeps all 14 cells and the data columns vanish.
        out = self._render(_zip_listing(Overflow.ELIDE_MIDDLE), 24, monkeypatch)
        assert "0x" in out, "data columns squeezed out of existence"

    @pytest.mark.parametrize("columns", [120, 60, 36, 28, 24, 20, 16])
    def test_never_overflows_the_console(self, monkeypatch, columns):
        out = self._render(_zip_listing(Overflow.ELIDE_MIDDLE), columns, monkeypatch)
        widest = max(len(line) for line in out.splitlines())
        assert widest <= columns

    def test_styled_cells_keep_their_style_when_elided(self, monkeypatch):
        # An eliding cell is a custom renderable rather than a Rich Text, so
        # the per-cell style has to be carried into it explicitly.
        from asyoulikeit import STYLE_FOREGROUND_COLOR
        content = TableContent()
        content.add_column("filename", "Filename", header=True)
        content.add_column("load", "Load", overflow=Overflow.ELIDE_MIDDLE)
        content.add_row(filename="Copyf254", load="0xFFFFFB3F")
        styles = TableContent()
        styles.add_column("filename", "Filename", header=True)
        styles.add_column("load", "Load")
        styles.add_row(filename=None, load={STYLE_FOREGROUND_COLOR: "#FF0000"})
        monkeypatch.setenv("COLUMNS", "24")
        monkeypatch.delenv("NO_COLOR", raising=False)
        rendered = format_as(
            Reports(r=Report(data=content, styles=styles)), "display"
        )
        bare = format_as(Reports(r=Report(data=content)), "display")
        assert ELLIPSIS in strip_ansi_codes(rendered), "expected an elided cell"
        # Which escape encodes the colour depends on the terminal's colour
        # depth, which differs between a developer's terminal and CI. What
        # must hold either way: the styled render carries markup the bare one
        # does not, and the glyphs underneath are the same.
        assert rendered != bare, "cell style lost on an elided cell"
        assert strip_ansi_codes(rendered) == strip_ansi_codes(bare)


def _archive_tree(policy=Overflow.WRAP, header_policy=None) -> TreeContent:
    tree = TreeContent(title="Archive")
    tree.add_column(
        "filename", "Filename", header=True,
        overflow=policy if header_policy is None else header_policy,
    )
    tree.add_column("load", "Load", overflow=policy)
    tree.add_column("length", "Length", overflow=policy)
    root = tree.add_root(filename="UNCRUNCHED", load="", length="")
    root.add_child(filename="Copyf254", load="0xFFFFFB3F", length=14985)
    root.add_child(filename="ArchivedFilenameLongEnoughToNeedEliding",
                   load="0xFFFFFB3F", length=7935)
    return tree


class TestDisplayTreeOverflow:
    """On the tree path the formatter owns the widths and elides directly."""

    @staticmethod
    def _render(content, columns, monkeypatch, header=True):
        monkeypatch.setenv("COLUMNS", str(columns))
        monkeypatch.setenv("NO_COLOR", "1")
        return strip_ansi_codes(
            format_as(Reports(r=Report(data=content, header=header)), "display")
        )

    def test_atomic_data_column_elides_instead_of_folding(self, monkeypatch):
        # An address split as 0xFFFFFB / 3F over two lines is harder to read
        # than 0xF…B3F on one, and makes every row in the table taller.
        wrapped = self._render(_archive_tree(), 40, monkeypatch)
        elided = self._render(
            _archive_tree(Overflow.ELIDE_MIDDLE), 40, monkeypatch
        )
        assert len(elided.splitlines()) < len(wrapped.splitlines())
        assert ELLIPSIS in elided

    def test_every_node_occupies_exactly_one_row(self, monkeypatch):
        out = self._render(_archive_tree(Overflow.ELIDE_MIDDLE), 40, monkeypatch)
        connector_rows = [ln for ln in out.splitlines() if "── " in ln]
        assert len(connector_rows) == 2

    def test_header_column_elides_the_name_and_keeps_the_art(self, monkeypatch):
        # The art is structure, not content: eliding a connector would say
        # something false about the shape of the tree.
        out = self._render(
            _archive_tree(header_policy=Overflow.ELIDE_MIDDLE), 40, monkeypatch
        )
        assert "└── " in out
        assert "├── " in out
        assert ELLIPSIS in out

    @pytest.mark.parametrize("columns", [80, 60, 40, 30])
    def test_never_overflows_the_console(self, monkeypatch, columns):
        out = self._render(
            _archive_tree(Overflow.ELIDE_MIDDLE), columns, monkeypatch
        )
        widest = max(len(line) for line in out.splitlines())
        assert widest <= columns

    @pytest.mark.parametrize("columns", [80, 40, 30, 26, 22])
    def test_one_row_per_node_at_every_width(self, monkeypatch, columns):
        # An eliding column undertakes to occupy a single line. That has to
        # hold in a tree deep enough that below about 30 cells the art alone
        # fills the header column, and the connectors have to be elided with
        # the name rather than wrapped away onto rows of their own.
        tree = TreeContent(title="Archive")
        tree.add_column("filename", "Filename", header=True,
                        overflow=Overflow.ELIDE_MIDDLE)
        tree.add_column("load", "Load", overflow=Overflow.ELIDE_MIDDLE)
        node = tree.add_root(filename="ProjectArchive", load="")
        for name in ("Sources", "Interpreters", "BasicTokeniserImplementation"):
            node = node.add_child(filename=name, load="0xFFFFFB3F")
        # Rendered without a header row: Rich draws the light box style on
        # Windows and the heavy one elsewhere, so the column-label row can
        # begin with the same border character as a body row. With no header
        # there is nothing to tell apart.
        out = self._render(tree, columns, monkeypatch, header=False)
        body = [ln for ln in out.splitlines() if ln.startswith("│")]
        assert len(body) == 4, f"{len(body)} rows for 4 nodes at {columns}"


class TestMachineFormattersIgnoreOverflow:
    """Eliding is safe in display precisely because nothing else elides."""

    @pytest.mark.parametrize("format_name", ["tsv", "json"])
    @pytest.mark.parametrize("policy", ELIDING)
    def test_table_output_is_unaffected(self, format_name, policy):
        plain = format_as(Reports(r=Report(data=_zip_listing())), format_name)
        declared = format_as(
            Reports(r=Report(data=_zip_listing(policy))), format_name
        )
        assert plain == declared

    @pytest.mark.parametrize("format_name", ["tsv", "json"])
    def test_tree_output_is_unaffected(self, format_name):
        plain = format_as(Reports(r=Report(data=_archive_tree())), format_name)
        declared = format_as(
            Reports(r=Report(data=_archive_tree(Overflow.ELIDE_MIDDLE))),
            format_name,
        )
        assert plain == declared

    def test_machine_output_carries_the_whole_value(self):
        out = format_as(
            Reports(r=Report(data=_zip_listing(Overflow.ELIDE_MIDDLE))), "json"
        )
        blob = json.dumps(json.loads(out))
        assert "Dircopy267" in blob
        assert ELLIPSIS not in blob
