---
type: architecture-review
subject: ARCHITECTURE-SPINE.md
focus: AD-36, AD-37, cross-section coherence, full rubric pass
reviewer: copilot-cli
date: 2026-08-05
verdict: CONDITIONAL PASS — 6 concrete defects; 4 must be resolved before implementation planning
---

# Architecture Spine Review — CodePlane Kubernetes-Native and Local-Daemon

## Rubric Checklist Results

| Criterion | Result | Notes |
|---|---|---|
| All divergence points at feature altitude are fixed | **PASS** | AD-1, AD-2, AD-25, AD-27, AD-32 cover every known mode branch. |
| Every AD Rule is enforceable and prevents its stated divergence | **CONDITIONAL** | AD-36 prevention clause partially unenforced — see F-1. |
| Deferred contains no dangerous undecided ownership | **PASS** | Deferred items are legitimately operator choices or UX; all ownership is assigned in AD and port tables. |
| Current technology claims are grounded | **PASS** | Stack table (Python 3.12, FastAPI 0.136.3 locked, K8s 1.34-1.36, Helm 3.21/4.2, RWOP v1, VolumeSnapshot v1) is explicitly versioned with noted basis. Helm 4.2 is a future-leaning claim but flagged as a qualification range, which is acceptable. |
| Brownfield conventions are ratified | **PASS** | AD-27 ratifies all existing seams explicitly. |
| CAP-1 through CAP-24 are covered | **PASS** | Capability → Architecture Map covers all 24 caps; cross-referenced to governing ADs. |
| AD-1 through AD-35 are preserved | **PASS** | All 35 prior ADs present with no substantive narrowing. |
| AD-36 preserved and enforceable | **CONDITIONAL** | See F-1, F-2. |
| AD-37 preserved and enforceable | **CONDITIONAL** | See F-3, F-4. |
| Operational dimensions addressed | **CONDITIONAL** | See F-5, F-6. |

---

## Findings

### F-1 — AD-36: "never silently used" rule has an unresolved enforcement gap for `ensure_repo_indexed` timeout path (MUST FIX)

**Location:** AD-36 rule body; Migration Phase 3 compatibility gate; AC-19.

**Defect:** AD-36 states that missing, stale, incompatible, or corrupt generations are "never silently used" and that policy "deterministically waits for rebuild or explicitly proceeds without derived intelligence." AC-19 confirms this. However, neither the AD text nor the Scheduling/Cancellation/Cleanup section defines who owns the decision to proceed-without-intelligence: is it a per-job policy field, a tenant policy field, a site-wide default, or an operator choice? The Configuration convention table lists `defaults < installation < tenant < repository < job`, but no named policy key binds the `proceed-without-intelligence` path. This means the prevention clause — "policy deterministically waits or explicitly proceeds" — cannot be enforced from the spine alone; an implementation could silently degrade by treating absence of the key as "wait" when the indexer is stuck, blocking jobs indefinitely, or treating absence as "proceed" and silently omitting intelligence.

**Required fix:** Name the policy field (e.g., `indexWaitPolicy: Wait | ProceedWithout`) and its default, and assign it to at least one level of the configuration hierarchy in the spine. One sentence is sufficient; no full schema is needed.

---

### F-2 — AD-36: "base generations are tenant-shareable" is not guarded by a cross-tenant isolation rule (MUST FIX)

**Location:** AD-36 rule body; AD-30 tenant isolation; Durable Data Ownership table; AC-19.

**Defect:** AD-36 declares that "base generations are immutable and tenant-shareable." AD-30 declares that "storage paths derive from immutable tenant/resource UIDs, not labels" and that "UID-derived storage paths enforce tenant context." These two claims are in direct tension: if a base generation is tenant-shareable, it must live at a path reachable by multiple tenants, but all other storage paths are UID-scoped to one tenant. The spine never states whether shared base generations live in a distinct cross-tenant pool with its own access control, or whether tenants get private copies that are derived from a shared build but stored per-tenant. Without resolving this, the AD-30 prevention of "one omitted label/filter… exposing another tenant" is not satisfied for the index path.

