Using asyoulikeit in your CLI
=============================

``asyoulikeit`` is a small library you apply to a Click-based
command-line tool to give your handlers a single source of truth for
structured output. Instead of printing in one hard-coded format, your
handler returns a :class:`~asyoulikeit.Reports` value and the library
handles rendering it as JSON, TSV, or a rich human-readable display,
according to whatever the user selected with the ``--as`` flag.

This page walks through the typical shape of an integration. See
:doc:`cli` for what your users will see on the command line, and
:doc:`api` for the full API reference.


Installation
------------

.. code-block:: bash

   pip install asyoulikeit

Or with uv:

.. code-block:: bash

   uv add asyoulikeit


The minimal example
-------------------

A Click command decorated with :func:`~asyoulikeit.report_output`
returns a :class:`~asyoulikeit.Reports` value. That's essentially all
there is to it.

.. code-block:: python

   import click
   from asyoulikeit import Report, Reports, TableContent, report_output


   @click.command()
   @report_output(reports={"users": "The users of the system."})
   def list_users():
       """List the users of the system."""
       data = (
           TableContent(title="Users")
           .add_column("name", "Name")
           .add_column("role", "Role")
           .add_row(name="Alice", role="admin")
           .add_row(name="Bob", role="user")
       )
       return Reports(users=Report(data=data))


   if __name__ == "__main__":
       list_users()

Run ``list_users`` attached to a terminal and it renders with the
``display`` formatter — borders, a title, legible rows. Pipe the output
into another program and it renders as TSV (``# Name\tRole`` header
then tab-separated values). Pass ``--as json`` and it emits structured
JSON. The handler is identical across all three modes; the choice of
format is a runtime concern the decorator handles.


The data model
--------------

Three classes carry all the state.

:class:`~asyoulikeit.TableContent` is a schema-validated table builder.
Add columns first, then rows. Every row must supply exactly the columns
that were declared — missing keys and unexpected keys both raise
:exc:`ValueError`, which catches typos early. ``TableContent`` also
holds optional ``title`` and ``description`` metadata that some
formatters display.

:class:`~asyoulikeit.TreeContent` is the hierarchical sibling — a
forest of nodes sharing a single column schema. See :ref:`tree-content`
below.

Both ``TableContent`` and ``TreeContent`` are implementations of
:class:`~asyoulikeit.ReportContent`. Future shapes (heterogeneous
trees, lists, description lists, …) will slot in as further subclasses
without changing the rest of the API.

:class:`~asyoulikeit.Report` is a frozen dataclass wrapping one piece
of ``ReportContent`` plus formatting preferences (``detail_level``,
``header``). These preferences are *suggestions* — the user can
override them from the command line.

:class:`~asyoulikeit.Reports` is a validated mapping of
``name → Report``. A command can return a single named report or
several; both are expressed by the same type. The names become keys in
JSON output and selectors for the user's ``--report`` flag.


Importance and detail level
---------------------------

Not every column is equally important. Some carry core identifying
information ("name", "id", "status"); others are supplementary
("notes", "last modified", "description"). Tag this with
:class:`~asyoulikeit.Importance` on columns, and if needed on
individual rows:

.. code-block:: python

   from asyoulikeit import Importance

   data = (
       TableContent()
       .add_column("name", "Name")                                    # ESSENTIAL (the default)
       .add_column("notes", "Notes", importance=Importance.DETAIL)
       .add_row(name="Alice", notes="Joined 2024-03")                 # essential row (the default)
       .add_row(name="Bob",   notes="Deprecated",
                _importance=Importance.DETAIL)
   )

When the user passes ``--essential``, DETAIL columns and DETAIL rows
drop out. When they pass ``--detailed``, everything stays. The default
is ``AUTO``, which each formatter resolves to whatever makes sense for
itself: TSV picks ``ESSENTIAL`` (pipe-friendly), JSON and display pick
``DETAILED`` (self-describing or human-facing).


Narrow terminals: wrapping and eliding
--------------------------------------

