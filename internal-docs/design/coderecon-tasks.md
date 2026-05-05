# CodeRecon Tasks for CodePlane Integration

Two tasks for the coderecon project. Each is self-contained with all context
needed to implement.

---

## Task 1: Add `scaffold` as a Standalone Dispatch Tool

### What

Expose the existing `_build_scaffold` function as a daemon dispatch tool so
SDK clients can call `scaffold(repo, path)` to get a compact structural
outline of a single file.

### Why

CodePlane's agent tool provisioning needs per-file structural outlines.
Currently `_build_scaffold` is an internal helper only called by the
checkpoint pipeline. Without a dispatch entry, agents must use `recon` (which
returns ranked spans, not a file outline) or read the whole file.

### Where the code lives

- **`_build_scaffold`**: `src/coderecon/mcp/tools/files.py` line 84. Takes
  `(app_ctx, rel_path, full_path, *, include_docstrings, include_constants)`
  and returns a dict with `path`, `language`, `total_lines`, `indexed`,
  `imports`, `symbols`, `summary`.

- **Dispatch table**: `src/coderecon/daemon/dispatch.py`, function
  `_load_core_functions()`. Maps method name strings to core functions. Each
  core function has signature `(app_ctx: AppContext, *, <params>) -> dict`.

- **SDK framework adapters**: `src/coderecon/sdk/frameworks.py`, `_TOOL_DEFS`
  list. Each entry has `name`, `description`, `method`, `params`, `required`.

- **SDK client methods**: `src/coderecon/sdk/client.py`. Each dispatch method
  has a corresponding async method on the `CodeRecon` class that calls
  `self._tool_call(method, params)`.

### Implementation steps

1. **Create a `scaffold_core` wrapper** in `src/coderecon/mcp/tools/files.py`:

   ```python
   def scaffold_core(
       app_ctx: "AppContext",
       *,
       path: str,
       include_docstrings: bool = False,
       include_constants: bool = False,
   ) -> dict[str, Any]:
       """Scaffold a single file — returns structural outline."""
       full_path = app_ctx.repo_root / path
       if not full_path.is_file():
           return {"error": f"File not found: {path}"}
       return _build_scaffold(
           app_ctx, path, full_path,
           include_docstrings=include_docstrings,
           include_constants=include_constants,
       )
   ```

   The wrapper resolves `full_path` from `app_ctx.repo_root` + the relative
   `path` param, matching the pattern used by other core functions.

2. **Add to dispatch table** in `dispatch.py` `_load_core_functions()`:

   ```python
   from coderecon.mcp.tools.files import scaffold_core
   # ...in the return dict:
   "scaffold": scaffold_core,
   ```

3. **Add SDK client method** in `client.py`:

   ```python
   async def scaffold(
       self,
       repo: str,
       path: str,
       *,
       worktree: str | None = None,
       include_docstrings: bool = False,
       include_constants: bool = False,
   ) -> dict[str, Any]:
       return await self._tool_call("scaffold", {
           "repo": repo,
           "worktree": worktree,
           "path": path,
           "include_docstrings": include_docstrings,
           "include_constants": include_constants,
       })
   ```

4. **Add to `_TOOL_DEFS`** in `frameworks.py`:

   ```python
   {
       "name": "scaffold",
       "description": "Compact structural outline of a file — imports, symbols, line ranges.",
       "method": "scaffold",
       "params": {
           "path": {"type": "string", "description": "File path relative to repo root."},
           "include_docstrings": {"type": "boolean", "description": "Include docstrings.", "default": False},
           "include_constants": {"type": "boolean", "description": "Include constants.", "default": False},
       },
       "required": ["path"],
   },
   ```

5. **Tests**: Add a test in the appropriate test file that calls
   `scaffold_core(app_ctx, path="some/file.py")` against an indexed test
   repo and checks that the result has `path`, `symbols`, `imports` keys.

### Scope

This should not require changes to the NDJSON protocol, event bus, or
indexing logic. It's purely wiring an existing internal function to the
dispatch table + SDK surface.

---

## Task 2: Wire Indexing Progress Events Through EventBus

### What

The daemon's `wire_event_hooks` function is a placeholder. During initial
repo registration, the `on_index_progress` callback is `lambda *_: None` —
progress events are silently discarded. Wire the actual progress callback
through the `EventBus` so SDK clients receive `index.progress` events during
both initial indexing and re-indexing.

### Current state

- **Progress callback exists**: `src/coderecon/index/ops_init.py` line 49
  defines `on_index_progress: Callable[[int, int, dict[str, int], str], None]`
  with signature `(indexed, total, by_ext, phase)`.

- **Re-index already wires it**: `src/coderecon/daemon/dispatch.py` lines
  216-224 define `_on_progress` that calls `event_bus.emit_sync("index.progress", ...)`
  during `_handle_reindex`. This works.

- **Initial register does NOT wire it**: `src/coderecon/daemon/global_app.py`
  line 145: `await coordinator.initialize(on_index_progress=lambda *_: None)`.
  Progress is discarded during the first index of a newly registered repo.

- **EventBus infrastructure is ready**: `src/coderecon/daemon/event_bus.py`
  has `emit()` (async) and `emit_sync()` (for blocking code paths). The
  `wire_event_hooks` function (line 78) is called at stdio startup but
  currently only logs a debug message.

- **SDK event routing exists**: `src/coderecon/sdk/client.py` has
  `_event_router` that dispatches events by name. Clients can subscribe
  with `sdk.on("index.progress", callback)`.

### What needs to change

1. **`GlobalDaemon._activate_repo`** (global_app.py ~line 145): Pass a real
   progress callback instead of `lambda *_: None`. The callback needs access
   to the `EventBus`, which means either:
   - Store the `EventBus` reference on `GlobalDaemon` (set during stdio
     startup), or
   - Accept an `event_bus` parameter in `_activate_repo` / `activate_repo`

   The `_handle_reindex` pattern in dispatch.py shows the working approach —
   define a closure that calls `event_bus.emit_sync()`.

2. **`wire_event_hooks`** (event_bus.py): This can remain a simple wiring
   point. The real fix is (1) — making sure `_activate_repo` has access to
   an event bus at registration time. If the event bus isn't available yet
   (e.g. daemon starting up before stdio transport is ready), fall back to
   the no-op lambda.

3. **Event format**: Match the existing format from `_handle_reindex`:

   ```json
   {"event": "index.progress", "ts": 1714835000.0, "data": {"repo": "my-repo", "indexed": 45, "total": 200, "phase": "structural"}}
   ```

4. **File watcher re-index path**: Check whether `BackgroundIndexer` also
   discards progress events. If it calls `coordinator.initialize()` or a
   similar path without a progress callback, wire that too.

### What NOT to change

- The NDJSON protocol format — `index.progress` events already follow the
  `{"event": ..., "ts": ..., "data": ...}` pattern.
- The SDK client — it already routes events by name. No SDK changes needed.
- The `on_index_progress` callback signature in `ops_init.py` — it's fine
  as-is.

### Tests

- Test that registering a new repo emits at least one `index.progress` event
  on stdout.
- Test that the event contains `repo`, `indexed`, `total`, `phase` in `data`.
- Test that if no event bus is available (e.g. non-stdio usage), registration
  still succeeds silently.
