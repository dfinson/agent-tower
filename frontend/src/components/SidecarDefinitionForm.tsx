import { useState, useCallback, useRef } from "react";
import { Info, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { generateSidecarDefinition } from "../api/client";
import { MicButton } from "./VoiceButton";
import { TriggerPipelineEditor, type TriggerPipeline } from "./TriggerPipelineEditor";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { Combobox } from "./ui/combobox";
import { Tooltip } from "./ui/tooltip";

export interface SidecarDefinitionFormData {
  name: string;
  description: string;
  phase: string;
  lifetime: string;
  model: string;
  systemPrompt: string;
  triggers: string; // JSON string of the triggers array
}

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
}

export function SidecarDefinitionForm({
  initial,
  onSave,
  onCancel,
  saving,
  saveLabel = "Save",
}: SidecarDefinitionFormProps) {
  const [nlInput, setNlInput] = useState("");
  const [generating, setGenerating] = useState(false);
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [phase, setPhase] = useState(initial?.phase ?? "postflight");
  const [lifetime, setLifetime] = useState(initial?.lifetime ?? "ephemeral");
  const [model, setModel] = useState(initial?.model ?? "claude-sonnet-4-20250514");
  const [systemPrompt, setSystemPrompt] = useState(initial?.systemPrompt ?? "");
  const [triggers, setTriggers] = useState<TriggerPipeline[]>(
    parseTriggersString(initial?.triggers),
  );
  const [formPopulated, setFormPopulated] = useState(!!initial?.name);
  const waveformRef = useRef<HTMLDivElement>(null);

  const handleGenerate = useCallback(async () => {
    if (!nlInput.trim()) return;
    setGenerating(true);
    try {
      const result = await generateSidecarDefinition(nlInput.trim());
      const defn = result.definition;
      setName(defn.name as string || "");
      setDescription(defn.description as string || nlInput.trim().slice(0, 200));
      setPhase(defn.phase as string || "postflight");
      setLifetime(defn.lifetime as string || "ephemeral");
      setModel(defn.model as string || "claude-sonnet-4-20250514");
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
    const definition = {
      name: name.trim(),
      description: description.trim(),
      phase,
      lifetime,
      model: model || undefined,
      systemPrompt,
      triggers,
    };
    const definitionJson = JSON.stringify(definition);
    onSave(
      { name: name.trim(), description: description.trim(), phase, lifetime, model, systemPrompt, triggers: triggersJson },
      definitionJson,
    );
  }, [name, description, phase, lifetime, model, systemPrompt, triggers, onSave]);

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
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                  e.preventDefault();
                  handleGenerate();
                }
              }}
            />
            <div className="absolute bottom-2 right-2">
              <MicButton
                onTranscript={(text) => setNlInput((prev) => (prev ? prev + " " : "") + text)}
                waveformContainerRef={waveformRef}
              />
            </div>
          </div>
          <div ref={waveformRef} />
          <div className="flex items-center justify-between">
            <p className="text-[11px] text-muted-foreground">
              {generating ? "Generating sidecar configuration…" : "Ctrl+Enter to generate"}
            </p>
            <Button
              onClick={handleGenerate}
              disabled={!nlInput.trim() || generating}
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

          {/* Identity row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
                <Tooltip content="Short human-readable summary shown in the job timeline and metrics">
                  <Label className="cursor-help w-fit">Description</Label>
                </Tooltip>
              </div>
              <Input
                value={description}
                onChange={(e) => setDescription(e.currentTarget.value)}
                placeholder="Short summary of what this sidecar does"
              />
            </div>
          </div>

          {/* Behavior row */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
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
                onChange={(v) => setLifetime(v ?? "ephemeral")}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-1.5">
                <Tooltip content="LLM model for the sidecar session. Leave default unless you need a specific model.">
                  <Label className="cursor-help w-fit">Model</Label>
                </Tooltip>
              </div>
              <Input
                value={model}
                onChange={(e) => setModel(e.currentTarget.value)}
                placeholder="claude-sonnet-4-20250514"
              />
            </div>
          </div>

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
