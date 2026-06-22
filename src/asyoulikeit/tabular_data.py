"""Tabular data representation for CLI output formatting.

This module provides a structured way to build and represent tabular data
with a defined schema, suitable for formatting into various output formats
like TSV, JSON, or rich console tables.
"""

from collections.abc import Iterable, Mapping, Iterator
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from asyoulikeit.content import ReportContent

if TYPE_CHECKING:
    from asyoulikeit.audience import Audience, ByAudience

    # A string slot that may instead carry a ByAudience wrapper. It is
    # collapsed to the audience-appropriate string by
    # asyoulikeit.audience.resolve_audience before any formatter sees it, so
    # at runtime the alias is plain ``str``.
    AudienceStr = str | ByAudience
    # The set of audiences a column opts in to empty-omission for, and the
    # iterable accepted for it at the ``add_column`` boundary. Like AudienceStr
    # these resolve to neutral runtime types so they avoid a circular import
    # with the audience module (and keep generated docs unambiguous).
    AudienceSet = frozenset[Audience]
    AudienceIterable = Iterable[Audience]
else:
    AudienceStr = str
    AudienceSet = frozenset
    AudienceIterable = Iterable


# Style property keys for cell formatting
# These keys are used in style dictionaries within cells of a styles TableContent instance
STYLE_FOREGROUND_COLOR = "foreground_color"  # Hex color string, e.g., "#FFFFFF"
STYLE_BACKGROUND_COLOR = "background_color"  # Hex color string, e.g., "#0066CC"
STYLE_BOLD = "bold"                          # Boolean
STYLE_ITALIC = "italic"                      # Boolean
STYLE_ALIGNMENT = "alignment"                # "left", "center", "right"
STYLE_WIDTH = "width"                        # Integer (column width hint)


class Importance(Enum):
    """Importance level for columns and/or rows in tabular data.

    ESSENTIAL columns and rows are always included in output (suitable for machine parsing).
    DETAIL columns provide additional information for human-friendly output but may
    be omitted in machine-readable formats like TSV/CSV. Moreover, information about deprecated
    entities can be marked as DETAIL to allow users to focus on current data.
    """
    ESSENTIAL = "essential"
    DETAIL = "detail"


class DetailLevel(Enum):
    """Control which columns to include in formatted output.

    AUTO: Formatter decides based on its own default behavior (TSV excludes, table includes)
    DETAILED: Include all columns (ESSENTIAL + DETAIL)
    ESSENTIAL: Include only ESSENTIAL columns
    """
    AUTO = "auto"
    DETAILED = "detailed"
    ESSENTIAL = "essential"


@dataclass(frozen=True)
class Column:
    """Column definition for tabular data.

    Args:
        key: Internal identifier for the column (used in row dictionaries)
        label: Display name for the column (shown in output)
        header: Whether this column serves as a row header/label column
        importance: Column importance level (ESSENTIAL or DETAIL)
        omit_if_empty_for: Audiences for which this column is dropped when
            every data cell in it is empty (``None`` or ``""``) after
            audience collapse. Empty by default (the column is always kept).
            See :func:`~asyoulikeit.audience.prune_empty_columns`.
    """
    key: str
    label: AudienceStr
    header: bool = False
    importance: Importance = Importance.ESSENTIAL
    omit_if_empty_for: AudienceSet = frozenset()


