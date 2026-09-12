# 0004 — uv for Python version, virtualenv and lockfile

**Status:** Accepted · 2026-09-12

## Context

Code is written on Ubuntu (system Python 3.10) and runs on Windows. Both
machines must use the same Python version and the same dependency versions,
otherwise code that passes tests on one can break on the other. The standard
tools (`venv` + `pip`) create environments but don't install Python versions
and don't produce a cross-platform lockfile.

## Decision

Use **uv** for everything environment-related:

- `.python-version` pins the interpreter (3.12); uv downloads it if missing.
- `pyproject.toml` declares dependencies; Windows-only ones use an environment
  marker (`; sys_platform == "win32"`) so Linux skips them.
- `uv.lock` is a **universal lockfile**: one file, committed, resolving exact
  versions for both Linux and Windows.
- `uv sync` creates `.venv` and installs exactly what the lockfile says.

## Consequences

- One command sets up either machine identically.
- Contributors need uv installed (a single binary, one-line install).
- The project still follows standard `pyproject.toml` metadata, so moving back
  to pip later is possible.
