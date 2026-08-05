# Architecture Spine Red-Team Review — Security & Data Integrity (Final Gate)

**Reviewed:** `ARCHITECTURE-SPINE.md` (2026-08-05 draft, AD-1…AD-32)
**Baseline:** `reviews/review-security-data.md` (F-1…F-7, O-1…O-5)
**Reviewer:** Independent adversarial red-team (fresh pass, no carried assumptions)
**Date:** 2026-08-05
**Verdict:** **PASS, WITH 2 NEW HIGH-CONFIDENCE GAPS TO CLOSE BEFORE PHASE 3/4**

All seven prior HIGH/MEDIUM-HIGH/MEDIUM findings and four of five lower-confidence observations are closed by explicit, testable invariants. A fresh adversarial pass surfaces two new architecture-level gaps (hash-chain/retention interaction, RLS enforcement-mode ambiguity) plus one unchanged carryover. None require redesign; all are invariant-tightening.

---

## Part 1 — Closure Verification

| # | Prior gap | Closing decision(s) | Status |
|---|---|---|---|
| 1 | Mutual worker/control auth bound to Pod UID/attempt/lease/scheduling record (F-1) | **AD-29**: audience-restricted identity bound to tenant, job, Pod UID, attempt ID, lease/fence, scheduling record; control plane verifies against authoritative K8s/scheduling records before accepting callbacks; worker also authenticates control plane first. **AC-5** tests forged Pod identity/stale tokens. | **CLOSED** |
| 2 | PostgreSQL RLS + transaction-scoped tenant binding (F-2) | **AD-30**: RLS enabled on tenant-owned tables, `tenant_id` bound transaction-locally before any repository op; port fails closed when context absent/mismatched; separate roles for cross-tenant maintenance. **AC-5** requires "RLS enabled." | **CLOSED*** (see N-2) |
| 3 | Signed cross-instance export + audited reduced-trust local restore (F-3) | **AD-23**: export is checksummed **and signed** (not optional); unsigned packages accepted only as explicit same-instance DR restore, marked reduced-trust, immutably audited; never trusted as cross-instance history. **AC-14** covers signed round-trip + reduced-trust audit. | **CLOSED** |
| 4 | Egress allowlist bound to credential scope (F-4) | **AD-7**: per-job egress derived only from declared repository/agent-provider bindings. **AD-9**: credential scope verified before mount and rejected if broader than declared resource. Both now derive from the same declared-resource source, closing the divergence vector. **AC-11** tests scope match. | **CLOSED** |
| 5 | Cryptographic event hash chain (F-5) | **AD-31**: per-job hash over versioned canonical encoding incl. prior hash; genesis value, canonicalization version, algorithm fixed in export schema; chain validated on replay/export/import/restore, failure surfaced not silently repaired. | **CLOSED*** (see N-1) |
| 6 | Local-mode credential isolation from agent code (F-6) | **AD-32**: explicitly states local-daemon trusts the OS user, disclaims sandboxing, documents best-effort containment only. Honest boundary, not a false parity claim. | **CLOSED** |
| 7 | Delegation revocation/commit-time race (F-7) | **AD-5**: delegation scope/expiry/revocation/version read under lock and validated inside the same transaction that commits the approval and audit event; cached authorization cannot authorize a commit. | **CLOSED** |
| O-1 | SSRF via metadata/link-local endpoints | **AD-19**: preview/server-side fetch denies loopback, RFC1918/ULA, link-local, cloud metadata, cluster-service, control-plane, operator-configured ranges, post-DNS-resolution and on every redirect, with DNS-rebinding resistance. **AD-7** mirrors this for worker egress. | **CLOSED** |
| O-2 | Cache poisoning via unverified fetch-to-cache path | **AD-8**: only the trusted acquisition adapter writes the cache; verifies registered remote identity and Git object integrity before atomic promotion; jobs mount read-only. **AC-4** tests cache poisoning explicitly. | **CLOSED** |
| O-4 | Cursor as cross-tenant existence oracle | **AD-12**: cursor is opaque, authenticated, bound to tenant/instance/stream scope/position; scope mismatch fails without revealing existence in another tenant. | **CLOSED** |
| O-5 | Torn SQLite backup of a live daemon | Backup §6: valid only after clean shutdown + WAL checkpoint, **or** via SQLite online backup API from one consistent snapshot including WAL state; copying a live DB/tree unsupported. **AC-12** requires atomic restore for both online and stopped-daemon backups. | **CLOSED** |
| O-3 | Retention tombstone accumulation cap | Not in this review's mandatory closure list. **AD-16** still has no cap on tombstone volume from rapid create/delete cycles. | **STILL OPEN (carryover, low priority)** |

\* Marked CLOSED against the original finding's literal text, but each introduces a new second-order gap detailed below — the invariant intended to close the issue is present, yet is not tight enough to prevent a compliant-but-diverging implementation from silently defeating it.

---

## Part 2 — New High-Confidence Findings

### N-1 — Event Hash Chain Has No Anchor Surviving Retention-Driven Truncation (HIGH)