**Required fix:** Clarify in AD-36 or AD-30 whether shared base generations (a) occupy a separate pool with separate RBAC distinct from per-tenant paths, or (b) are copied into per-tenant storage after build. If (a), add a sentence stating the RBAC boundary. If (b), remove the word "tenant-shareable" and state "independent per-tenant copies built once and distributed."

---

### F-3 — AD-37: conflict resolution descendant has no ownership authority or actor assigned (MUST FIX)

**Location:** AD-37 rule body (last paragraph); AC-20; CRD Lifecycle table (`CodePlaneSessionHandoff`).

**Defect:** AD-37 states that conflicting repository-context candidates "require an explicit resolution descendant." It does not state who may create that descendant (operator role, tenant_admin, any operator-role user, the job owner?), whether resolution is a Kubernetes admission-controlled action, or what CRD field/condition transitions out of `Conflict`. AC-20 references "explicit descendant resolution" but delegates entirely to AD-37. The CRD table lists `Conflict` as a valid condition for `CodePlaneSessionHandoff` but names no controller or API actor responsible for resolving it. This means conflict can be a durable blocking state with no defined exit, violating the requirement that every blocking condition has a recoverable path.

**Required fix:** State the authorized actor (at minimum "an operator-role or above user via the API") and the CRD/port operation that transitions `Conflict` to a successor generation. One sentence is sufficient.

---

### F-4 — AD-37: "stable creation sequence then package ID" selection is non-deterministic under cross-replica clock skew (SHOULD FIX)

**Location:** AD-37, second paragraph — package selection tie-breaking logic.

**Defect:** The tie-breaking rule for selecting the handoff package on replacement/follow-up attempts is "stable creation sequence then package ID." Creation sequence implies wall-clock or CRD creation timestamp order. Under cross-replica or Kubernetes API clock skew (documented as possible at ~1 second in etcd leader elections), two simultaneously published packages may have the same creation-time second, making sequence non-stable across replicas. Package UUID tie-breaking is stable but only applied as secondary. The word "stable" in "stable creation sequence" is aspirational, not mechanically defined. This creates a window where two replicas could select different handoff packages for the same replacement attempt.

**Required fix:** Replace "stable creation sequence" with a mechanically stable ordering — for example, "the package with the lexicographically highest monotonic `resourceVersion` within the lineage, with package UUID as final tie-break, evaluated atomically in the attempt controller before credential issuance." Alternatively, bind selection to a single controller with a leader Lease to eliminate the concurrency window.

---

### F-5 — Egress-unavailability and policy-denial are observability-separated in AD-7 and AD-18 but AC-18 lacks a metric name commitment (ADVISORY)

**Location:** AD-7 rule (EgressUnavailable); AD-18 metrics list; AC-18.

**Defect:** AD-7 names `EgressUnavailable` as a distinct condition and requires it be distinguishable from an "audited policy denial." AD-18 lists "egress denial" as a required metric/alert. AC-18 tests that the two are "distinguishable." However, no metric name or condition field is committed in the spine, so nothing prevents an implementation that uses a single generic `EgressError` counter for both, satisfying the text literally while failing the observability intent. For a feature with high operational impact (admission paused, in-flight quota held) this is a gap that would surface only in post-deployment diagnosis.

**Recommended fix:** Add the canonical metric name pair (e.g., `codeplane_egress_unavailable_total` vs. `codeplane_egress_policy_denied_total`) to AD-18 or the Stack table. This is advisory because the spine makes the intent clear; the gap is implementation-discipline rather than structural ambiguity.

---

### F-6 — Cross-section: "AD-31 callback epoch" advance sequence is specified in AD-31 and AD-13 but not in AD-34 takeover path (ADVISORY)

**Location:** AD-31 (callback epoch); AD-13 (claim replacement advances callback epoch); AD-34 takeover (no mention of callback epoch).

