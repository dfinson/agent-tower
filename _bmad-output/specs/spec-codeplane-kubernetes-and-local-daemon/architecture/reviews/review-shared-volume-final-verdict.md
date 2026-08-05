---
target: ../ARCHITECTURE-SPINE.md
reviewed_source_reviews:
  - review-data-integrity-shared-volume-final.md
  - review-incompatibility-authority-shared-volume-final.md
  - review-rubric-shared-volume-final.md
date: 2026-08-05
verdict: PASS
---

# Shared-Volume Final Gate Verdict

| Finding / selected closure | Status | Fresh closure evidence |
| --- | --- | --- |
| Data-integrity B1 — mirror mutation safety | CLOSED | AD-8/AD-24 restrict mutation to the RWOP-bound control-plane adapter and require Lease coordination plus Git locks, ref CAS, fsck, quarantine, and rebuild. |
| Data-integrity B2 — restore incarnation | CLOSED | AD-12/AD-13/AD-31 and restore step 4 bind fences, names, and cursors to a durable incarnation rotated on restore. |
| Data-integrity B3 — backup writer quiescence | CLOSED AFTER GATE FIX | Backup step 1 and AC-12 now require positive Kubernetes-API verification that no non-control Pod retains any read-write mount to the RWX PVC; timeout aborts capture. |
| Incompatibility B-1 — SQLite-first intent | CLOSED | AD-10/AD-11/AD-33, the CRD contract, and topology make CRD spec/status projection-only and reject or revert direct intent. |
| Incompatibility B-2 — etcd state on restore | CLOSED | Restore step 4 explicitly excludes etcd CRs, overwrites/recreates projections from SQLite, and scopes projection-ahead suspension to the restore barrier. |
| Incompatibility B-3 — overloaded fence | CLOSED | AD-3/AD-13/AD-29 define exactly one `attemptFence` tuple and explicitly prohibit `callbackEpoch` or a second fence. |
| Rubric High — AD-3 and AD-26 AC coverage | CLOSED | AC-4 governs AD-3; AC-13 governs AD-26. |
| RWOP baseline private SQLite PVC everywhere | CLOSED | Diagrams, AD-10/AD-17/AD-21/AD-34, topology, packaging, and AC-3 consistently require RWOP. |
| AD-15 terminal CR wording | CLOSED | AD-15 now names terminal attempt/approval CRs only; operations remain in SQLite. |
| AC-4 honest subPath isolation and shared-writer ownership | CLOSED | AC-4 limits the claim to accidental/casual isolation, tests explicit writer roles/shared surfaces, and includes AD-3. |
| Baseline worker API isolation / reviewed API profile | CLOSED | AD-6/AD-29/AD-30 require `automountServiceAccountToken: false`, no API credential/RBAC, and a separate reviewed API-enabled profile. |
| Orphan cleanup and immutable attempt-UID paths | CLOSED | AD-10/AD-14 sweep orphan temp/artifact/session/workspace paths; AD-8/AD-34 and the ownership table require immutable-attempt-UID workspaces. |
| Executable RWX qualification | CLOSED | AD-21/AD-34 and AC-3 require cross-node/cross-Pod fsync, atomic rename, directory fsync, crash/remount, and `subPath` qualification. |

**Gate verdict: PASS — every Blocking/High finding from the three source reviews is closed in the repaired spine.**