When a report is wider than the terminal, cells have to give somewhere.
Wrapping is right for prose, which reads on regardless of where the
lines break. It is wrong for an *atomic* value — a filename, an
address, a byte count — which has no meaningful break opportunities:
wrapping one makes the row twice as tall, and where the value contains
a space it splits across two lines in a way that reads as two separate
rows:

.. code-block:: text

   │ ├──        │ 0xFFFFFB3F │
   │ Copyf254   │            │

Declare an :class:`~asyoulikeit.Overflow` policy to say that a column's
values are atomic, and which of their ends is worth keeping:

.. code-block:: python

   from asyoulikeit import Overflow

   data = (
       TableContent()
       .add_column("filename", "Filename", header=True,
                   overflow=Overflow.ELIDE_MIDDLE)
       .add_column("load", "Load", overflow=Overflow.ELIDE_END)
       .add_column("notes", "Notes")                # WRAP, the default
   )

.. code-block:: text

   │ ├── Copyf254   │ 0xFFF… │
   │ └── Dircopy267 │ 0xFFF… │

``ELIDE_MIDDLE`` is usually the one to reach for on identifiers.
Filenames, paths and generated names tend to be distinguished by their
tails — ``Dircopy267`` and ``Dircopy254``, ``LIBRARY/AAOBJ`` and
``LIBRARY/Aform`` — so eliding from the end discards exactly the
characters that tell two neighbouring rows apart, while eliding from
the middle keeps both discriminating ends.

Three things are worth knowing about how the policy behaves:

* **It costs nothing until it is needed.** A value that fits is left
  alone, so declaring a policy does not change output on a wide
  terminal.
* **Only bounded-width output honours it.** TSV and JSON always carry
  the whole value — which is what makes eliding safe in the human
  output. Nothing is lost from what a pipeline reads.
* **An eliding column is the last to be squeezed.** The point of
  declaring the policy is that this column carries the discriminating
  information, so other columns give up their width first — up to the
  point where they would become unreadable themselves.

On a :class:`~asyoulikeit.TreeContent` header column the policy applies
to the node's name and leaves the tree art intact, since eliding a
connector would say something false about the shape of the tree.


Multiple reports
----------------

A single command can return more than one report. The command's
*default selection policy* — set by the ``default_reports=`` argument
to :func:`~asyoulikeit.report_output` — decides what happens when the
user doesn't pass ``--report``:

.. code-block:: python

   return Reports(
       users=Report(data=users_data),
       roles=Report(data=roles_data),
   )

There are three shapes for ``default_reports``. Pick the one that
fits the command's purpose:

* **Show everything by default** — ``default_reports=ALL_REPORTS``
  (also the default when the argument is omitted). Typical for
  reporting commands where every report is useful information and the
  user's opt-out is explicit. Users narrow the set with
  ``--report <name>`` (repeatable), drop everything with
  ``--no-reports``, or leave well enough alone to see it all.

* **Show nothing by default** — ``default_reports=None``. Typical for
  *action commands* whose reports are useful interactively but noisy
  when the command is orchestrated. Users opt into specific reports
  with ``--report <name>``, or grab the full set with
  ``--all-reports``.

* **Show a specific subset by default** — ``default_reports=["X", "Y"]``.
  For commands with a natural "most commonly wanted" subset. Users
  narrow further with ``--report``, suppress with ``--no-reports``, or
  override to everything with ``--all-reports``.

The names in ``default_reports`` must appear in the ``reports=``
declaration (or be admitted by an ``Ellipsis`` slot); a typo raises
:exc:`~asyoulikeit.ReportDeclarationError` at decoration time. Action
commands that never return a :class:`~asyoulikeit.Reports` (always
``None``) declare ``reports={}``.

.. _all-reports-by-default:

All-reports-by-default: the reporting-command shape
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   @click.command()
   @report_output(reports={
       "users":  "The system's users.",
       "groups": "The system's groups.",
   })
   def status():
       return Reports(
           users=Report(data=...),
           groups=Report(data=...),
       )

.. code-block:: console

   $ mytool status                         # users + groups
   $ mytool status --report users          # just users
   $ mytool status --no-reports            # nothing (rare; mostly for uniformity)

.. _no-reports-by-default:

