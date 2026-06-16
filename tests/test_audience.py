"""Tests for audience-aware values (issue #14).

Two orthogonal additions:

1. Formatters declare an :class:`Audience` (human / machine).
2. A cell can carry both representations via :class:`ByAudience`, and the
   dispatcher (:func:`format_as`) collapses each ``ByAudience`` to the
   representation matching the chosen formatter's audience *before* the
   formatter ever sees it.
"""

import json
import re

import pytest

from asyoulikeit import (
    Audience,
    ByAudience,
    Importance,
    Report,
    Reports,
    ScalarContent,
    TableContent,
    TreeContent,
    create_formatter,
    format_as,
    resolve_audience,
)


def strip_ansi_codes(text: str) -> str:
    return re.compile(r"\x1b\[[0-9;]*m").sub("", text)


# -- 1. Formatters declare an audience --------------------------------------


class TestFormatterAudience:
    def test_audience_enum_has_two_members(self):
        assert {a for a in Audience} == {Audience.HUMAN, Audience.MACHINE}

    def test_display_is_human(self):
        assert create_formatter("display").audience is Audience.HUMAN

    def test_tsv_is_machine(self):
        assert create_formatter("tsv").audience is Audience.MACHINE

    def test_json_is_machine(self):
        assert create_formatter("json").audience is Audience.MACHINE

    def test_base_default_is_machine(self):
        """A formatter that never declares an audience defaults to MACHINE.

        Conservative: an undeclared third-party formatter gets the raw /
        canonical value, never a lossy human rendering.
        """
        from asyoulikeit.formatter import Formatter

        assert Formatter.audience is Audience.MACHINE


# -- 2. ByAudience wrapper ---------------------------------------------------


class TestByAudience:
    def test_is_frozen(self):
        value = ByAudience(machine=1048576, human="1.0 MiB")
        with pytest.raises(Exception):
            value.machine = 0  # type: ignore[misc]

    def test_carries_both_representations(self):
        value = ByAudience(machine=1048576, human="1.0 MiB")
        assert value.machine == 1048576
        assert value.human == "1.0 MiB"


# -- 3. resolve_audience on each content shape ------------------------------


class TestResolveTable:
    def _table(self):
        data = (
            TableContent(title="Users", description="Quota report")
            .add_column("user", "User", header=True)
            .add_column("quota", "Quota")
            .add_column("note", "Note", importance=Importance.DETAIL)
        )
        data.add_row(
            user="alice",
            quota=ByAudience(machine=1048576, human="1.0 MiB"),
            note="plain",
        )
        data.add_row(
            user="bob",
            quota=ByAudience(machine=2097152, human="2.0 MiB"),
            note="detail-row",
            _importance=Importance.DETAIL,
        )
        return data

    def test_machine_collapse(self):
        resolved = resolve_audience(
            Reports(r=Report(data=self._table())), Audience.MACHINE
        )
        rows = resolved["r"].data.rows
        assert rows[0]["quota"] == 1048576
        assert rows[1]["quota"] == 2097152

    def test_human_collapse(self):
        resolved = resolve_audience(
            Reports(r=Report(data=self._table())), Audience.HUMAN
        )
        rows = resolved["r"].data.rows
        assert rows[0]["quota"] == "1.0 MiB"
        assert rows[1]["quota"] == "2.0 MiB"

    def test_plain_cells_unchanged(self):
        resolved = resolve_audience(
            Reports(r=Report(data=self._table())), Audience.MACHINE
        )
        rows = resolved["r"].data.rows
        assert rows[0]["user"] == "alice"
        assert rows[0]["note"] == "plain"

    def test_schema_and_importances_preserved(self):
        resolved = resolve_audience(
            Reports(r=Report(data=self._table())), Audience.MACHINE
        )["r"].data

        assert [c.key for c in resolved.columns] == ["user", "quota", "note"]
        assert [c.label for c in resolved.columns] == ["User", "Quota", "Note"]
        assert resolved.columns[0].header is True
        assert resolved.columns[2].importance is Importance.DETAIL
        assert resolved.title == "Users"
        assert resolved.description == "Quota report"
        assert resolved.row_importances == (
            Importance.ESSENTIAL,
            Importance.DETAIL,
        )

    def test_present_transposed_preserved(self):
        data = (
            TableContent(present_transposed=True)
            .add_column("k", "K", header=True)
            .add_column("v", "V")
        )
        data.add_row(k="a", v=ByAudience(machine=1, human="one"))
        resolved = resolve_audience(
            Reports(r=Report(data=data)), Audience.HUMAN
        )["r"].data
        assert resolved.present_transposed is True
        assert resolved.rows[0]["v"] == "one"


