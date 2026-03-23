# CLI Reference

CodePlane provides the `cpl` command-line interface for managing the server.

## Usage

```bash
uv run cpl <command> [options]
```

## Commands

### `cpl up`

Start the CodePlane server.

```bash
uv run cpl up [options]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--remote` | Enable Dev Tunnels for remote access | disabled |
| `--dev` | Skip frontend build (backend-only development) | disabled |
| `--port PORT` | Server port | `8080` |
| `--password SECRET` | Tunnel authentication password | from `CPL_TUNNEL_PASSWORD` env var |

**Examples:**

```bash
# Basic local server
uv run cpl up

# Remote access with password
uv run cpl up --remote --password my-secret

# Development mode on custom port
uv run cpl up --dev --port 9090
```

On startup, the server:

1. Runs database migrations (Alembic)
2. Builds the frontend (unless `--dev`)
3. Starts the FastAPI server
4. Opens Dev Tunnels (if `--remote`)
5. Marks any previously-running jobs as failed (restart recovery)

### `cpl version`

Display the current CodePlane version.

```bash
uv run cpl version
```

### `cpl setup`

Run the interactive first-time setup wizard.

```bash
uv run cpl setup
```

Walks you through:

- Registering your first repository
- Selecting a default SDK
- Configuring preferences

### `cpl doctor`

Diagnose environment issues.

```bash
uv run cpl doctor
```

Checks for:

- Python version compatibility
- Node.js version compatibility
- Required dependencies
- SDK availability
- Git configuration

## Using Make Targets

The `Makefile` provides convenience targets:

| Target | Command |
|--------|---------|
| `make install` | `uv sync` + `cd frontend && npm ci` |
| `make run` | Build frontend + `cpl up --remote` |
| `make lint` | `ruff check` + `eslint` |
| `make format` | `ruff format` |
| `make typecheck` | `mypy` + `tsc` |
| `make test` | `pytest` (70% coverage) + `vitest` |
| `make ci` | All of the above |
| `make clean` | Remove build artifacts and caches |