No-reports-by-default: the action-command shape
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   @click.command()
   @click.argument("path", type=click.Path(exists=True))
   @report_output(
       reports={
           "summary":  "Totals of what was imported.",
           "rejected": "Rows that couldn't be imported.",
       },
       default_reports=None,
   )
   def import_data(path):
       do_the_import(path)                 # side effect
       return Reports(
           summary=Report(data=_summary_data()),
           rejected=Report(data=_rejected_data()),
       )

.. code-block:: console

   $ mytool import-data file.csv                            # silent — side effect only
   $ mytool import-data file.csv --report summary           # just the totals
   $ mytool import-data file.csv --all-reports              # everything

The handler runs in all three cases — only the rendering differs.
Drift detection and the :class:`~asyoulikeit.Reports` return-type
check still fire whenever the handler returns something, so a buggy
return isn't hidden by ``--no-reports``.

CLI selection flags are mutually exclusive
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``--report``, ``--no-reports``, and ``--all-reports`` are three
different ways to override the command's default selection policy.
Any combination of them is incoherent (you can't ask for "only users"
*and* "all of them" *and* "none of them"), so the decorator rejects
the combination with a ``click.UsageError`` at the wrapper boundary,
before the handler runs.


.. _tree-content:

Tree content
------------

When your data is hierarchical — a filesystem subtree, an organisation
chart, a syntax tree — return :class:`~asyoulikeit.TreeContent` from
your handler instead of ``TableContent``. The API is deliberately
parallel: you declare a column schema just like for a table, but every
*node* in the tree carries values matching that schema (homogeneous
columns across all nodes) and nodes form a parent/child hierarchy
instead of a flat list.

.. code-block:: python

   from asyoulikeit import (
       Importance, Report, Reports, TreeContent, report_output,
   )

   @click.command()
   @report_output(reports={"fs": "A filesystem subtree."})
   def list_usr():
       tree = (
           TreeContent(title="/usr")
           .add_column("name", "Name", header=True)
           .add_column("size", "Size")
           .add_column("kind", "Kind", importance=Importance.DETAIL)
       )
       usr = tree.add_root(name="/usr", size=0, kind="dir")
       bin_dir = usr.add_child(name="bin", size=4096, kind="dir")
       bin_dir.add_child(name="ls", size=150_296, kind="exec")
       bin_dir.add_child(name="cat", size=52_024, kind="exec")
       return Reports(fs=Report(data=tree))

Key differences from ``TableContent``:

* **Exactly one column must be marked** ``header=True``. Trees always
  need a label for each node; that label is what the display formatter
  draws alongside the ASCII-art connectors.
* **Repeatable roots.** ``add_root`` may be called once for a single
  tree, or many times to build a forest — useful when listing several
  independent top-level items.
* **Return the child, not the parent.** ``Node.add_child(...)`` hands
  back the newly-added child, so you descend by keeping a reference
  to each level you need. Siblings come from calling ``add_child`` on
  the shared parent again.
* **Per-node** :class:`~asyoulikeit.Importance` **tagging prunes whole
  subtrees**. A node marked ``DETAIL`` and *all its descendants* drop
  out under ``--essential``, because you cannot show a child while
  hiding its parent.

The three built-in formatters each render trees in the way best suited
to their audience:

* ``display`` lays ASCII-art connectors (``├──``, ``└──``, ``│``) into
  the first column of a Rich table, with the other columns lining up
  as usual. When the tree has only the header column *and* it's the
  only report being shown, the bordered-table chrome is dropped and
  the tree renders as bare ASCII — the connectors already convey the
  hierarchy, and the box adds no information. Multi-column trees and
  multi-report outputs keep the chrome (there's no other way to line
  up siblings or distinguish reports from one another).
* ``tsv`` flattens the tree in pre-order into fixed-width rows. Column
  one always carries the node's own header-column value (the leaf), so
  ``awk '{print $1}'`` yields the node name regardless of depth.
  Columns two onwards carry the full root-to-node path, one component
  per cell, left-packed and padded on the right with empty cells so
  every row has the same number of path cells. The leaf therefore also
  appears as the last non-empty path cell — intentional duplication
  that keeps the row human-readable as a full path while giving
  scripts a fixed leaf column. Path columns are labelled ``Path1``,
  ``Path2``, … in 1-based style so that ``PathK`` is "the node at
  depth K" (root = depth 1); the largest ``PathN`` in the header row
  reveals the tree's maximum visible depth. Non-header data columns
  follow the path cells with their usual labels.
