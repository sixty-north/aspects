"""Human-oriented display formatter.

Where ``json`` is structured output for machines and ``tsv`` is tabular output
for machines, ``display`` is presentation for humans: borders, colors, bold
and italic typography. Both :class:`~asyoulikeit.TableContent` and
:class:`~asyoulikeit.TreeContent` are rendered through Rich; trees get
ASCII-art connectors drawn into the header column of a Rich Table so the
hierarchical shape is visible while other columns still line up as a table.
"""

from io import StringIO
from typing import Optional

from rich.cells import cell_len
from rich.console import Console
from rich.style import Style
from rich.table import Table
from rich.text import Text

from asyoulikeit.audience import Audience
from asyoulikeit.formatter import Formatter
from asyoulikeit.scalar_data import ScalarContent
from asyoulikeit.tabular_data import (
    STYLE_BACKGROUND_COLOR,
    STYLE_BOLD,
    STYLE_FOREGROUND_COLOR,
    STYLE_ITALIC,
    Column,
    DetailLevel,
    Importance,
    Reports,
    TableContent,
)
from asyoulikeit.tree_data import Node, TreeContent


# C0 control bytes (U+0000–U+001F) and DEL (U+007F) are replaced with a
# space before a value is handed to Rich — except TAB and LF, which are
# legitimate in-cell layout and left intact. Everything else in that range
# can drive the cursor (CR, backspace), ring the bell, or smuggle an escape
# sequence into the terminal and corrupt the rendered table. This is the
# minimum needed to stop arbitrary content mangling the output; how a
# *visible* rendering of control characters should look (escape sequences,
# Unicode control pictures, …) is the client's decision, not this layer's.
_DISPLAY_CONTROL_TO_SPACE = {
    codepoint: " "
    for codepoint in (*range(0x20), 0x7F)
    if codepoint not in (0x09, 0x0A)
}


def _sanitize_display(value) -> str:
    """Neutralise corrupting control bytes in a value bound for the terminal."""
    return str(value).translate(_DISPLAY_CONTROL_TO_SPACE)


