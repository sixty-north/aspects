"""Hierarchical report content with a uniform column schema across nodes.

Where :class:`~asyoulikeit.TableContent` carries a flat table of rows
against a column schema, :class:`TreeContent` carries a hierarchical
forest: one or more root nodes, each optionally with children, where
every node holds values keyed by the same column schema. Think file
trees, syntax trees, project organisation hierarchies — anywhere the
shape is hierarchical but the per-node data is homogeneous.

Construction mirrors :class:`~asyoulikeit.TableContent`'s builder
pattern; :meth:`TreeContent.add_root` starts a top-level node and
:meth:`Node.add_child` grows the tree downward. Both return the
newly-added node so the caller can retain a handle for adding its
own children or siblings.

Example::

    tree = (
        TreeContent(title="/usr")
        .add_column("name", "Name", header=True)
        .add_column("size", "Size")
    )
    root = tree.add_root(name="/usr", size=0)
    bin_dir = root.add_child(name="bin", size=4096)
    bin_dir.add_child(name="ls", size=150_296)
    bin_dir.add_child(name="cat", size=52_024)

``TreeContent`` supports a forest rather than strictly a tree: call
:meth:`~TreeContent.add_root` more than once to add multiple top-level
nodes.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Optional

from asyoulikeit.content import ReportContent
from asyoulikeit.tabular_data import AudienceStr, Column, Importance


class Node:
    """A single node in a :class:`TreeContent`.

    A node owns its values (a dict keyed by the tree's column schema),
    its importance (ESSENTIAL / DETAIL), and a list of child
    :class:`Node` objects in insertion order.
    """

    def __init__(
        self,
        owner: "TreeContent",
        values: dict[str, Any],
        importance: Importance,
    ):
        self._owner = owner
        self._values: dict[str, Any] = values
        self._importance = importance
        self._children: list[Node] = []

    def add_child(
        self,
        *,
        _importance: Importance = Importance.ESSENTIAL,
        **values: Any,
    ) -> "Node":
        """Append a child to this node and return the new child.

        Args:
            _importance: The child's :class:`~asyoulikeit.Importance`.
                Underscore-prefixed so it cannot clash with a column key.
            **values: The child's column values. Must match the owning
                :class:`TreeContent`'s column schema exactly — missing
                keys and extra keys both raise :exc:`ValueError`.

        Returns:
            The newly-added child. Retain it to chain more descendants;
            to add siblings, call ``add_child`` on the *parent* again.
        """
        self._owner._validate_values(values)
        child = Node(self._owner, dict(values), _importance)
        self._children.append(child)
        return child

    @property
    def values(self) -> Mapping[str, Any]:
        """Immutable view of this node's column values."""
        return MappingProxyType(self._values)

    @property
    def children(self) -> tuple["Node", ...]:
        """Immutable tuple of this node's children in insertion order."""
        return tuple(self._children)

    @property
    def importance(self) -> Importance:
        """This node's :class:`~asyoulikeit.Importance` tag."""
        return self._importance


class TreeContent(ReportContent):
    """Hierarchical content with a uniform column schema across nodes.

    Every node — roots and descendants alike — holds a set of column
    values keyed by the same schema declared on the ``TreeContent``
    itself. Most trees have a single root; ``TreeContent`` also
    supports a forest via repeated calls to :meth:`add_root`.

    Construction rules:

    * All columns must be declared before the first :meth:`add_root`
      call.
    * Exactly one column must be marked ``header=True``; it is the
      label column displayed in the tree's first column by the
      ``display`` formatter.
    * Header columns must be ``Importance.ESSENTIAL`` (the default).
    * Every node's values must match the column schema exactly.

    Filtering on :class:`~asyoulikeit.Importance` prunes a ``DETAIL``
    node *and its entire subtree* when the resolved detail level is
    ``ESSENTIAL`` — a detail node's descendants cannot out-rank their
    ancestor.
    """

    def __init__(
        self,
        title: Optional[AudienceStr] = None,
        description: Optional[AudienceStr] = None,
    ):
        """Initialise a new :class:`TreeContent`.

        Args:
            title: Optional title for the tree. May be a ``ByAudience`` to
                vary it between human and machine output.
            description: Optional description, shown as caption below
                the tree by the display formatter. May be a ``ByAudience``.
        """
        self._title = title
        self._description = description
        self._columns: dict[str, Column] = {}
        self._roots: list[Node] = []

    @classmethod
    def kind(cls) -> str:
        """Return the :class:`ReportContent` kind identifier: ``"tree"``."""
        return "tree"

    def add_column(
        self,
        key: str,
        label: AudienceStr,
        header: bool = False,
        importance: Importance = Importance.ESSENTIAL,
    ) -> "TreeContent":
        """Add a column to the tree's schema.

        Args:
            key: Internal identifier for the column; must be a valid
                Python identifier and not start with an underscore.
            label: Display name shown in formatted output.
            header: Whether this column is the tree's label column.
                Exactly one column on a tree must be marked header.
            importance: ``ESSENTIAL`` (default) or ``DETAIL``. Header
                columns must be ``ESSENTIAL``.

        Returns:
            ``self``, for method chaining.

        Raises:
            ValueError: If columns are added after roots exist, the
                key clashes with an existing column, the key is not a
                valid identifier (or starts with underscore), or a
                header column is tagged ``DETAIL``.
        """
        if self._roots:
            raise ValueError("Cannot add columns after roots have been added")
        if key in self._columns:
            raise ValueError(f"Column '{key}' already defined")
        if not key.isidentifier():
            raise ValueError(
                f"Column key '{key}' must be a valid Python identifier"
            )
        if key.startswith("_"):
            raise ValueError(
                f"Column key '{key}' cannot start with underscore "
                f"(reserved for internal use)"
            )
        if header and importance != Importance.ESSENTIAL:
            raise ValueError("Header columns must be ESSENTIAL")
        self._columns[key] = Column(
            key=key, label=label, header=header, importance=importance
        )
        return self

    def add_root(
        self,
        *,
        _importance: Importance = Importance.ESSENTIAL,
        **values: Any,
    ) -> Node:
        """Append a top-level node and return it.

        May be called multiple times to build a forest (a
        :class:`TreeContent` with more than one root). The common
        single-tree case is a single :meth:`add_root` call, after
        which :meth:`Node.add_child` builds the rest.

        Args:
            _importance: The root's :class:`~asyoulikeit.Importance`.
                Underscore-prefixed to avoid clashing with a column
                key.
            **values: The root's column values. Must match the schema
                exactly.

        Returns:
            The newly-added root. Retain it to attach children.

        Raises:
            ValueError: If no columns are declared yet, if exactly one
                column is not marked header, or if the values do not
                match the column schema.
        """
        if not self._columns:
            raise ValueError("Must define columns before adding roots")
        self._require_single_header_column()
        self._validate_values(values)
        root = Node(self, dict(values), _importance)
        self._roots.append(root)
        return root

    def _validate_values(self, values: dict[str, Any]) -> None:
        """Check ``values`` matches the column schema exactly."""
        column_keys = self._columns.keys()
        missing = column_keys - values.keys()
        if missing:
            raise ValueError(
                f"Node missing required columns: {sorted(missing)}"
            )
        extra = values.keys() - column_keys
        if extra:
            raise ValueError(
                f"Node contains unexpected columns: {sorted(extra)}"
            )

    def _require_single_header_column(self) -> None:
        """Enforce that exactly one column is marked ``header=True``."""
        header_count = sum(
            1 for col in self._columns.values() if col.header
        )
        if header_count != 1:
            raise ValueError(
                f"TreeContent requires exactly one column marked "
                f"header=True (got {header_count})"
            )

    @property
    def title(self) -> Optional[AudienceStr]:
        """The tree's title, if any (may be a ``ByAudience`` until resolved)."""
        return self._title

    @property
    def description(self) -> Optional[AudienceStr]:
        """The tree's description / caption (may be a ``ByAudience`` until resolved)."""
        return self._description

    @property
    def columns(self) -> tuple[Column, ...]:
        """Immutable tuple of the tree's columns in declared order."""
        return tuple(self._columns.values())

    @property
    def essential_columns(self) -> tuple[Column, ...]:
        """Columns marked ``Importance.ESSENTIAL``."""
        return tuple(
            c for c in self._columns.values()
            if c.importance == Importance.ESSENTIAL
        )

    @property
    def detailed_columns(self) -> tuple[Column, ...]:
        """Columns marked ``Importance.DETAIL``."""
        return tuple(
            c for c in self._columns.values()
            if c.importance == Importance.DETAIL
        )

    @property
    def header_column(self) -> Optional[Column]:
        """The single column marked ``header=True``, if declared."""
        for col in self._columns.values():
            if col.header:
                return col
        return None

    @property
    def roots(self) -> tuple[Node, ...]:
        """Immutable tuple of top-level nodes in insertion order."""
        return tuple(self._roots)
