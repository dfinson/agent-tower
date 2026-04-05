import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, ListChecks, ChevronRight, Send, User, ShieldQuestion, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { cn } from "../lib/utils";
import { useStore, selectJobSteps, selectActiveStep, selectStepGroups, selectSteplessEntries, selectJobApprovals } from "../store";
import type { JobSummary, Step, StepGroup, TranscriptEntry, ApprovalRequest } from "../store";
import { useIsMobile } from "../hooks/useIsMobile";
import { StepContainer } from "./StepContainer";
import { StepSearchBar } from "./StepSearchBar";
import type { FilterChipKey } from "./StepSearchBar";
import { ResumeBanner } from "./ResumeBanner";
import { AgentMarkdown } from "./AgentMarkdown";
import { sendOperatorMessage, resumeJob, resolveApproval } from "../api/client";
import { MicButton } from "./VoiceButton";

interface StepListViewProps {
  job: JobSummary;
  /** Step ID to auto-scroll and expand on mount (from deep link) */
  targetStepId?: string | null;
  /** Called when user clicks "View changes in this step" */
  onViewDiff?: (step: { stepId: string; startSha: string | null; endSha: string | null }) => void;
}

export function StepListView({ job, targetStepId, onViewDiff }: StepListViewProps) {
  const jobId = job.id;
  const steps = useStore(selectJobSteps(jobId));
  const activeStep = useStore(selectActiveStep(jobId));
  const stepGroups = useStore(selectStepGroups(jobId));
  const steplessEntries = useStore(selectSteplessEntries(jobId));
  const approvals = useStore(selectJobApprovals(jobId));
  const isMobile = useIsMobile();
  const activeStepRef = useRef<HTMLDivElement | null>(null);
  const listTopRef = useRef<HTMLDivElement | null>(null);
  const stepRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const isRunning = job.state === "running" || job.state === "agent_running";
  const canInteract = ["running", "agent_running", "waiting_for_approval"].includes(job.state);

  // Expanded step tracking (supports external triggers from search/deep links)
  const [expandedStepIds, setExpandedStepIds] = useState<Set<string>>(new Set());

  const toggleStep = useCallback((stepId: string) => {
    setExpandedStepIds((prev) => {
      const next = new Set(prev);
      if (next.has(stepId)) next.delete(stepId);
      else next.add(stepId);
      return next;
    });
  }, []);

  const scrollToStep = useCallback((stepId: string) => {
    const el = stepRefs.current.get(stepId);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  // Deep link: auto-scroll and expand target step
  useEffect(() => {
    if (!targetStepId || steps.length === 0) return;
    const match = steps.find((s) => s.stepId === targetStepId);
    if (match) {
      setExpandedStepIds((prev) => new Set(prev).add(targetStepId));
      // Defer scroll to allow render
      requestAnimationFrame(() => scrollToStep(targetStepId));
    }
  }, [targetStepId, steps, scrollToStep]);

  const scrollToActiveStep = () => {
    activeStepRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const scrollToTop = () => {
    listTopRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const scrollToLastError = useCallback(() => {
    const failed = [...steps].reverse().find((s) => s.status === "failed");
    if (failed) {
      setExpandedStepIds((prev) => new Set(prev).add(failed.stepId));
      requestAnimationFrame(() => scrollToStep(failed.stepId));
    }
  }, [steps, scrollToStep]);

  const handleSearchSelect = useCallback((result: { stepId: string | null }) => {
    if (!result.stepId) return;
    setExpandedStepIds((prev) => new Set(prev).add(result.stepId!));
    requestAnimationFrame(() => scrollToStep(result.stepId!));
  }, [scrollToStep]);

  const hasErrors = steps.some((s) => s.status === "failed");

  // Filter chips: track active filter and compute which steps match
  const [activeFilter, setActiveFilter] = useState<FilterChipKey | null>(null);

  const stepMatchesFilter = useCallback((step: Step, filter: FilterChipKey | null): boolean => {
    if (!filter) return true;
    switch (filter) {
      case "errors": return step.status === "failed";
      case "tools": return step.toolCount > 0;
      case "agent": return step.agentMessage != null;
      case "files": return (step.filesWritten ?? []).length > 0;
      case "running": return step.status === "running";
      default: return true;
    }
  }, []);

  // Compute visible filter chips dynamically from actual step data
  const visibleChips = useMemo(() => {
    const chips: { key: FilterChipKey; label: string; count?: number }[] = [];
    const errorCount = steps.filter((s) => s.status === "failed").length;
    if (errorCount > 0) chips.push({ key: "errors", label: "Errors", count: errorCount });
    const toolSteps = steps.filter((s) => s.toolCount > 0).length;
    if (toolSteps > 0) chips.push({ key: "tools", label: "Tool calls" });
    const agentSteps = steps.filter((s) => s.agentMessage != null).length;
    if (agentSteps > 0) chips.push({ key: "agent", label: "Agent messages" });
    const fileSteps = steps.filter((s) => (s.filesWritten ?? []).length > 0).length;
    if (fileSteps > 0) chips.push({ key: "files", label: "File changes", count: fileSteps });
    const runningSteps = steps.filter((s) => s.status === "running").length;
    if (runningSteps > 0) chips.push({ key: "running", label: "Running", count: runningSteps });
    return chips;
  }, [steps]);

  // Collapsed group tracking
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const toggleGroup = useCallback((groupId: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  }, []);

  // Build render items: interleave groups, ungrouped steps, interstitials, and approvals
  type RenderItem =
    | { kind: "step"; step: Step }
    | { kind: "group"; group: StepGroup; steps: Step[] }
    | { kind: "operator"; entry: TranscriptEntry }
    | { kind: "approval"; approval: ApprovalRequest };

  const renderItems = useMemo<RenderItem[]>(() => {
    // Build base items from steps/groups
    const baseItems: (RenderItem & { ts: string })[] = [];

    if (stepGroups.length === 0) {
      for (const step of steps) {
        baseItems.push({ kind: "step", step, ts: step.startedAt });
      }
    } else {
      const stepIdToGroup = new Map<string, StepGroup>();
      for (const group of stepGroups) {
        for (const sid of group.stepIds) stepIdToGroup.set(sid, group);
      }
      const emittedGroups = new Set<string>();
      for (const step of steps) {
        const group = stepIdToGroup.get(step.stepId);
        if (group) {
          if (!emittedGroups.has(group.groupId)) {
            emittedGroups.add(group.groupId);
            const groupSteps = steps.filter((s) => group.stepIds.includes(s.stepId));
            baseItems.push({ kind: "group", group, steps: groupSteps, ts: groupSteps[0]?.startedAt ?? "" });
          }
        } else {
          baseItems.push({ kind: "step", step, ts: step.startedAt });
        }
      }
    }

    // Add stepless operator messages as interstitials
    for (const entry of steplessEntries) {
      if (entry.role === "operator") {
        baseItems.push({ kind: "operator", entry, ts: entry.timestamp });
      }
    }

    // Add pending approvals
    for (const a of approvals) {
      if (!a.resolvedAt) {
        baseItems.push({ kind: "approval", approval: a, ts: a.requestedAt });
      }
    }

    // Sort by timestamp to get chronological interleaving
    baseItems.sort((a, b) => a.ts.localeCompare(b.ts));

    return baseItems;
  }, [steps, stepGroups, steplessEntries, approvals]);

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div ref={listTopRef} />

      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border">
        <ListChecks size={14} className="text-muted-foreground" />
        <span className="text-sm font-medium">Steps</span>
        {steps.length > 0 && (
          <span className="text-xs text-muted-foreground">{steps.length}</span>
        )}
        {isRunning && activeStep && (
          <span className="ml-auto text-[10px] font-medium text-blue-500">LIVE</span>
        )}
      </div>

      {/* Search & filters — only shown when there are steps */}
      {steps.length > 0 && (
        <StepSearchBar jobId={jobId} onSelect={handleSearchSelect} activeFilter={activeFilter} onFilterChange={setActiveFilter} visibleChips={visibleChips} />
      )}

      <ResumeBanner jobId={jobId} onJumpToFirst={scrollToTop} />

      {/* Empty / startup state */}
      {steps.length === 0 && (
        <div className="flex flex-col items-center justify-center py-10 px-4">
          {isRunning ? (
            <>
              <Loader2 className="h-6 w-6 text-muted-foreground/50 animate-spin mb-3" />
              <p className="text-sm text-muted-foreground">Waiting for first step…</p>
              <p className="text-xs text-muted-foreground/60 mt-1">The agent is initializing</p>
            </>
          ) : (
            <>
              <ListChecks className="h-6 w-6 text-muted-foreground/30 mb-3" />
              <p className="text-sm text-muted-foreground">No steps recorded</p>
            </>
          )}
        </div>
      )}

      {/* Step list (grouped + ungrouped + interstitials + approvals) */}
      {(steps.length > 0 || renderItems.length > 0) && (
        <div className="flex flex-col divide-y divide-border/50">
          {renderItems.map((item) => {
            if (item.kind === "operator") {
              const { entry } = item;
              return (
                <div key={`op-${entry.seq}`} className="px-4 py-3">
                  <div className="flex items-start gap-2 justify-end">
                    <div className="rounded-lg bg-primary/10 border border-primary/20 px-3 py-2 max-w-[85%]">
                      <div className="text-sm text-foreground/90 leading-relaxed">
                        <AgentMarkdown content={entry.content} />
                      </div>
                      <div className="text-[10px] text-muted-foreground/60 mt-1 text-right">
                        {new Date(entry.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </div>
                    </div>
                    <div className="shrink-0 w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center mt-0.5">
                      <User size={12} className="text-primary" />
                    </div>
                  </div>
                </div>
              );
            }

            if (item.kind === "approval") {
              const { approval } = item;
              return (
                <ApprovalInline key={`apr-${approval.id}`} approval={approval} />
              );
            }

            if (item.kind === "step") {
              const { step } = item;
              const isActive = step.stepId === activeStep?.stepId;
              const dimmed = activeFilter != null && !stepMatchesFilter(step, activeFilter);
              return (
                <div
                  key={step.stepId}
                  data-step-id={step.stepId}
                  ref={(el) => {
                    if (el) stepRefs.current.set(step.stepId, el);
                    if (isActive) activeStepRef.current = el;
                  }}
                  className={cn(dimmed && "opacity-40 transition-opacity")}
                >
                  <StepContainer
                    step={step}
                    isActive={isActive}
                    expanded={expandedStepIds.has(step.stepId)}
                    onToggle={() => toggleStep(step.stepId)}
                    onViewDiff={onViewDiff}
                  />
                </div>
              );
            }

            // Grouped steps
            const { group, steps: groupSteps } = item;
            const isCollapsed = collapsedGroups.has(group.groupId);
            const groupToolCount = groupSteps.reduce((s, st) => s + st.toolCount, 0);
            const groupDurationMs = groupSteps.reduce((s, st) => s + (st.durationMs ?? 0), 0);
            const groupHasActive = groupSteps.some((s) => s.stepId === activeStep?.stepId);
            const allDimmed = activeFilter != null && groupSteps.every((s) => !stepMatchesFilter(s, activeFilter));

            return (
              <div
                key={group.groupId}
                className={cn(allDimmed && "opacity-40 transition-opacity")}
              >
                {/* Group header */}
                <button
                  type="button"
                  onClick={() => toggleGroup(group.groupId)}
                  className={cn(
                    "flex items-center gap-2 w-full text-left px-4 py-2.5 transition-colors",
                    "hover:bg-accent/30",
                    groupHasActive && "bg-blue-500/5",
                  )}
                >
                  <ChevronRight
                    size={14}
                    className={cn(
                      "shrink-0 text-muted-foreground transition-transform",
                      !isCollapsed && "rotate-90",
                    )}
                  />
                  <span className="text-sm font-medium truncate flex-1">
                    {group.headline}
                  </span>
                  <span className="flex items-center gap-2 shrink-0 text-xs text-muted-foreground">
                    <span>{groupSteps.length} steps</span>
                    {groupToolCount > 0 && <span>{groupToolCount} tools</span>}
                    {groupDurationMs > 0 && (
                      <span className="tabular-nums">
                        {groupDurationMs < 1000 ? `${groupDurationMs}ms` : `${Math.round(groupDurationMs / 1000)}s`}
                      </span>
                    )}
                  </span>
                </button>

                {/* Group children */}
                {!isCollapsed && (
                  <div className="ml-3 border-l border-border/50">
                    {groupSteps.map((step) => {
                      const isActive = step.stepId === activeStep?.stepId;
                      const dimmed = activeFilter != null && !stepMatchesFilter(step, activeFilter);
                      return (
                        <div
                          key={step.stepId}
                          data-step-id={step.stepId}
                          ref={(el) => {
                            if (el) stepRefs.current.set(step.stepId, el);
                            if (isActive) activeStepRef.current = el;
                          }}
                          className={cn(
                            "border-b border-border/30 last:border-b-0",
                            dimmed && "opacity-40 transition-opacity",
                          )}
                        >
                          <StepContainer
                            step={step}
                            isActive={isActive}
                            expanded={expandedStepIds.has(step.stepId)}
                            onToggle={() => toggleStep(step.stepId)}
                            onViewDiff={onViewDiff}
                          />
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Message composer — pinned at bottom when job is interactive */}
      {canInteract && (
        <MessageComposer jobId={jobId} isTerminal={false} />
      )}

      {/* Jump-to quick actions */}
      {isRunning && activeStep && (
        isMobile ? (
          <button
            onClick={scrollToActiveStep}
            className="fixed bottom-20 left-1/2 -translate-x-1/2 z-40 px-4 py-2 rounded-full
                       bg-primary text-primary-foreground text-sm font-medium shadow-lg min-h-[44px]"
          >
            Jump to current step ↓
          </button>
        ) : (
          <div className="sticky bottom-0 flex gap-2 p-2 bg-card/95 backdrop-blur border-t border-border">
            <button
              onClick={scrollToActiveStep}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Jump to current step
            </button>
            {hasErrors && (
              <button
                onClick={scrollToLastError}
                className="text-xs text-destructive/80 hover:text-destructive"
              >
                Jump to last error
              </button>
            )}
          </div>
        )
      )}
    </div>
  );
}

/* ---------- Inline approval banner ---------- */

function ApprovalInline({ approval }: { approval: ApprovalRequest }) {
  const [loading, setLoading] = useState<string | null>(null);

  const handleResolve = useCallback(async (resolution: "approved" | "rejected") => {
    setLoading(resolution);
    try {
      await resolveApproval(approval.id, resolution);
      toast.success(`Approval ${resolution}`);
    } catch (e) {
      toast.error(String(e));
    } finally {
      setLoading(null);
    }
  }, [approval.id]);

  return (
    <div className="px-4 py-3">
      <div className={cn(
        "rounded-lg border p-3",
        approval.requiresExplicitApproval
          ? "border-red-500/40 bg-red-500/5"
          : "border-amber-500/40 bg-amber-500/5",
      )}>
        <div className="flex items-start gap-2">
          <ShieldQuestion size={16} className={cn(
            "shrink-0 mt-0.5",
            approval.requiresExplicitApproval ? "text-red-500" : "text-amber-500",
          )} />
          <div className="flex-1 min-w-0">
            <p className="text-sm text-foreground/90">{approval.description}</p>
            {approval.proposedAction && (
              <pre className="mt-1.5 text-xs text-muted-foreground bg-background/50 rounded px-2 py-1 overflow-x-auto">
                {approval.proposedAction}
              </pre>
            )}
            <div className="flex items-center gap-2 mt-2">
              <button
                onClick={() => handleResolve("approved")}
                disabled={loading !== null}
                className="flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50"
              >
                <CheckCircle2 size={12} />
                {loading === "approved" ? "…" : "Approve"}
              </button>
              <button
                onClick={() => handleResolve("rejected")}
                disabled={loading !== null}
                className="flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium bg-muted hover:bg-muted/80 text-muted-foreground disabled:opacity-50"
              >
                <XCircle size={12} />
                {loading === "rejected" ? "…" : "Reject"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- Compact message composer ---------- */

function MessageComposer({ jobId, isTerminal }: { jobId: string; isTerminal: boolean }) {
  const [msg, setMsg] = useState("");
  const [sending, setSending] = useState(false);
  const isMobile = useIsMobile();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const waveformRef = useRef<HTMLDivElement>(null);
  const [micState, setMicState] = useState<"idle" | "recording" | "transcribing">("idle");

  const handleSend = useCallback(async () => {
    const text = msg.trim();
    if (!text) return;
    setSending(true);
    try {
      if (isTerminal) {
        await resumeJob(jobId, text);
      } else {
        await sendOperatorMessage(jobId, text);
      }
      setMsg("");
      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
      }
    } catch (e) {
      toast.error(String(e));
    } finally {
      setSending(false);
    }
  }, [jobId, msg, isTerminal]);

  return (
    <div className="border-t border-border px-3 py-2">
      {/* Waveform strip for voice */}
      <div className={cn(
        "rounded border border-blue-600/50 bg-card px-3 py-1 mb-2",
        micState === "recording" ? "block" : "hidden",
      )}>
        <div ref={waveformRef} />
      </div>
      {micState === "transcribing" && (
        <div className="flex items-center gap-2 px-1 mb-2 text-xs text-muted-foreground">
          <Loader2 size={12} className="animate-spin" />
          <span>Transcribing…</span>
        </div>
      )}
      <div className="flex items-end gap-2">
        <div className="relative flex-1">
          <textarea
            ref={textareaRef}
            placeholder="Message the agent…"
            value={msg}
            onChange={(e) => {
              setMsg(e.currentTarget.value);
              e.currentTarget.style.height = "auto";
              e.currentTarget.style.height = Math.min(e.currentTarget.scrollHeight, isMobile ? 200 : 120) + "px";
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !isMobile && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            disabled={sending || micState !== "idle"}
            rows={1}
            className="flex w-full rounded-md border border-input bg-transparent px-3 py-1.5 text-sm text-foreground shadow-sm placeholder:text-muted-foreground/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 resize-none pr-8 overflow-y-auto"
            style={{ maxHeight: isMobile ? 200 : 120 }}
          />
          <div className="absolute right-2 bottom-1.5">
            <MicButton
              onTranscript={(t) => setMsg((prev) => (prev ? prev + " " : "") + t)}
              onStateChange={setMicState}
              waveformContainerRef={waveformRef}
            />
          </div>
        </div>
        <button
          onClick={handleSend}
          disabled={sending || !msg.trim() || micState !== "idle"}
          className="flex items-center justify-center h-8 w-8 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
        >
          <Send size={14} />
        </button>
      </div>
    </div>
  );
}
