# Getting Started

Welcome to CodePlane! This section will get you from zero to running your first coding job.

## What You'll Need

- **Python 3.11+** — Backend runtime
- **Node.js 20+** — Frontend build toolchain
- **[uv](https://docs.astral.sh/uv/)** — Python package manager (replaces pip/venv)
- **Git** — Version control
- A local Git repository to run jobs against

## Quick Overview

1. [**Install**](installation.md) — Clone the repo and install dependencies
2. [**Quick Start**](quick-start.md) — Launch the server and create your first job
3. [**Configure**](configuration.md) — Set up repositories, SDKs, and preferences

## How It Works

CodePlane runs as a local server on your machine. You interact with it through a web browser:

1. **Register a repository** — Point CodePlane at a local Git repo
2. **Create a job** — Write a prompt describing what you want the agent to do
3. **Watch it work** — The agent executes in an isolated Git worktree while you monitor
4. **Review & merge** — When the agent finishes, review the changes and merge or create a PR

The agent runs in a sandboxed worktree, so your working directory is never touched.
