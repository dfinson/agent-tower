import { useEffect, useId, useState, useCallback } from "react";
import { Save, Bell } from "lucide-react";
import { toast } from "sonner";
import {
  fetchSettings, updateSettings,
  fetchProjects,
  fetchVapidKey, subscribePush, unsubscribePush,
} from "../api/client";
import type { Settings } from "../api/types";
import type { ProjectResponse } from "../api/types";
import { Link } from "react-router-dom";
import { PolicySettingsPanel } from "./PolicySettingsPanel";
import { IntegrationsSettings } from "./IntegrationsSettings";
import { TrackerSyncPanel } from "./TrackerSyncPanel";
import { SidecarLibraryPanel } from "./SidecarLibraryPanel";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Spinner } from "./ui/spinner";

function NumberField({ label, value, onChange, min, max, description, placeholder }: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  description?: string;
  placeholder?: string;
}) {
  const inputId = useId();
  const [raw, setRaw] = useState(String(value));

  useEffect(() => {
    setRaw(String(value));
  }, [value]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const str = e.target.value.replace(/[^0-9]/g, "");
    setRaw(str);
    if (str !== "") {
      const num = parseInt(str, 10);
      if (!isNaN(num)) {
        onChange(num);
      }
    }
  };

  const handleBlur = () => {
    if (raw === "" || isNaN(parseInt(raw, 10))) {
      setRaw(String(value));
      return;
    }
    const num = parseInt(raw, 10);
    const clamped = Math.max(min ?? 0, Math.min(max ?? Infinity, num));
    setRaw(String(clamped));
    onChange(clamped);
  };

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={inputId}>{label}</Label>
      <Input
        id={inputId}
        type="text"
        inputMode="numeric"
        pattern="[0-9]*"
        value={raw}
        onChange={handleChange}
        onBlur={handleBlur}
        className="w-32"
        placeholder={placeholder}
      />
      {description && <p className="text-xs text-muted-foreground">{description}</p>}
    </div>
  );
}

