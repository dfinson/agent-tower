import { useEffect, useState, useCallback, useRef } from "react";
import { Trash2, Plus } from "lucide-react";
import { toast } from "sonner";
import {
  fetchPolicySettings,
  updatePolicyPreset,
  updatePolicyConfig,
  createPathRule,
  deletePathRule,
  createActionRule,
  deleteActionRule,
  createCostRule,
  deleteCostRule,
  deleteTrustGrant,
} from "../api/client";
import type { PolicyState } from "../api/client";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Spinner } from "./ui/spinner";
import { ConfirmDialog } from "./ui/confirm-dialog";
import { useStore } from "../store";

const PRESETS = [
  { value: "autonomous", label: "Autonomous", description: "Agent runs freely — observe and checkpoint only" },
  { value: "supervised", label: "Supervised", description: "Default — gates irreversible or uncontained actions" },
  { value: "strict", label: "Strict", description: "All mutations require approval" },
];

const TIERS = [
  { value: "observe", label: "Observe (○)" },
  { value: "checkpoint", label: "Checkpoint (◐)" },
  { value: "gate", label: "Gate (●)" },
];

const COST_TIERS = [
  { value: "checkpoint", label: "Checkpoint (◐)" },
  { value: "gate", label: "Gate (●)" },
];

export function PolicySettingsPanel() {
  const [policy, setPolicy] = useState<PolicyState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ type: string; id: string } | null>(null);

  // New rule forms
  const [newPathRule, setNewPathRule] = useState({ pathPattern: "", tier: "gate", reason: "" });
  const [newActionRule, setNewActionRule] = useState({ matchPattern: "", tier: "gate", reason: "" });
  const [newCostRule, setNewCostRule] = useState({ thresholdValue: "", promoteTo: "gate", reason: "" });

  // Debounced batch window
  const [localBatchWindow, setLocalBatchWindow] = useState<number | null>(null);
  const batchWindowTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchPolicySettings();
      setPolicy(data);
      setLocalBatchWindow(data.config.batchWindowSeconds);
    } catch {
      // Policy not configured yet — show empty state
      setPolicy(null);
    } finally {
      setLoading(false);
    }
  }, []);

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

  const handleAddPathRule = async () => {
    if (!newPathRule.pathPattern.trim()) return;
    try {
      await createPathRule(newPathRule);
      setNewPathRule({ pathPattern: "", tier: "gate", reason: "" });
      await load();
      toast.success("Path rule added");
    } catch (e) {
      toast.error(String(e));
    }
  };

  const handleAddActionRule = async () => {
    if (!newActionRule.matchPattern.trim()) return;
    try {
      await createActionRule(newActionRule);
      setNewActionRule({ matchPattern: "", tier: "gate", reason: "" });
      await load();
      toast.success("Action rule added");
    } catch (e) {
      toast.error(String(e));
    }
  };

  const handleAddCostRule = async () => {
    const threshold = parseFloat(newCostRule.thresholdValue);
    if (isNaN(threshold) || threshold < 0) {
      toast.error("Threshold must be a non-negative number");
      return;
    }
    try {
      await createCostRule({
        condition: "job_spend_usd_gte",
        promoteTo: newCostRule.promoteTo,
        thresholdValue: threshold,
        reason: newCostRule.reason,
      });
      setNewCostRule({ thresholdValue: "", promoteTo: "gate", reason: "" });
      await load();
      toast.success("Cost rule added");
    } catch (e) {
      toast.error(String(e));
    }
  };

  const handleDelete = async (type: string, id: string) => {
    try {
      if (type === "path") await deletePathRule(id);
      else if (type === "action") await deleteActionRule(id);
      else if (type === "cost") await deleteCostRule(id);
      else if (type === "trust") await deleteTrustGrant(id);
      await load();
      toast.success("Rule deleted");
    } catch (e) {
      toast.error(String(e));
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
          How long to accumulate gate-tier actions before presenting a batch for approval.
        </p>
      </div>

      {/* Path rules */}
      <div className="space-y-2">
        <Label>Path Rules</Label>
        {policy.pathRules.length === 0 && (
          <p className="text-xs text-muted-foreground">No path rules configured.</p>
        )}
        {policy.pathRules.map((rule) => (
          <div key={rule.id} className="flex items-center gap-2 text-xs bg-background border border-border/50 rounded px-2.5 py-1.5">
            <code className="flex-1 font-mono">{rule.pathPattern}</code>
            <span className="text-muted-foreground">{rule.tier}</span>
            <button
              onClick={() => setDeleteTarget({ type: "path", id: rule.id })}
              className="text-red-400 hover:text-red-300 p-1"
              aria-label="Delete rule"
            >
              <Trash2 size={12} />
            </button>
          </div>
        ))}
        <div className="flex gap-2 items-end">
          <Input
            placeholder="*.lock"
            value={newPathRule.pathPattern}
            onChange={(e) => setNewPathRule((r) => ({ ...r, pathPattern: e.target.value }))}
            className="flex-1 text-xs"
          />
          <select
            value={newPathRule.tier}
            onChange={(e) => setNewPathRule((r) => ({ ...r, tier: e.target.value }))}
            className="h-9 rounded-md border border-input bg-background px-2 text-xs"
          >
            {TIERS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
          <Input
            placeholder="Reason"
            value={newPathRule.reason}
            onChange={(e) => setNewPathRule((r) => ({ ...r, reason: e.target.value }))}
            className="flex-1 text-xs"
          />
          <Button size="sm" variant="outline" onClick={handleAddPathRule} className="gap-1">
            <Plus size={12} /> Add
          </Button>
        </div>
      </div>

      {/* Action rules */}
      <div className="space-y-2">
        <Label>Action Rules</Label>
        {policy.actionRules.length === 0 && (
          <p className="text-xs text-muted-foreground">No action rules configured.</p>
        )}
        {policy.actionRules.map((rule) => (
          <div key={rule.id} className="flex items-center gap-2 text-xs bg-background border border-border/50 rounded px-2.5 py-1.5">
            <code className="flex-1 font-mono">{rule.matchPattern}</code>
            <span className="text-muted-foreground">{rule.tier}</span>
            <button
              onClick={() => setDeleteTarget({ type: "action", id: rule.id })}
              className="text-red-400 hover:text-red-300 p-1"
              aria-label="Delete rule"
            >
              <Trash2 size={12} />
            </button>
          </div>
        ))}
        <div className="flex gap-2 items-end">
          <Input
            placeholder="rm -rf.*"
            value={newActionRule.matchPattern}
            onChange={(e) => setNewActionRule((r) => ({ ...r, matchPattern: e.target.value }))}
            className="flex-1 text-xs"
          />
          <select
            value={newActionRule.tier}
            onChange={(e) => setNewActionRule((r) => ({ ...r, tier: e.target.value }))}
            className="h-9 rounded-md border border-input bg-background px-2 text-xs"
          >
            {TIERS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
          <Input
            placeholder="Reason"
            value={newActionRule.reason}
            onChange={(e) => setNewActionRule((r) => ({ ...r, reason: e.target.value }))}
            className="flex-1 text-xs"
          />
          <Button size="sm" variant="outline" onClick={handleAddActionRule} className="gap-1">
            <Plus size={12} /> Add
          </Button>
        </div>
      </div>

      {/* Cost rules */}
      <div className="space-y-2">
        <Label>Cost Rules</Label>
        <p className="text-xs text-muted-foreground">
          Promote actions to a higher tier when cumulative job spend reaches a threshold.
        </p>
        {[...policy.costRules]
          .sort((a, b) => (a.thresholdValue ?? 0) - (b.thresholdValue ?? 0))
          .map((rule) => (
          <div key={rule.id} className="flex items-center gap-2 text-xs bg-background border border-border/50 rounded px-2.5 py-1.5">
            <code className="font-mono">${rule.thresholdValue?.toFixed(2) ?? "—"}</code>
            <span className="text-muted-foreground">→ {rule.promoteTo}</span>
            {rule.reason && <span className="text-muted-foreground flex-1 truncate">— {rule.reason}</span>}
            {!rule.reason && <span className="flex-1" />}
            <button
              onClick={() => setDeleteTarget({ type: "cost", id: rule.id })}
              className="text-red-400 hover:text-red-300 p-1"
              aria-label="Delete cost rule"
            >
              <Trash2 size={12} />
            </button>
          </div>
        ))}
        <div className="flex gap-2 items-end">
          <Input
            type="number"
            step="0.01"
            min="0"
            placeholder="Threshold ($)"
            value={newCostRule.thresholdValue}
            onChange={(e) => setNewCostRule((r) => ({ ...r, thresholdValue: e.target.value }))}
            className="w-32 text-xs"
          />
          <select
            value={newCostRule.promoteTo}
            onChange={(e) => setNewCostRule((r) => ({ ...r, promoteTo: e.target.value }))}
            className="h-9 rounded-md border border-input bg-background px-2 text-xs"
          >
            {COST_TIERS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
          <Input
            placeholder="Reason"
            value={newCostRule.reason}
            onChange={(e) => setNewCostRule((r) => ({ ...r, reason: e.target.value }))}
            className="flex-1 text-xs"
          />
          <Button size="sm" variant="outline" onClick={handleAddCostRule} className="gap-1">
            <Plus size={12} /> Add
          </Button>
        </div>
      </div>

      {/* Trust grants */}
      {policy.trustGrants.length > 0 && (
        <div className="space-y-2">
          <Label>Active Trust Grants</Label>
          {policy.trustGrants.map((grant) => (
            <div key={grant.id} className="flex items-center gap-2 text-xs bg-background border border-border/50 rounded px-2.5 py-1.5">
              <span className="flex-1">
                {grant.kinds.join(", ")}
                {grant.pathPattern && <code className="ml-1 font-mono">{grant.pathPattern}</code>}
                {grant.commandPattern && <code className="ml-1 font-mono">{grant.commandPattern}</code>}
                {grant.reason && <span className="text-muted-foreground ml-1">— {grant.reason}</span>}
              </span>
              {grant.expiresAt && (
                <span className="text-muted-foreground">expires {new Date(grant.expiresAt).toLocaleString()}</span>
              )}
              <button
                onClick={() => setDeleteTarget({ type: "trust", id: grant.id })}
                className="text-red-400 hover:text-red-300 p-1"
                aria-label="Revoke trust"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={async () => {
          if (deleteTarget) await handleDelete(deleteTarget.type, deleteTarget.id);
          setDeleteTarget(null);
        }}
        title="Delete Rule?"
        description="This rule will be removed. Actions will be classified using the remaining rules and defaults."
        confirmLabel="Delete"
      />
    </div>
  );
}
