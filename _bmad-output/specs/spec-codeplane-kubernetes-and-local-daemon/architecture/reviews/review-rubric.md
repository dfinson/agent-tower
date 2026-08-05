# Architecture Spine Review — Rubric Pass

**Reviewed artifact:** `architecture/ARCHITECTURE-SPINE.md`  
**Review date:** 2026-08-05  
**Reviewers sources:** `SPEC.md`, `brownfield-constraints.md`, `mode-requirements.md`  
**Verdict:** ✅ **PASS with CONDITIONS** — the spine is structurally sound and internally consistent. Twelve findings below; none fatal. Three are MEDIUM severity and require resolution before the spine is promoted to `approved`; nine are LOW/INFO.

---

## Checklist Summary

| Criterion | Status | Notes |
|---|---|---|
| Fixes real divergence one level down | ✅ Pass | ADs address ports/adapters, worker boundary, scheduling, persistence, security |
| Each AD has enforceable Rule matching Prevents | ⚠️ Conditional | AD-12 Prevents/Rule mismatch (F-1); AD-11 Rule exceeds Prevents (F-2) |
| Deferred contains no hidden structural divergence | ⚠️ Conditional | Deferred omits worker image trust chain (F-3) |
| Named technology is current | ✅ Pass | Kubernetes 1.34–1.36, PostgreSQL 17, Python 3.12.x, React 18.3.x, Zustand 5.x are current at authoring |
| Brownfield conventions are ratified | ✅ Pass | AD-27 ratifies all conventions listed in brownfield-constraints.md; AD-25 ratifies local-only list |
| CAP-1 through CAP-24 all covered | ✅ Pass | Capability → Architecture Map enumerates all 24; see F-4 for CAP-11 mapping weakness |
| Every owned structural dimension decided/deferred/assumed | ⚠️ Conditional | Local scheduling recovery path is decided in text but not explicitly routed through the state machine (F-5) |
| Operational envelope complete | ✅ Pass with note | Envelope present and specific; `arm64` conditionality noted (F-6 INFO) |

---

## Findings

### MEDIUM

---

#### F-1 — AD-12 Prevents/Rule mismatch: "slow-client disconnect" not captured in Prevents

**Section:** AD-12 — At-least-once delivery converges by replay or snapshot  
**Criterion:** Each AD has an enforceable Rule whose effect matches its Prevents clause.

**Observation:**  
AD-12's `Prevents` lists "Silent stream loss, cross-job ordering assumptions, and non-convergent clients." The Rule additionally mandates that slow clients *are disconnected* to replay. Disconnecting a client is an affirmative behavior (not merely preventing silent loss) and there is no enforcement test in the AC table that directly targets slow-client eviction. AC-7 covers "slow-client overflow" only as one of several SSE convergence scenarios, so the enforcement path exists but is obscured.

More critically, `Prevents` does not state "unbounded backpressure or HOL blocking on slow consumers," which is what the disconnect rule actually prevents. A reviewer reading only `Prevents` cannot verify the Rule is proportionate.

**Fix:** Append to AD-12 `Prevents`: "; unbounded back-pressure or head-of-line blocking on slow consumers." Confirm AC-7 explicitly names "slow-client disconnect-and-replay" as a tested scenario.

---

#### F-2 — AD-11 Rule covers "message.delta ephemerality" not mentioned in Prevents

**Section:** AD-11 — State mutation and canonical event append are atomic  
**Criterion:** Rule is scoped to what Prevents claims.

**Observation:**  
AD-11's `Prevents` states "State/event dual-write gaps, reordered lifecycle evidence, and event vocabulary translation." The Rule adds a clause: "`message.delta` may remain ephemeral only when a complete canonical event follows." This is a legitimate constraint but it addresses a *different* risk — ephemeral streaming deltas being confused with durable events — which is not named in `Prevents`. If a future implementer only reads `Prevents` to understand scope, the delta-ephemerality constraint is invisible.

**Fix:** Append to AD-11 `Prevents`: "; ephemeral streaming deltas being persisted or delivered as authoritative canonical events."

---

#### F-3 — Deferred section omits worker container image trust chain

**Section:** Deferred  
**Criterion:** Deferred contains no hidden structural divergence.