* ``json`` emits a nested ``{"values": {...}, "children": [...]}``
  structure under a ``"roots"`` list, with ``metadata.kind = "tree"``
  distinguishing it from table-shaped output.


.. _scalar-content:

Scalar content
--------------

Some commands produce just a single value — a name, a number, an
address, a status string. Wrapping that in a transposed 1×1 table
reads as ceremony around a single cell, and the JSON output ends up
with ``"rows": [{"load": "00001900"}]`` where the consumer really
just wants ``"value": "00001900"``. Use :class:`~asyoulikeit.ScalarContent`
instead:

.. code-block:: python

   from asyoulikeit import (
       Report, Reports, ScalarContent, report_output,
   )

   @click.command()
   @report_output(reports={"title": "The disc image's title."})
   @click.argument("image")
   def disc_title(image):
       return Reports(title=Report(data=ScalarContent(
           value=_read_title(image),
           title="Disc title",
       )))

The three formatters render scalars differently, following what each
format's consumer actually wants:

* ``display`` emits ``Title: value`` on a single line when a title is
  set (``value`` alone otherwise), and the description — if any —
  dim/italic on the line below.
* ``tsv`` emits **just the raw value** by default. The dominant pipe
  use case (``disc title image | pbcopy``) wants the answer, not a
  commented label.
* ``json`` emits the usual ``metadata`` / ``value`` shape, with
  ``metadata.kind = "scalar"``. Consumers can read
  ``.reports.title.value`` via ``jq`` and get exactly what they want.

Header resolution for scalars (and every other content kind) is
three-tier: the explicit CLI ``--header`` / ``--no-header`` wins if
given; otherwise ``Report.header`` is consulted; otherwise the
formatter picks a per-content default. TSV's default for scalars is
``header=False`` (bare value); display's is ``True`` (labelled, if a
title is set). To force the labelled TSV form ``# Title\nvalue``,
pass ``header=True`` on the :class:`~asyoulikeit.Report`, or
``--header`` on the CLI.


Transposition
-------------

Sometimes a table reads better flipped: columns of values paired with
a label column on the left rather than a header row on top. Set
``present_transposed=True`` on ``TableContent`` and the ``display`` and
``tsv`` formatters will rotate the data at render time. JSON is
unaffected — it's a structural format, not a visual one, and surfaces
the intent via a ``metadata.present_transposed`` flag instead.


Styling
-------

The ``display`` formatter supports per-cell styling (foreground colour,
background colour, bold, italic). Attach a second ``TableContent`` to
your ``Report`` via the ``styles`` argument, with the same shape as the
data table but cell values as dictionaries keyed by
:data:`~asyoulikeit.STYLE_FOREGROUND_COLOR`,
:data:`~asyoulikeit.STYLE_BOLD`, and so on. TSV and JSON ignore styles;
display applies them via Rich.


Custom formatters
-----------------

The built-in ``display``, ``tsv``, and ``json`` formatters are
stevedore-loaded entry points under the ``asyoulikeit.formatter``
namespace. Third-party packages (or your own consumer project) can
register additional formatters the same way:

.. code-block:: toml

   # in the consumer's pyproject.toml
   [project.entry-points."asyoulikeit.formatter"]
   xml = "mypackage.xml_formatter:Formatter"

Subclass :class:`~asyoulikeit.Formatter` and implement the single
``format(reports) -> str`` method. After ``pip install`` / ``uv sync``
of the registering package, the new format name appears automatically
in the ``--as`` choices of every command decorated with
``@report_output``.


Declaring reports
-----------------

Every ``@report_output`` command **must** declare the report names it
produces via a ``reports=`` mapping of ``name → description``.
Omitting the declaration raises
:exc:`~asyoulikeit.ReportDeclarationError` at decoration time — there
is no back-compat fallback. This keeps the declaration honest and
lets the library validate ``--report`` values, generate help, and
run drift detection without guesswork.

