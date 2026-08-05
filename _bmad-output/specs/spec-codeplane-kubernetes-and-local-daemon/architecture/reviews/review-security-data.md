# Architecture Spine Red-Team Review — Security & Data Integrity

**Reviewed:** `ARCHITECTURE-SPINE.md` (2026-08-05 draft)
**Reviewer:** Independent adversarial red-team
**Date:** 2026-08-05
**Verdict:** **CONDITIONAL PASS — 7 high-confidence gaps requiring closure before implementation**

---

## Methodology

Reviewed each invariant (AD-1 through AD-28) and acceptance criteria (AC-1 through AC-16) for:
1. Exploitable gaps between two independently-compliant implementations.
2. Security boundary violations achievable without breaking any stated rule.
3. Data integrity or consistency failures permitted by ambiguity.
4. Credential/secret exposure paths not explicitly closed.
5. Tenant isolation escape routes.

---

## Top Findings

### F-1 — Worker-to-Control-Plane Authentication Has No Specified Mutual Trust Bootstrap (HIGH)

**Location:** AD-3, AD-6, Security diagram
**Gap:** AD-3 says workers communicate through a "versioned worker protocol carrying … fencing token." AD-6 says workers get short-lived projected tokens. But no invariant specifies how the control plane authenticates the worker's identity *before* issuing a fencing token. Two implementations could diverge: one might use a Kubernetes TokenReview + Pod UID binding, another might accept any bearer token from the execution namespace.
**Exploit:** A compromised Pod in the tenant namespace could impersonate a worker, present a valid service-account token, and inject fabricated events for any job in that tenant.
**Recommendation:** Add an invariant requiring mutual authentication: worker must present Pod UID + attempt ID bound to the lease, and control plane must verify the Pod identity against the scheduling record before accepting any worker event.

---

### F-2 — Tenant Isolation Relies Solely on `tenant_id` Filtering — No Row-Level Enforcement Mandate (HIGH)

**Location:** AD-4, AD-10
**Gap:** AD-4 says "every durable row … carries `tenant_id`." AD-10 says PostgreSQL "owns" authoritative data. But no invariant mandates row-level security (RLS), connection-per-tenant, or query-middleware enforcement. Two implementations — one using application-layer filtering and one using database RLS — are both compliant, but the application-layer implementation is vulnerable to a single missed WHERE clause leaking cross-tenant data.
**Exploit:** A service bug or new query path omitting tenant context exposes another tenant's jobs, events, or secrets metadata.
**Recommendation:** Add a rule that either (a) PostgreSQL RLS is mandatory with session-variable tenant binding, or (b) the persistence port contract must enforce tenant context injection at the port boundary (not caller responsibility), with a conformance test that detects unscoped queries.

---

### F-3 — Export Signing Is "Optional" — Import Cannot Verify Provenance (HIGH)

**Location:** AD-23
**Gap:** Export is "checksummed, *optionally* signed." Import validates "signatures/checksums." If signing is optional, a compliant exporter may omit signatures. An importer that accepts unsigned packages has no provenance guarantee. Two compliant instances could create a situation where unsigned exports are accepted as trustworthy, enabling tampered event injection or history rewriting on import.
**Exploit:** Attacker intercepts an unsigned export bundle, modifies event payloads or policy, recalculates checksums, and imports into a target instance — the import succeeds because checksums are valid and signature is absent (not invalid).
**Recommendation:** Either (a) make signing mandatory for cross-instance export, or (b) add an invariant that unsigned imports require explicit operator acknowledgment with audit trail, and imported unsigned events are marked with reduced trust provenance.

---

### F-4 — No Egress Credential Scope Bound on Worker Network Policy (MEDIUM-HIGH)

**Location:** AD-7, AD-9, AD-19
**Gap:** AD-7 says workers have "default-deny network policy, explicit egress allowlists." AD-9 says credentials are "mounted as read-only files on memory-backed volumes." But no rule binds the egress allowlist to the credential scope. An implementation could allowlist `*.github.com:443` for Git access while the mounted credential (e.g., a PAT) has broader scope than the declared repository.
**Exploit:** Agent code running in the worker uses the mounted credential to access repositories or APIs beyond the declared job scope, because the network policy permits the destination and the credential permits the action.
**Recommendation:** Add a rule that egress allowlists must be scoped to the specific hosts/paths required by the declared repository and agent provider bindings for that job, not tenant-wide. Credential scope should be verified at mount time to match declared resource scope.

---

### F-5 — Event Sequence Integrity Has No Cryptographic Chain (MEDIUM-HIGH)