**Location:** AD-31 vs AD-16
**Gap:** AD-31 mandates each event's hash include the "prior hash," rooted at a fixed "genesis value" per job, and requires full-chain verification on replay/export/import/restore. AD-16 mandates canonical lifecycle events are retained only 365 days by default, then tombstoned. Once the earliest events in a job's chain are deleted, the oldest *retained* event's `prior_hash` references a hash whose preimage record no longer exists. No invariant specifies a rolling checkpoint/root-hash anchor to be preserved at truncation time.
**Exploit / divergence:** Two compliant implementations diverge — one persists a checkpoint hash-of-truncation-point so verification can still prove "everything after here is untampered," the other simply drops old rows, silently invalidating chain verification for any job older than the retention window (verification either fails permanently for legitimate reasons, masking real tampering signals, or is quietly skipped for pre-retention-boundary jobs). Either outcome defeats the integrity guarantee AD-31 exists to provide for any long-lived job or a re-imported instance whose history spans a retention cycle.
**Recommendation:** Add an invariant that tombstoning the oldest event(s) of a job's chain must first commit a signed checkpoint record (last surviving hash + sequence + retention timestamp) in the same transaction as the tombstone, and that chain verification treats a valid checkpoint as an acceptable chain root equivalent to genesis.

---

### N-2 — RLS Mandate Does Not Exclude Table-Owner / BYPASSRLS Defeat (HIGH)

**Location:** AD-30
**Gap:** AD-30 says PostgreSQL "enables row-level security for tenant-owned tables and binds `tenant_id` transaction-locally." PostgreSQL RLS policies are silently skipped for the table owner and for any role with the `BYPASSRLS` attribute unless `FORCE ROW LEVEL SECURITY` is also set. No invariant mandates `FORCE ROW LEVEL SECURITY`, nor that the runtime application role be distinct from (and non-superuser/non-owner relative to) the migration/DDL role.
**Exploit / divergence:** A compliant implementation that runs the application under the same role that owns the tables (a common simplification, e.g. reusing the migration role for the API service) has RLS enabled in `pg_tables` metadata yet enforces nothing — every query returns cross-tenant rows regardless of the AD-30 session-variable binding, and no test surfaces this because "RLS enabled" is true. This is the same class of failure F-2 originally warned about, reintroduced one layer deeper.
**Recommendation:** Extend AD-30 (or AD-6) to require: the runtime application database role is distinct from the migration/owner role, holds no `BYPASSRLS` attribute, and every tenant-owned table has `FORCE ROW LEVEL SECURITY` set; add an AC-5 sub-test that connects as the runtime role and asserts a missing/mismatched tenant context yields zero rows, not just "RLS enabled" in schema metadata.

---

## Part 3 — New Medium-Confidence Finding

### N-3 — Audit Trail Has No Tamper-Evidence Chain Analogous to Canonical Events (MEDIUM-HIGH)

**Location:** AD-18 vs AD-31
**Gap:** AD-18 requires audit to be "immutable application data" recording actor, role, delegation, action, target, decision, reason, time — but this immutability is asserted only as a data-modeling property (no `UPDATE`/`DELETE` path in the service layer), not backed by any cryptographic chain, unlike AD-31's explicit per-job hash chain for canonical events. Audit is exactly the record that proves delegation revocation (AD-5), approval legitimacy, and cross-tenant maintenance actions (AD-30) actually happened as claimed.
**Exploit / divergence:** A compliant implementation stores audit rows in an ordinary mutable table protected only by omitting app-layer update/delete code paths. Direct SQL access (migration tooling, a bug, or a future admin feature) can silently alter or delete audit history with no detection mechanism — while canonical events would catch the equivalent tampering via AD-31. Two implementations diverge on whether audit gets any integrity backing at all, and neither violates the letter of AD-18.
**Recommendation:** Extend AD-18 (or fold audit into AD-31's chain family) to require audit records carry the same prior-hash/sequence chaining as canonical events, or are appended to the canonical event log itself as a reserved event class, so audit inherits AD-31's tamper-evidence and verification-on-restore guarantees.

---

## Part 4 — Carryover / Lower-Confidence, Track Only

| # | Area | Observation |
|---|---|---|
| O-3 | Retention tombstone volume | AD-16 still has no cap or throttling on tombstone accumulation from rapid create/delete cycles; unchanged from baseline review. Low urgency relative to N-1/N-2/N-3. |
| N-4 | Delegation re-delegation depth | AD-5 does not state whether a delegated approver can further delegate, or bound recursion depth/expiry-narrowing across a delegation chain. Minor; flag for Phase 4 tightening, not a blocking gap. |

---

## Summary

| Severity | Count | Items |
|---|---|---|
| Prior findings closed | 11 / 12 | F-1…F-7, O-1, O-2, O-4, O-5 |
| Prior findings still open (carryover) | 1 | O-3 |
| New HIGH | 2 | N-1 (chain/retention anchor), N-2 (RLS FORCE/role-separation) |
| New MEDIUM-HIGH | 1 | N-3 (audit tamper-evidence) |
| New LOW/track-only | 1 | N-4 (delegation re-delegation depth) |

**Verdict:** The spine has genuinely closed every mandatory gap from the prior review with specific, testable invariants (AD-29 through AD-32 plus targeted amendments to AD-5, AD-7, AD-8, AD-9, AD-12, AD-19, AD-23, and the backup section). This pass's new findings are second-order: the closing invariants for the RLS mandate and the event hash chain are each real but not airtight against a well-known implementation-level defeat (owner/BYPASSRLS bypass; retention-window chain truncation), and the audit trail was never given the same integrity treatment as canonical events despite carrying equivalent security weight. None require architectural redesign — each is a one- or two-sentence invariant tightening plus an AC amendment, consistent with the pattern that closed the original seven findings.

---

**Review path:** `_bmad-output\specs\spec-codeplane-kubernetes-and-local-daemon\architecture\reviews\review-security-data-final.md`
