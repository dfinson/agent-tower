<p align="center">
  <img src="docs/images/logo.png" alt="CodePlane" width="200" />
</p>

<h1 align="center">CodePlane</h1>

<p align="center">
  <strong>Run and supervise coding agents — or just watch the ones you already use</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-pre--alpha-orange" alt="Status: Pre-alpha">
  <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python ≥3.11">
  <a href="https://github.com/dfinson/codeplane/actions/workflows/ci.yml"><img src="https://github.com/dfinson/codeplane/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/dfinson/codeplane"><img src="https://codecov.io/gh/dfinson/codeplane/branch/main/graph/badge.svg" alt="Coverage"></a>
  <img src="https://img.shields.io/github/license/dfinson/codeplane" alt="License">
</p>

---

> **Pre-alpha** — Under active development.

CodePlane is an orchestration and observability layer for coding agents. It launches agents headless for you, or mirrors native CLI sessions you're already running — same dashboard either way.

You bring your own CLI. CodePlane wraps the agent CLIs you already have (Claude Code, Copilot) and adds supervision, cost intelligence, structural review, and cross-job memory on top.

<p align="center"><img src="docs/images/screenshots/desktop/hero-dashboard.png" alt="CodePlane — dashboard with active jobs" width="800" /></p>

## Two Ways to Use It

### 1. Launch jobs through CodePlane (headless orchestration)

Write a prompt, pick a repo and model, hit go. The agent runs in an isolated worktree. Review the diff when it's done, merge or discard.

### 2. Mirror your native CLI sessions (zero workflow change)

Keep using `claude` or `copilot` in your terminal exactly as you do now. CodePlane auto-discovers running sessions via file-tailing, ingests them into the same pipeline, and gives you the full dashboard — cost tracking, trail, structural review — without you changing anything.

## What You Get

**Orchestration & supervision:**

- Start a task, walk away. Approve risky actions from your phone
- Remote access via Dev Tunnels or Cloudflare — supervise from anywhere
- Diff review with merge/PR/discard controls

**Intelligence layer:**

- **Decision trail** — What the agent did, why it did it, where it backtracked
- **Structural risk scoring** — Breaking vs. additive changes, coupling risks, merge confidence verdict
- **Cost attribution** — Every turn classified by activity; waste patterns surfaced across jobs
- **Workspace memory** — Per-repo knowledge that carries forward so each job starts smarter
- **Narrative review** — Answers "why was this change made?" with verified references, not hallucinated summaries

## Quick Start

> Requires Python 3.11+ and Git. Install and authenticate at least one agent CLI: [Claude Code](https://docs.anthropic.com/en/docs/claude-code) or [GitHub Copilot CLI](https://docs.github.com/en/copilot/managing-copilot/configure-personal-settings/using-github-copilot-in-the-cli).

```bash
pip install codeplane
cpl up                        # start server on localhost:8080
```

Open `http://localhost:8080`. Any native CLI sessions running in registered repos are picked up automatically. Or create a new job from the UI.

## CLI

```bash
cpl up                                       # start server
cpl up --remote                              # enable Dev Tunnels for remote access
cpl up --phone                               # shortcut for --remote
cpl up --remote --provider cloudflare        # use Cloudflare Tunnel
cpl up --port 9090                           # custom port
cpl down                                     # stop server
cpl restart                                  # stop and restart
cpl setup                                    # interactive first-time setup
cpl doctor                                   # diagnose environment issues
cpl info                                     # show connection details and QR code
cpl version                                  # show version
```

## Who This Is For

- **Solo devs using Claude Code or Copilot CLI** who want cost visibility and review tools without changing their workflow
- **Teams running many agent sessions** who need cost forensics and behavioral pattern analysis, not just a billing page
- **Reviewers of agent output** who need structural risk triage, not just a raw diff
- **Regulated environments** where AI-generated code requires decision provenance

## Documentation

Full docs: [dfinson.github.io/codeplane](https://dfinson.github.io/codeplane)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and conventions.

## License

[MIT](LICENSE)
