"""Formatter extension point for tabular data output."""

from abc import abstractmethod
from typing import Type

from asyoulikeit.audience import Audience, prune_empty_columns, resolve_audience
from asyoulikeit.extension import (
    Extension, ExtensionError, create_extension, describe_extension,
    list_extensions, extension,
)
from asyoulikeit.tabular_data import Reports

KIND = "formatter"
FORMATTER_NAMESPACE = f"asyoulikeit.{KIND}"


class Formatter(Extension):
    """Base class for formatters.

    Formatters convert a :class:`Reports` collection into text suitable for a
    particular output channel (terminal table, TSV, JSON, etc.).

    Attributes:
        audience: The reader this formatter's output is aimed at. Drives
            :class:`~asyoulikeit.ByAudience` collapse in :func:`format_as`.
            Defaults to :attr:`Audience.MACHINE` so that a yet-undeclared
            third-party formatter receives the raw / canonical value, never a
            lossy human rendering — subclasses override as appropriate.
    """

    audience: Audience = Audience.MACHINE

    @classmethod
    def _kind(cls):
        return KIND

    @abstractmethod
    def format(self, reports: Reports) -> str:
        """Format reports as string output.

        Args:
            reports: A Reports object containing one or more named reports.
                Each report has its own data, optional styles, and formatting preferences
                (detail_level, header) that may have been overridden by CLI flags.

        Returns:
            Formatted string representation suitable for the chosen output channel.
        """
        raise NotImplementedError


class FormatterExtensionError(ExtensionError):
    """Exception raised when a formatter extension cannot be loaded."""
    pass


def create_formatter(formatter_name: str) -> Formatter:
    """Create a formatter instance by name.

    Args:
        formatter_name: The name of the formatter to create (e.g., "tsv", "json")

    Returns:
        A Formatter instance

    Raises:
        FormatterExtensionError: If the formatter cannot be loaded
    """
    return create_extension(
        kind=KIND,
        namespace=FORMATTER_NAMESPACE,
        name=formatter_name,
        exception_type=FormatterExtensionError,
    )


def describe_formatter(formatter_name: str, *, single_line: bool = False) -> str:
    """Get the description of a formatter.

    Args:
        formatter_name: The name of the formatter
        single_line: If True, return only the first non-empty line of the description.

    Returns:
        Description string from the formatter's docstring

    Raises:
        FormatterExtensionError: If the formatter cannot be loaded
    """
    return describe_extension(
        kind=KIND,
        namespace=FORMATTER_NAMESPACE,
        name=formatter_name,
        exception_type=FormatterExtensionError,
        single_line=single_line
    )


def formatter_names() -> list[str]:
    """Get the names of all available formatters.

    Returns:
        List of formatter names (e.g., ["display", "json", "tsv"])
    """
    return list_extensions(FORMATTER_NAMESPACE)


def formatter_type(formatter_name: str) -> Type[Formatter]:
    """Obtain the type of a formatter by name.

    Args:
        formatter_name: The name of a formatter. Available formatter names can be
            obtained from :py:func:`~formatter_names`.

    Returns:
        The type (i.e. class) of the requested formatter.

    Raises:
        FormatterExtensionError: If the requested formatter could not be found.
    """
    return extension(
        kind=KIND,
        namespace=FORMATTER_NAMESPACE,
        name=formatter_name,
        exception_type=FormatterExtensionError
    )


def format_as(
    reports: Reports,
    format_name: str,
) -> str:
    """Format reports using the specified formatter.

    This is the primary dispatcher function for formatters.

    Args:
        reports: A Reports object containing one or more named reports.
            Each report contains its own data, styles, and formatting preferences
            that may have been adjusted by CLI flags.
        format_name: Name of the format (e.g., "tsv", "json", "display")

    Returns:
        Formatted string

    Raises:
        FormatterExtensionError: If format_name is not recognized
    """
    try:
        formatter = create_formatter(format_name)
        # Collapse any ByAudience cells to the representation matching this
        # formatter's audience before dispatch, so format() never sees them.
        reports = resolve_audience(reports, formatter.audience)
        # Then drop columns an author marked omit-if-empty for this audience
        # whose cells are all empty after collapse — invisible to format().
        reports = prune_empty_columns(reports, formatter.audience)
        return formatter.format(reports)
    except FormatterExtensionError:
        # Provide a more user-friendly error message
        available = ", ".join(sorted(formatter_names()))
        raise FormatterExtensionError(
            f"Unknown format '{format_name}'. Available: {available}"
        )