class TestResolveTree:
    def _tree(self):
        tree = (
            TreeContent(title="/usr")
            .add_column("name", "Name", header=True)
            .add_column("size", "Size")
        )
        root = tree.add_root(
            name="usr", size=ByAudience(machine=0, human="0 B")
        )
        child = root.add_child(
            name="bin", size=ByAudience(machine=4096, human="4.0 KiB")
        )
        child.add_child(
            name="ls",
            size=ByAudience(machine=150296, human="146.8 KiB"),
            _importance=Importance.DETAIL,
        )
        return tree

    def test_machine_collapse_recurses(self):
        resolved = resolve_audience(
            Reports(r=Report(data=self._tree())), Audience.MACHINE
        )["r"].data
        root = resolved.roots[0]
        assert root.values["size"] == 0
        bin_node = root.children[0]
        assert bin_node.values["size"] == 4096
        assert bin_node.children[0].values["size"] == 150296

    def test_human_collapse_recurses(self):
        resolved = resolve_audience(
            Reports(r=Report(data=self._tree())), Audience.HUMAN
        )["r"].data
        root = resolved.roots[0]
        assert root.values["size"] == "0 B"
        assert root.children[0].values["size"] == "4.0 KiB"

    def test_node_importance_and_header_preserved(self):
        resolved = resolve_audience(
            Reports(r=Report(data=self._tree())), Audience.MACHINE
        )["r"].data
        leaf = resolved.roots[0].children[0].children[0]
        assert leaf.importance is Importance.DETAIL
        assert resolved.header_column.key == "name"
        assert resolved.title == "/usr"


class TestResolveScalar:
    def test_machine_collapse(self):
        data = ScalarContent(
            value=ByAudience(machine=1048576, human="1.0 MiB"),
            title="Quota",
        )
        resolved = resolve_audience(
            Reports(r=Report(data=data)), Audience.MACHINE
        )["r"].data
        assert resolved.value == 1048576
        assert resolved.title == "Quota"

    def test_human_collapse(self):
        data = ScalarContent(value=ByAudience(machine=1048576, human="1.0 MiB"))
        resolved = resolve_audience(
            Reports(r=Report(data=data)), Audience.HUMAN
        )["r"].data
        assert resolved.value == "1.0 MiB"

    def test_plain_scalar_passes_through(self):
        data = ScalarContent(value="hello")
        resolved = resolve_audience(
            Reports(r=Report(data=data)), Audience.MACHINE
        )["r"].data
        assert resolved.value == "hello"


class TestResolveMetadata:
    """ByAudience is honoured in titles, descriptions and column labels too,
    not just cell values (issue #16)."""

    def test_table_title_description_and_label_collapse(self):
        data = TableContent(
            title=ByAudience(machine="M-title", human="H-title"),
            description=ByAudience(machine="M-desc", human="H-desc"),
        )
        data.add_column(
            "name", ByAudience(machine="M-Name", human="H-Name"), header=True
        )
        data.add_row(name="x")

        machine = resolve_audience(
            Reports(r=Report(data=data)), Audience.MACHINE
        )["r"].data
        human = resolve_audience(
            Reports(r=Report(data=data)), Audience.HUMAN
        )["r"].data

        assert (machine.title, machine.description) == ("M-title", "M-desc")
        assert machine.columns[0].label == "M-Name"
        assert (human.title, human.description) == ("H-title", "H-desc")
        assert human.columns[0].label == "H-Name"

    def test_tree_title_description_and_label_collapse(self):
        data = TreeContent(
            title=ByAudience(machine="M-title", human="H-title"),
            description=ByAudience(machine="M-desc", human="H-desc"),
        )
        data.add_column(
            "name", ByAudience(machine="M-Name", human="H-Name"), header=True
        )
        data.add_root(name="root")

        machine = resolve_audience(
            Reports(r=Report(data=data)), Audience.MACHINE
        )["r"].data
        human = resolve_audience(
            Reports(r=Report(data=data)), Audience.HUMAN
        )["r"].data

        assert (machine.title, machine.description) == ("M-title", "M-desc")
        assert machine.columns[0].label == "M-Name"
        assert (human.title, human.description) == ("H-title", "H-desc")
        assert human.columns[0].label == "H-Name"

    def test_scalar_title_and_description_collapse(self):
        data = ScalarContent(
            value="v",
            title=ByAudience(machine="M-title", human="H-title"),
            description=ByAudience(machine="M-desc", human="H-desc"),
        )
        machine = resolve_audience(
            Reports(r=Report(data=data)), Audience.MACHINE
        )["r"].data
        human = resolve_audience(
            Reports(r=Report(data=data)), Audience.HUMAN
        )["r"].data

        assert (machine.title, machine.description) == ("M-title", "M-desc")
        assert (human.title, human.description) == ("H-title", "H-desc")

    def test_plain_metadata_strings_unchanged(self):
        """Regression: plain-string metadata passes through byte-for-byte."""
        data = TableContent(title="Users", description="A report")
        data.add_column("name", "Name", header=True)
        data.add_row(name="x")

        resolved = resolve_audience(
            Reports(r=Report(data=data)), Audience.HUMAN
        )["r"].data
        assert resolved.title == "Users"
        assert resolved.description == "A report"
        assert resolved.columns[0].label == "Name"


