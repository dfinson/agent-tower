---
name: 'Security Honesty Review — Shared-RWX Single-Trusted-Tenant Baseline'
type: review
reviews: '../ARCHITECTURE-SPINE.md'
status: final
---

# Review: Security Tradeoff Honesty for the Simplified Single-Trusted-Tenant Shared-RWX Baseline

## Scope

Independent critical review of `ARCHITECTURE-SPINE.md`, focused solely on whether the document is honest
about the security tradeoffs of its simplified single-trusted-tenant, shared-RWX baseline: same-installation
hostile-job isolation claims, subPath limits, intentional shared mirror/context surfaces, worker SA/RBAC,
network/egress, secret mounts, callback authentication/fencing, and namespace/cluster-admin trust.

## Verdict

**Solid overall, no blocking issues.** The spine is unusually disciplined about this tradeoff: AD-4, AD-30,
AD-32, and the "Security and Trust Boundaries" section (lines 464–489) explicitly refuse to claim
same-installation hostile-job isolation, explicitly name cluster-admin/storage-admin as trusted and
undefended, explicitly call out the local-daemon OS-user boundary, and explicitly mark the shared mirror and
repository-context as *intentional* shared surfaces rather than accidental ones. That is the right shape for
this baseline. The findings below are precision/consistency gaps in that honesty, not missing security
controls, and none of them require blocking the architecture — they should be tightened before this framing
is relied on by implementers or reviewers.

## Top Findings

### 1. AC-4's absolute claim is stronger than AD-30's hedged claim it is supposed to verify — Non-Blocking

- AD-30 and the trust-boundary bullet (line 483) both use deliberately hedged language: subPath mounts
  "prevent **casual** sibling-workspace access" — implying protection against accidental/naive collision, not
  necessarily a deliberate breakout attempt from a hostile job (which AD-4 explicitly says is out of scope).
- AC-4, the testable acceptance criterion meant to operationalize this, asserts the unhedged opposite: "Two
  concurrent jobs **cannot write** one another's subPath workspace ... fail boundary tests."
- These two statements test different threat models but are presented as the same guarantee. If AC-4 is
  implemented as a literal "cannot write" boundary test, it will pass against accidental/naive access but says
  nothing about a job that deliberately tries to escape its subPath (e.g., via a compromised container image
  attempting known subPath TOCTOU/symlink techniques) — which AD-4 already disclaims defending against. As
  written, a reader of AC-4 alone could reasonably (and wrongly) conclude sibling-workspace writes are fully
  closed even under a hostile-actor model.
- **Recommendation:** Either soften AC-4 to match AD-30's "casual/misconfiguration" scope explicitly, or state
  in AD-30/AC-4 what specific attack class the boundary test is proving (accidental path collision under
  cooperative workers) versus what it is not (deliberate container/subPath escape by a hostile job), so the
  two sections stop implying different guarantee strengths for the same mechanism.

### 2. No stated RBAC scope for a worker SA when a declared adapter needs Kubernetes API access — Non-Blocking

- AD-6 says the control plane, indexer, and "each attempt worker" use distinct service accounts, and workers
  get `automountServiceAccountToken: false` "unless a declared adapter requires Kubernetes API access." AD-7
  separately states its explicit purpose is to prevent "host escape, cross-job access, and unbounded resource
  use," and AD-30 repeats "workers cannot reach the Kubernetes API unless a declared adapter requires it ...
  [or] other attempts' workspaces ... by default."
- Nowhere is it stated whether, in the case where a declared adapter *does* require API access, that worker
  SA's RBAC is scoped to only its own attempt's resources (e.g., `resourceNames` restricted to its own Pod/CR)
  versus a namespace-wide "worker" role shared across all concurrently running attempts. Under the latter
  reading, a job using such an adapter could `get`/`list` sibling `CodePlaneExecutionAttempt`/Pod objects or
  other namespace resources it has no operational need for — which would directly contradict AD-7's own
  stated "Prevents: cross-job access" line, even under the accepted "siblings are not hostile" framing, since
  RBAC is normally the one mechanism that *is* supposed to be least-privilege regardless of trust level.
- **Recommendation:** Add an explicit rule (in AD-6, AD-29, or AD-30) that any worker SA granted Kubernetes API
  access is scoped per-attempt (own Pod/own CR only, no list/watch across sibling attempts, Pods, or Secrets),
  not a shared broad "worker" role.

### 3. The "no isolation against a hostile same-installation job" disclaimer names no concrete residual risk — Suggestion

- AD-4/AD-30/line 483 state plainly that the baseline "does not claim isolation against a hostile job inside
  the same installation." That's honest as far as it goes, but AC-4 then enumerates a long, nearly exhaustive
  list of things that *are* tested and protected against cross-job interference: subPath workspace, shared
  mirror, index directory, handoff file, repository-context file, secret mount, attempt status, and
  repository target ref. Combined with AD-13's per-repository/per-identity quotas and AD-7's resource
  requests/limits, most obvious noisy-neighbor and cross-job-write vectors already have a stated control.
- This leaves the disclaimer reading as boilerplate rather than actionable: it's unclear to an implementer or
  a security reviewer what a hostile same-installation job actor is actually still assumed able to do (e.g.,
  degrade the single-replica control plane's own request-handling capacity, exploit RBAC scope gaps like
  Finding 2, or exhaust the shared egress gateway in ways quotas don't bound). Contrast this with AD-32, which
  is concrete about local-daemon's accepted gap ("may access any user-readable file or credential").
- **Recommendation:** Name one or two concrete residual risks the Kubernetes baseline explicitly accepts (or
  state "no further residual risk beyond Finding 2's RBAC scope is currently known" if that's actually true),
  mirroring AD-32's specificity, so the disclaimer is falsifiable/testable rather than generic hedging.

### 4. subPath is the load-bearing isolation primitive but its qualification bar doesn't mention its known escape history — Suggestion

- AD-21/AD-34/line 456 require the CSI/StorageClass be "qualified for ... POSIX atomic rename, durability
  after fsync, and the required subPath semantics," and installation fails if it can't prove this. subPath is
  also the primary mechanism cited in AD-30/AC-4 for keeping concurrent attempt workspaces apart.
- Kubernetes subPath mounts have a known history of container-breakout classes (symlink-swap/TOCTOU races,
  e.g. the issues fixed by KEP-1855's subPath re-implementation). The spine's qualification bar doesn't mention
  that "required subPath semantics" should include resistance to symlink-based subPath escape on the target
  kubelet/CSI version, so a reader could satisfy the letter of AD-21/AD-34 on a kubelet/CSI combination that is
  still vulnerable to a known subPath escape class.
- **Recommendation:** Add a line to the CSI/subPath qualification bar (AD-21 or AD-34) naming resistance to
  subPath symlink/TOCTOU escape as part of "required subPath semantics," since that is precisely the property
  Finding 1's boundary test depends on once "casual" access is no longer the only threat considered.

## Path

`C:\Users\davidfinson\.copilot\repos\copilot-worktrees\codeplane\dfinson-didactic-couscous\_bmad-output\specs\spec-codeplane-kubernetes-and-local-daemon\architecture\reviews\review-security-shared-volume-final.md`