**Observation:**  
The Deferred section correctly defers PostgreSQL HA operator, S3 vendor, ingress controller, OIDC provider, and Secrets Store CSI provider. It also defers "worker container image build pipeline, base distribution, and optional stronger sandbox runtime." However, it does not explicitly address how the control plane **verifies** the integrity or identity of a worker image before scheduling a job. This is a structural gap: AD-7 mandates workload hardening controls, but those controls can be undermined if an operator-supplied image is not verified. Neither the Deferred section nor any AD decides or defers "image signature/digest verification at admission." Without that decision, two legitimate implementations of AD-7 could diverge incompatibly — one enforcing signed digests via an admission webhook, one accepting any image.

**Fix:** Add one sentence to Deferred: "Worker image digest pinning and optional signature admission policy are operator-owned deployment decisions subject to AD-7; the control plane never substitutes its own image tag at scheduling time."

---

### LOW

---

#### F-4 — CAP-11 capability mapping lists only AD-18, missing AD-17 and AD-15

**Section:** Capability → Architecture Map, row "CAP-11 diagnostics"  
**Criterion:** Every CAP is fully covered.

**Observation:**  
CAP-11 intent requires diagnosing service, job, agent, repository, storage, and event-stream health using correlated logs, metrics, traces, events, and artifacts. AD-18 (observability) is the primary binding. However, AC-15 — which validates that AD-15 load + AD-17 SLO + observability together let you identify a failure "without direct DB access" — governs CAP-11's acceptance. The map entry should reference AD-15 and AD-17 alongside AD-18 so acceptance evidence traces correctly.

**Fix:** Change CAP-11 map row `Governed by` from `AD-18` to `AD-15, AD-17, AD-18`.

---

#### F-5 — Local-daemon interrupted-state recovery path is prose-only; state diagram is Kubernetes-only

**Section:** Scheduling, Cancellation, and Cleanup; AD-14  
**Criterion:** Every owned structural dimension decided/deferred/assumed.

**Observation:**  
The state diagram in "Scheduling, Cancellation, and Cleanup" shows `interrupted → queued: recovery policy`. This models the Kubernetes recovery path (lease expiry → re-queue). The local-daemon recovery path on process restart is governed by AD-2 and the `server_restart` requirement from brownfield-constraints.md, but the state machine does not show the local path. For local mode, `interrupted` should transition differently (resume in-place via `server_restart`, not re-queue via a lease). The diagram note says "These scheduler substates are execution records and do not replace the canonical shared JobState machine," which partially mitigates this, but the local recovery path remains undecided in the spine's structural terms.

**Fix:** Add a note alongside the state diagram: "In local-daemon mode, recovery from `interrupted` uses the `server_restart` resume path (brownfield-constraints.md) rather than re-queuing via a lease; this is an intentional mode difference decided in AD-2."

---

#### F-6 (INFO) — `arm64` conditionality in operational envelope references A-5 but A-5 itself lacks a verification step

**Section:** Kubernetes Packaging and Operational Envelope; Assumptions table  
**Criterion:** Operational envelope complete.

**Observation:**  
The operational envelope states "`arm64` support is conditional under Assumption A-5." A-5 says it is "supported only when every selected agent image has a qualified `arm64` build." The correction trigger is "`arm64` must be mandatory at first release or explicitly unsupported." This is fine, but there is no AC (acceptance criterion) that validates `arm64` build qualification or that the qualification check happens before a release claim is made. Without an AC, the assumption cannot be promoted or falsified in CI.

**Fix (INFO — no blocker):** Consider adding to AC-3 or as a new AC: "Before claiming `arm64` support, a qualification matrix confirms that all bundled agent adapter images have a published `arm64` digest."

---

#### F-7 — AD-4 assumption mixes tenancy topology with row-level filtering; "single-tenant simplification" not named

**Section:** AD-4 — Team tenant mapped to an execution namespace [ASSUMPTION]  
**Criterion:** Each AD has enforceable Rule matching Prevents.

