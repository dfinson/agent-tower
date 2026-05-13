import { useState, useCallback, useRef, useEffect } from "react";
import { Info, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { generateSidecarDefinition, fetchModels } from "../api/client";
import { MicButton } from "./VoiceButton";
import { TriggerPipelineEditor, type TriggerPipeline } from "./TriggerPipelineEditor";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { Combobox } from "./ui/combobox";
import { Tooltip } from "./ui/tooltip";
import { Spinner } from "./ui/spinner";

export interface SidecarDefinitionFormData {
  name: string;
  description: string;
  scope: string;
  phase: string;
  lifetime: string;
  model: string;
  systemPrompt: string;
  triggers: string; // JSON string of the triggers array
  maxTurns?: number;
  timeoutS?: number;
}

const SCOPE_OPTIONS = [
  { value: "global", label: "Global", description: "All jobs, all repos" },
  { value: "repo", label: "Repository", description: "All jobs in a specific repo" },
  { value: "job", label: "Job", description: "Only this job" },
];

const PHASE_OPTIONS = [
  { value: "preflight", label: "Preflight", description: "Before the agent starts" },
  { value: "midflight", label: "Midflight", description: "During agent execution" },
  { value: "postflight", label: "Postflight", description: "After the agent finishes" },
];

const LIFETIME_OPTIONS = [
  { value: "ephemeral", label: "Ephemeral", description: "Fresh session per trigger" },
  { value: "windowed", label: "Windowed", description: "Bounded by turns or time" },
  { value: "persistent", label: "Persistent", description: "Lives for the entire phase" },
];

/** Tooltip helper — renders a small info icon with hover text. */
function FieldTip({ text }: { text: string }) {
  return (
    <Tooltip content={text} side="right">
      <span className="inline-flex text-muted-foreground cursor-help">
        <Info size={13} />
      </span>
    </Tooltip>
  );
}

const DEFAULT_TRIGGERS: TriggerPipeline[] = [{
  condition: { kind: "manual" },
  contextSources: ["job_diff"],
  promptTemplate: "{diff}",
  outputParser: { kind: "plain_text" },
  outputRoutes: [{ kind: "event_bus", eventKind: "sidecar_result" }],
}];

function parseTriggersString(raw: string | undefined): TriggerPipeline[] {
  if (!raw) return DEFAULT_TRIGGERS;
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length > 0) return parsed;
  } catch { /* fall through */ }
  return DEFAULT_TRIGGERS;
}

interface SidecarDefinitionFormProps {
  initial?: Partial<SidecarDefinitionFormData>;
  onSave: (data: SidecarDefinitionFormData, definitionJson: string) => void;
  onCancel: () => void;
  saving?: boolean;
  saveLabel?: string;
  /** Hide the "job" scope option (used when creating from settings, not from a job). */
  hideJobScope?: boolean;
}

