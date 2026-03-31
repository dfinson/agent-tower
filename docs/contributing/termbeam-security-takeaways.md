# TermBeam Security Takeaways for CodePlane

Reference: [TermBeam Security Page](https://dorlugasigal.github.io/TermBeam/security/)

TermBeam is a remote terminal tool with a thorough, user-facing security page.
CodePlane already has strong fundamentals. This document cross-references
TermBeam's security features against the **actual CodePlane codebase** (audited
2025-03-31) and identifies real gaps worth closing — both in code and
documentation.

---

## Audit Summary — What CodePlane Already Has

These items were **verified in code** and need no changes:

| Area | Status | Where |
|------|--------|-------|
| **Password hashing** | PBKDF2-HMAC-SHA256, 600k iterations, 16-byte salt | `backend/services/auth.py` |
| **Session tokens** | 512-bit `secrets.token_hex(32)`, 24h TTL, in-memory store | `auth.py` |
| **Cookie flags** | `httponly=True`, `samesite="lax"`, `secure` set dynamically via `_is_https_request()`, `max_age=86400`, `path="/"` | `auth.py` lines ~261-268 |
| **HTTPS detection** | Checks scheme, `X-Forwarded-Proto`, `Forwarded`, `Origin`/`Referer`, `.devtunnels.ms` suffix | `auth.py` lines ~205-230 |
| **Login rate limiting** | 5 attempts / 60s / IP, sliding window, `time.monotonic()` | `auth.py` lines ~52-66 |
| **Localhost auth bypass** | `127.0.0.1`, `::1`, `localhost` skip password (by design) | `auth.py` lines ~165-176 |
| **WebSocket auth** | `check_websocket_auth()` called before `ws.accept()`, validates cookie + localhost | `terminal.py` line ~167 |
| **Terminal resize bounds** | `isinstance(cols, int) and isinstance(rows, int) and 0 < cols <= 500 and 0 < rows <= 200` — silent drop on invalid | `terminal.py` lines ~211-213 |
| **Path traversal prevention** | Consistent `Path.resolve()` + `.is_relative_to()` pattern | `workspace.py`, `artifacts.py` |
| **File size limits** | Workspace reads 5 MB, voice uploads configurable, artifacts 100 MB | `workspace.py`, `voice.py`, config |
| **Voice MIME whitelist** | `ALLOWED_AUDIO_TYPES` set, codec suffix handling | `voice.py` |
| **Block dangerous bind** | `host == "0.0.0.0" and no_password` → `SystemExit(1)` | `cli.py` |
| **Block remote + no-password** | `--remote` with `--no-password` rejected | `cli.py` |
| **Auto-password for 0.0.0.0** | Generates password and logs warning when binding publicly without explicit password | `cli.py` |
| **Worktree isolation** | Per-job git worktrees, agents never touch main branch | `git_service.py`, SPEC §8 |
| **Approval system** | Hard-gated commands (merge/pull/rebase/reset), protected paths, full audit trail | `approval_service.py`, `permission_policy.py` |
| **CORS** | Restricts to `localhost:5173` (dev) + tunnel origin; `allow_credentials=True` | `app_factory.py` lines ~74-81 |
| **SSE auth** | Checked inline (not via middleware, avoiding SSE buffering) | `app_factory.py` lines ~83-105 |
| **SSE connection limit** | Max 5 concurrent SSE connections | `config.py` `RateLimitConfig` |
| **Default binding** | `127.0.0.1:8080` (localhost only) | `config.py` |
| **SPA path traversal** | `..` and `\x00` detected in SPA fallback handler | `app_factory.py` lines ~130-155 |

---

## Product / Code Changes — Actual Gaps

### P1 — High priority — ✅ All implemented

| # | Area | Status | Where |
|---|------|--------|-------|
| 1 | **HTTP security headers** | ✅ Implemented | `app_factory.py` — middleware sets `X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`, `Referrer-Policy`, `Cache-Control` on every response. CSP includes WS allowance for tunnel + Vite HMR in dev. |
| 2 | **WebSocket origin validation** | ✅ Implemented | `terminal.py` — `Origin` header checked against allowed CORS origins + localhost before `ws.accept()`. Cross-origin connections rejected with close code 1008. |
| 3 | **Cookie SameSite upgrade** | ✅ Implemented | `auth.py` — changed from `samesite="lax"` to `samesite="strict"`. |

### P2 — Medium priority — ✅ All implemented

| # | Area | Status | Where |
|---|------|--------|-------|
| 4 | **WS auth rate limiting** | ✅ Implemented | `auth.py` — `check_websocket_auth` now tracks failed attempts per IP with same 5/min sliding window as login. |
| 5 | **Upload magic-byte validation** | ✅ Implemented | `voice.py` — magic-byte signatures checked for WebM, Ogg, WAV, MP3, MP4 after data is read. Returns 415 on mismatch. |
| 6 | **CORS tightening** | ✅ Implemented | `app_factory.py` — narrowed `allow_methods` to specific verbs, `allow_headers` to `Content-Type`, `Authorization`, `Last-Event-ID`. |

### P3 — Low priority (nice-to-have)

| # | Area | Recommendation |
|---|------|----------------|
| 7 | **Periodic session cleanup** | Current lazy cleanup on token validation works fine. Optional: add a background task in `lifespan.py` to sweep expired sessions every 5 min. |
| 8 | **One-time share tokens** | No equivalent feature yet. Future note: if we add shareable access links, use single-use tokens with short TTL (TermBeam uses 5 min). |

### Removed from original list (already implemented)

These were flagged in the first pass but **already exist in the codebase**:

| Item | Why removed |
|------|-------------|
| Cookie `Secure` flag | Already set dynamically via `_is_https_request()` — checks scheme, `X-Forwarded-Proto`, `.devtunnels.ms` |
| Terminal resize bounds | Already validated: `0 < cols <= 500`, `0 < rows <= 200`, with type checks |
| Block dangerous flag combos | `cli.py` already blocks `0.0.0.0 + --no-password` and `--remote + --no-password` |
| Shell path validation | `CreateTerminalSessionRequest` accepts a `shell` param but the service detects the shell server-side; arbitrary paths are not user-controllable |

---

## Documentation Changes

TermBeam's security page is a model of clarity. CodePlane has **no dedicated
security documentation**. The SPEC.md covers security-relevant features
(permissions, worktree isolation, approvals) but there's nothing user-facing
that ties them together.

### D1 — New `docs/security.md` page — ✅ Created

Full security documentation page with: Overview, Threat Model, Safe Defaults,
Security Features (auth, permissions, worktree isolation, approvals, terminal,
uploads, headers, CORS, SSE), Dangerous Configurations, Best Practices, and
Vulnerability Reporting. Added to mkdocs nav.

### D2 — Add security callout to `docs/quick-start.md` — ✅ Done

Admonition note added after the remote access section.

### D3 — Add `SECURITY.md` to repo root — ✅ Done

Standard GitHub security policy file with supported versions and advisories link.

### D4 — Inline CLI warnings (already partially done)

`cli.py` already prints warnings for dangerous flag combos. Consider adding:
- Warning when `full_auto` is the default permission mode and a remote tunnel is
  active.

---

## Implementation Status

All P1, P2, and documentation items have been implemented. Remaining:

- **P3 #7** (periodic session cleanup) — optional, deferred
- **P3 #8** (one-time share tokens) — future feature note only
- **D4** (CLI warning for `full_auto` + remote tunnel) — nice-to-have, deferred
