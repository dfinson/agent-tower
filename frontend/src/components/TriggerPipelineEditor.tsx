/**
 * Visual editor for sidecar trigger pipelines.
 *
 * Replaces raw JSON editing with a structured form — each trigger is a card
 * with typed condition fields, context source checkboxes, prompt template,
 * output parser dropdown, and output route builder.
 */

import { useCallback } from "react";
import { ChevronDown, ChevronUp, Copy, Plus, Trash2 } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { Combobox } from "./ui/combobox";
import { Tooltip } from "./ui/tooltip";

// ---------------------------------------------------------------------------
// Types (mirrors the backend DSL)
// ---------------------------------------------------------------------------

interface TriggerCondition {
  kind: string;
  // event
  eventKind?: string;
  // threshold
  metric?: string;
  value?: number;
  // regex
  pattern?: string;
  source?: string;
  // file_pattern
  glob?: string;
  changeKind?: string;
  // content_match
  keywords?: string[];
  caseSensitive?: boolean;
  // shared
  once?: boolean;
}

interface OutputRoute {
  kind: string;
  // event_bus
  eventKind?: string;
  // job_metadata
  field?: string;
  // agent_message
  role?: string;
  label?: string;
  // gate
  verdictField?: string;
  reasonField?: string;
  timeoutS?: number;
}

interface TriggerPipeline {
  condition: TriggerCondition;
  contextSources: string[];
  promptTemplate: string;
  outputParser: { kind: string };
  outputRoutes: OutputRoute[];
}

// ---------------------------------------------------------------------------
// Option sets
// ---------------------------------------------------------------------------

const CONDITION_OPTIONS = [
  { value: "manual", label: "Manual", description: "Triggered via API call" },
  { value: "threshold", label: "Threshold", description: "After N messages or tool calls" },
  { value: "event", label: "Event", description: "On a domain event" },
  { value: "regex", label: "Regex", description: "When output matches a pattern" },
  { value: "content_match", label: "Content Match", description: "When output contains keywords" },
  { value: "file_pattern", label: "File Pattern", description: "When changed files match a glob" },
];

const CONTEXT_OPTIONS = [
  { key: "job_diff", label: "Job Diff", tip: "The current diff of all file changes" },
  { key: "job_prompt", label: "Job Prompt", tip: "The original task prompt" },
  { key: "recent_messages", label: "Recent Messages", tip: "Last N agent/tool messages" },
  { key: "trigger_event", label: "Trigger Event", tip: "Payload of the event that fired the trigger" },
];

const PARSER_OPTIONS = [
  { value: "plain_text", label: "Plain Text", description: "Use response as-is" },
  { value: "json_object", label: "JSON Object", description: "Parse as JSON object" },
  { value: "json_array", label: "JSON Array", description: "Parse as JSON array" },
];

const ROUTE_OPTIONS = [
  { value: "event_bus", label: "Event Bus", description: "Publish a domain event" },
  { value: "job_metadata", label: "Job Metadata", description: "Write to a job field" },
  { value: "agent_message", label: "Agent Message", description: "Inject into agent conversation" },
  { value: "gate", label: "Gate", description: "Block agent until approved" },
];

const METRIC_OPTIONS = [
  { value: "messages", label: "Messages" },
  { value: "tool_calls", label: "Tool Calls" },
];

const SOURCE_OPTIONS = [
  { value: "messages", label: "Messages" },
  { value: "tool_calls", label: "Tool Calls" },
  { value: "tool_output", label: "Tool Output" },
];

const CHANGE_KIND_OPTIONS = [
  { value: "any", label: "Any Change" },
  { value: "added", label: "Added" },
  { value: "modified", label: "Modified" },
  { value: "deleted", label: "Deleted" },
];