export function SettingsScreen() {
  const [loading, setLoading] = useState(true);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [saved, setSaved] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [pushEnabled, setPushEnabled] = useState(false);
  const [pushLoading, setPushLoading] = useState(false);

  const pushSupported = "serviceWorker" in navigator && "PushManager" in window;

  useEffect(() => {
    Promise.all([fetchSettings(), fetchProjects()])
      .then(([s, projectsRes]) => {
        setSettings(s);
        setSaved(s);
        setProjects(projectsRes.items);
      })
      .catch(() => toast.error("Failed to load settings"))
      .finally(() => setLoading(false));
  }, []);

  // Check whether a push subscription already exists and re-register with
  // the server (subscriptions survive in the browser but the server may have
  // restarted and lost its registry). The endpoint URL is the idempotency
  // key on the server side, so duplicate POSTs are harmless.
  useEffect(() => {
    if (!pushSupported) return;
    navigator.serviceWorker.ready
      .then((reg) => reg.pushManager.getSubscription())
      .then((sub) => {
        if (!sub) {
          setPushEnabled(false);
          return;
        }
        // Re-register with server; only mark enabled after server confirms.
        subscribePush(sub.toJSON() as PushSubscriptionJSON)
          .then(() => setPushEnabled(true))
          .catch((err) => {
            console.warn("Push re-registration failed; notifications may not work until next visit", err);
            toast.error("Push re-registration failed");
            setPushEnabled(false);
          });
      })
      .catch(() => {});
  }, [pushSupported]);

  const togglePush = useCallback(async () => {
    if (!pushSupported) return;
    setPushLoading(true);
    try {
      const reg = await navigator.serviceWorker.ready;
      if (pushEnabled) {
        const sub = await reg.pushManager.getSubscription();
        if (sub) {
          await unsubscribePush(sub.endpoint);
          await sub.unsubscribe();
        }
        setPushEnabled(false);
        toast.success("Push notifications disabled");
      } else {
        const { publicKey } = await fetchVapidKey();
        // Convert URL-safe base64 to Uint8Array
        const padding = "=".repeat((4 - (publicKey.length % 4)) % 4);
        const raw = atob(publicKey.replace(/-/g, "+").replace(/_/g, "/") + padding);
        const key = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i++) key[i] = raw.charCodeAt(i);

        const sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: key,
        });
        await subscribePush(sub.toJSON());
        setPushEnabled(true);
        toast.success("Push notifications enabled");
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes("denied") || msg.includes("NotAllowedError")) {
        toast.error("Notification permission denied by browser");
      } else {
        toast.error(`Push notification error: ${msg}`);
      }
    } finally {
      setPushLoading(false);
    }
  }, [pushEnabled, pushSupported]);

  const dirty = settings !== null && saved !== null && JSON.stringify(settings) !== JSON.stringify(saved);

  const handleSave = useCallback(async () => {
    if (!settings) return;
    setSaving(true);
    try {
      const res = await updateSettings(settings);
      setSettings(res);
      setSaved(res);
      toast.success("Settings saved");
    } catch (e) {
      toast.error(String(e));
    } finally {
      setSaving(false);
    }
  }, [settings]);

  const handleReset = useCallback(() => {
    if (saved) setSettings(saved);
  }, [saved]);

  const patch = useCallback((partial: Partial<Settings>) => {
    setSettings((prev) => prev ? { ...prev, ...partial } : prev);
  }, []);

  if (loading || !settings) {
    return (
      <div className="flex justify-center py-20">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Settings</h3>
        {dirty && (
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={handleReset}>Reset</Button>
            <Button size="sm" onClick={handleSave} loading={saving}>
              <Save size={14} />
              Save
            </Button>
          </div>

        )}
      </div>

      <div className="rounded-lg border border-border bg-card p-5">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-semibold">Projects ({projects.length})</span>
          <span className="text-xs text-muted-foreground">Manage membership from each Project</span>
        </div>
        {projects.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-3">No Projects registered</p>
        ) : (
          <div className="space-y-1">
            {projects.map((project) => (
              <Link key={project.id} to={`/projects/id/${encodeURIComponent(project.id)}/settings`} className="flex items-center justify-between rounded-md px-3 py-2 hover:bg-accent">
                <span className="text-sm">{project.name}</span>
                <span className="text-xs text-muted-foreground">{project.repoPaths.length} repos</span>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* Runtime */}
      <div className="rounded-lg border border-border bg-card p-5">
        <p className="text-sm font-semibold mb-4">Runtime</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <NumberField
            label="Max Concurrent Jobs"
            value={settings.maxConcurrentJobs}
            onChange={(v) => patch({ maxConcurrentJobs: v })}
            min={1}
            max={10}
            placeholder="5"
            description="Maximum number of agent jobs that can run simultaneously."
          />
        </div>
      </div>

      {/* Action Policy */}
      <PolicySettingsPanel />

      {/* Integrations */}
      <IntegrationsSettings />

      <TrackerSyncPanel />

      {/* Retention */}
      <div className="rounded-lg border border-border bg-card p-5">
        <p className="text-sm font-semibold mb-4">Retention</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <NumberField
            label="Artifact Retention (days)"
            value={settings.artifactRetentionDays}
            onChange={(v) => patch({ artifactRetentionDays: v })}
            min={1}
            max={365}
            placeholder="30"
            description="Artifacts older than this are automatically deleted."
          />
          <NumberField
            label="Max Artifact Size (MB)"
            value={settings.maxArtifactSizeMb}
            onChange={(v) => patch({ maxArtifactSizeMb: v })}
            min={1}
            max={10000}
            placeholder="500"
            description="Maximum size for individual job artifacts."
          />
          <NumberField
            label="Auto-archive (days)"
            value={settings.autoArchiveDays}
            onChange={(v) => patch({ autoArchiveDays: v })}
            min={1}
            max={365}
            placeholder="30"
            description="Jobs older than this are automatically archived."
          />
        </div>
      </div>



      {/* Notifications */}
      {pushSupported && (
        <div className="rounded-lg border border-border bg-card p-5">
          <h3 className="text-sm font-semibold mb-4">Notifications</h3>
          <div
            className="flex items-center gap-3 cursor-pointer min-h-[44px]"
            role="switch"
            aria-checked={pushEnabled}
            aria-label="Push notifications"
            tabIndex={0}
            onClick={togglePush}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); togglePush(); } }}
          >
            <span
              className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors shrink-0 ${
                pushEnabled ? "bg-primary" : "bg-muted"
              } ${pushLoading ? "opacity-50" : ""}`}
              aria-hidden="true"
            >
              <span
                className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform ${
                  pushEnabled ? "translate-x-6" : "translate-x-1"
                }`}
              />
            </span>
            <div className="flex items-center gap-2">
              <Bell size={16} className="text-muted-foreground" />
              <span className="text-sm">Push notifications</span>
            </div>
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            Receive browser notifications when a job needs approval, completes, or fails.
          </p>
        </div>
      )}

      {/* Sidecar Templates */}
      <div className="rounded-lg border border-border bg-card p-5">
        <SidecarLibraryPanel />
      </div>

    </div>
  );
}
