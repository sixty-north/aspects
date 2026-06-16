"""Tab-separated values formatter."""

from asyoulikeit.audience import Audience
from asyoulikeit.formatter import Formatter
from asyoulikeit.scalar_data import ScalarContent
from asyoulikeit.tabular_data import DetailLevel, Importance, Reports, TableContent
from asyoulikeit.tree_data import Node, TreeContent


def _escape_tsv(value) -> str:
    """Escape a cell value so it cannot break TSV's line/tab structure.

    Backslash-escapes the four structural bytes — the backslash itself
    first, so the encoding is reversible — turning an arbitrary value into
    exactly one tab-free, newline-free field. A reader recovers the original
    bytes by reversing the same four substitutions, the TSV analogue of
    what JSON already does for free. Every other byte (including other C0
    control characters) is left verbatim: it does not affect TSV parsing,
    and TSV is a machine channel, not a terminal.
    """
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


class TsvFormatter(Formatter):
    """Tab-separated values formatter for UNIX-style processing.

    Outputs data as TSV with optional header rows, suitable for
    ``awk``, ``cut``, ``grep`` and friends. Headers are prefixed with
    ``# `` by default so downstream tools can skip the first line as a
    comment.

    Cell values (and column labels) are escaped so that a value
    containing a tab, newline or carriage return cannot invent a column
    or split one logical record across physical lines. The four
    structural bytes are backslash-escaped — ``\\`` → ``\\\\`` (first, so
    the encoding is reversible), then ``\\t`` ``\\r`` ``\\n`` → their
    two-character forms. A reader recovers the exact original bytes by
    reversing those four substitutions. Other bytes pass through
    untouched.

    Multiple reports are separated by blank lines. Within a single
    tree report, every node is flattened into its own row. Column 1
    always carries the node's own header-column value (the leaf), so
    ``awk '{print $1}'`` yields the node name regardless of tree
    depth. Columns 2 onwards carry the full root-to-node path, one
    component per cell, left-packed and padded on the right with
    empty cells so every row has exactly ``max_depth`` path cells.
    The leaf value therefore also appears as the last non-empty path
    cell (intentional duplication — preserves the human-readable
    full-path reading). Non-header data columns follow the path
    cells. Path columns are labelled ``Path1``, ``Path2``, … in
    1-based style so that ``PathK`` is exactly "the node at depth K"
    (counting the root as depth 1); the largest ``PathN`` in the
    header row reveals the tree's maximum visible depth.
    """

    audience = Audience.MACHINE

    def format(self, reports: Reports) -> str:
        """Format reports as TSV with optional header rows.

        Args:
            reports: A Reports object containing one or more named reports.

        Returns:
            TSV string with reports separated by blank lines.
        """
        sections = []
        for _report_name, report in reports.items():
            detail_level = report.detail_level
            header = self._resolve_header(report)
            # TSV defaults to essential-only for machine parseability
            if detail_level == DetailLevel.AUTO:
                detail_level = DetailLevel.ESSENTIAL

            if isinstance(report.data, TableContent):
                sections.append(
                    self._format_table(report.data, detail_level, header)
                )
            elif isinstance(report.data, TreeContent):
                sections.append(
                    self._format_tree(report.data, detail_level, header)
                )
            elif isinstance(report.data, ScalarContent):
                sections.append(self._format_scalar(report.data, header))
            else:
                raise TypeError(
                    f"TsvFormatter does not know how to render "
                    f"{type(report.data).__name__} content "
                    f"(kind={report.data.kind()!r})"
                )

        return "\n\n".join(sections)

    # -- header resolution --------------------------------------------------

    def _resolve_header(self, report) -> bool:
        """Resolve the effective header flag for ``report``.

        Returns ``report.header`` if the author set it explicitly to
        ``True`` or ``False``; otherwise falls back to this formatter's
        per-content default.
        """
        if report.header is not None:
            return report.header
        return self._default_header(report.data)

    def _default_header(self, content) -> bool:
        """Per-content default for TSV when neither CLI nor Report author asked.

        For tables and trees the default is ``True`` — the ``# Name\\t…``
        header line and the column labels are what make the TSV output
        parseable by downstream tools. For :class:`ScalarContent`,
        though, the overwhelmingly common case is piping a single value
        to another tool (``disc title image | pbcopy``), which wants
        the raw answer on its own; the ``# Title`` comment line is
        chrome, not information. Scalars therefore default to ``False``
        — explicit ``--header`` or ``header=True`` on the Report opts
        the label back in.
        """
        if isinstance(content, ScalarContent):
            return False
        return True

    # -- table --------------------------------------------------------------

    def _format_table(
        self, data: TableContent, detail_level: DetailLevel, header: bool
    ) -> str:
        if data.present_transposed:
            data = data.transpose()

        columns = (
            data.columns if detail_level == DetailLevel.DETAILED
            else data.essential_columns
        )
        rows = data.rows_for_detail_level(detail_level)

        lines = []
        if header:
            labels = [_escape_tsv(col.label) for col in columns]
            if labels:
                labels[0] = f"# {labels[0]}"
            lines.append("\t".join(labels))
        for row in rows:
            lines.append("\t".join(_escape_tsv(row[col.key]) for col in columns))
        return "\n".join(lines)

    # -- tree ---------------------------------------------------------------

    def _format_tree(
        self, data: TreeContent, detail_level: DetailLevel, header: bool
    ) -> str:
        columns = (
            data.columns if detail_level == DetailLevel.DETAILED
            else data.essential_columns
        )
        header_col = data.header_column  # always present — enforced at add_root
        non_header_cols = [col for col in columns if not col.header]

        # Gather every visible node together with its ancestor chain —
        # a tuple of header-column values from the root down to (but
        # not including) the node itself. Roots yield with an empty
        # ancestors tuple. A DETAIL node prunes its entire subtree, so
        # the max-depth computation sees only the surviving tree.
        visible = list(self._walk_with_ancestors(data, detail_level))
        # 1-based depth of the deepest visible node: root is depth 1,
        # its children depth 2, etc. An empty tree has max_depth 0.
        max_depth = max((len(anc) + 1 for anc, _ in visible), default=0)

        lines = []
        if header:
            path_labels = [f"Path{k}" for k in range(1, max_depth + 1)]
            data_labels = [_escape_tsv(col.label) for col in non_header_cols]
            all_labels = [_escape_tsv(header_col.label)] + path_labels + data_labels
            all_labels[0] = f"# {all_labels[0]}"
            lines.append("\t".join(all_labels))

        for ancestors, node in visible:
            leaf_value = _escape_tsv(node.values[header_col.key])
            # Full root-to-node path, left-packed, padded on the right.
            full_path = [_escape_tsv(a) for a in ancestors] + [leaf_value]
            path_cells = full_path + [""] * (max_depth - len(full_path))
            data_cells = [_escape_tsv(node.values[col.key]) for col in non_header_cols]
            lines.append("\t".join([leaf_value] + path_cells + data_cells))

        return "\n".join(lines)

    # -- scalar -------------------------------------------------------------

    def _format_scalar(self, data: ScalarContent, header: bool) -> str:
        """Format a single-value content as TSV.

        ``header`` arrives already-resolved via ``_resolve_header`` —
        for scalars, the default is ``False`` (just the value), but
        an explicit ``--header`` or ``Report(header=True)`` flips to
        the labelled form. ``description`` is never emitted in TSV
        regardless of the flag — it's pipe-noise.
        """
        if header and data.title:
            return f"# {_escape_tsv(data.title)}\n{_escape_tsv(data.value)}"
        return _escape_tsv(data.value)

    # -- shared helpers -----------------------------------------------------

    @classmethod
    def _walk_with_ancestors(cls, data: TreeContent, detail_level: DetailLevel):
        """Yield (ancestor_tuple, node) for every visible node in pre-order.

        ``ancestor_tuple`` is a tuple of header-column values from the
        root down to (but not including) the yielded node. A root
        yields with an empty tuple.
        """
        header_key = data.header_column.key
        for root in data.roots:
            yield from cls._walk_node_with_ancestors(
                root, (), header_key, detail_level
            )

    @classmethod
    def _walk_node_with_ancestors(
        cls,
        node: Node,
        ancestors: tuple,
        header_key: str,
        detail_level: DetailLevel,
    ):
        if not cls._node_visible(node, detail_level):
            return
        yield ancestors, node
        child_ancestors = ancestors + (node.values[header_key],)
        for child in node.children:
            yield from cls._walk_node_with_ancestors(
                child, child_ancestors, header_key, detail_level
            )

    @staticmethod
    def _node_visible(node: Node, detail_level: DetailLevel) -> bool:
        if detail_level == DetailLevel.ESSENTIAL and node.importance == Importance.DETAIL:
            return False
        return True
