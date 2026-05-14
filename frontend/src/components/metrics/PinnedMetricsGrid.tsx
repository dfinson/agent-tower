/**
 * Grid of pinned custom metric tiles on the analytics dashboard.
 *
 * Each tile re-evaluates its SQL query on load and renders through
 * the appropriate viz template.
 */

import { useState, useEffect, useCallback } from "react";
import {
  Loader2, X, Settings2, AlertTriangle,
} from "lucide-react";
import {
  listCustomMetrics,
  deleteMetric,
  updateMetric,
  type CustomMetricWithData,
} from "../../api/client-metrics";
import { MetricViz } from "./VizTemplates";

interface PinnedMetricsGridProps {
  refreshKey?: number;
}

export function PinnedMetricsGrid({ refreshKey }: PinnedMetricsGridProps) {
  const [metrics, setMetrics] = useState<CustomMetricWithData[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await listCustomMetrics();
      setMetrics(resp.metrics.filter((m) => m.metric.pinDashboard));
    } catch {
      // Non-critical — grid just stays empty
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  if (loading && metrics.length === 0) return null;
  if (!metrics.length) return null;

  return (
    <div className="space-y-3">
      <h2 className="text-sm font-medium text-foreground">Pinned Metrics</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {metrics.map((m) => (
          <MetricTile key={m.metric.id} item={m} onDelete={load} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single metric tile
// ---------------------------------------------------------------------------

function MetricTile({
  item,
  onDelete,
}: {
  item: CustomMetricWithData;
  onDelete: () => void;
}) {
  const [showSettings, setShowSettings] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const { metric, data, error } = item;

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteMetric(metric.id);
      onDelete();
    } catch {
      setDeleting(false);
    }
  };

  // Tile size classes
  const sizeClass = metric.tileSize === "2x1"
    ? "md:col-span-2"
    : metric.tileSize === "2x2"
      ? "md:col-span-2 row-span-2"
      : "";

  return (
    <div className={`rounded-lg border border-border bg-card p-4 relative group ${sizeClass}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-medium text-foreground truncate">{metric.name}</h3>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={() => setShowSettings(!showSettings)}
            className="p-1 rounded hover:bg-accent/50 text-muted-foreground"
            title="Settings"
          >
            <Settings2 size={12} />
          </button>
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="p-1 rounded hover:bg-red-500/20 text-muted-foreground hover:text-red-400"
            title="Remove"
          >
            {deleting ? <Loader2 size={12} className="animate-spin" /> : <X size={12} />}
          </button>
        </div>
      </div>

      {/* Alert indicator */}
      {metric.alertEnabled && (
        <div className="flex items-center gap-1 text-xs text-amber-400 mb-2">
          <AlertTriangle size={10} />
          Alert: {metric.alertOp} {metric.alertValue}
        </div>
      )}

      {/* Content */}
      {error ? (
        <div className="text-xs text-red-400 py-4 text-center">{error}</div>
      ) : (
        <MetricViz
          viz={metric.viz}
          data={data}
          config={(metric.vizConfig ?? {}) as Record<string, unknown>}
        />
      )}

      {/* Explanation */}
      {metric.explanation && (
        <p className="text-xs text-muted-foreground mt-2 line-clamp-2">
          {metric.explanation}
        </p>
      )}

      {/* Settings popover */}
      {showSettings && (
        <TileSettings
          metric={metric}
          onClose={() => setShowSettings(false)}
          onSaved={onDelete}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tile settings popover (alert config)
// ---------------------------------------------------------------------------

function TileSettings({
  metric,
  onClose,
  onSaved,
}: {
  metric: CustomMetricWithData["metric"];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [alertEnabled, setAlertEnabled] = useState(metric.alertEnabled);
  const [alertOp, setAlertOp] = useState(metric.alertOp ?? ">");
  const [alertValue, setAlertValue] = useState(metric.alertValue ?? 0);
  const [alertSeverity, setAlertSeverity] = useState(metric.alertSeverity ?? "warning");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateMetric(metric.id, {
        alertEnabled,
        alertOp,
        alertValue,
        alertSeverity,
      });
      onSaved();
      onClose();
    } catch {
      setSaving(false);
    }
  };

  return (
    <div className="absolute right-0 top-0 z-10 w-64 rounded-lg border border-border bg-card shadow-lg p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-foreground">Alert Settings</span>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
          <X size={12} />
        </button>
      </div>

      <label className="flex items-center gap-2 text-xs text-foreground">
        <input
          type="checkbox"
          checked={alertEnabled}
          onChange={(e) => setAlertEnabled(e.target.checked)}
          className="rounded"
        />
        Enable alert
      </label>

      {alertEnabled && (
        <div className="space-y-2">
          <div className="flex gap-2">
            <select
              value={alertOp}
              onChange={(e) => setAlertOp(e.target.value)}
              className="flex-1 rounded border border-border bg-background px-2 py-1 text-xs text-foreground"
            >
              <option value=">">Greater than</option>
              <option value="<">Less than</option>
              <option value=">=">≥</option>
              <option value="<=">≤</option>
              <option value="==">Equals</option>
            </select>
            <input
              type="number"
              value={alertValue}
              onChange={(e) => setAlertValue(Number(e.target.value))}
              className="w-20 rounded border border-border bg-background px-2 py-1 text-xs text-foreground"
            />
          </div>
          <select
            value={alertSeverity}
            onChange={(e) => setAlertSeverity(e.target.value)}
            className="w-full rounded border border-border bg-background px-2 py-1 text-xs text-foreground"
          >
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="critical">Critical</option>
          </select>
        </div>
      )}

      <button
        onClick={handleSave}
        disabled={saving}
        className="w-full rounded bg-indigo-600 px-3 py-1.5 text-xs text-white hover:bg-indigo-500 disabled:opacity-50"
      >
        {saving ? "Saving..." : "Save"}
      </button>
    </div>
  );
}
