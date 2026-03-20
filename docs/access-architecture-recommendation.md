# CodePlane.dev — Access & Auth Architecture Recommendation Memo

> **Date:** 2026-03-20
> **Status:** Proposal
> **Scope:** Access architecture for mobile-first product positioning

---

## 1. Executive Summary

- **CodePlane today is a single-operator, localhost-first application** with no multi-user model, no RBAC, and no user database. Auth is password-based with session cookies, enforced by Starlette HTTP middleware.
- **Remote access is exclusively via Tailscale Funnel**, which provides public HTTPS ingress and delegates auth to the built-in password system. There is no Tailscale Serve (private tailnet) mode — Funnel is used directly.
- **Tailscale on mobile is a documented product liability.** Android VPN conflicts (always-on VPN, MDM, carrier filtering) cause rapid disconnects and broken connectivity. This is not theoretical — it is a known, open issue in the Tailscale issue tracker with no resolution timeline.
- **The current auth middleware is cleanly separated from routes** — a major architectural advantage. Routes have zero auth awareness; auth can be swapped by changing middleware configuration alone.
- **No proxy-header trust infrastructure exists.** The app checks `x-forwarded-proto` for cookie security but does not validate `X-Forwarded-For` or accept identity headers from upstream proxies. Behind a reverse proxy, `request.client.host` becomes `127.0.0.1`, triggering unconditional localhost bypass — a security hole.
- **The recommended architecture is Hybrid (Option 5):** Tailscale remains available for dev/admin access; a reverse proxy (Pomerium or oauth2-proxy) provides the primary mobile/browser path with OIDC/SSO auth.
- **oauth2-proxy is the right first step** — it is simpler to deploy, sufficient for current single-operator use, and provides a clean upgrade path to Pomerium when multi-user/enterprise needs arise.
- **The minimum viable secure architecture requires approximately 4 code changes** in the backend and zero frontend changes, plus one infrastructure component (oauth2-proxy in front of the app).
- **Enterprise-grade SSO, audit logging, and RBAC are intentionally deferred** — they require a user model that doesn't exist yet. The proxy-first pattern keeps the door open.
- **The biggest risk in any public-ingress model is the localhost bypass.** If the app runs behind any reverse proxy, `request.client.host` will be `127.0.0.1` and auth is silently bypassed. This must be fixed regardless of which option is chosen.

**Final recommendation:** **Hybrid model with oauth2-proxy as the public ingress path, Tailscale retained for dev/admin, phased migration starting with the localhost-bypass fix.**

---

## 2. Current-State Findings from the Codebase

### 2.1 How CodePlane Is Currently Exposed

| Mode | Mechanism | Auth | File(s) |
|------|-----------|------|---------|
| **Default** | `127.0.0.1:8080` (localhost only) | None (localhost bypass) | `backend/config.py:76-78`, `backend/config.py:102-104` |
| **`--remote`** | Tailscale Funnel → public HTTPS | Password + session cookie | `backend/cli.py:100-112`, `backend/cli.py:168-195` |
| **`0.0.0.0` bind** | All interfaces | Warning emitted, no auth enforced | `backend/cli.py:155-165` |

There is **no** Docker/docker-compose, no nginx/caddy config, no separate reverse proxy. The FastAPI app serves both API and frontend (SPA + static assets) directly.

### 2.2 Current Auth Architecture

**File:** `backend/services/auth.py` (~277 lines)

| Component | Implementation | Notes |
|-----------|----------------|-------|
| Password storage | In-memory SHA-256 hash | Set at startup, no persistence |
| Session tokens | In-memory dict `{token: timestamp}` | 64-char hex, 24h TTL, no DB |
| Localhost bypass | `request.client.host in {"127.0.0.1", "::1", "localhost"}` | Unconditional — **breaks behind proxy** |
| Rate limiting | 5 attempts/60s per IP | In-memory, resets on restart |
| Cookie | `cpl_session`, httpOnly, SameSite=Lax, Secure if HTTPS | Correct cookie hygiene |
| Login page | Backend-rendered HTML (`backend/templates/login.html`) | No frontend route |
| WebSocket auth | Inline check in `backend/api/terminal.py:138-158` | Not middleware-based |
| SSE auth | Inline check in `backend/app_factory.py:93-98` | Bypasses middleware to avoid buffering |
| CORS | Dynamic origins (dev: `localhost:5173`, tunnel: Funnel URL) | `backend/app_factory.py:61-74` |