.. code-block:: python

   from asyoulikeit import report_output, Report, Reports, TableContent

   @click.command()
   @report_output(reports={
       "summary":   "Site-wide totals",
       "courses":   "Per-course breakdown",
       "structure": "Module and section hierarchy",
   })
   def video_audit():
       """Audit the video library."""
       return Reports(
           summary=Report(data=...),
           courses=Report(data=...),
           structure=Report(data=...),
       )

The declaration drives four behaviours:

- **Decoration-time validation.** Non-identifier keys, non-string
  descriptions, and ``default_reports`` entries that refer to an
  undeclared name all raise :exc:`~asyoulikeit.ReportDeclarationError`
  at import time, not at first invocation.
- **Auto-documented** ``--help``. A ``Produces reports:`` block is
  appended to the command's help text, listing each declared name with
  its description.
- **Parse-time validation on** ``--report``. When the declaration is
  fully static (no ``Ellipsis`` slot), ``--report`` becomes a
  ``click.Choice`` — typos fail at parse with Click's list of valid
  values.
- **Runtime drift detection.** If the handler returns a
  :class:`~asyoulikeit.Reports` whose keys don't match the declaration
  (and no ``Ellipsis`` slot was declared, see below),
  :exc:`~asyoulikeit.ReportDeclarationError` is raised — catching the
  refactor-renamed-a-report-silently bug.

For action commands that always return ``None`` (no reports ever),
declare ``reports={}``: the declaration is empty, the ``Produces
reports:`` help block is suppressed, and any accidental future return
of a named report will trip drift detection.

Dynamic report names
~~~~~~~~~~~~~~~~~~~~

Some commands produce one report per input — a map-style command whose
report names are known only at runtime. Use ``Ellipsis`` (``...``) as a
key to declare "this command also produces dynamically-named reports":

.. code-block:: python

   @report_output(reports={
       ...: "One report per input YAML file; name is the file stem.",
   })
   def validate(files):
       return Reports({f.stem: Report(data=...) for f in files})

Mixed declarations work too — a fixed set of known names *plus* a
dynamic tail:

.. code-block:: python

   @report_output(reports={
       "overall": "Global summary across all files",
       Ellipsis:  "One report per validated file; name is the file stem.",
   })
   def validate_all(files):
       ...

Dynamic commands skip the ``click.Choice`` step on ``--report`` (the
valid set isn't knowable at decoration time), but the rest of the
benefits — validation, help, drift detection on the static subset —
still apply.

Hyphens on the command line
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Python identifiers can't contain hyphens, but CLI convention strongly
prefers them. ``asyoulikeit`` normalises ``--report`` values
automatically: ``--report monthly-sales`` resolves to the declared
``monthly_sales`` report.

Discovering reports: ``list-reports`` and ``describe-report``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Mirroring :ref:`formatter introspection <formatter-introspection>`,
asyoulikeit ships two ready-made command factories that the host CLI
drops into its group:

.. code-block:: python

   import click
   from asyoulikeit import (
       list_reports_command, describe_report_command,
   )

   @click.group()
   def cli(): ...

   cli.add_command(list_reports_command(),     name="list-reports")
   cli.add_command(describe_report_command(),  name="describe-report")

Both commands walk ``click.get_current_context().find_root()`` at
invoke time, so they find every command the host has registered
without per-command wiring. They are themselves ``@report_output``
commands, so they inherit ``--as / --report / --header / --detailed``
and render in any format:

.. code-block:: console

   $ mytool list-reports                       # report-producing commands
   $ mytool list-reports --detailed            # every command, reports or not
   $ mytool list-reports video-audit           # one command
   $ mytool describe-report video-audit courses
   $ mytool describe-report video-audit '<dynamic>'   # describe the Ellipsis slot

With no command argument, ``list-reports`` defaults to *essential*
detail and lists only the commands that actually produce named
reports. Commands that produce none — plain ``@click.command``
commands that aren't asyoulikeit-aware, and action commands declared
with ``reports={}`` — are shown with a single ``<no reports>`` marker
child and surface only under ``--detailed``. Naming a specific command
always shows it in full, whatever its kind.


.. _formatter-introspection:

Formatter introspection
-----------------------

Any CLI that lets users pass ``--as <format>`` eventually wants to
answer "which values are legal, and what does each one do?" asyoulikeit
exposes a primitive plus two command factories for exactly that.

The primitive :func:`~asyoulikeit.describe_formatter` reads the
formatter class's docstring (cleaned via :func:`inspect.cleandoc`,
without instantiating the class):

