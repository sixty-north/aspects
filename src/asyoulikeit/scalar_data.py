"""A single-value ``ReportContent`` kind.

Where :class:`~asyoulikeit.TableContent` carries a table of rows and
:class:`~asyoulikeit.TreeContent` carries a hierarchy, :class:`ScalarContent`
carries *one value*: a title, a number, a status string, an address — the
kind of thing a command like ``disc title image`` produces. It exists so
that such commands can flow through ``@report_output`` with the same
``--as`` / ``--report`` / ``--header`` machinery as the other content
kinds, rather than skipping the decorator (and losing those affordances)
or wrapping the scalar in a 1×1 transposed table (which reads as ceremony
around a single cell and clutters JSON output with empty tabular shape).

Example::

    from asyoulikeit import (
        Report, Reports, ScalarContent, report_output,
    )

    @click.command()
    @report_output(reports={"title": "The disc image's title."})
    def disc_title(image):
        return Reports(title=Report(data=ScalarContent(
            value=_read_title(image),
            title="Disc title",
        )))

In a terminal the user sees ``Disc title: My Disc Image``; piped to
another tool with ``| pbcopy`` they get just ``My Disc Image`` (the
TSV formatter's per-content default for scalars is "no header line,
just the value"). JSON output is always self-describing — consumers
parse ``.reports.title.value`` via ``jq``.
"""

from typing import Any, Optional

from asyoulikeit.content import ReportContent
from asyoulikeit.tabular_data import AudienceStr


class ScalarContent(ReportContent):
    """A single value as a :class:`ReportContent`.

    No columns, no rows, no children — just one opaque ``value`` plus
    optional ``title`` and ``description`` metadata. The value's Python
    type is unconstrained; the formatters will coerce via ``str()`` for
    text rendering and pass primitives through directly for JSON.
    """

    def __init__(
        self,
        value: Any,
        title: Optional[AudienceStr] = None,
        description: Optional[AudienceStr] = None,
    ):
        """Initialise a new :class:`ScalarContent`.

        Args:
            value: The single value this report carries. Accepts any
                Python object; ``str()`` is applied for display / TSV
                rendering, and JSON serialises primitives (str, int,
                float, bool, None) natively.
            title: Optional title / label. Used by the display
                formatter as a prefix (``"Title: value"``) and by JSON
                as ``metadata.title``. Not emitted by TSV unless the
                caller explicitly sets ``header=True`` on the
                :class:`~asyoulikeit.Report` — TSV defaults to bare
                value output for scalars. May be a ``ByAudience`` to vary
                it between human and machine output.
            description: Optional longer description. Shown dim/italic
                below the value in display mode when headers are on;
                present in JSON metadata; never emitted in TSV. May be a
                ``ByAudience``.
        """
        self._value = value
        self._title = title
        self._description = description

    @classmethod
    def kind(cls) -> str:
        """Return the :class:`ReportContent` kind identifier: ``"scalar"``."""
        return "scalar"

    @property
    def value(self) -> Any:
        """The single value carried by this report."""
        return self._value

    @property
    def title(self) -> Optional[AudienceStr]:
        """The scalar's title / label (may be a ``ByAudience`` until resolved)."""
        return self._title

    @property
    def description(self) -> Optional[AudienceStr]:
        """The scalar's description (may be a ``ByAudience`` until resolved)."""
        return self._description
