import { useEffect, useState, useCallback, useRef } from "react";
import { toast } from "sonner";
import {
  fetchPolicySettings,
  updatePolicyPreset,
  updatePolicyConfig,
  updateUsdCeilings,
} from "../api/client";
import type { PolicyState, UsdCeiling } from "../api/client";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Tooltip } from "./ui/tooltip";
import { Spinner } from "./ui/spinner";
import { useStore } from "../store";

const PRESETS = [
  { value: "autonomous", label: "Autonomous", description: "Broad autonomy. Protected paths and destructive-op budgets still escalate to you." },
  { value: "supervised", label: "Supervised", description: "Moderate budget and spend ceilings. Network and higher-risk actions escalate for review." },
  { value: "locked", label: "Locked", description: "Tight budgets and spend ceilings. Protected paths are denied; most actions need approval." },
];

const CEILING_PRESETS = ["autonomous", "supervised", "locked"] as const;

/** A dollar field: empty string ↔ null (no limit); otherwise a non-negative number. */
function parseUsd(raw: string): number | null {
  const t = raw.trim();
  if (t === "") return null;
  const v = parseFloat(t);
  return isNaN(v) || v < 0 ? null : v;
}

function usdToInput(v: number | null): string {
  return v == null ? "" : String(v);
}

export function PolicySettingsPanel() {
  const [policy, setPolicy] = useState<PolicyState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Debounced batch window
  const [localBatchWindow, setLocalBatchWindow] = useState<number | null>(null);
  const batchWindowTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Local per-preset USD ceiling edits (string-backed so a cleared field = no limit)
  const [ceilingEdits, setCeilingEdits] = useState<Record<string, { warn: string; ceiling: string }>>({});
  const [savingCeilings, setSavingCeilings] = useState(false);

  const syncCeilingEdits = useCallback((ceilings: Record<string, UsdCeiling>) => {
    const next: Record<string, { warn: string; ceiling: string }> = {};
    for (const preset of CEILING_PRESETS) {
      const entry = ceilings[preset] ?? { warnUsd: null, ceilingUsd: null };
      next[preset] = { warn: usdToInput(entry.warnUsd), ceiling: usdToInput(entry.ceilingUsd) };
    }
    setCeilingEdits(next);
  }, []);

  const load = useCallback(async () => {
    try {
      const data = await fetchPolicySettings();
      setPolicy(data);
      setLocalBatchWindow(data.config.batchWindowSeconds);
      syncCeilingEdits(data.usdCeilings);
    } catch {
      // Policy not configured yet — show empty state
      setPolicy(null);
    } finally {
      setLoading(false);
    }
  }, [syncCeilingEdits]);

  useEffect(() => { load(); }, [load]);

  // Re-fetch when another client changes policy settings (SSE event)
  const policySettingsVersion = useStore((s) => s.policySettingsVersion);
  useEffect(() => {
    if (policySettingsVersion > 0) load();
  }, [policySettingsVersion, load]);

  const handlePresetChange = async (preset: string) => {
    setSaving(true);
    try {
      const config = await updatePolicyPreset(preset);
      setPolicy((p) => p ? { ...p, config } : p);
      toast.success(`Preset changed to ${preset}`);
    } catch (e) {
      toast.error(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleBatchWindowChange = useCallback((value: number) => {
    setLocalBatchWindow(value);
    if (batchWindowTimer.current) clearTimeout(batchWindowTimer.current);
    batchWindowTimer.current = setTimeout(async () => {
      setSaving(true);
      try {
        const config = await updatePolicyConfig({ batchWindowSeconds: value });
        setPolicy((p) => p ? { ...p, config } : p);
      } catch (e) {
        toast.error(String(e));
      } finally {
        setSaving(false);
      }
    }, 500);
  }, []);

  const handleSaveCeilings = async () => {
    setSavingCeilings(true);
    try {
      const payload: Record<string, UsdCeiling> = {};
      for (const preset of CEILING_PRESETS) {
        const edit = ceilingEdits[preset] ?? { warn: "", ceiling: "" };
        payload[preset] = { warnUsd: parseUsd(edit.warn), ceilingUsd: parseUsd(edit.ceiling) };
      }
      const result = await updateUsdCeilings(payload);
      setPolicy((p) => p ? { ...p, usdCeilings: result.ceilings } : p);
      syncCeilingEdits(result.ceilings);
      toast.success("Spend ceilings saved");
    } catch (e) {
      toast.error(String(e));
    } finally {
      setSavingCeilings(false);
    }
  };

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-5">
        <p className="text-sm font-semibold mb-4">Action Policy</p>
        <div className="flex justify-center py-4"><Spinner /></div>
      </div>
    );
  }

  if (!policy) {
    return (
      <div className="rounded-lg border border-border bg-card p-5">
        <p className="text-sm font-semibold mb-2">Action Policy</p>
        <p className="text-xs text-muted-foreground">
          No policy configured. Run the database migration to enable the action policy system.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card p-5 space-y-5">
      <p className="text-sm font-semibold">Action Policy</p>

      {/* Preset selector */}
      <div className="space-y-2">
        <Label>Preset</Label>
        <div className="grid gap-2 sm:grid-cols-3">
          {PRESETS.map((p) => (
            <button
              key={p.value}
              disabled={saving}
              onClick={() => handlePresetChange(p.value)}
              className={`text-left rounded-md border px-3 py-2 text-xs transition-colors ${
                policy.config.preset === p.value
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border bg-background text-foreground hover:bg-muted"
              }`}
            >
              <span className="font-medium">{p.label}</span>
              <p className="text-muted-foreground mt-0.5">{p.description}</p>
            </button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          Each preset selects a TraceForge governance profile — its rules, protected paths, and
          tool-call budget. Fine-grained rule authoring is governed by TraceForge, not CodePlane.
        </p>
      </div>

      {/* Batch window */}
      <div className="space-y-1.5">
        <Label>Batch Window (seconds)</Label>
        <Input
          type="number"
          step="0.5"
          min="0.5"
          max="30"
          value={localBatchWindow ?? policy.config.batchWindowSeconds}
          onChange={(e) => {
            const v = parseFloat(e.target.value);
            if (!isNaN(v)) handleBatchWindowChange(v);
          }}
          className="w-32"
        />
        <p className="text-xs text-muted-foreground">
          How long to accumulate actions needing approval before presenting a batch.
        </p>
      </div>

      {/* Per-preset USD spend ceilings */}
      <div className="space-y-2">
        <Tooltip content="When a job's cumulative spend reaches these dollar amounts, actions are escalated for approval. Leave blank for no limit.">
          <Label className="cursor-help w-fit">Spend Ceilings (USD, per preset)</Label>
        </Tooltip>
        <div className="grid grid-cols-[7rem_1fr_1fr] gap-2 items-center text-xs text-muted-foreground">
          <span />
          <span>Warn at ($)</span>
          <span>Escalate at ($)</span>
        </div>
        {CEILING_PRESETS.map((preset) => {
          const edit = ceilingEdits[preset] ?? { warn: "", ceiling: "" };
          return (
            <div key={preset} className="grid grid-cols-[7rem_1fr_1fr] gap-2 items-center">
              <span className="text-xs capitalize text-foreground/80">{preset}</span>
              <Input
                type="number"
                step="0.01"
                min="0"
                placeholder="none"
                value={edit.warn}
                onChange={(e) => setCeilingEdits((c) => ({ ...c, [preset]: { ...edit, warn: e.target.value } }))}
                className="text-xs"
              />
              <Input
                type="number"
                step="0.01"
                min="0"
                placeholder="none"
                value={edit.ceiling}
                onChange={(e) => setCeilingEdits((c) => ({ ...c, [preset]: { ...edit, ceiling: e.target.value } }))}
                className="text-xs"
              />
            </div>
          );
        })}
        <div className="flex justify-end">
          <Button size="sm" variant="outline" disabled={savingCeilings} onClick={handleSaveCeilings}>
            {savingCeilings ? "Saving…" : "Save ceilings"}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Enforced natively as a TraceForge policy assessor alongside the profile's tool-call budget.
        </p>
      </div>
    </div>
  );
}