**Location:** AD-11, AD-12, AD-23, Backup/Recovery §3
**Gap:** Events have "immutable UUID … per-job monotonic sequence." Backup restore "validates event hashes." But no invariant specifies a hash chain or Merkle structure linking events. Two implementations could use different hashing strategies — one hashing payloads independently, another chaining them. Neither detects insertion or deletion of events within a valid sequence range after a database-level compromise.
**Exploit:** A database administrator (acknowledged as trusted in the security model, but relevant for compliance/audit) or a backup-restore bug silently drops or inserts events. Without chaining, the gap is undetectable by application logic.
**Recommendation:** Add an invariant that the event log maintains a per-job hash chain (each event includes the hash of its predecessor) so that any gap, insertion, or modification is detectable by consumers, export validation, and restore verification.

---

### F-6 — Local-Mode Credentials Have No Isolation From Agent Code (MEDIUM-HIGH)

**Location:** AD-2, AD-9, AD-25
**Gap:** AD-9's credential isolation rules (memory-backed volumes, read-only files, revocation on completion) are described in Kubernetes context. AD-2 says local mode uses "local agent credentials" and runs agents as local processes. No invariant prevents the agent process from reading `~/.codeplane` configuration, other job credentials, the SQLite database, or the user's SSH keys/Git credentials.
**Exploit:** A malicious agent (or injected tool) running locally reads `~/.codeplane/data.db`, extracts all job history, or reads credentials for other repositories configured in the same instance.
**Recommendation:** Add an invariant that local-mode execution must document and enforce a minimum credential boundary — at minimum, agents receive only their declared credentials via environment/files and must not have filesystem access to `~/.codeplane` internals or other jobs' workspaces. If enforcement is OS-user-trust-only, state that explicitly as an accepted risk with mitigation guidance.

---

### F-7 — Approval Delegation Revocation Timing Is Ambiguous During Active Use (MEDIUM)

**Location:** AD-5
**Gap:** Delegation is "expiring, revocable." But no rule specifies whether revocation is synchronous (blocks pending approval decisions) or eventual (a decision made milliseconds before revocation commits is valid). Two implementations could diverge: one checks delegation validity at decision time, another caches delegation grants.
**Exploit:** Operator revokes a compromised reviewer's delegation. The reviewer's cached session approves an agent action within the race window. The approval is recorded as valid because the implementation checked delegation at grant time, not decision time.
**Recommendation:** Add a rule that delegation validity is checked at decision commit time within the same transaction that records the approval, and any approval committed after revocation is retroactively invalid or prevented by serialized check.

---

## Additional Observations (Lower Confidence)

| # | Area | Observation |
|---|------|-------------|
| O-1 | Preview proxy | AD-19 says previews "deny private control networks" but doesn't specify SSRF protection against metadata endpoints (169.254.169.254, link-local). |
| O-2 | Cache poisoning | AD-8's "read-only bare-object cache" is tenant-scoped but no rule prevents a job from poisoning the cache if the fetch-to-cache path trusts remote content without verification. |
| O-3 | Retention tombstone abuse | AD-16 tombstones prevent deletion. No rule caps tombstone accumulation — an attacker triggering rapid create/delete cycles could bloat metadata. |
| O-4 | SSE cursor as oracle | AD-12's storage-local cursor could leak existence of events in other tenants if cursor values are globally sequential and observable. |
| O-5 | Local-mode backup atomicity | §6 says backup while "daemon is stopped." No rule prevents backup of a running daemon producing a torn SQLite state (WAL not checkpointed). |

---

## Divergence Risk Assessment

Two independently compliant implementations could create exploitable divergence in:

1. **Worker authentication** (F-1): One binds Pod UID, another accepts any namespace token → federation between them creates impersonation vectors.
2. **Tenant query enforcement** (F-2): Application-filter vs. RLS implementations have different failure modes under code evolution.
3. **Export trust** (F-3): Signed-exporter ↔ unsigned-importer creates a provenance gap neither side considers a violation.
4. **Event integrity** (F-5): Different hash strategies make cross-instance event verification non-interoperable.

These are not theoretical — they arise naturally when two teams implement the same spec without the tightening recommended above.

---

## Summary

| Severity | Count | Immediate action required |
|----------|-------|--------------------------|
| HIGH | 3 | F-1, F-2, F-3 — close before implementation begins |
| MEDIUM-HIGH | 3 | F-4, F-5, F-6 — close before Phase 3 (worker plane) |
| MEDIUM | 1 | F-7 — close before Phase 4 (OIDC/RBAC) |
| Observation | 5 | Track; address during implementation |

**Verdict:** The spine is structurally sound and covers an impressive breadth of concerns. However, the seven findings above represent specification ambiguities that permit two compliant implementations to diverge in security-critical ways. Tightening these invariants is straightforward and does not require architectural redesign.