class TableContent(ReportContent):
    """Container for tabular data with schema validation.

    TableContent enforces that all rows match a defined column schema,
    providing a builder-style API for constructing tables programmatically.

    Example:

        .. code-block:: python

            data = TableContent(title="User List", description="Active users in the system")
            data.add_column("name", "Name")
            data.add_column("age", "Age")
            data.add_row(name="Alice", age=30)
            data.add_row(name="Bob", age=25)

            # Access immutable views
            for row in data.rows:
                print(row["name"], row["age"])
    """

    def __init__(
        self,
        title: Optional[AudienceStr] = None,
        description: Optional[AudienceStr] = None,
        present_transposed: bool = False
    ):
        """Initialize a TableContent instance with optional metadata.

        Args:
            title: Optional title for the table. May be a ``ByAudience`` to
                vary it between human and machine output.
            description: Optional description of the table's contents. May be
                a ``ByAudience``.
            present_transposed: Whether the table should be presented with rows
                               and columns transposed (default: False)
        """
        self._title = title
        self._description = description
        self._present_transposed = present_transposed
        self._columns: dict[str, Column] = {}
        self._rows: list[dict[str, Any]] = []
        self._row_importances: list[Importance] = []

    @classmethod
    def kind(cls) -> str:
        """Return the :class:`ReportContent` kind identifier: ``"table"``."""
        return "table"

    @classmethod
    def from_mappings(
        cls,
        mappings: Iterable[Mapping[str, Any]],
        title: Optional[AudienceStr] = None,
        description: Optional[AudienceStr] = None,
        present_transposed: bool = False
    ) -> "TableContent":
        """Create TableContent from an iterable of mappings (e.g., list of dicts).

        Columns are inferred from the union of all keys across all mappings.
        Column keys and labels will be identical. Missing keys in individual
        mappings will be filled with None.

        Column order is determined by the order of first appearance across all
        mappings (not sorted).

        Args:
            mappings: Iterable of mappings (e.g., list of dictionaries)
            title: Optional title for the table
            description: Optional description
            present_transposed: Whether to present transposed

        Returns:
            A new TableContent instance

        Raises:
            ValueError: If any key is not a valid Python identifier

        Example:

            .. code-block:: python

                data = TableContent.from_mappings([
                    {"name": "Alice", "age": 30},
                    {"name": "Bob", "age": 25, "city": "NYC"}
                ])
                # Results in columns: name, age, city
                # Row 1: Alice, 30, None
                # Row 2: Bob, 25, NYC
        """
        # Convert to list to allow multiple passes
        mappings_list = list(mappings)

        if not mappings_list:
            # Empty list - return empty table
            return cls(title=title, description=description, present_transposed=present_transposed)

        # Collect all keys from all mappings, preserving order of first appearance
        all_keys = []
        seen_keys = set()
        for mapping in mappings_list:
            for key in mapping.keys():
                if key not in seen_keys:
                    all_keys.append(key)
                    seen_keys.add(key)

        # Validate all keys are valid identifiers
        for key in all_keys:
            if not isinstance(key, str) or not key.isidentifier():
                raise ValueError(f"Key '{key}' must be a valid Python identifier")

        # Create table and add columns
        table = cls(title=title, description=description, present_transposed=present_transposed)
        for key in all_keys:
            table.add_column(key, key)  # Use key as both key and label

        # Add rows, filling missing keys with None
        for mapping in mappings_list:
            row_data = {key: mapping.get(key, None) for key in all_keys}
            table.add_row(**row_data)

        return table

    def add_column(
        self,
        key: str,
        label: AudienceStr,
        header: bool = False,
        importance: Importance = Importance.ESSENTIAL,
        omit_if_empty_for: AudienceIterable = ()
    ) -> "TableContent":
        """Add a column definition to the schema.

        Columns must be added before any rows. This method uses the builder
        pattern and returns self for method chaining.

        Args:
            key: Internal identifier for the column (must be a valid Python identifier)
            label: Display name for the column
            header: Whether this column serves as a row header/label column (default: False).
                   Can only be True for the first column. Header columns must be ESSENTIAL.
            importance: Column importance level (default: ESSENTIAL). Header columns must
                       always be ESSENTIAL. DETAIL columns provide supplementary information,
                       and may be omitted in machine-readable output formats to reduce clutter
                       and ease parsing.
            omit_if_empty_for: Audiences for which this column is dropped when
                       all of its data cells are empty (``None`` or ``""``) after
                       audience collapse — e.g. ``{Audience.HUMAN}`` to keep a
                       provably-empty column out of human output while machine
                       formats retain it as part of a stable schema. Accepts any
                       iterable of :class:`~asyoulikeit.Audience`; defaults to none
                       (the column is always kept). Header columns are never
                       dropped. See
                       :func:`~asyoulikeit.audience.prune_empty_columns`.

        Returns:
            Self for method chaining

        Raises:
            ValueError: If rows have already been added, if column key already exists,
                       if key is not a valid Python identifier, if header=True is set on
                       a non-first column, or if header=True is combined with DETAIL importance
        """
        if self._rows:
            raise ValueError("Cannot add columns after rows have been added")
        if key in self._columns:
            raise ValueError(f"Column '{key}' already defined")
        if not key.isidentifier():
            raise ValueError(f"Column key '{key}' must be a valid Python identifier")
        if key.startswith('_'):
            raise ValueError(f"Column key '{key}' cannot start with underscore (reserved for internal use)")
        if header and self._columns:
            raise ValueError("Header column must be the first column")
        if header and importance != Importance.ESSENTIAL:
            raise ValueError("Header columns must be ESSENTIAL")

        self._columns[key] = Column(
            key=key,
            label=label,
            header=header,
            importance=importance,
            omit_if_empty_for=frozenset(omit_if_empty_for),
        )
        return self

    def add_row(self, *, _importance: Importance = Importance.ESSENTIAL, **values: Any) -> "TableContent":
        """Add a data row with strict validation.

        All defined columns must be present in the row, and no extra columns
        are allowed. This enforces schema consistency across all rows.

        Args:
            _importance: Row importance level (default: ESSENTIAL). Underscore prefix
                        reserves this parameter name to avoid conflict with column keys.
            **values: Column key-value pairs for the row

        Returns:
            Self for method chaining

        Raises:
            ValueError: If no columns defined, if required columns are missing,
                       or if extra unexpected columns are present
        """
        if not self._columns:
            raise ValueError("Must define columns before adding rows")

        column_keys = self._columns.keys()

        # Check for missing required columns
        missing_keys = column_keys - values.keys()
        if missing_keys:
            raise ValueError(f"Row missing required columns: {sorted(missing_keys)}")

        # Check for unexpected extra columns (strict validation)
        extra_keys = values.keys() - column_keys
        if extra_keys:
            raise ValueError(f"Row contains unexpected columns: {sorted(extra_keys)}")

        # Store row data preserving column order
        row = {key: values[key] for key in column_keys}
        self._rows.append(row)
        self._row_importances.append(_importance)
        return self

    @property
    def columns(self) -> tuple[Column, ...]:
        """Get an immutable view of the column definitions.

        Columns are returned in the order they were added.

        Returns:
            Tuple of Column objects
        """
        return tuple(self._columns.values())

    @property
    def essential_columns(self) -> tuple[Column, ...]:
        """Get columns marked as ESSENTIAL.

        Essential columns are suitable for machine-readable output formats
        and provide core identifying information.

        Returns:
            Tuple of Column objects with importance=ESSENTIAL
        """
        return tuple(col for col in self._columns.values() if col.importance == Importance.ESSENTIAL)

    @property
    def detailed_columns(self) -> tuple[Column, ...]:
        """Get columns marked as DETAIL.

        Detail columns provide supplementary information for human-friendly
        output but may be omitted in machine-readable formats.

        Returns:
            Tuple of Column objects with importance=DETAIL
        """
        return tuple(col for col in self._columns.values() if col.importance == Importance.DETAIL)

    @property
    def rows(self) -> tuple[dict[str, Any], ...]:
        """Get an immutable view of the data rows.

        Each row is a dictionary mapping column keys to values.

        Returns:
            Tuple of row dictionaries
        """
        return tuple(self._rows)

    @property
    def row_importances(self) -> tuple[Importance, ...]:
        """Get row importance levels.

        Returns:
            Tuple of ColumnImportance values, one per row, in same order as rows
        """
        return tuple(self._row_importances)

    @property
    def essential_rows(self) -> tuple[dict[str, Any], ...]:
        """Get rows marked as ESSENTIAL.

        Essential rows are always included in output.

        Returns:
            Tuple of row dictionaries with importance=ESSENTIAL
        """
        return tuple(
            row for row, importance in zip(self._rows, self._row_importances)
            if importance == Importance.ESSENTIAL
        )

    def rows_for_detail_level(self, detail_level: DetailLevel) -> tuple[dict[str, Any], ...]:
        """Get rows appropriate for the specified detail level.

        This method mirrors the column filtering pattern used in formatters:
        - DETAILED: Returns all rows (ESSENTIAL + DETAIL)
        - ESSENTIAL: Returns only ESSENTIAL rows
        - AUTO: Treated as ESSENTIAL (should be resolved to DETAILED or ESSENTIAL by caller)

        Args:
            detail_level: DetailLevel.DETAILED or DetailLevel.ESSENTIAL.
                         AUTO is treated as ESSENTIAL (should be resolved by caller).

        Returns:
            Tuple of row dictionaries filtered by importance

        Example:
            >>> # In a formatter:
            >>> if detail_level == DetailLevel.AUTO:
            ...     detail_level = DetailLevel.ESSENTIAL  # or DETAILED
            >>> rows = data.rows_for_detail_level(detail_level)
        """
        if detail_level == DetailLevel.DETAILED:
            return self.rows  # All rows
        else:  # ESSENTIAL or AUTO
            return self.essential_rows

    @property
    def title(self) -> Optional[AudienceStr]:
        """Get the table title.

        Returns:
            The table title, or None if not set. May be a ``ByAudience``
            until :func:`~asyoulikeit.audience.resolve_audience` collapses it.
        """
        return self._title

    @property
    def description(self) -> Optional[AudienceStr]:
        """Get the table description.

        Returns:
            The table description, or None if not set. May be a ``ByAudience``
            until :func:`~asyoulikeit.audience.resolve_audience` collapses it.
        """
        return self._description

    @property
    def present_transposed(self) -> bool:
        """Get whether the table should be presented transposed.

        Returns:
            True if the table should be presented with rows and columns swapped
        """
        return self._present_transposed

    @property
    def header_column(self) -> Optional[Column]:
        """Get the header column if one exists.

        Returns:
            The header column, or None if no column is marked as header
        """
        for col in self._columns.values():
            if col.header:
                return col
        return None

    def transpose(
        self,
        value_column_importance: Importance = Importance.ESSENTIAL
    ) -> "TableContent":
        """Transpose rows and columns.

        Returns a new TableContent with rows and columns swapped. The header
        column (if present) becomes the column labels of the transposed data,
        and the original column labels become the first column of the transposed
        data (marked as header).

        If no header column exists, row indices are used as column labels.

        Note: Original column importance metadata is not directly preserved. Original row data
        does not carry importance metadata, so all value columns receive the same importance
        level specified by `value_column_importance`.

        Args:
            value_column_importance: Importance level for all value columns in the transposed
                table. Defaults to ESSENTIAL (safe for machine-readable output).

        Returns:
            A new transposed TableContent with present_transposed=False
        """
        transposed = TableContent(
            title=self.title,
            description=self.description,
            present_transposed=False  # We're doing the actual transposition
        )

        # First column contains the original column labels (always ESSENTIAL header)
        header_col = self.header_column
        if header_col:
            # Use header column label for the first column
            transposed.add_column("label", header_col.label, header=True)
        else:
            # Use empty label for the first column
            transposed.add_column("label", "", header=True)

        # Subsequent columns: one per original row
        # Use header column values as labels (or row indices)
        # All value columns get the specified importance
        for row_idx, row in enumerate(self.rows):
            if header_col:
                col_label = str(row[header_col.key])
            else:
                col_label = str(row_idx)
            transposed.add_column(f"row_{row_idx}", col_label, importance=value_column_importance)

        # Add rows: one for each original data column (excluding header column)
        # Build row data maintaining column key order
        data_columns = [col for col in self.columns if not col.header]
        for col in data_columns:
            # Construct row_data with keys in the same order as transposed columns
            row_data = {
                "label": col.label,
                **{f"row_{row_idx}": row[col.key] for row_idx, row in enumerate(self.rows)}
            }
            transposed.add_row(**row_data)

        return transposed

    def is_compatible(self, other: "TableContent") -> bool:
        """Check if another TableContent has compatible structure.

        Compatibility requires:
        - Same number of columns
        - Same column keys in same order
        - Same number of rows

        Note: Column labels are NOT checked (styles may use different labels)

        Args:
            other: Another TableContent instance to compare

        Returns:
            True if structures are compatible, False otherwise
        """
        if len(self.columns) != len(other.columns):
            return False

        if len(self.rows) != len(other.rows):
            return False

        for self_col, other_col in zip(self.columns, other.columns):
            if self_col.key != other_col.key:
                return False

        return True