**Observation:**  
AD-4's Rule states "every durable row, object key, cache key, request context, event, and audit record carries `tenant_id`." This is an enforcement-level claim. However, mode-requirements.md and SPEC.md both note tenancy model is open and A-1 explicitly labels this an assumption. For local-daemon mode, there is no multi-tenant use case: all data belongs to one user. The Rule does not acknowledge that local-daemon mode may omit `tenant_id` on internal records (since there is only one implicit tenant). If a developer reads AD-4 and implements `tenant_id` on every SQLite row in local mode, they are compliant with the letter but doing unnecessary work; if they omit it, a future reader will call it a violation. The intentional difference is not declared.

**Fix:** Append to AD-4 Rule: "Local-daemon implementations may use a single implicit tenant constant rather than storing `tenant_id` on each row, as a declared intentional difference per AD-1."

---

#### F-8 — AD-22 "contract migration" is referenced but "contract phase" definition absent in spine

**Section:** AD-22 — Expand-migrate-contract upgrades with bounded skew  
**Criterion:** Enforceable Rule.

**Observation:**  
AD-22 states "Rollback is supported until contract migration; afterward restore or forward-fix is required." The term "contract migration" is critical — it is the point of no return — but neither AD-22 nor the spine elsewhere defines what makes a schema change a "contract migration" (as opposed to an expand or migrate step). Without this, the rollback gate cannot be enforced in CI or a release checklist.

**Fix:** Add to AD-22 Rule: "A contract migration is one that removes or changes the meaning of a column, table, or object key that the previous release reads; it must be labeled as such in the migration metadata and triggers an explicit release gate in AC-13."

---

#### F-9 — AC-9 references AD-13 but should reference AD-14 for Kubernetes interruption recovery

**Section:** Architecture Acceptance Criteria, AC-9  
**Criterion:** AC-to-AD traceability.

**Observation:**  
AC-9 reads: "Graceful local CLI shutdown pauses sessions and startup resumes in place with `server_restart`; Kubernetes worker/control/node interruption yields explicit recoverable or terminal evidence. Governing decisions: AD-2, AD-13, AD-14."

AD-13 governs fenced lease scheduling; AD-14 governs cancellation and cleanup. Interruption evidence and recovery are primarily AD-14's domain. AD-13 is not wrong (the fencing mechanism is how duplicate workers are prevented on recovery), but the current ordering lists AD-13 before AD-14, implying scheduling primacy over cleanup. This is not harmful but is misleading for implementers.

**Fix:** Reorder to `AD-2, AD-14, AD-13` in AC-9 Governing decisions.

---

#### F-10 — Consistency Conventions table omits idempotency key scoping for local-daemon mode

**Section:** Consistency Conventions, "Idempotency" row  
**Criterion:** Brownfield conventions ratified.

**Observation:**  
The Idempotency row states "Mutating client commands accept an idempotency key scoped to actor/action/target; worker writes key by attempt/event ID." In local-daemon mode there is no multi-worker race, but idempotency keys are still a client-side contract. The convention is silent on whether local mode enforces deduplication at the persistence layer or at the in-process bus. brownfield-constraints.md requires canonical event atomicity and correct ordering, so the convention is consistent, but a reader implementing local mode may skip idempotency enforcement thinking it is Kubernetes-only.

**Fix (INFO):** Add parenthetical to the row: "(both modes enforce deduplication; local mode may use SQLite UNIQUE constraint; Kubernetes mode uses a distributed idempotency table or advisory lock)."

---

#### F-11 — AD-3 worker protocol content (job ID, attempt ID, locality, fencing token) not cross-referenced from AD-13

**Section:** AD-3; AD-13  
**Criterion:** Decisions at one level down that reference each other are linked.

**Observation:**  
AD-3 names the worker protocol payload: "job ID, attempt ID, execution locality, and fencing token." AD-13 defines how the fencing token is generated and validated ("monotonically increasing fencing token … every worker write must present the current attempt and fence"). The two ADs are complementary but neither cross-references the other, so an implementer reading only AD-13 might omit the execution locality claim, and one reading only AD-3 might not know fencing token lifecycle rules.

**Fix (INFO):** Add to AD-3 Rule: "The fencing token lifecycle is governed by AD-13." Add to AD-13 Rule: "The worker protocol structure carrying the fence is defined in AD-3."

---

#### F-12 — "Supervised" default policy named in Consistency Conventions but not in any AD Prevents/Rule

**Section:** Consistency Conventions, "Configuration" row; SPEC.md §Constraints  
**Criterion:** Brownfield conventions ratified.