class TestFormatAsResolvesMetadata:
    """End-to-end: a ByAudience title renders, rather than crashing or leaking
    the wrapper's repr."""

    def _reports(self):
        data = TableContent(
            title=ByAudience(machine="M-title", human="H-title")
        )
        data.add_column("name", "Name", header=True)
        data.add_row(name="HELLO")
        return Reports(d=Report(data=data))

    def test_display_renders_human_title(self):
        out = strip_ansi_codes(format_as(self._reports(), "display"))
        assert "H-title" in out
        assert "M-title" not in out
        assert "ByAudience" not in out

    def test_json_renders_machine_title(self):
        parsed = json.loads(format_as(self._reports(), "json"))
        assert parsed["reports"]["d"]["metadata"]["title"] == "M-title"

    def test_tsv_does_not_leak_the_wrapper_repr(self):
        # The pre-fix bug: TSV silently emitted ``ByAudience(machine=...)``
        # for a column label (the table *title* isn't rendered by TSV, so the
        # label is the real silent-corruption vector here).
        data = TableContent()
        data.add_column(
            "name", ByAudience(machine="M-Name", human="H-Name"), header=True
        )
        data.add_row(name="HELLO")
        out = format_as(Reports(d=Report(data=data)), "tsv")
        assert "ByAudience" not in out
        assert "# M-Name" in out


class TestResolveLeavesStylesUntouched:
    def test_styles_object_identity_preserved(self):
        data = (
            TableContent()
            .add_column("user", "User", header=True)
            .add_column("quota", "Quota")
        )
        data.add_row(user="alice", quota=ByAudience(machine=1, human="one"))
        styles = (
            TableContent()
            .add_column("user", "User", header=True)
            .add_column("quota", "Quota")
        )
        styles.add_row(user={}, quota={"bold": True})

        resolved = resolve_audience(
            Reports(r=Report(data=data, styles=styles)), Audience.HUMAN
        )["r"]
        # Styles are audience-invariant: same object, not rebuilt.
        assert resolved.styles is styles


# -- 4. End-to-end through format_as ----------------------------------------


class TestFormatAsResolvesAudience:
    """The headline behaviour: one cell, three correct renderings."""

    def _reports(self):
        data = (
            TableContent()
            .add_column("user", "User", header=True)
            .add_column("quota", "Quota")
        )
        data.add_row(
            user="alice",
            quota=ByAudience(machine=1048576, human="1.0 MiB"),
        )
        return Reports(users=Report(data=data))

    def test_json_emits_a_number_not_a_string(self):
        parsed = json.loads(format_as(self._reports(), "json"))
        quota = parsed["reports"]["users"]["rows"][0]["quota"]
        assert quota == 1048576
        assert isinstance(quota, int)

    def test_tsv_emits_the_machine_value(self):
        out = format_as(self._reports(), "tsv")
        assert "1048576" in out
        assert "1.0 MiB" not in out

    def test_display_emits_the_human_value(self):
        out = strip_ansi_codes(format_as(self._reports(), "display"))
        assert "1.0 MiB" in out
        assert "1048576" not in out