def validate_styles_compatibility(data: TableContent, styles: TableContent) -> None:
    """Verify styles table is compatible with data table.

    Args:
        data: The data table
        styles: The styles table

    Raises:
        ValueError: If tables are not compatible with detailed message
    """
    if not data.is_compatible(styles):
        if len(data.columns) != len(styles.columns):
            raise ValueError(
                f"Column count mismatch: data has {len(data.columns)}, "
                f"styles has {len(styles.columns)}"
            )
        if len(data.rows) != len(styles.rows):
            raise ValueError(
                f"Row count mismatch: data has {len(data.rows)}, "
                f"styles has {len(styles.rows)}"
            )
        for i, (data_col, style_col) in enumerate(zip(data.columns, styles.columns)):
            if data_col.key != style_col.key:
                raise ValueError(
                    f"Column {i} key mismatch: data has '{data_col.key}', "
                    f"styles has '{style_col.key}'"
                )


@dataclass(frozen=True)
class Report:
    """A self-contained report with data and formatting preferences.

    Reports are named via dictionary keys when returned from commands.
    Each report contains its data, optional styling, and formatting preferences.

    Report names must be valid Python identifiers (alphanumeric + underscore,
    not starting with digit) to ensure compatibility with JSON/JavaScript.

    Attributes:
        data: The content of this report (a :class:`ReportContent` subclass).
        styles: Optional styling information with same structure as data.
        title: Optional title for the report (may differ from TableContent title).
        description: Optional description (may differ from TableContent description).
        detail_level: Default detail level for this report (can be overridden by CLI).
        header: Tri-state preference for whether headers/titles/chrome are
            emitted. ``True`` or ``False`` are honoured as explicit requests;
            ``None`` (the default) defers to the formatter, which picks a
            sensible default per content type. Resolution order, highest
            first: CLI ``--header``/``--no-header`` → this field → formatter
            default.
    """
    data: ReportContent
    styles: Optional[TableContent] = None
    title: Optional[str] = None
    description: Optional[str] = None
    detail_level: DetailLevel = DetailLevel.AUTO
    header: Optional[bool] = None


