# Installation

## Prerequisites

Ensure you have the following installed:

| Tool | Version | Check |
|------|---------|-------|
| Python | ≥ 3.11 | `python --version` |
| Node.js | ≥ 20 | `node --version` |
| Git | any | `git --version` |

## Install

For development or evaluation, clone the repository and install dependencies from the root:

```bash
git clone https://github.com/dfinson/codeplane.git
cd codeplane
uv sync
cd frontend && npm ci
```

This matches the project's supported workflow: Python dependencies via `uv`, frontend dependencies via `npm ci`.

### Frontend (for UI)

Build the frontend before starting the full application:

```bash
cd frontend
npm run build
```

Or use the repo helpers from the root:

```bash
make install
```

## Environment Setup

```bash
cp .env.sample .env
```

Edit `.env` if you want remote access:

```bash
# Password for Dev Tunnels remote access
CPL_DEVTUNNEL_PASSWORD=your-secret-password
```

## Verify Installation

```bash
uv run cpl doctor
```

This checks that all dependencies are installed and configured correctly.

## Next Steps

→ [Quick Start](quick-start.md) — Launch the server and create your first job