**Defect:** AD-31 states that "cancellation/replacement advances callback epoch before projecting CRD status, and takeover verifies both epochs before readiness." AD-34 defines takeover as a fenced sequence (old Pod terminated → attachment detached/CSI-fenced → exclusive mount proven → on-PVC head/epoch integrity verified → durable head epoch advances atomically before readiness). AD-34 does not name the callback epoch as a required verification step during takeover; it references "on-PVC head/epoch integrity" which covers the storage epoch but is silent on the callback epoch. If a stale worker Pod is still alive during a race between takeover and its last callback, the callback epoch check in AD-31 would block it, but the takeover sequence in AD-34 gives no ordering guarantee for that check.

**Recommended fix:** Add one clause to AD-34 takeover requiring that the callback epoch is advanced (matching AD-31 and AD-13 semantics) before the replacement gateway reaches readiness. This closes the cross-section gap without changing either AD's primary intent.

---

## Cross-Section Coherence Assessment

| Cross-section pair | Status | Note |
|---|---|---|
| AD-36 generation identity ↔ AD-23 export index transfer | Coherent | AD-23 correctly requires full AD-36 identity and integrity digest revalidation before optional cache transfer. |
| AD-37 handoff selection ↔ AD-12 at-least-once delivery | Coherent | Handoff packages go through ArtifactStoragePort, not SSE/cursor path; no ordering conflict. |
| AD-37 conflict preservation ↔ AD-11 preconditioned mutations | Coherent | Parent-generation and content-hash preconditions in AD-37 map correctly to AD-11 CAS semantics. |
| AD-36 GC lease ↔ AD-14 cleanup orchestration | Coherent | AD-36 "GC only after every durable reference and live lease is gone" is consistent with AD-14 ordered cleanup. |
| AD-36 shared base generation ↔ AD-30 tenant isolation | **GAP — F-2** | See F-2. |
| AD-37 conflict exit ↔ AD-5/AD-6 authorization | **GAP — F-3** | Authorized actor for conflict resolution descendant unspecified. |
| AD-31 callback epoch ↔ AD-34 takeover sequence | **GAP — F-6** | See F-6. |
| AD-36 proceed-without-intelligence ↔ Configuration convention | **GAP — F-1** | See F-1. |
| CRD table CodePlaneSessionHandoff ↔ AD-37 | Coherent | Conditions `Staged`, `Ready`, `Selected`, `Incompatible`, `Missing`, `Conflict` are enumerated in both. |
| AC-3 qualification criterion ↔ AD-33 through AD-37 governing ADs | Coherent | AC-3 binds AD-33–37 and validates combined installation. |
| AC-20 handoff/context survival ↔ AD-34 takeover and AD-37 durability | Coherent except F-6 | Core immutability chain intact; callback epoch gap is advisory. |

---

## Summary Verdict

The spine is structurally complete: all 37 ADs are present, all 24 CAPs are mapped, brownfield conventions are ratified, technology claims are versioned, the Deferred section contains no dangerous undecided ownership, and the dual-mode paradigm is coherent. AD-36 and AD-37 are substantive and close real divergence risks.

**Four concrete defects require resolution before implementation planning:**

1. **F-1** — `proceed-without-intelligence` policy has no named key or default in the configuration hierarchy. AD-36's prevention clause is unenforced.
2. **F-2** — "Tenant-shareable" base generations are not reconciled with AD-30's UID-scoped storage isolation. A cross-tenant data-access path is architecturally ambiguous.
3. **F-3** — Repository-context `Conflict` condition has no authorized actor or CRD operation defined for resolution exit. A durable blocking state with no defined exit violates recovery requirements.
4. **F-4** — Handoff package tie-breaking uses "stable creation sequence" which is not mechanically stable under cross-replica clock skew. Selection could diverge across controllers.

**Two advisory findings** (F-5, F-6) should be addressed before Phase 3 implementation to avoid operational diagnosis gaps and a subtle cross-section ordering hole in the storage takeover path.
