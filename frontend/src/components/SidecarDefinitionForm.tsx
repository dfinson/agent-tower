import { useState, useCallback } from "react";
import { Sparkles } from "lucide-react";
import { toast } from "sonner";
import { generateSidecarDefinition } from "../api/client";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { Combobox } from "./ui/combobox";

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
  { value: "preflight", label: "Preflight", description: "Runs before the agent starts" },
  { value: "midflight", label: "Midflight", description: "Runs during agent execution" },
  { value: "postflight", label: "Postflight", description: "Runs after the agent finishes" },
];

const LIFETIME_OPTIONS = [
  { value: "ephemeral", label: "Ephemeral", description: "Single completion, then discarded" },
  { value: "windowed", label: "Windowed", description: "Lives for a bounded window" },
  { value: "persistent", label: "Persistent", description: "Lives for the entire job" },
];

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
  const [triggers, setTriggers] = useState(initial?.triggers ?? '[{"condition":{"kind":"manual"},"contextSources":["job_diff"],"promptTemplate":"{diff}","outputParser":{"kind":"plain_text"},"outputRoutes":[{"kind":"event_bus","eventKind":"sidecar_result"}]}]');
  const [formPopulated, setFormPopulated] = useState(!!initial?.name);

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
      if (defn.triggers) {
        setTriggers(JSON.stringify(defn.triggers, null, 2));
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
    // Build the full definition JSON
    let parsedTriggers;
    try {
      parsedTriggers = JSON.parse(triggers);
    } catch {
      toast.error("Invalid triggers JSON");
      return;
    }
    const definition = {
      name: name.trim(),
      description: description.trim(),
      phase,
      lifetime,
      model: model || undefined,
      systemPrompt,
      triggers: parsedTriggers,
    };
    const definitionJson = JSON.stringify(definition);
    onSave(
      { name: name.trim(), description: description.trim(), phase, lifetime, model, systemPrompt, triggers },
      definitionJson,
    );
  }, [name, description, phase, lifetime, model, systemPrompt, triggers, onSave]);

  return (
    <div className="flex flex-col gap-4">
      {/* NL input for generation */}
      {!initial?.name && (
        <div className="flex flex-col gap-2">
          <Label>Describe what you want</Label>
          <div className="flex gap-2">
            <div className="flex-1">
              <Textarea
                value={nlInput}
                onChange={(e) => setNlInput(e.target.value)}
                placeholder="e.g., Review every file change for security issues and flag OWASP top 10"
                autoResize
                className="min-h-[44px]"
                onKeyDown={(e) => {
                  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                    e.preventDefault();
                    handleGenerate();
                  }
                }}
              />
            </div>
            <Button
              onClick={handleGenerate}
              disabled={!nlInput.trim() || generating}
              loading={generating}
              size="sm"
              className="shrink-0 self-end"
            >
              <Sparkles size={14} />
              Generate
            </Button>
          </div>
          {generating && (
            <p className="text-xs text-muted-foreground">Generating sidecar configuration…</p>
          )}
        </div>
      )}

      {/* Form fields — shown once populated or when editing */}
      {(formPopulated || initial?.name) && (
        <>
          <hr className="border-border" />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="flex flex-col gap-1.5">
              <Label>Name</Label>
              <Input
                value={name}
                onChange={(e) => setName(e.currentTarget.value)}
                placeholder="e.g., security-reviewer"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Description</Label>
              <Input
                value={description}
                onChange={(e) => setDescription(e.currentTarget.value)}
                placeholder="Short summary"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Combobox
              label="Phase"
              items={PHASE_OPTIONS}
              value={phase}
              onChange={(v) => setPhase(v ?? "postflight")}
            />
            <Combobox
              label="Lifetime"
              items={LIFETIME_OPTIONS}
              value={lifetime}
              onChange={(v) => setLifetime(v ?? "ephemeral")}
            />
            <div className="flex flex-col gap-1.5">
              <Label>Model</Label>
              <Input
                value={model}
                onChange={(e) => setModel(e.currentTarget.value)}
                placeholder="claude-sonnet-4-20250514"
              />
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>System Prompt</Label>
            <Textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="Instructions for the sidecar LLM session"
              autoResize
              className="min-h-[80px]"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Triggers (JSON)</Label>
            <Textarea
              value={triggers}
              onChange={(e) => setTriggers(e.target.value)}
              autoResize
              className="min-h-[80px] font-mono text-xs"
            />
            <p className="text-[11px] text-muted-foreground">
              Trigger pipeline config. Conditions: event, threshold, manual.
              Context sources: trigger_event, job_diff, job_prompt, recent_messages.
            </p>
          </div>

          <div className="flex justify-end gap-2">
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
