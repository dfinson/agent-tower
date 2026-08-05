# Final Focused Operability Gate — Kubernetes

**Artifact reviewed:** `architecture/ARCHITECTURE-SPINE.md`  
**Review date:** 2026-08-05  
**Verdict:** **BLOCKED — 0 critical, 2 high architecture blockers remain**

The install/preflight contract, chart ownership of both gateways, storage-gateway fencing, controller correctness under HA, bounded/fair admission, Kubernetes API budgets, RWO topology, backup scope, CRD migration gates, telemetry cardinality, worker isolation, and attempt recovery now have enforceable invariants. Implementation choices beneath those invariants are not blockers. Two cross-component failure contracts remain structurally open.

## Remaining findings

### HIGH — OP-FINAL-01 — The mandatory egress gateway still has no availability or job-state contract

AD-7 makes the authenticated job-policy gateway the only permitted external path for every worker. AD-21 and the packaging envelope now correctly make it a chart-supplied component, but neither defines its production availability boundary or what authoritative state transition occurs when it is unavailable. AD-18 covers egress denial, not the distinct case of gateway/DNS/control dependency failure. AD-13 defines attempt replacement after worker loss, but does not say whether gateway loss pauses admission, interrupts attempts, consumes retry budgets, or retains active quota.

This is not a replica-count or timeout implementation detail. The choice changes canonical job state, fairness, retry accounting, and whether one gateway outage can fail all active jobs and create a retry storm. The production profile needs an invariant that removes the gateway as a single failure domain, gates new admission on gateway readiness, distinguishes policy denial from dependency unavailability, and fixes in-flight state, quota, and retry treatment until recovery. The corresponding acceptance gate must cover gateway loss and partial policy rollout under AD-15 load.

### HIGH — OP-FINAL-02 — Retaining CRDs during uninstall can make retained resources unreadable when conversion is required

AD-22 permits CRD evolution that requires a conversion webhook and correctly requires webhook availability during upgrade. The removal contract then allows application/controllers to be uninstalled while retaining CRDs and tenant custom resources. It does not require proving that every retained object remains readable without the removed webhook, nor retaining an independently available conversion service. After a multi-version upgrade, removing that service can make LIST/GET, cleanup, backup, and reinstall/adoption fail for the resources the uninstall contract promises to preserve.

This cannot be repaired only by uninstall ordering or a runbook. The lifecycle invariant must block controller/webhook removal while any retained object requires conversion, or first complete a verified storage-version migration to a directly served version whose reads no longer depend on the retiring service. Destructive cleanup and reinstall/adoption must use the same compatibility gate; ordinary Helm uninstall must never strand retained CRDs behind an unavailable conversion endpoint.

## Gate result

No critical blockers remain. Production operability remains blocked on the two high findings above; all other reviewed focus areas have architecture-level invariants sufficient to proceed to implementation and qualification.