**Observation:**  
The Consistency Conventions table includes: "default policy is `supervised`." brownfield-constraints.md and SPEC.md §Constraints both mandate the `supervised` default. This is a brownfield load-bearing guarantee. However, no AD has a Rule that enforces the `supervised` default as an invariant. AD-5 governs authorization; AD-20 governs secrets; neither mentions policy preset. If a developer implements a Kubernetes configuration that ships with `permissive` as the default, no AD will catch it — only the conformance suite (AC-1 references it via AD-27 transitively).

**Fix:** Add to AD-27 Rule: "The default action-policy preset is `supervised` in both modes; shipping an alternative default requires an intentional-difference contract."

---

## Structural Dimension Coverage Audit

| Dimension | Decided | Deferred | Assumed | Status |
|---|---|---|---|---|
| Ports/adapters composition root | AD-1 | — | — | ✅ |
| Local-daemon autonomy | AD-2 [ADOPTED] | — | — | ✅ |
| Agent execution isolation | AD-3, AD-7 | — | — | ✅ |
| Tenancy boundary | AD-4 [ASSUMPTION] | — | A-1 | ✅ (see F-7) |
| Identity/OIDC/roles | AD-5 | — | — | ✅ |
| Service identities | AD-6 | — | — | ✅ |
| Repository/workspace ports | AD-8 | — | — | ✅ |
| Credential JIT lifecycle | AD-9 | — | — | ✅ |
| Durable data ownership | AD-10 | — | — | ✅ |
| Atomic event/state writes | AD-11 | — | — | ✅ (see F-2) |
| Event delivery / replay | AD-12 | — | — | ✅ (see F-1) |
| Scheduling/fencing | AD-13 | — | — | ✅ |
| Cancellation/cleanup | AD-14 | — | — | ✅ |
| Scale envelope | AD-15 [ASSUMPTION] | — | A-2 | ✅ |
| Retention classes | AD-16 [ASSUMPTION] | — | A-3 | ✅ |
| Availability/SLO | AD-17 [ASSUMPTION] | — | A-4 | ✅ |
| Observability/audit | AD-18 | — | — | ✅ |
| Ingress/transport | AD-19 | — | — | ✅ |
| Secret store/rotation | AD-20 | — | — | ✅ |
| Helm/OCI packaging | AD-21 | — | — | ✅ |
| Schema upgrade/rollback | AD-22 | — | — | ✅ (see F-8) |
| Export/import manifest | AD-23 | — | — | ✅ |
| Repository/ref ownership | AD-24 | — | — | ✅ |
| Local-only capability treatment | AD-25 [ADOPTED] | — | — | ✅ |
| Migration phases | AD-26 | — | — | ✅ |
| Brownfield conventions | AD-27 [ADOPTED] | — | — | ✅ (see F-12) |
| Acceptance evidence | AD-28 | — | — | ✅ |
| Worker image trust chain | — | ❌ missing | — | ⚠️ F-3 |
| Contract migration definition | — | — | ❌ implicit | ⚠️ F-8 |

---

## CAP Coverage Check

| CAP | Spine coverage | Complete? |
|---|---|---|
| CAP-1 | AD-1, AD-2, AD-21, AD-26 | ✅ |
| CAP-2 | AD-1, AD-11, AD-27, AD-28 | ✅ |
| CAP-3 | AD-8, AD-9, AD-24 | ✅ |
| CAP-4 | AD-3, AD-7 | ✅ |
| CAP-5 | AD-10, AD-11, AD-16 | ✅ |
| CAP-6 | AD-9, AD-20, conventions | ✅ |
| CAP-7 | AD-4, AD-5, AD-6 | ✅ |
| CAP-8 | AD-13, AD-14, AD-15 | ✅ |
| CAP-9 | AD-11, AD-12 | ✅ |
| CAP-10 | AD-5, AD-19, AD-25 | ✅ |
| CAP-11 | AD-18 (AD-15, AD-17 missing from map — F-4) | ⚠️ |
| CAP-12 | AD-13, AD-14, AC-9 | ✅ |
| CAP-13 | AD-21, AD-22, AD-26 | ✅ |
| CAP-14 | AD-23, AD-24 | ✅ |
| CAP-15 | AD-3 through AD-9, AD-19, AD-20 | ✅ |
| CAP-16 | AD-21, AD-22 | ✅ |
| CAP-17 | AD-8, AD-9 | ✅ |
| CAP-18 | AD-7, AD-13 through AD-15 | ✅ |
| CAP-19 | AD-10, AD-16, AD-17, AD-22 | ✅ |
| CAP-20 | AD-4 through AD-6 | ✅ |
| CAP-21 | AD-15, AD-17 through AD-22 | ✅ |
| CAP-22 | AD-2, AC-9 | ✅ |
| CAP-23 | AD-2, AD-8, AD-25 | ✅ |
| CAP-24 | AD-2, AD-10, AD-25 | ✅ |

