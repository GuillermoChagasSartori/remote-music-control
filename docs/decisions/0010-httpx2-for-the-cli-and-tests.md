# 0010 — httpx2 instead of httpx for the CLI and tests

**Status:** Accepted · 2026-09-13 · Changes the original plan, which named `httpx`

## Context

The CLI was built on `httpx`, as the project plan specified. When the test
suite was written, Starlette (the framework under FastAPI) turned out to have
moved its `TestClient` to `httpx2` — the maintained successor of `httpx`,
published by the Pydantic organisation with the same API. With only `httpx`
installed, the test client emits a deprecation warning, and a future Starlette
release will require `httpx2`.

The best way to test the CLI end to end is in-process: replace the CLI's HTTP
client with FastAPI's `TestClient`, which runs the real app without a network.
That only works if the CLI and `TestClient` use the **same** library — the CLI
catches `httpx.ConnectError`, which never matches an `httpx2` exception.

Options considered:

1. **Switch the CLI to `httpx2`** — one HTTP library everywhere.
2. Keep `httpx` for the CLI, add `httpx2` for tests only, and test the CLI
   against a real server started in a background thread — two libraries,
   slower and more complex tests.
3. Keep `httpx` and silence the warning — breaks when Starlette drops it.

## Decision

Option 1. The CLI imports `httpx2`; the API is the same, so the change was the
import name. The CLI creates its client in one function, `make_client()`, which
tests replace with `TestClient`.

## Consequences

- One HTTP library in the project; no deprecation warning.
- CLI tests run in milliseconds with no ports or threads.
- `httpx2` is younger (first release 2026) than `httpx`; it is marked
  production/stable and maintained by the team behind Pydantic, which FastAPI
  already depends on.