class DisplayFormatter(Formatter):
    """Human-oriented presentation formatter.

    Renders a :class:`~asyoulikeit.TableContent` as a Rich table with
    borders, titles, and optional per-cell styling, and a
    :class:`~asyoulikeit.TreeContent` as the same Rich table with
    ASCII-art tree connectors (``├──``, ``└──``, ``│``) laid into the
    header-column cell of each node.

    Multiple reports are separated by blank lines.
    """

    audience = Audience.HUMAN

    def format(self, reports: Reports) -> str:
        """Format reports as Rich tables, separated by blank lines."""
        sections = []
        # When only one report is being rendered, certain chrome
        # (bordered box around a single-column tree) stops earning its
        # keep and is dropped. With multiple reports the chrome is what
        # visually separates them, so it's kept.
        solo = len(reports) == 1
        for _report_name, report in reports.items():
            detail_level = report.detail_level
            header = self._resolve_header(report)
            # Display defaults to showing all columns.
            if detail_level == DetailLevel.AUTO:
                detail_level = DetailLevel.DETAILED

            if isinstance(report.data, TableContent):
                sections.append(
                    self._format_table(
                        report.data, report.styles, detail_level, header
                    )
                )
            elif isinstance(report.data, TreeContent):
                sections.append(
                    self._format_tree(
                        report.data, detail_level, header, solo=solo
                    )
                )
            elif isinstance(report.data, ScalarContent):
                sections.append(self._format_scalar(report.data, header))
            else:
                raise TypeError(
                    f"DisplayFormatter does not know how to render "
                    f"{type(report.data).__name__} content "
                    f"(kind={report.data.kind()!r})"
                )

        return "\n\n".join(sections)

    # -- header resolution --------------------------------------------------

    def _resolve_header(self, report) -> bool:
        """Resolve the effective header flag for ``report``.

        Returns ``report.header`` if the author set it explicitly to
        ``True`` or ``False``; otherwise falls back to this formatter's
        per-content default. The CLI ``--header`` / ``--no-header`` has
        already been applied upstream (by ``@report_output``) by the
        time we see the report, so we only need to handle the two-tier
        "explicit-on-report or formatter-default" case here.
        """
        if report.header is not None:
            return report.header
        return self._default_header(report.data)

    def _default_header(self, content) -> bool:
        """Per-content default when neither CLI nor Report author asked.

        Display chooses ``True`` for every content type: humans
        generally want titles and column labels visible. Subclasses or
        new content kinds can specialise here.
        """
        return True

    # -- table --------------------------------------------------------------

    def _format_table(
        self,
        data: TableContent,
        styles: Optional[TableContent],
        detail_level: DetailLevel,
        header: bool,
    ) -> str:
        if data.present_transposed:
            data = data.transpose()
            if styles:
                styles = styles.transpose()

        columns = (
            data.columns if detail_level == DetailLevel.DETAILED
            else data.essential_columns
        )
        rows = data.rows_for_detail_level(detail_level)

        table = Table(
            title=data.title if header else None,
            caption=data.description if header else None,
            show_header=header,
        )
        for col in columns:
            if col.header:
                table.add_column(col.label, style="bold")
            else:
                table.add_column(col.label)

        for row in rows:
            if styles:
                original_idx = data.rows.index(row)
                style_row = styles.rows[original_idx]
                rich_cells = []
                for col in columns:
                    cell_value = _sanitize_display(row[col.key])
                    cell_style_dict = style_row.get(col.key)
                    if cell_style_dict and isinstance(cell_style_dict, dict):
                        rich_cells.append(
                            Text(cell_value, style=self._build_rich_style(cell_style_dict))
                        )
                    else:
                        rich_cells.append(cell_value)
                table.add_row(*rich_cells)
            else:
                table.add_row(*[_sanitize_display(row[col.key]) for col in columns])

        return self._render_to_string(table)

    # -- tree ---------------------------------------------------------------

    def _format_tree(
        self,
        data: TreeContent,
        detail_level: DetailLevel,
        header: bool,
        solo: bool = False,
    ) -> str:
        columns = (
            data.columns if detail_level == DetailLevel.DETAILED
            else data.essential_columns
        )
        header_col: Column = data.header_column  # guaranteed by TreeContent

        # Single-column tree with no sibling reports to disambiguate
        # from? The bordered table around the tree adds visual noise
        # without adding information — the ASCII-art connectors
        # already convey hierarchy. Drop the chrome.
        if solo and len(columns) == 1:
            return self._format_tree_bare(data, detail_level, header, header_col)

        non_header_cols = [c for c in columns if not c.header]

        # Walk the forest and emit (ascii_art, continuation_prefix, node)
        # triples. ``continuation_prefix`` is the spine to repeat in the
        # Name column on wrapped continuation rows: ``│`` at every
        # ancestor depth that still has following siblings, blank where
        # the branch has ended.
        rendered: list[tuple[str, str, Node]] = []
        for root in data.roots:
            self._walk_subtree(
                root,
                prefix="",
                is_root=True,
                is_last=True,
                detail_level=detail_level,
                out=rendered,
            )

        console = Console(file=StringIO(), force_terminal=True)
        table = Table(
            title=data.title if header else None,
            caption=data.description if header else None,
            show_header=header,
        )

        # Natural (unwrapped) content widths — what Rich would size each
        # column to if nothing needed wrapping. The header column carries
        # the tree art, so its content is ``art + name``.
        name_w = max(
            [cell_len(art + _sanitize_display(node.values[header_col.key]))
             for art, _c, node in rendered]
            + ([cell_len(header_col.label)] if header else [])
            + [1]
        )
        data_naturals = [
            max(
                [cell_len(_sanitize_display(node.values[col.key]))
                 for _a, _c, node in rendered]
                + ([cell_len(col.label)] if header else [])
                + [1]
            )
            for col in non_header_cols
        ]
        # Box overhead for N columns with the default box + (0, 1)
        # padding: N+1 vertical borders plus 2 padding columns each.
        overhead = 3 * len(columns) + 1
        natural_total = name_w + sum(data_naturals) + overhead

        if natural_total <= console.width:
            # Nothing wraps: keep Rich's natural, content-sized layout —
            # byte-identical to the pre-#13 rendering.
            for col in columns:
                table.add_column(col.label, style="bold" if col.header else None)
            for art, _cont, node in rendered:
                header_cell = art + _sanitize_display(node.values[header_col.key])
                other_cells = [
                    _sanitize_display(node.values[col.key])
                    for col in non_header_cols
                ]
                table.add_row(header_cell, *other_cells)
        else:
            # At least one cell must wrap. Pin every column to an explicit
            # width and emit one Rich row per *visual* line, so the Name
            # column can carry the tree's vertical spine down the wrapped
            # continuation rows (issue #13). Pinning the widths also keeps
            # the box square — Rich's auto-sizer otherwise drew a bottom
            # border wider than the body once a column wrapped.
            data_widths = self._distribute_widths(
                data_naturals, console.width - overhead - name_w
            )
            width_of = {header_col.key: name_w}
            for col, w in zip(non_header_cols, data_widths):
                width_of[col.key] = w
            for col in columns:
                table.add_column(
                    col.label,
                    style="bold" if col.header else None,
                    width=width_of[col.key],
                )
            for art, cont, node in rendered:
                name_text = art + _sanitize_display(node.values[header_col.key])
                name_lines = self._wrap(console, name_text, name_w)
                data_lines = [
                    self._wrap(
                        console,
                        _sanitize_display(node.values[col.key]),
                        width_of[col.key],
                    )
                    for col in non_header_cols
                ]
                height = max([len(name_lines)] + [len(dl) for dl in data_lines])
                # Continuation rows repeat the spine in the Name column;
                # data columns pad with blanks.
                name_col = name_lines + [cont] * (height - len(name_lines))
                data_cols = [dl + [""] * (height - len(dl)) for dl in data_lines]
                for i in range(height):
                    table.add_row(name_col[i], *[dc[i] for dc in data_cols])

        console.print(table)
        return console.file.getvalue()

    def _format_tree_bare(
        self,
        data: TreeContent,
        detail_level: DetailLevel,
        header: bool,
        header_col: Column,
    ) -> str:
        """Emit a single-column tree as bare ASCII art, without table chrome.

        Called only when there's exactly one report and the tree has
        exactly one column, so the bordered table wouldn't add any
        information. Title and description are included as plain lines
        above and below the tree when ``header`` is true.
        """
        rendered: list[tuple[str, str, Node]] = []
        for root in data.roots:
            self._walk_subtree(
                root,
                prefix="",
                is_root=True,
                is_last=True,
                detail_level=detail_level,
                out=rendered,
            )

        lines = []
        if header and data.title:
            lines.append(data.title)
            lines.append("")
        for art, _cont, node in rendered:
            lines.append(art + _sanitize_display(node.values[header_col.key]))
        if header and data.description:
            lines.append("")
            lines.append(data.description)
        # Match the trailing newline that Rich's Console.print adds on
        # the chrome'd path, so callers that concatenate sections with
        # "\n\n" don't see a shape discontinuity between modes.
        return "\n".join(lines) + "\n"

    def _walk_subtree(
        self,
        node: Node,
        prefix: str,
        is_root: bool,
        is_last: bool,
        detail_level: DetailLevel,
        out: list,
    ) -> None:
        """Populate ``out`` with (ascii_art, continuation_prefix, node) triples.

        Emitted in pre-order. ``continuation_prefix`` is what the Name
        column should show on this node's wrapped continuation rows: the
        same spine its children inherit (``│`` where a sibling still
        follows, blank under a ``└──``). DETAIL nodes (and their
        descendants) are pruned when ``detail_level == ESSENTIAL``.
        """
        if not self._node_visible(node, detail_level):
            return

        if is_root:
            art = ""
            child_prefix = ""
        else:
            connector = "└── " if is_last else "├── "
            art = prefix + connector
            child_prefix = prefix + ("    " if is_last else "│   ")

        out.append((art, child_prefix, node))

        visible_children = [
            c for c in node.children if self._node_visible(c, detail_level)
        ]
        for i, child in enumerate(visible_children):
            last = i == len(visible_children) - 1
            self._walk_subtree(
                child,
                child_prefix,
                is_root=False,
                is_last=last,
                detail_level=detail_level,
                out=out,
            )

    @staticmethod
    def _node_visible(node: Node, detail_level: DetailLevel) -> bool:
        if detail_level == DetailLevel.ESSENTIAL and node.importance == Importance.DETAIL:
            return False
        return True

    @staticmethod
    def _wrap(console: Console, text: str, width: int) -> list[str]:
        """Word-wrap ``text`` to ``width`` using Rich's own wrapper.

        Returns the plain text of each wrapped line (never empty — an
        empty cell yields a single empty line) so it matches exactly how
        Rich would lay the same text out inside a fixed-width table cell.
        """
        lines = [line.plain for line in Text(text).wrap(console, width)]
        return lines or [""]

    @staticmethod
    def _distribute_widths(naturals: list[int], available: int) -> list[int]:
        """Split ``available`` columns across data columns, mirroring Rich.

        Allocates proportionally to each column's natural content width,
        never below 1, summing to exactly ``available``. The common
        single-data-column case simply takes the whole budget. Used only
        on the wrapping path, where the columns must fit a fixed width.
        """
        if not naturals:
            return []
        if available < len(naturals):
            return [1] * len(naturals)
        total = sum(naturals) or 1
        exact = [n / total * available for n in naturals]
        widths = [max(1, int(x)) for x in exact]
        remainder = available - sum(widths)
        # Hand leftover columns to the largest fractional parts first.
        order = sorted(
            range(len(naturals)),
            key=lambda i: exact[i] - int(exact[i]),
            reverse=True,
        )
        j = 0
        while remainder > 0:
            widths[order[j % len(order)]] += 1
            remainder -= 1
            j += 1
        return widths

    # -- scalar -------------------------------------------------------------

    def _format_scalar(self, data: ScalarContent, header: bool) -> str:
        """Format a single-value content for a terminal.

        Rules:

        - If ``header`` is True and ``title`` is set: one line
          ``Title: value``.
        - Otherwise: ``value`` on its own line.
        - If ``header`` is True and ``description`` is set: on the
          following line, rendered dim/italic via Rich.
        """
        value_str = _sanitize_display(data.value)
        if header and data.title:
            first_line = f"{data.title}: {value_str}"
        else:
            first_line = value_str

        if header and data.description:
            # Use Rich to render the description dimly + italic, then
            # capture as a string so the section composes into the
            # wider output like every other section.
            from rich.text import Text
            desc = Text(data.description, style="dim italic")
            buffer = StringIO()
            console = Console(file=buffer, force_terminal=True)
            console.print(desc)
            return first_line + "\n" + buffer.getvalue()
        return first_line + "\n"

    # -- shared Rich helpers ------------------------------------------------

    def _build_rich_style(self, style_dict: dict) -> Style:
        return Style(
            color=style_dict.get(STYLE_FOREGROUND_COLOR),
            bgcolor=style_dict.get(STYLE_BACKGROUND_COLOR),
            bold=style_dict.get(STYLE_BOLD, False),
            italic=style_dict.get(STYLE_ITALIC, False),
        )

    def _render_to_string(self, table: Table) -> str:
        buffer = StringIO()
        console = Console(file=buffer, force_terminal=True)
        console.print(table)
        return buffer.getvalue()
