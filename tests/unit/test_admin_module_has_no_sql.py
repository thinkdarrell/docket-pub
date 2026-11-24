"""A pin on one module: ``src/docket/web/admin.py`` holds no SQL.

``ARCHITECTURE.md`` says nothing under ``src/docket/web/`` opens a
connection or executes a statement; the admin module broke that rule until
plan `admin-routes-call-services` moved its 27 transaction blocks into
``docket.services``. This file keeps the module as that plan left it. It
reads the module's source with ``ast`` (nothing is imported and no database
is touched) and fails when the module

- imports anything from ``docket.db`` or from ``psycopg2``, or
- calls anything named ``db``, ``db_cursor`` or ``execute``, as a bare name
  or as an attribute (``cur.execute(...)``, ``docket.db.db()``).

It is a pin on this one module, not the ``boundary-lint`` capability of
``docs/capabilities/index.md``, which would check every web module and is
not built. The four other modules row ``D7`` of ``docs/DEBT.md`` names are
not read here.

The fix, when this fails: move the statement into a function under
``src/docket/services/`` (reads in ``query.py``, writes in the service that
owns the table) and call that function from the route.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ADMIN_MODULE = Path(__file__).resolve().parents[2] / "src" / "docket" / "web" / "admin.py"

FORBIDDEN_MODULES = ("docket.db", "psycopg2")
FORBIDDEN_CALLS = ("db", "db_cursor", "execute")


def _is_forbidden_module(name: str) -> bool:
    return any(name == m or name.startswith(m + ".") for m in FORBIDDEN_MODULES)


def findings(source: str) -> list[str]:
    """One line per forbidden import or call in ``source``, in line order."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_module(alias.name):
                    found.append((node.lineno, f"line {node.lineno}: import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_forbidden_module(module):
                names = ", ".join(a.name for a in node.names)
                found.append((node.lineno, f"line {node.lineno}: from {module} import {names}"))
            else:
                # ``from docket import db`` names the same module another way.
                for alias in node.names:
                    if _is_forbidden_module(f"{module}.{alias.name}"):
                        found.append((node.lineno, f"line {node.lineno}: from {module} import {alias.name}"))
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if name in FORBIDDEN_CALLS:
                found.append((node.lineno, f"line {node.lineno}: a call of {name}()"))
    return [line for _, line in sorted(found)]


def test_the_admin_module_imports_no_database_helper_and_executes_no_statement():
    found = findings(ADMIN_MODULE.read_text(encoding="utf-8"))
    assert not found, (
        "src/docket/web/admin.py reaches the database itself; move each statement into "
        "docket.services and call it from the route (ARCHITECTURE.md, Layer map):\n  " + "\n  ".join(found)
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from docket.db import db, db_cursor\n", ["line 1: from docket.db import db, db_cursor"]),
        ("from docket import db\n", ["line 1: from docket import db"]),
        ("import docket.db\n", ["line 1: import docket.db"]),
        ("import psycopg2\n", ["line 1: import psycopg2"]),
        ("from psycopg2.extras import Json\n", ["line 1: from psycopg2.extras import Json"]),
        ("import psycopg2.extras as extras\n", ["line 1: import psycopg2.extras"]),
        ("def f():\n    with db() as conn:\n        pass\n", ["line 2: a call of db()"]),
        ("def f():\n    with db_cursor() as cur:\n        pass\n", ["line 2: a call of db_cursor()"]),
        ("def f(cur):\n    cur.execute('SELECT 1')\n", ["line 2: a call of execute()"]),
        ("import docket\n\ndef f():\n    return docket.db.db_cursor()\n", ["line 4: a call of db_cursor()"]),
    ],
)
def test_findings_names_each_forbidden_import_and_call(source, expected):
    assert findings(source) == expected


def test_findings_passes_a_route_that_asks_a_service():
    source = (
        "from docket.services import query\n"
        "from docket.dbx import thing\n"
        "import psycopg2x\n"
        "\n"
        "def page(meeting_id):\n"
        "    # db() and cur.execute( in a comment are not calls\n"
        "    executed = query.get_meeting_city_slug(meeting_id)\n"
        "    return executed\n"
    )
    assert findings(source) == []