export function SidecarDefinitionForm({
  initial,
  onSave,
  onCancel,
  saving,
  saveLabel = "Save",
  hideJobScope,
}: SidecarDefinitionFormProps) {
  const [nlInput, setNlInput] = useState("");
  const [generating, setGenerating] = useState(false);
  const [voiceState, setVoiceState] = useState<"idle" | "recording" | "transcribing">("idle");
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [scope, setScope] = useState(initial?.scope ?? "global");
  const [phase, setPhase] = useState(initial?.phase ?? "postflight");
  const [lifetime, setLifetime] = useState(initial?.lifetime ?? "ephemeral");
  const [maxTurns, setMaxTurns] = useState<number | undefined>(initial?.maxTurns);
  const [timeoutS, setTimeoutS] = useState<number | undefined>(initial?.timeoutS);
  const [model, setModel] = useState(initial?.model ?? "");
  const [systemPrompt, setSystemPrompt] = useState(initial?.systemPrompt ?? "");
  const [triggers, setTriggers] = useState<TriggerPipeline[]>(
    parseTriggersString(initial?.triggers),
  );
  const [formPopulated, setFormPopulated] = useState(!!initial?.name);
  const waveformRef = useRef<HTMLDivElement>(null);

  // Fetch available models + SDKs for the model dropdown
  const [modelOptions, setModelOptions] = useState<{ value: string; label: string; description?: string }[]>([]);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Fetch models from default SDK
        const models = await fetchModels();
        if (cancelled) return;
        const options = models
          .filter((m) => m.id)
          .map((m) => ({
            value: m.id as string,
            label: (m.name as string) || (m.id as string),
            description: m.id as string,
          }));
        setModelOptions(options);
      } catch {
        // Fallback — manual entry still works via the combobox
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleGenerate = useCallback(async () => {
    if (!nlInput.trim()) return;
    setGenerating(true);
    try {
      const result = await generateSidecarDefinition(nlInput.trim());
      const defn = result.definition;
      setName(defn.name as string || "");
      setDescription(defn.description as string || nlInput.trim().slice(0, 200));
      const sc = defn.scope as string || "global";
      // If job scope is hidden (settings context) and LLM picked job, fall back to repo
      setScope(hideJobScope && sc === "job" ? "repo" : sc);
      setPhase(defn.phase as string || "postflight");
      const lt = defn.lifetime as string || "ephemeral";
      setLifetime(lt);
      if (lt === "windowed") {
        setMaxTurns(typeof defn.maxTurns === "number" ? defn.maxTurns : undefined);
        setTimeoutS(typeof defn.timeoutS === "number" ? defn.timeoutS : undefined);
      }
      setModel(defn.model as string || "");
      setSystemPrompt(defn.systemPrompt as string || "");
      if (Array.isArray(defn.triggers) && defn.triggers.length > 0) {
        setTriggers(defn.triggers as TriggerPipeline[]);
      }
      setFormPopulated(true);
    } catch (e) {
      toast.error(`Failed to generate: ${e}`);
    } finally {
      setGenerating(false);
    }
  }, [nlInput]);

  const handleSave = useCallback(() => {
    if (!name.trim()) {
      toast.error("Name is required");
      return;
    }
    if (!description.trim()) {
      toast.error("Description is required");
      return;
    }
    if (triggers.length === 0) {
      toast.error("At least one trigger is required");
      return;
    }
    const triggersJson = JSON.stringify(triggers);
    const definition: Record<string, unknown> = {
      name: name.trim(),
      description: description.trim(),
      scope,
      phase,
      lifetime,
      model: model || undefined,
      systemPrompt,
      triggers,
    };
    if (lifetime === "windowed") {
      if (maxTurns !== undefined) definition.maxTurns = maxTurns;
      if (timeoutS !== undefined) definition.timeoutS = timeoutS;
    }
    const definitionJson = JSON.stringify(definition);
    onSave(
      { name: name.trim(), description: description.trim(), scope, phase, lifetime, model, systemPrompt, triggers: triggersJson, maxTurns, timeoutS },
      definitionJson,
    );
  }, [name, description, scope, phase, lifetime, maxTurns, timeoutS, model, systemPrompt, triggers, onSave]);

  return (
    <div className="flex flex-col gap-5">
      {/* ── NL input with voice ── */}
      {!initial?.name && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-1.5">
            <Label className="text-sm">Describe what you want</Label>
            <FieldTip text="Describe the sidecar's purpose in plain language. The LLM will generate a full configuration from your description." />
          </div>
          <div className="relative">
            <Textarea
              value={nlInput}
              onChange={(e) => setNlInput(e.target.value)}
              placeholder="e.g., Review every file change for security issues and flag anything OWASP top 10"
              autoResize
              className="min-h-[52px] pr-11"
              disabled={voiceState === "transcribing"}
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                  e.preventDefault();
                  handleGenerate();
                }
              }}
            />
            <div className="absolute bottom-2 right-2">
              {voiceState === "transcribing" ? (
                <Spinner size="sm" />
              ) : (
                <MicButton
                  onTranscript={(text) => setNlInput((prev) => (prev ? prev + " " : "") + text)}
                  waveformContainerRef={waveformRef}
                  onStateChange={setVoiceState}
                />
              )}
            </div>
          </div>
          <div ref={waveformRef} />
          <div className="flex items-center justify-between">
            <p className="text-[11px] text-muted-foreground">
              {voiceState === "transcribing"
                ? "Transcribing…"
                : generating
                  ? "Generating sidecar configuration…"
                  : "Ctrl+Enter to generate"}
            </p>
            <Button
              onClick={handleGenerate}
              disabled={!nlInput.trim() || generating || voiceState !== "idle"}
              loading={generating}
              size="sm"
            >
              <Sparkles size={14} />
              Generate
            </Button>
          </div>
        </div>
      )}

      {/* ── Config form ── */}
      {(formPopulated || initial?.name) && (
        <>
          {!initial?.name && <hr className="border-border" />}

          {/* Identity: name + description */}
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-1.5">
                <Tooltip content="Unique kebab-case identifier for this sidecar">
                  <Label className="cursor-help w-fit">Name</Label>
                </Tooltip>
              </div>
              <Input
                value={name}
                onChange={(e) => setName(e.currentTarget.value)}
                placeholder="e.g., security-reviewer"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-1.5">
                <Tooltip content="Human-readable summary shown in the job timeline, metrics, and transcript. Supports multiple lines for detailed descriptions.">
                  <Label className="cursor-help w-fit">Description</Label>
                </Tooltip>
              </div>
              <Textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What this sidecar does, when it runs, what it watches for…"
                autoResize
                className="min-h-[56px]"
              />
            </div>
          </div>

          {/* Behavior: scope + phase + lifetime + model */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-1.5">
                <Tooltip content="Where this sidecar applies: globally across all jobs, per repository, or for a single job">
                  <Label className="cursor-help w-fit">Scope</Label>
                </Tooltip>
              </div>
              <Combobox
                items={hideJobScope ? SCOPE_OPTIONS.filter((o) => o.value !== "job") : SCOPE_OPTIONS}
                value={scope}
                onChange={(v) => setScope(v ?? "global")}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-1.5">
                <Tooltip content="When the sidecar is active relative to the agent's lifecycle">
                  <Label className="cursor-help w-fit">Phase</Label>
                </Tooltip>
              </div>
              <Combobox
                items={PHASE_OPTIONS}
                value={phase}
                onChange={(v) => setPhase(v ?? "postflight")}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-1.5">
                <Tooltip content="How long the sidecar's LLM session persists between triggers">
                  <Label className="cursor-help w-fit">Lifetime</Label>
                </Tooltip>
              </div>
              <Combobox
                items={LIFETIME_OPTIONS}
                value={lifetime}
                onChange={(v) => {
                  const next = v ?? "ephemeral";
                  setLifetime(next);
                  if (next !== "windowed") {
                    setMaxTurns(undefined);
                    setTimeoutS(undefined);
                  }
                }}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-1.5">
                <Tooltip content="LLM model for the sidecar session. The generator picks the cheapest viable option; override here if needed.">
                  <Label className="cursor-help w-fit">Model</Label>
                </Tooltip>
              </div>
              <Combobox
                items={modelOptions.length > 0 ? modelOptions : [
                  { value: "claude-sonnet-4-20250514", label: "Claude Sonnet 4" },
                  { value: "gpt-4o-mini", label: "GPT-4o Mini" },
                  { value: "gpt-4o", label: "GPT-4o" },
                ]}
                value={model || null}
                onChange={(v) => setModel(v ?? "")}
                placeholder="Auto (cheapest viable)"
              />
            </div>
          </div>

          {/* Windowed lifetime parameters */}
          {lifetime === "windowed" && (
            <div className="rounded-md border border-border/60 bg-muted/20 p-3">
              <div className="flex items-center gap-1.5 mb-2">
                <Label className="text-[11px] uppercase tracking-wide text-muted-foreground">
                  Window Bounds
                </Label>
                <FieldTip text="The session resets when either limit is reached. Leave blank for no limit on that dimension." />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="flex flex-col gap-1.5">
                  <Tooltip content="Maximum number of LLM calls before the session resets. Leave empty for unlimited turns.">
                    <Label className="text-xs cursor-help w-fit">Max Turns</Label>
                  </Tooltip>
                  <Input
                    type="number"
                    min={1}
                    value={maxTurns ?? ""}
                    onChange={(e) => {
                      const v = e.currentTarget.value;
                      setMaxTurns(v ? parseInt(v) || undefined : undefined);
                    }}
                    placeholder="No limit"
                    className="h-8 text-xs"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Tooltip content="Maximum seconds before the session resets. Leave empty for no time limit.">
                    <Label className="text-xs cursor-help w-fit">Timeout (seconds)</Label>
                  </Tooltip>
                  <Input
                    type="number"
                    min={1}
                    value={timeoutS ?? ""}
                    onChange={(e) => {
                      const v = e.currentTarget.value;
                      setTimeoutS(v ? parseInt(v) || undefined : undefined);
                    }}
                    placeholder="No limit"
                    className="h-8 text-xs"
                  />
                </div>
              </div>
            </div>
          )}

          {/* Ephemeral context hint */}
          {lifetime === "ephemeral" && (
            <p className="text-[11px] text-muted-foreground -mt-2">
              Each trigger fire creates a fresh LLM session with no conversation history. Context is provided solely via the trigger's context sources.
            </p>
          )}

          {/* Persistent hint */}
          {lifetime === "persistent" && (
            <p className="text-[11px] text-muted-foreground -mt-2">
              The session persists for the entire phase. All trigger outputs accumulate as conversation history, giving the sidecar full context of its previous decisions.
            </p>
          )}

          {/* System prompt */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5">
              <Tooltip content="Instructions that define the sidecar's role and behavior. This is the system prompt for its LLM session.">
                <Label className="cursor-help w-fit">System Prompt</Label>
              </Tooltip>
            </div>
            <Textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="Instructions for the sidecar LLM session…"
              autoResize
              className="min-h-[80px]"
            />
          </div>

          {/* Triggers */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5">
              <Tooltip content="Pipeline stages that fire this sidecar. Each trigger has a condition, context, prompt template, parser, and output routes.">
                <Label className="cursor-help w-fit">Triggers</Label>
              </Tooltip>
            </div>
            <TriggerPipelineEditor value={triggers} onChange={setTriggers} />
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={onCancel}>Cancel</Button>
            <Button onClick={handleSave} loading={saving} disabled={!name.trim()}>
              {saveLabel}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
