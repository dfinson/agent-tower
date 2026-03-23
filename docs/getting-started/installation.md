# Installation

## Prerequisites

Ensure you have the following installed:

| Tool | Version | Check |
|------|---------|-------|
| Python | ≥ 3.11 | `python --version` |
| Node.js | ≥ 20 | `node --version` |
| uv | latest | `uv --version` |
| Git | any | `git --version` |

!!! tip "Installing uv"
    If you don't have `uv`, install it with:
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

## Clone & Install

```bash
git clone https://github.com/dfinson/codeplane.git
cd codeplane
```

### One Command

```bash
make install
```

This runs `uv sync` (backend) and `npm ci` (frontend).

### Manual Steps

```bash
# Backend dependencies
uv sync

# Frontend dependencies
cd frontend && npm ci && cd ..
```

## Environment Setup

```bash
cp .env.sample .env
```

Edit `.env` if you want remote access:

```bash
# Password for Dev Tunnels remote access
CPL_TUNNEL_PASSWORD=your-secret-password
```

## Verify Installation

```bash
uv run cpl doctor
```

This checks that all dependencies are installed and configured correctly.

## Next Steps

→ [Quick Start](quick-start.md) — Launch the server and create your first job