const ROLE_OPTIONS = [
  { value: "system", label: "System" },
  { value: "tool_result", label: "Tool Result" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeDefaultTrigger(): TriggerPipeline {
  return {
    condition: { kind: "manual" },
    contextSources: ["job_diff"],
    promptTemplate: "{diff}",
    outputParser: { kind: "plain_text" },
    outputRoutes: [{ kind: "event_bus", eventKind: "sidecar_result" }],
  };
}

function makeDefaultCondition(kind: string): TriggerCondition {
  switch (kind) {
    case "threshold": return { kind, metric: "messages", value: 1 };
    case "event": return { kind, eventKind: "transcript_updated" };
    case "regex": return { kind, pattern: "", source: "messages" };
    case "file_pattern": return { kind, glob: "**/*", changeKind: "any" };
    case "content_match": return { kind, keywords: [], caseSensitive: false, source: "messages" };
    default: return { kind: "manual" };
  }
}

function makeDefaultRoute(kind: string): OutputRoute {
  switch (kind) {
    case "event_bus": return { kind, eventKind: "sidecar_result" };
    case "job_metadata": return { kind, field: "description" };
    case "agent_message": return { kind, role: "system", label: "" };
    case "gate": return { kind, verdictField: "verdict", reasonField: "reason", timeoutS: 30 };
    default: return { kind };
  }
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface TriggerPipelineEditorProps {
  value: TriggerPipeline[];
  onChange: (triggers: TriggerPipeline[]) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export type { TriggerPipeline };

export function TriggerPipelineEditor({ value, onChange }: TriggerPipelineEditorProps) {
  const triggers = value;

  const update = useCallback(
    (index: number, patch: Partial<TriggerPipeline>) => {
      const next = triggers.map((t, i) => (i === index ? { ...t, ...patch } : t));
      onChange(next);
    },
    [triggers, onChange],
  );

  const add = useCallback(() => {
    onChange([...triggers, makeDefaultTrigger()]);
  }, [triggers, onChange]);

  const remove = useCallback(
    (index: number) => {
      onChange(triggers.filter((_, i) => i !== index));
    },
    [triggers, onChange],
  );

  const duplicate = useCallback(
    (index: number) => {
      const copy = JSON.parse(JSON.stringify(triggers[index])) as TriggerPipeline;
      const next = [...triggers];
      next.splice(index + 1, 0, copy);
      onChange(next);
    },
    [triggers, onChange],
  );

  const move = useCallback(
    (index: number, dir: -1 | 1) => {
      const target = index + dir;
      if (target < 0 || target >= triggers.length) return;
      const next = [...triggers];
      const tmp = next[index]!;
      next[index] = next[target]!;
      next[target] = tmp;
      onChange(next);
    },
    [triggers, onChange],
  );

  return (
    <div className="flex flex-col gap-3">
      {triggers.map((trigger, i) => (
        <TriggerCard
          key={i}
          index={i}
          trigger={trigger}
          total={triggers.length}
          onUpdate={(patch) => update(i, patch)}
          onRemove={() => remove(i)}
          onDuplicate={() => duplicate(i)}
          onMoveUp={() => move(i, -1)}
          onMoveDown={() => move(i, 1)}
        />
      ))}
      <Button variant="outline" size="sm" onClick={add} className="w-fit">
        <Plus size={14} />
        Add Trigger
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trigger card
// ---------------------------------------------------------------------------

interface TriggerCardProps {
  index: number;
  trigger: TriggerPipeline;
  total: number;
  onUpdate: (patch: Partial<TriggerPipeline>) => void;
  onRemove: () => void;
  onDuplicate: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}

function TriggerCard({
  index,
  trigger,
  total,
  onUpdate,
  onRemove,
  onDuplicate,
  onMoveUp,
  onMoveDown,
}: TriggerCardProps) {
  const cond = trigger.condition;
  const condLabel = CONDITION_OPTIONS.find((o) => o.value === cond.kind)?.label ?? cond.kind;

  return (
    <div className="rounded-lg border border-border bg-card/50">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <span className="text-xs font-medium text-foreground">
          Trigger {total > 1 ? `${index + 1}` : ""} — {condLabel}
        </span>
        <div className="flex items-center gap-0.5">
          {total > 1 && (
            <>
              <Tooltip content="Move up">
                <Button size="icon-sm" variant="ghost" onClick={onMoveUp} disabled={index === 0} className="h-6 w-6">
                  <ChevronUp size={12} />
                </Button>
              </Tooltip>
              <Tooltip content="Move down">
                <Button size="icon-sm" variant="ghost" onClick={onMoveDown} disabled={index === total - 1} className="h-6 w-6">
                  <ChevronDown size={12} />
                </Button>
              </Tooltip>
            </>
          )}
          <Tooltip content="Duplicate">
            <Button size="icon-sm" variant="ghost" onClick={onDuplicate} className="h-6 w-6">
              <Copy size={12} />
            </Button>
          </Tooltip>
          <Tooltip content="Remove">
            <Button size="icon-sm" variant="ghost" onClick={onRemove} className="h-6 w-6 text-destructive hover:text-destructive">
              <Trash2 size={12} />
            </Button>
          </Tooltip>
        </div>
      </div>

      <div className="flex flex-col gap-3 p-3">
        {/* ── Condition ── */}
        <div className="flex flex-col gap-1.5">
          <Tooltip content="When this trigger fires">
            <Label className="text-[11px] uppercase tracking-wide text-muted-foreground cursor-help w-fit">
              Condition
            </Label>
          </Tooltip>
          <div className="flex flex-wrap gap-2">
            <div className="w-40">
              <Combobox
                items={CONDITION_OPTIONS}
                value={cond.kind}
                onChange={(v) => onUpdate({ condition: makeDefaultCondition(v ?? "manual") })}
              />
            </div>
            <ConditionFields
              condition={cond}
              onChange={(c) => onUpdate({ condition: c })}
            />
          </div>
        </div>

        {/* ── Context sources ── */}
        <div className="flex flex-col gap-1.5">
          <Tooltip content="Data available to the prompt template as {variable} placeholders">
            <Label className="text-[11px] uppercase tracking-wide text-muted-foreground cursor-help w-fit">
              Context
            </Label>
          </Tooltip>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {CONTEXT_OPTIONS.map((ctx) => (
              <Tooltip key={ctx.key} content={ctx.tip}>
                <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                  <input
                    type="checkbox"
                    checked={trigger.contextSources.includes(ctx.key)}
                    onChange={() => {
                      const has = trigger.contextSources.includes(ctx.key);
                      const next = has
                        ? trigger.contextSources.filter((s) => s !== ctx.key)
                        : [...trigger.contextSources, ctx.key];
                      onUpdate({ contextSources: next });
                    }}
                    className="accent-primary"
                  />
                  <span className="text-foreground">{ctx.label}</span>
                </label>
              </Tooltip>
            ))}
          </div>
        </div>

        {/* ── Prompt template ── */}
        <div className="flex flex-col gap-1.5">
          <Tooltip content="Template sent to the sidecar LLM. Use {variable} for context values: {diff}, {task}, {messages}, {payload}, etc.">
            <Label className="text-[11px] uppercase tracking-wide text-muted-foreground cursor-help w-fit">
              Prompt Template
            </Label>
          </Tooltip>
          <Textarea
            value={trigger.promptTemplate}
            onChange={(e) => onUpdate({ promptTemplate: e.target.value })}
            autoResize
            className="min-h-[48px] text-xs"
            placeholder="e.g., Review this diff for security issues:\n{diff}"
          />
        </div>

        {/* ── Output parser + routes ── */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <Tooltip content="How to interpret the sidecar's LLM response">
              <Label className="text-[11px] uppercase tracking-wide text-muted-foreground cursor-help w-fit">
                Output Parser
              </Label>
            </Tooltip>
            <Combobox
              items={PARSER_OPTIONS}
              value={trigger.outputParser.kind}
              onChange={(v) => onUpdate({ outputParser: { kind: v ?? "plain_text" } })}
            />
          </div>
        </div>

        {/* ── Output routes ── */}
        <div className="flex flex-col gap-1.5">
          <Tooltip content="Where to send the parsed sidecar response">
            <Label className="text-[11px] uppercase tracking-wide text-muted-foreground cursor-help w-fit">
              Output Routes
            </Label>
          </Tooltip>
          <div className="flex flex-col gap-2">
            {trigger.outputRoutes.map((route, ri) => (
              <RouteRow
                key={ri}
                route={route}
                onChange={(r) => {
                  const next = [...trigger.outputRoutes];
                  next[ri] = r;
                  onUpdate({ outputRoutes: next });
                }}
                onRemove={() => {
                  onUpdate({ outputRoutes: trigger.outputRoutes.filter((_, j) => j !== ri) });
                }}
                removable={trigger.outputRoutes.length > 1}
              />
            ))}
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                onUpdate({
                  outputRoutes: [...trigger.outputRoutes, makeDefaultRoute("event_bus")],
                })
              }
              className="w-fit text-xs h-7"
            >
              <Plus size={12} />
              Add Route
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Condition-specific fields
// ---------------------------------------------------------------------------

function ConditionFields({
  condition,
  onChange,
}: {
  condition: TriggerCondition;
  onChange: (c: TriggerCondition) => void;
}) {
  switch (condition.kind) {
    case "threshold":
      return (
        <div className="flex items-center gap-2">
          <div className="w-32">
            <Combobox
              items={METRIC_OPTIONS}
              value={condition.metric ?? "messages"}
              onChange={(v) => onChange({ ...condition, metric: v ?? "messages" })}
              placeholder="Metric"
            />
          </div>
          <span className="text-xs text-muted-foreground">≥</span>
          <Input
            type="number"
            min={1}
            value={condition.value ?? 1}
            onChange={(e) => onChange({ ...condition, value: parseInt(e.currentTarget.value) || 1 })}
            className="w-16 h-8 text-xs"
          />
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={condition.once ?? false}
              onChange={(e) => onChange({ ...condition, once: e.target.checked })}
              className="accent-primary"
            />
            once
          </label>
        </div>
      );

    case "event":
      return (
        <Input
          value={condition.eventKind ?? ""}
          onChange={(e) => onChange({ ...condition, eventKind: e.currentTarget.value })}
          placeholder="Event kind (e.g., transcript_updated)"
          className="w-56 h-8 text-xs"
        />
      );

    case "regex":
      return (
        <div className="flex items-center gap-2 flex-wrap">
          <Input
            value={condition.pattern ?? ""}
            onChange={(e) => onChange({ ...condition, pattern: e.currentTarget.value })}
            placeholder="Regex pattern"
            className="w-56 h-8 text-xs font-mono"
          />
          <div className="w-32">
            <Combobox
              items={SOURCE_OPTIONS}
              value={condition.source ?? "messages"}
              onChange={(v) => onChange({ ...condition, source: v ?? "messages" })}
              placeholder="Source"
            />
          </div>
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={condition.once ?? false}
              onChange={(e) => onChange({ ...condition, once: e.target.checked })}
              className="accent-primary"
            />
            once
          </label>
        </div>
      );

    case "file_pattern":
      return (
        <div className="flex items-center gap-2">
          <Input
            value={condition.glob ?? ""}
            onChange={(e) => onChange({ ...condition, glob: e.currentTarget.value })}
            placeholder="e.g., **/*.sql"
            className="w-40 h-8 text-xs font-mono"
          />
          <div className="w-32">
            <Combobox
              items={CHANGE_KIND_OPTIONS}
              value={condition.changeKind ?? "any"}
              onChange={(v) => onChange({ ...condition, changeKind: v ?? "any" })}
            />
          </div>
        </div>
      );

    case "content_match":
      return (
        <div className="flex items-center gap-2 flex-wrap">
          <Input
            value={(condition.keywords ?? []).join(", ")}
            onChange={(e) =>
              onChange({
                ...condition,
                keywords: e.currentTarget.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
            placeholder="Comma-separated keywords"
            className="w-56 h-8 text-xs"
          />
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={condition.caseSensitive ?? false}
              onChange={(e) => onChange({ ...condition, caseSensitive: e.target.checked })}
              className="accent-primary"
            />
            case-sensitive
          </label>
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={condition.once ?? false}
              onChange={(e) => onChange({ ...condition, once: e.target.checked })}
              className="accent-primary"
            />
            once
          </label>
        </div>
      );

    case "manual":
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Output route row
// ---------------------------------------------------------------------------

function RouteRow({
  route,
  onChange,
  onRemove,
  removable,
}: {
  route: OutputRoute;
  onChange: (r: OutputRoute) => void;
  onRemove: () => void;
  removable: boolean;
}) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-border/60 bg-muted/20 px-2.5 py-2">
      <div className="w-36 shrink-0">
        <Combobox
          items={ROUTE_OPTIONS}
          value={route.kind}
          onChange={(v) => onChange(makeDefaultRoute(v ?? "event_bus"))}
        />
      </div>
      <div className="flex-1 min-w-0">
        <RouteFields route={route} onChange={onChange} />
      </div>
      {removable && (
        <Button size="icon-sm" variant="ghost" onClick={onRemove} className="h-6 w-6 shrink-0 text-destructive hover:text-destructive mt-0.5">
          <Trash2 size={11} />
        </Button>
      )}
    </div>
  );
}

function RouteFields({
  route,
  onChange,
}: {
  route: OutputRoute;
  onChange: (r: OutputRoute) => void;
}) {
  switch (route.kind) {
    case "event_bus":
      return (
        <Input
          value={route.eventKind ?? ""}
          onChange={(e) => onChange({ ...route, eventKind: e.currentTarget.value })}
          placeholder="Event name (e.g., sidecar_result)"
          className="h-8 text-xs"
        />
      );

    case "job_metadata":
      return (
        <Input
          value={route.field ?? ""}
          onChange={(e) => onChange({ ...route, field: e.currentTarget.value })}
          placeholder="Field name (e.g., description)"
          className="h-8 text-xs"
        />
      );

    case "agent_message":
      return (
        <div className="flex items-center gap-2">
          <div className="w-28">
            <Combobox
              items={ROLE_OPTIONS}
              value={route.role ?? "system"}
              onChange={(v) => onChange({ ...route, role: v ?? "system" })}
            />
          </div>
          <Input
            value={route.label ?? ""}
            onChange={(e) => onChange({ ...route, label: e.currentTarget.value })}
            placeholder="Label prefix (optional)"
            className="h-8 text-xs flex-1"
          />
        </div>
      );

    case "gate":
      return (
        <div className="flex items-center gap-2 flex-wrap">
          <Input
            value={route.verdictField ?? "verdict"}
            onChange={(e) => onChange({ ...route, verdictField: e.currentTarget.value })}
            placeholder="Verdict field"
            className="w-24 h-8 text-xs"
          />
          <Input
            value={route.reasonField ?? "reason"}
            onChange={(e) => onChange({ ...route, reasonField: e.currentTarget.value })}
            placeholder="Reason field"
            className="w-24 h-8 text-xs"
          />
          <div className="flex items-center gap-1">
            <span className="text-[11px] text-muted-foreground">timeout</span>
            <Input
              type="number"
              min={1}
              value={route.timeoutS ?? 30}
              onChange={(e) => onChange({ ...route, timeoutS: parseInt(e.currentTarget.value) || 30 })}
              className="w-16 h-8 text-xs"
            />
            <span className="text-[11px] text-muted-foreground">s</span>
          </div>
        </div>
      );

    default:
      return null;
  }
}