All 24 capabilities are bound; CAP-11 has a minor map gap (F-4).

---

## SPEC / Brownfield / Mode-Requirements Reconciliation

| Normative source | Spine coverage | Gap? |
|---|---|---|
| brownfield-constraints.md — `supervised` default | Consistency Conventions, not an AD Rule | F-12 (LOW) |
| brownfield-constraints.md — `server_restart` pause/resume | AD-2, AC-9 | ✅ |
| brownfield-constraints.md — TraceForge envelope / no snake_case | AD-11, AD-12, Consistency Conventions | ✅ |
| brownfield-constraints.md — transport keepalives ≠ session.heartbeat | AD-12, Consistency Conventions | ✅ |
| brownfield-constraints.md — native mirroring as product capability | AD-25 | ✅ |
| brownfield-constraints.md — SQLite / local filesystem | AD-2, AD-10 | ✅ |
| brownfield-constraints.md — no Kubernetes/cloud requirement for local | AD-2 | ✅ |
| mode-requirements.md — intentional differences declared | Local-Only and Kubernetes-Analogue table | ✅ |
| mode-requirements.md — conformance matrix | AD-28, AC-1 | ✅ |
| mode-requirements.md — open architectural decisions deferred | Deferred section matches mode-requirements.md open questions | ✅ |
| SPEC.md — SPEC open questions answered or deferred | Open questions resolved through ADs or Deferred | ✅ |
| SPEC.md — both modes first-class product modes | AD-1, AD-2 | ✅ |
| SPEC.md — secret non-disclosure | AD-9, AD-20 | ✅ |
| SPEC.md — approval delegation auditable and expiring | AD-5 | ✅ |

No brownfield guarantee is silently dropped. Mode-requirements.md intentional differences are captured in the Local-Only and Kubernetes-Analogue table and AD-25. The Deferred section does not conceal any structural divergence except the worker image trust chain (F-3).

---

## Summary Table

| ID | Severity | Finding | Fix location |
|---|---|---|---|
| F-1 | MEDIUM | AD-12 Prevents does not name HOL/backpressure risk that the disconnect Rule prevents | AD-12 Prevents |
| F-2 | MEDIUM | AD-11 Prevents does not name ephemeral-delta risk that the Rule addresses | AD-11 Prevents |
| F-3 | MEDIUM | Deferred omits worker image trust-chain disposition; hidden structural divergence risk | Deferred section |
| F-4 | LOW | CAP-11 map row missing AD-15 and AD-17 references | Capability → Architecture Map |
| F-5 | LOW | Local-daemon interrupted-state recovery undeclared in state machine diagram | Scheduling/Cancellation diagram note |
| F-6 | INFO | `arm64` assumption lacks a qualifying AC | Assumptions / AC-3 |
| F-7 | LOW | AD-4 Rule mandates `tenant_id` on every row without declaring local-daemon exception | AD-4 Rule |
| F-8 | LOW | "Contract migration" term used in AD-22 without definition; rollback gate cannot be enforced | AD-22 Rule |
| F-9 | LOW | AC-9 governing-decision order implies AD-13 primacy over AD-14 for interruption recovery | AC-9 |
| F-10 | INFO | Idempotency convention silent on local-mode enforcement mechanism | Consistency Conventions |
| F-11 | INFO | AD-3 and AD-13 are complementary but do not cross-reference each other | AD-3 Rule, AD-13 Rule |
| F-12 | LOW | `supervised` default is a load-bearing brownfield guarantee but no AD Rule enforces it | AD-27 Rule |
