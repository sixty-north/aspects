"""Cell-budget elision for the display formatter.

Eliding is measured in terminal cells rather than characters, because that
is the resource being budgeted: a double-width CJK character costs two, a
box-drawing connector one, and a column that fits ten characters of one may
fit only five of the other.

This is display-specific and private to the formatter. Machine formats have
no bounded width to elide into, and must carry the whole value — which is
precisely what makes eliding safe here: nothing is lost from the output a
pipeline reads, only from the one a human is looking at.
"""

from typing import Optional

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.measure import Measurement
from rich.style import Style
from rich.text import Text

from asyoulikeit.tabular_data import Overflow


# U+2026, one cell wide in every terminal that can draw the box around it.
ELLIPSIS = "…"


def _clusters(text: str) -> list[str]:
    """Split ``text`` into the smallest units an elision may not divide.

    A user-perceived character can span several code points — a base letter
    and its combining accents, a flag, an emoji with a skin-tone modifier —
    and cutting between them turns one character into two broken ones. The
    correct unit is the Unicode grapheme cluster.

    This splits on code points instead, which is right for the identifiers
    and addresses elision is aimed at and wrong for combining sequences.
    It is the single place that decides where a cut may fall: a real
    segmenter dropped in here gives every policy correct behaviour without
    any of them changing, and nothing else in this module inspects the
    string. Deliberately not a dependency until something needs it.
    """
    return list(text)


def _take_cells(clusters: list[str], budget: int, from_end: bool = False) -> str:
    """Take whole clusters from one end of ``clusters`` up to ``budget`` cells.

    Stops before any cluster that would overrun the budget, so the result
    never exceeds it — a double-width character simply doesn't go in when
    only one cell is left. Returns the clusters in their original order
    whichever end they were taken from.
    """
    taken: list[str] = []
    remaining = budget
    for cluster in reversed(clusters) if from_end else clusters:
        width = cell_len(cluster)
        if width > remaining:
            break
        taken.append(cluster)
        remaining -= width
    return "".join(reversed(taken) if from_end else taken)


def elide(text: str, width: int, policy: Overflow) -> str:
    """Fit ``text`` into ``width`` terminal cells under ``policy``.

    Text that already fits is returned unchanged, so an elision policy
    costs nothing until the column is actually too narrow. Otherwise one
    cell is spent on the ellipsis and the rest is divided according to the
    policy — for ``ELIDE_MIDDLE``, with the odd cell going to the head,
    since a value's opening is marginally more orienting than its close.

    The formula degrades on its own as the budget shrinks: at two cells
    middle-elision has nothing to keep at the tail and reads as an
    end-elision, and at one cell every policy is a bare ellipsis. No
    special-casing is needed to get there, and none is done.

    ``WRAP`` returns the text unchanged: this function is only ever asked
    about a column that declared elision, and answering for the wrapping
    policy keeps callers from having to special-case it.
    """
    if policy == Overflow.WRAP or cell_len(text) <= width:
        return text
    if width <= 0:
        return ""
    if width == 1:
        return ELLIPSIS

    clusters = _clusters(text)
    budget = width - 1  # one cell for the ellipsis
    if policy == Overflow.ELIDE_END:
        return _take_cells(clusters, budget) + ELLIPSIS
    if policy == Overflow.ELIDE_START:
        return ELLIPSIS + _take_cells(clusters, budget, from_end=True)
    head_budget = budget - budget // 2
    head = _take_cells(clusters, head_budget)
    tail = _take_cells(clusters, budget - cell_len(head), from_end=True)
    return head + ELLIPSIS + tail


class Elided:
    """A table cell that elides itself to whatever width it is given.

    On the tree path the formatter computes its own column widths and can
    elide directly. On the table path it cannot: Rich decides the widths,
    after the terminal width and every column's natural width are known,
    and that is the whole reason the policy could not be applied by the
    calling application either.

    So the elision is deferred to render time, where Rich hands each cell
    the width it was allotted as ``options.max_width``. Rich keeps doing
    the layout; only what happens inside the cell changes.
    """

    def __init__(
        self, text: str, policy: Overflow, style: Optional[Style] = None
    ):
        self.text = text
        self.policy = policy
        self.style = style

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        yield Text(elide(self.text, options.max_width, self.policy), style=self.style or "")

    def __rich_measure__(
        self, console: Console, options: ConsoleOptions
    ) -> Measurement:
        """Report the natural width, and a minimum of one cell for the ellipsis.

        The maximum is what the column asks for; the minimum is what it can
        survive on, which for a cell that elides is a single ellipsis. The
        ceiling that stops such a column starving its neighbours is applied
        by the formatter as the Rich column's ``max_width``, not here —
        this measurement describes one cell, and has no view of the others.
        """
        natural = min(cell_len(self.text), options.max_width)
        return Measurement(min(1, natural), natural)
