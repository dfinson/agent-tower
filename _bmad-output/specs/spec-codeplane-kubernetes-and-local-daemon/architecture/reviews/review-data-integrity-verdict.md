# Post-Fix Data-Integrity Verification

**Reviewed:** `architecture/ARCHITECTURE-SPINE.md`  
**Verdict:** **REVISIONS REQUIRED — 0 critical, 4 high architecture blockers remain.**

## High Blockers

### HIGH-1 — The callback epoch is not explicitly durable

AD-31 explicitly stores the storage epoch durably in the PVC head, but only says the per-job callback epoch is “advanced under this sequencer.” It does not require that advance to be persisted and fsynced in the same durable head metadata checked by append. A gateway crash after callback invalidation but before CRD projection can therefore permit a replacement gateway to recover an older callback epoch and accept a stale worker.

Require callback-epoch advance to atomically persist and fsync with the per-job head before claim cancellation/replacement is projected, and require takeover recovery to verify that value.

### HIGH-2 — Participant vectors do not define a consistency boundary

AD-12 returns participant UID/resourceVersion values, but does not bind the expected vector to the job projection’s sequence/hash or to the `CodePlaneOperation` that produced the participant states. “Mismatch” is consequently undefined: an implementation may read mutually inconsistent approval, attempt, binding, and operation versions once, report those observed versions, and satisfy the stated contract.

Require the bounded job projection or durable operation record to name the expected participant identities/versions for its history prefix, with retry/degraded behavior when that exact vector cannot be assembled.

### HIGH-3 — Backup/import coordination records violate the CRD size bound

All CRDs are capped at 256 KiB, yet `CodePlaneBackupEpoch.status` contains a participant map for a tenant that may have thousands of jobs/resources, and `CodePlaneImportSession` durably records per-object phases for an arbitrarily large package. No bounded chunking or storage-backed manifest/index contract is defined. At the supported scale, either record can exceed the cap before it can prove complete quiescence or quarantine, making crash recovery and completeness unverifiable.

Require bounded CRD summaries that reference immutable, checksummed storage-backed participant/phase manifests, with atomic head/version advancement and replay rules.

### HIGH-4 — Local backup claims unsupported cross-store atomicity

Backup step 8 says it “atomically” captures the artifact tree with a stopped/checkpointed SQLite database or SQLite online-backup snapshot. Neither SQLite backup mode atomically snapshots the separate filesystem tree, and a retention pause prevents deletion but does not fence in-flight artifact creation or mutation. The resulting database and artifact copy can represent different logical points while being called atomic.

Require a local mutation barrier that drains or durably parks operations and freezes artifact writers, plus a manifest binding the SQLite snapshot to verified artifact versions/hashes; otherwise describe the capture as a validated non-atomic set and reject drift.

## Gate Result

**Critical:** 0  
**High:** 4  
**Decision:** Not implementation-ready for data integrity until these blockers are resolved.