**No user model. No user table. No RBAC. No OAuth. No JWT. No API keys.** Auth is entirely password-based, single-operator, in-memory.

### 2.3 Frontend Auth Posture

**File:** `frontend/src/api/client.ts`

- All API calls use `fetch()` with no custom auth headers — relies entirely on browser cookie handling
- No login page in the React SPA — login is a backend-rendered HTML page
- No 401/403 redirect handling — errors bubble to callers
- **Fully compatible with proxy-based auth** — if a proxy sets cookies or handles auth upstream, the frontend requires zero changes

### 2.4 Critical Trust Assumption: Localhost Bypass

```python
# backend/services/auth.py
LOCALHOST_ADDRS = {"127.0.0.1", "::1", "localhost"}

def is_localhost(request: Request) -> bool:
    client = request.client
    if client is None:
        return False
    host = client.host
    return host in LOCALHOST_ADDRS
```

**This is a security-critical design decision that becomes a vulnerability behind any reverse proxy.** When nginx, Caddy, oauth2-proxy, Pomerium, or any other proxy forwards requests to the FastAPI app, `request.client.host` is `127.0.0.1` (the proxy's address). Auth is silently bypassed for all traffic.

**No `ProxyHeadersMiddleware` or trusted-proxy configuration exists.** There is no `--forwarded-allow-ips` in the uvicorn startup.

### 2.5 Abstraction Boundary Assessment

| Dimension | Status |
|-----------|--------|
| Auth middleware is separable from routes | ✅ Clean — `password=None` disables all auth |
| Routes are auth-agnostic | ✅ No auth decorators or dependencies on routes |
| Proxy header trust | ❌ Not implemented — must be added |
| WebSocket auth is in middleware | ❌ Inline — requires separate modification |
| SSE auth is in middleware | ⚠️ Partially — inline check for buffering reasons |
| User identity propagation | ❌ Not implemented — no concept of "who is calling" |
| Configurable auth mode | ❌ Binary: password or nothing |

### 2.6 Key Files Index

| File | Relevance |
|------|-----------|
| `backend/services/auth.py` | All auth logic: password, sessions, rate limiting, middleware |
| `backend/app_factory.py` | Middleware wiring, CORS, auth gate installation |
| `backend/cli.py` | `--remote`, tunnel lifecycle, password handling |
| `backend/config.py` | Server config, defaults, permission mode |
| `backend/api/terminal.py` | WebSocket auth (inline) |
| `backend/api/events.py` | SSE endpoint |
| `backend/templates/login.html` | Login page |
| `frontend/src/api/client.ts` | API client (no auth headers) |
| `frontend/src/App.tsx` | SPA routes (no login route) |
| `backend/models/db.py` | Database schema (no user/session tables) |
| `SPEC.md` §21 | Security model specification |
| `.env.sample` | `CPL_TUNNEL_PASSWORD=` only |
| `pyproject.toml` | No auth library dependencies |

---

## 3. Option-by-Option Comparison Table

| Option | Security Posture | Mobile Friendliness | Enterprise Readiness | Complexity | OSS/Self-Hosted Fit | Main Risks | Verdict |
|--------|-----------------|---------------------|---------------------|------------|---------------------|------------|---------|
| **1. Tailscale-only** | Strong (network-level identity) | **Poor** — VPN conflicts on Android/iOS, MDM blocks | Low (requires Tailscale on every device) | Low | Good (OSS client) | Mobile users can't reliably connect; product-blocking | **Reject for mobile path** |
| **2. Tailscale Funnel + app auth** | Medium (current state — password auth) | Good (HTTPS in browser) | Low (shared password, no SSO) | Already implemented | Good | Shared password doesn't scale; no per-user identity; localhost bypass vuln behind proxy | **Current default, insufficient for growth** |
| **3. Tailscale Funnel + reverse proxy auth** | Strong (OIDC/SSO at proxy) | Good (browser-based SSO) | High (SSO-ready) | Medium | Good (Pomerium/oauth2-proxy are OSS) | Funnel + proxy = two layers; Funnel dependency for transport | **Viable but unnecessarily coupled** |
| **4. Identity-aware proxy (no Tailscale for users)** | Strong (proxy enforces identity) | **Excellent** (standard browser auth) | High (SSO, audit, policy) | Medium-High | Good (Pomerium is OSS) | Requires DNS, certs, proxy infra; overkill now | **Target enterprise architecture** |
| **5. Hybrid** | Strong (dual path) | **Excellent** (proxy for mobile/browser) | High (SSO path exists) | Medium | Good | Two access paths to maintain; configuration surface | **Recommended** |
| **6. Cloudflare Access** | Strong (cloud ZTNA) | Excellent (clientless) | High (enterprise SSO) | Low | **Poor** (proprietary, traffic inspected by 3rd party) | Vendor lock-in; data sovereignty; not self-hostable | **Reject for OSS positioning** |

---

## 4. Deep Analysis of Each Viable Option

### Option 2: Tailscale Funnel + App Auth (Current State)

**What exists today:**
- `cpl up --remote` starts Tailscale Funnel, auto-generates or uses explicit password
- Tunnel watchdog monitors health every 10s, restarts on 2 consecutive failures
- Public HTTPS at `https://{machine}.{tailnet}.ts.net`
- Password auth enforced for non-localhost requests

**What works:**
- Zero infrastructure beyond Tailscale — one command to deploy
- HTTPS handled by Tailscale (free, automatic certs)
- Reasonable for single-operator, personal use

**What doesn't work for the stated goals:**
- Shared password is not per-user identity — no audit trail of who did what
- Password must be communicated out-of-band (printed to terminal, QR code)
- No SSO integration possible without significant new code
- Localhost bypass vulnerability if ever placed behind another proxy
- 24h session TTL with no refresh mechanism — sessions just expire

**Codebase impact of staying here:** Zero changes needed. This is status quo.

**Verdict:** Acceptable for `v0.x` personal use. Not viable for mobile-first product or any multi-user scenario.

### Option 3: Tailscale Funnel + Reverse Proxy Auth

**Architecture:**
```
Mobile Browser → Tailscale Funnel (HTTPS) → oauth2-proxy/Pomerium → CodePlane
```

**Analysis:** This couples Tailscale as a transport layer with a proxy as the auth layer. It works, but Tailscale Funnel adds latency (traffic routes through Tailscale relays) and complexity (two infrastructure components to manage) without clear benefit over just running the proxy with its own TLS.

**The only reason to keep Funnel in this path is if you don't have your own domain/DNS/certs.** Funnel provides free `*.ts.net` HTTPS — genuinely useful for ad-hoc dev. But for production, you'd want your own domain anyway.

**Verdict:** Transitional step — useful during migration but not a target state.

### Option 4: Identity-Aware Proxy (Pomerium, No Tailscale for Users)

**Architecture:**
```
Mobile Browser → Pomerium (HTTPS, OIDC auth) → CodePlane (localhost only)
```

**Security model:**
- Pomerium sits at the edge, terminates TLS, authenticates via OIDC (Google, GitHub, Azure AD, Okta)
- Every request is re-evaluated for identity and context (not just session start)
- Upstream app receives identity headers (`X-Pomerium-Jwt-Assertion`, `X-Pomerium-Claim-Email`)
- App trusts these headers when configured to run behind a trusted proxy

**Mobile UX:** Excellent — standard browser SSO flow, no VPN required, works on any phone.

**Enterprise credibility:** High — OIDC/SAML SSO, per-request authorization, audit logging built into Pomerium.

**Why not now:**
- Requires DNS (a real domain)
- Requires IdP registration (OAuth app in Google/GitHub/etc.)
- Requires cert management (ACME/Let's Encrypt, or Pomerium handles it)
- Overkill for single-operator dev use
- Pomerium's policy engine is powerful but adds configuration surface

**Verdict:** Target enterprise architecture. Defer to Phase 3.

### Option 5: Hybrid Model (Recommended)

**Architecture:**
```
┌─────────────────────────────────────────────────────────┐
│                    TRUST BOUNDARY                        │
│                                                         │
│  Path A: Dev/Admin (Tailscale)                         │
│  ┌──────────┐    ┌─────────────┐    ┌──────────────┐  │
│  │ Tailscale │───▶│ Tailscale   │───▶│  CodePlane   │  │
│  │  Client   │    │ Funnel/Serve│    │  (password   │  │
│  │ (laptop)  │    │             │    │   auth)      │  │
│  └──────────┘    └─────────────┘    └──────┬───────┘  │
│                                            │           │
│  Path B: Mobile/Browser Users              │           │
│  ┌──────────┐    ┌─────────────┐           │           │
│  │  Mobile   │───▶│ oauth2-proxy│───────────┘           │
│  │  Browser  │    │ (OIDC auth) │                       │
│  └──────────┘    └─────────────┘                       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**How it works:**
1. **Dev/admin path:** Tailscale Funnel (existing `--remote` mode) for power users who have Tailscale installed. Password auth, current behavior.
2. **Mobile/browser path:** oauth2-proxy in front of CodePlane, authenticating via OIDC (GitHub, Google, etc.). No VPN required. Works on any phone browser.
3. **CodePlane itself** doesn't need to know which path a request came from — it checks for either a valid session cookie OR a trusted proxy identity header.

**Why this is the best fit now:**
- **Preserves existing behavior** — Tailscale path is unchanged, zero regression risk
- **Adds mobile-first access** without requiring Tailscale on phones
- **oauth2-proxy is simple** — one Docker container, one OAuth app registration, works today
- **Frontend requires zero changes** — oauth2-proxy sets cookies, browser sends them
- **Backend requires ~4 surgical changes** (detailed in implementation plan)
- **Upgrade path to Pomerium is clean** — swap oauth2-proxy for Pomerium when policy/audit needs arise

**Risks:**
- Two access paths = two things to monitor
- Proxy trust headers must be validated (not just blindly trusted)
- localhost bypass must be fixed to avoid auth bypass behind proxy

### Option 6: Cloudflare Access (Rejected)

**Why rejected:**
- **Not self-hostable** — contradicts OSS/self-hosted positioning
- **All traffic decrypted on Cloudflare's infrastructure** — data sovereignty concern
- **High vendor lock-in** — DNS, tunnels, policies, and access logic all in Cloudflare
- **Proprietary** — not auditable, not forkable
- **Overkill for current scale** — designed for large org fleet management

**Honest advantage:** Easiest setup (Cloudflare Tunnel + Access dashboard), excellent mobile UX, free tier available. If CodePlane were a hosted SaaS rather than self-hosted tool, this would be a reasonable choice.

---

## 5. Final Recommendation

### Recommended Architecture: Hybrid with oauth2-proxy

**Trust Boundaries:**

```
UNTRUSTED                    TRUST BOUNDARY              TRUSTED
─────────────────────────────┬──────────────────────────────────
                             │
  Internet/Mobile            │   Internal / Localhost
  Browser                    │
       │                     │
       ▼                     │
  ┌──────────────┐           │
  │ oauth2-proxy │           │   ┌──────────────────┐
  │  (port 443)  │──────────────▶│   CodePlane      │
  │  OIDC auth   │           │   │  (127.0.0.1:8080)│
  └──────────────┘           │   │                  │
                             │   │  Trusts:         │
  ┌──────────────┐           │   │  - valid session │
  │ Tailscale    │           │   │    cookie        │
  │ Funnel       │──────────────▶│  - proxy identity│
  │ (*.ts.net)   │           │   │    header from   │
  └──────────────┘           │   │    127.0.0.1     │
                             │   └──────────────────┘
                             │
─────────────────────────────┴──────────────────────────────────
```

**Threat Model Notes:**

| Threat | Mitigation |
|--------|------------|
| Proxy identity header spoofing | Only trust headers from connections where `request.client.host` is localhost AND proxy mode is enabled in config |
| Localhost bypass behind proxy | Fix: disable localhost bypass when `proxy_mode=true` in config |
| Session cookie theft | httpOnly + Secure + SameSite=Lax (existing) |
| Brute-force login | Rate limiting (existing) + OIDC eliminates password for proxy path |
| Tailscale Funnel URL discovery | URL is stable MagicDNS, not secret — password auth required anyway |
| oauth2-proxy misconfiguration | Restrict allowed emails/domains; cookie secret rotation |
| SSE/WebSocket auth bypass | Extend proxy-header trust to inline auth checks |

**Why Rejected Options Were Rejected:**

| Option | Reason |
|--------|--------|
| **1. Tailscale-only** | Mobile users cannot reliably run Tailscale (VPN conflicts, MDM, carrier issues). Product-blocking for mobile-first proposition. |
| **3. Funnel + proxy** | Unnecessarily couples Tailscale transport with proxy auth. Adds latency through relay. No clear benefit over proxy with its own TLS. |
| **4. Pomerium-only** | Right target architecture but overkill for current scale. Requires DNS, IdP, certs, policy config that adds operational burden for single-operator use. |
| **6. Cloudflare Access** | Proprietary, vendor lock-in, not self-hostable, traffic inspected by third party. Contradicts OSS positioning. |

---

## 6. Concrete Implementation Plan

### Phase 1: Fix Localhost Bypass Vulnerability (Required Regardless of Option)

**Smallest first step. Do this now.**

**Problem:** If CodePlane ever runs behind any proxy (nginx, Caddy, oauth2-proxy, Pomerium, even a local dev proxy), `request.client.host` is `127.0.0.1` and all auth is bypassed.

**Changes:**

1. **`backend/config.py`** — Add `proxy_mode` config field:
   ```python
   @dataclass
   class ServerConfig:
       host: str = "127.0.0.1"
       port: int = 8080
       proxy_mode: bool = False  # When True, disable localhost bypass
       trusted_proxy_header: str = ""  # e.g., "X-Forwarded-User"
   ```

2. **`backend/services/auth.py`** — Modify `is_localhost()` to respect proxy mode:
   ```python
   def is_localhost(request: Request, *, proxy_mode: bool = False) -> bool:
       if proxy_mode:
           return False  # Never bypass auth when behind a proxy
       # ... existing logic
   ```

3. **`backend/cli.py`** — Add `--proxy-mode` flag to `cpl up`.

**Risk:** Low. Opt-in flag, no behavior change for existing users.
**Rollback:** Remove flag, revert to existing behavior.

### Phase 2: Add Proxy Identity Header Trust

**Changes:**

4. **`backend/services/auth.py`** — Add proxy-header authentication:
   ```python
   def is_proxy_authenticated(request: Request, *, trusted_header: str) -> bool:
       """Check if request has been authenticated by a trusted upstream proxy."""
       if not trusted_header:
           return False
       # Only trust proxy headers from localhost (the proxy itself)
       if request.client and request.client.host not in LOCALHOST_ADDRS:
           return False
       return bool(request.headers.get(trusted_header))
   ```

5. **`backend/app_factory.py`** — Wire proxy auth into middleware:
   ```python
   # In _auth_gate middleware:
   if proxy_mode and is_proxy_authenticated(request, trusted_header=trusted_proxy_header):
       return await call_next(request)
   ```

6. **`backend/api/terminal.py`** — Extend WebSocket auth to accept proxy headers:
   ```python
   def check_websocket_auth(*, client_host, cookies, headers=None, proxy_mode=False, trusted_header=""):
       if proxy_mode and headers and trusted_header and headers.get(trusted_header):
           if client_host and client_host in LOCALHOST_ADDRS:
               return True
       # ... existing logic
   ```

**Risk:** Medium. Must ensure header trust is only granted when request comes from localhost (the proxy), preventing header injection from external clients.
**Rollback:** Disable `proxy_mode` in config.

### Phase 3: Deploy oauth2-proxy (Infrastructure)

**No code changes required in CodePlane.** This is pure infrastructure.

1. Deploy oauth2-proxy (Docker container or binary) on the same machine
2. Configure:
   - Provider: GitHub or Google (whichever the operator uses)
   - Upstream: `http://127.0.0.1:8080`
   - Cookie secret: auto-generated
   - Allowed emails: operator's email
   - Pass headers: `X-Forwarded-User`, `X-Forwarded-Email`
3. Start CodePlane with `--proxy-mode --trusted-proxy-header X-Forwarded-User`
4. Point DNS (if available) or use direct IP:port to oauth2-proxy

**Minimum deployment:**
```yaml
# docker-compose.yml (example, not committed to repo)
services:
  oauth2-proxy:
    image: quay.io/oauth2-proxy/oauth2-proxy:latest
    ports:
      - "443:4180"
    environment:
      OAUTH2_PROXY_PROVIDER: github
      OAUTH2_PROXY_CLIENT_ID: <from GitHub OAuth app>
      OAUTH2_PROXY_CLIENT_SECRET: <from GitHub OAuth app>
      OAUTH2_PROXY_COOKIE_SECRET: <openssl rand -base64 32>
      OAUTH2_PROXY_UPSTREAMS: http://127.0.0.1:8080
      OAUTH2_PROXY_EMAIL_DOMAINS: "*"  # or specific domain
      OAUTH2_PROXY_PASS_USER_HEADERS: "true"
```

**Risk:** Requires OAuth app registration (GitHub/Google). 5-minute setup.
**Rollback:** Stop oauth2-proxy, start CodePlane without `--proxy-mode`.

### Phase 4 (Future): Upgrade to Pomerium

When multi-user, per-user policy, or enterprise SSO requirements arise:

1. Replace oauth2-proxy with Pomerium (single binary/container)
2. Configure Pomerium routes and policies
3. CodePlane code changes: none — same proxy header trust mechanism
4. Gain: per-request authorization, group-based policies, audit logging, device posture checks

### Phase 5 (Future): User Model in CodePlane

When CodePlane needs to know who is making requests (not just "is this request authenticated"):

1. Add `UserRow` to database
2. Extract user identity from proxy headers into request context
3. Associate jobs, events, approvals with user identity
4. Enable RBAC / permission scoping per user

This is a major feature, not a security change. The proxy-first architecture means it can be deferred until there's a product need.

### Migration Risks

| Risk | Mitigation |
|------|------------|
| Proxy header injection from external clients | Only trust headers when `request.client.host` is localhost |
| Existing Tailscale users lose access | Tailscale path is preserved, not removed |
| oauth2-proxy cookie conflict with `cpl_session` | Different cookie names, no conflict |
| OAuth provider outage blocks access | Tailscale path remains as backup |
| DNS not available for small deployments | oauth2-proxy works on IP:port, DNS optional for dev |

### Rollback Plan

Every phase is independently rollbackable:
- **Phase 1:** Remove `proxy_mode` config, revert `is_localhost()` changes
- **Phase 2:** Disable `trusted_proxy_header` in config
- **Phase 3:** Stop oauth2-proxy container, restart CodePlane without `--proxy-mode`
- **Phase 4:** Swap Pomerium back to oauth2-proxy (same upstream config)

---

## 7. Appendix

### A. Cited Sources

| Source | URL |
|--------|-----|
| Tailscale Serve docs | https://tailscale.com/docs/features/tailscale-serve |
| Tailscale Funnel docs | https://tailscale.com/docs/features/tailscale-funnel |
| Tailscale Android VPN conflict (GitHub #12850) | https://github.com/tailscale/tailscale/issues/12850 |
| Tailscale Android force-stop bug (GitHub #17190) | https://github.com/tailscale/tailscale/issues/17190 |
| Tailscale Android network switching (GitHub #17886) | https://github.com/tailscale/tailscale/issues/17886 |
| Pomerium vs oauth2-proxy (Pomerium) | https://www.pomerium.com/comparisons/nginx-oauth2proxy |
| Pomerium vs Cloudflare Access (Pomerium) | https://www.pomerium.com/comparisons/cloudflare-access |
| Cloudflare Access vs Tailscale vs Pomerium | https://www.pomerium.com/blog/cloudflare-access-vs-tailscale-vs-pomerium |
| Pomerium GitHub (OSS, Apache 2.0) | https://github.com/pomerium/pomerium |
| oauth2-proxy GitHub | https://github.com/oauth2-proxy/oauth2-proxy |
| oauth2-proxy installation docs | https://oauth2-proxy.github.io/oauth2-proxy/installation/ |
| FastAPI behind a proxy | https://fastapi.tiangolo.com/advanced/behind-a-proxy/ |
| Pomerium minimum deployment | https://www.pomerium.com/docs/get-started/fundamentals/core/get-started |
| Top 5 ZTNA OSS components | https://aimultiple.com/ztna-open-source |
| Tailscale Funnel security blog | https://tailscale.com/blog/introducing-tailscale-funnel |

### B. Repo Files Reviewed

| File | Purpose |
|------|---------|
| `backend/services/auth.py` | Complete auth service (~277 lines) |
| `backend/app_factory.py` | App factory, middleware wiring, CORS |
| `backend/cli.py` | CLI, `--remote`, tunnel lifecycle |
| `backend/config.py` | Configuration, defaults |
| `backend/api/terminal.py` | WebSocket endpoint + inline auth |
| `backend/api/events.py` | SSE endpoint |
| `backend/api/deps.py` | Dependency injection (DB session only) |
| `backend/models/db.py` | Database schema (no user tables) |
| `backend/templates/login.html` | Login page |
| `backend/mcp/server.py` | MCP server (stdio only) |
| `frontend/src/api/client.ts` | API client (no auth headers) |
| `frontend/src/App.tsx` | SPA routes (no login route) |
| `SPEC.md` §21 | Security model specification |
| `.env.sample` | Environment config template |
| `pyproject.toml` | Dependencies (no auth libraries) |
| `backend/tests/unit/test_auth.py` | Auth test suite |
| `backend/tests/unit/test_terminal_ws_auth.py` | WebSocket auth tests |

### C. Pomerium vs oauth2-proxy Decision Matrix

| Criterion | oauth2-proxy | Pomerium | Winner for CodePlane Now |
|-----------|-------------|----------|--------------------------|
| Setup complexity | Low (one binary + env vars) | Medium (config.yaml + IdP + DNS) | oauth2-proxy |
| Mobile browser support | Good (some redirect quirks reported) | Excellent (designed for mobile) | Pomerium |
| Enterprise SSO | OAuth2/OIDC, basic | OIDC/SAML, group policies, device posture | Pomerium |
| Policy granularity | Email allowlist only | Per-route, per-group, per-device, per-context | Pomerium |
| Audit logging | Minimal | Built-in | Pomerium |
| IdP requirements | OAuth app registration | OAuth app registration | Tie |
| Session/cookie on mobile | Functional, occasional quirks | Designed for it | Pomerium |
| Multi-app support | One upstream per instance | Multiple routes, service mesh | Pomerium |
| OSS license | MIT | Apache 2.0 | Tie |
| Time to first working deployment | ~15 minutes | ~45 minutes | oauth2-proxy |
| Upgrade path | Replace with Pomerium later | Already at target | Pomerium |

**For CodePlane today:** oauth2-proxy wins on simplicity. The path to Pomerium is clean and non-breaking.

### D. Tailscale's Role Going Forward

| Role | Recommendation |
|------|---------------|
| Primary user access mechanism | **No** — mobile reliability is a product blocker |
| Admin/developer path | **Yes** — convenient for operators who already have Tailscale |
| Implementation detail (transport) | **Conditionally** — useful for ad-hoc HTTPS without DNS, but not required |
| Removed from end-user path | **Yes** — end users should never need to install Tailscale |

Tailscale provides genuine value (device identity, encrypted mesh, zero-config HTTPS) but it cannot be the primary access mechanism for a mobile-first product. It should be an optional, parallel path.