class Reports(Mapping[str, Report]):
    """An immutable collection of named reports.

    Reports is a value object representing a mapping from report names to Report objects.
    Report names are validated to be valid Python identifiers on construction, ensuring
    compatibility with JSON/JavaScript object keys.

    This class is constructable like a regular dictionary and can be used anywhere a
    Mapping is expected. It provides a clean abstraction for collections of reports
    and leaves room for future metadata additions.

    Examples:
        Dict-style construction::

            reports = Reports({"masters": master_report, "themes": theme_report})

        Keyword arguments::

            reports = Reports(masters=master_report, themes=theme_report)

        From iterable of tuples::

            reports = Reports([("masters", master_report)])

        Access like a dict::

            master_report = reports["masters"]
            for name, report in reports.items():
                print(name, report.data.title)

    Raises:
        ValueError: If any report name is not a valid Python identifier
    """

    def __init__(self, *args, **kwargs):
        """Initialize Reports from dict-compatible arguments.

        Accepts same arguments as dict() constructor. Validates that all keys
        are valid Python identifiers.

        Args:
            *args: Positional arguments (dict, iterable of pairs, etc.)
            **kwargs: Keyword arguments (name=report pairs)

        Raises:
            ValueError: If any key is not a valid Python identifier, or if any
                value is not a Report instance
        """
        # Construct internal dict using standard dict() behavior
        self._reports = dict(*args, **kwargs)

        # Validate all keys are valid Python identifiers and values are Reports
        for name, report in self._reports.items():
            if not isinstance(name, str):
                raise ValueError(
                    f"Report name must be a string, not {type(name).__name__}"
                )
            if not name.isidentifier():
                raise ValueError(
                    f"Report name '{name}' must be a valid Python identifier "
                    f"(alphanumeric + underscore, not starting with digit)"
                )
            if not isinstance(report, Report):
                raise ValueError(
                    f"Report value for '{name}' must be a Report instance, "
                    f"not {type(report).__name__}"
                )

    # Mapping protocol implementation
    def __getitem__(self, key: str) -> Report:
        return self._reports[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._reports)

    def __len__(self) -> int:
        return len(self._reports)

    def __repr__(self) -> str:
        return f"Reports({self._reports!r})"
