"""Utilities for enriching CLI tools with structured report output."""

__version__ = "1.4.0"

from asyoulikeit.audience import (
    Audience,
    ByAudience,
    prune_empty_columns,
    resolve_audience,
)
from asyoulikeit.cli import (
    ALL_REPORTS,
    describe_formatter_command,
    describe_report_command,
    list_formatters_command,
    list_reports_command,
    report_output,
)
from asyoulikeit.content import ReportContent
from asyoulikeit.exceptions import AsyoulikeitError, ReportDeclarationError
from asyoulikeit.extension import Extension, ExtensionError
from asyoulikeit.formatter import (
    Formatter,
    FormatterExtensionError,
    create_formatter,
    describe_formatter,
    format_as,
    formatter_names,
)
from asyoulikeit.tabular_data import (
    STYLE_ALIGNMENT,
    STYLE_BACKGROUND_COLOR,
    STYLE_BOLD,
    STYLE_FOREGROUND_COLOR,
    STYLE_ITALIC,
    STYLE_WIDTH,
    Column,
    DetailLevel,
    Importance,
    Overflow,
    Report,
    Reports,
    TableContent,
)
from asyoulikeit.scalar_data import ScalarContent
from asyoulikeit.tree_data import Node, TreeContent

__all__ = [
    "ALL_REPORTS",
    "AsyoulikeitError",
    "Audience",
    "ByAudience",
    "Column",
    "DetailLevel",
    "Extension",
    "ExtensionError",
    "Formatter",
    "FormatterExtensionError",
    "Importance",
    "Node",
    "Overflow",
    "Report",
    "ReportContent",
    "ReportDeclarationError",
    "Reports",
    "STYLE_ALIGNMENT",
    "STYLE_BACKGROUND_COLOR",
    "STYLE_BOLD",
    "STYLE_FOREGROUND_COLOR",
    "STYLE_ITALIC",
    "STYLE_WIDTH",
    "ScalarContent",
    "TableContent",
    "TreeContent",
    "create_formatter",
    "describe_formatter",
    "describe_formatter_command",
    "describe_report_command",
    "format_as",
    "formatter_names",
    "list_formatters_command",
    "list_reports_command",
    "prune_empty_columns",
    "report_output",
    "resolve_audience",
]
