# 0005 — The MediaController port is asynchronous

**Status:** Accepted · 2026-09-12

## Context

The port's method signatures must be fixed before the Windows adapter exists,
because Phase 4 is supposed to swap adapters without changing anything above
them. The real adapter uses WinRT through the `winrt-*` packages, whose calls
return awaitable operations (e.g. `await manager.request_async()`). FastAPI
handlers are themselves `async`.

A synchronous port would force the Windows adapter to run async WinRT calls
from synchronous code — starting or borrowing an event loop inside a server
that already runs one, which is fragile and a known source of deadlocks.

## Decision

Every `MediaController` method is `async def`. The API layer `await`s them.

## Consequences

- The Windows adapter can `await` WinRT operations directly.
- The fake adapter's methods are `async` but never actually wait; that costs
  nothing.
- Synchronous callers (a quick script, a REPL) must use `asyncio.run(...)`.
- `pycaw` (volume) is synchronous; its calls are fast local COM calls, so the
  Windows adapter may call them directly from async methods. If they ever prove
  slow, they can be moved to a worker thread without changing the port.