.. code-block:: python

   from asyoulikeit import describe_formatter, formatter_names

   for name in formatter_names():
       print(name, "—", describe_formatter(name, single_line=True))

Built on that primitive are two Click command factories,
:func:`~asyoulikeit.list_formatters_command` and
:func:`~asyoulikeit.describe_formatter_command`. Each returns a fully
assembled :class:`click.Command` decorated with ``@report_output`` —
so the meta-commands render in every format asyoulikeit already
supports. The host CLI picks the displayed command name on
``add_command``:

.. code-block:: python

   import click
   from asyoulikeit import (
       list_formatters_command, describe_formatter_command,
   )

   @click.group()
   def cli():
       pass

   cli.add_command(list_formatters_command(), name="list-formatters")
   cli.add_command(describe_formatter_command(), name="describe-formatter")

The list command returns a
:class:`~asyoulikeit.TableContent` of ``Name`` + one-line
``Description`` rows; the describe command takes a ``NAME`` argument
(restricted via ``click.Choice`` to the currently-registered
formatters) and returns a :class:`~asyoulikeit.ScalarContent` whose
``value`` is the full cleaned docstring and whose ``title`` is the
formatter name. Both inherit ``--as / --report / --header /
--detailed``, so:

- ``cli list-formatters --as json | jq`` gives you a machine-readable
  catalogue;
- ``cli describe-formatter tsv`` (TTY) shows ``tsv: <description>``;
- ``cli describe-formatter tsv --as tsv`` pipes the bare description
  (headerless — the TSV default for :class:`~asyoulikeit.ScalarContent`).

The factories are functions (not module-level command instances)
deliberately: ``formatter_names()`` and the ``click.Choice`` over it
are evaluated at factory-call time, so any formatter registered via
entry point before the host CLI builds its group is picked up without
a restart.


.. _testing:

Testing commands that use ``@report_output``
--------------------------------------------

Click's :class:`click.testing.CliRunner` captures stdout into a string
buffer. That buffer's ``isatty()`` returns ``False``, so the smart
default for ``--as`` lands on ``tsv``. If the test has assertions
about TSV output that's fine — you don't need to do anything. But if
your assertions depend on ``display``-mode layout (Rich borders,
titles, colour, wrapped text) or ``json`` structure, the captured
buffer's default doesn't exercise that path.

Two ways to get the format you want in tests:

**Pin the format on each invocation.** Pass ``--as <format>``
explicitly to the command under test:

.. code-block:: python

   def test_my_command_renders_the_title(runner):
       result = runner.invoke(cli, ["my-command", "--as", "display", "input"])
       assert "My Title" in result.output   # only visible in display mode

This is the clearest option when a handful of tests care about format;
the intent is visible at the call site and each test remains self-
contained.

**Set the environment variable.** The decorator consults
``ASYOULIKEIT_FORMAT`` before falling back to the TTY check, so a
session-wide, conftest-wide, or even test-wide override is one
line away:

.. code-block:: python

   # conftest.py — force display mode for every test in the suite
   import os
   os.environ["ASYOULIKEIT_FORMAT"] = "display"

   # or per-test with pytest's monkeypatch fixture
   def test_display_layout(runner, monkeypatch):
       monkeypatch.setenv("ASYOULIKEIT_FORMAT", "display")
       result = runner.invoke(cli, ["my-command", "input"])
       assert "My Title" in result.output

Precedence: an explicit ``--as`` on the command line still wins over
``ASYOULIKEIT_FORMAT``, so individual tests can opt out of a
suite-wide default without interference. An invalid value in the env
var fails fast with a clear error rather than silently falling back,
so typos don't quietly change which rendering path a test exercises.
