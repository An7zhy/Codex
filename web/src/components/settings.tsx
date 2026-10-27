"use client";

import { useEffect, useState } from "react";
import { Download, Save, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  BusyLabel,
  ErrorState,
  Field,
  LoadingState,
  PageHeading,
  Panel,
} from "@/components/ui/primitives";
import { useWorkspace } from "@/components/workspace-provider";
import { api, jsonBody, percent } from "@/lib/utils";
import type { PriorityConfig } from "@/lib/types";

type SettingsResponse = {
  priority: PriorityConfig;
  capabilities: Record<string, string | boolean>;
};
const labels: Record<string, string> = {
  urgency: "Deadline urgency",
  delay: "Estimated delay",
  financial: "Potential financial impact",
  value: "Shipment value",
  downstream: "Downstream disruption",
};
export function Settings() {
  const { refresh, notify, data } = useWorkspace();
  const [settings, setSettings] = useState<SettingsResponse | null>(null),
    [draft, setDraft] = useState<PriorityConfig | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    api<SettingsResponse>("/settings")
      .then((value) => {
        setSettings(value);
        setDraft(value.priority);
      })
      .catch((err) => setError(err.message));
  }, []);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!draft) return;
    setBusy(true);
    setError("");
    try {
      const saved = await api<PriorityConfig>("/settings/priority", {
        ...jsonBody(draft),
        method: "PUT",
      });
      setSettings((old) => (old ? { ...old, priority: saved } : null));
      setDraft(saved);
      refresh();
      notify(
        "Priority settings saved. Exceptions now use the applied weights.",
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function exportSettings() {
    if (!settings) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(settings.priority, null, 2)], {
        type: "application/json",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "priority_settings.json";
    a.click();
    URL.revokeObjectURL(url);
  }
  const total = draft
    ? Object.values(draft.weights).reduce((a, b) => a + b, 0)
    : 0;
  return (
    <>
      <PageHeading
        title="Workspace settings"
        description="Make the rules explicit. Keep assumptions and evidence requirements visible."
        action={
          <Button
            variant="outline"
            size="sm"
            onClick={exportSettings}
            disabled={!settings}
          >
            <Download size={13} />
            Applied settings
          </Button>
        }
      />
      {error && <ErrorState message={error} />}
      {!draft || !settings ? (
        !error && <LoadingState />
      ) : (
        <>
          <Panel
            title="Exception priority methodology"
            subtitle="These V2 settings affect triage, not V1 KPIs or V3 transportation constraints."
          >
            <form onSubmit={save}>
              <div className="form-section">
                <h3>Relative component weights</h3>
                <div className="form-grid">
                  {Object.entries(draft.weights).map(([key, value]) => (
                    <Field
                      label={`${labels[key]} weight`}
                      hint={`Draft share: ${total ? percent(value / total) : "Invalid all-zero configuration"}`}
                      key={key}
                    >
                      <input
                        className="input"
                        type="number"
                        required
                        min="0"
                        max="100000"
                        step="any"
                        value={value}
                        onChange={(e) =>
                          setDraft((old) =>
                            old
                              ? {
                                  ...old,
                                  weights: {
                                    ...old.weights,
                                    [key]: Number(e.target.value),
                                  },
                                }
                              : old,
                          )
                        }
                      />
                    </Field>
                  ))}
                </div>
              </div>
              <div className="form-section">
                <h3>Normalization scales and thresholds</h3>
                <div className="form-grid">
                  {(
                    [
                      ["Urgency window (hours)", "urgency_window_hours"],
                      ["Delay scale (hours)", "delay_scale_hours"],
                      ["Financial impact scale (USD)", "financial_scale_usd"],
                      ["Shipment value scale (USD)", "value_scale_usd"],
                      ["Dependency count scale", "dependency_scale"],
                      ["Medium priority threshold", "medium_threshold"],
                      ["High priority threshold", "high_threshold"],
                    ] as const
                  ).map(([label, key]) => (
                    <Field label={label} key={key}>
                      <input
                        className="input"
                        type="number"
                        step="any"
                        min="0.001"
                        max={key.includes("threshold") ? 100 : undefined}
                        required
                        value={draft[key]}
                        onChange={(e) =>
                          setDraft((old) =>
                            old
                              ? { ...old, [key]: Number(e.target.value) }
                              : old,
                          )
                        }
                      />
                    </Field>
                  ))}
                </div>
              </div>
              <div className="form-actions">
                <p>
                  Draft edits are applied only after saving. Settings persist in
                  local SQLite.
                </p>
                <Button type="submit" disabled={busy}>
                  <Save size={13} />
                  <BusyLabel busy={busy}>Apply priority settings</BusyLabel>
                </Button>
              </div>
            </form>
            <details className="disclosure">
              <summary>Last applied configuration</summary>
              <pre>{JSON.stringify(settings.priority, null, 2)}</pre>
            </details>
          </Panel>
          <div className="notice">
            <ShieldCheck size={17} />
            <p>
              Enabled components require valid evidence. Missing inputs produce
              Insufficient information, not a zero score. Shipment value
              represents exposure context and is never treated as realized loss.
            </p>
          </div>
          <div className="dashboard-grid dashboard-grid-equal">
            <Panel
              title="Calculation and persistence"
              subtitle="The premium interface uses the existing Python business logic."
            >
              <div className="panel-body">
                {Object.entries(settings.capabilities).map(([key, value]) => (
                  <p className="muted small mb-3" key={key}>
                    <strong>{key.replaceAll("_", " ")}:</strong>{" "}
                    {typeof value === "boolean"
                      ? value
                        ? "Yes"
                        : "No"
                      : value}
                  </p>
                ))}
              </div>
            </Panel>
            <Panel
              title="Local data and provenance"
              subtitle="This prototype is designed for one local trusted workspace."
            >
              <div className="panel-body">
                <p className="muted small">
                  Uploads, priority settings and optimization runs persist
                  locally. Exception handling history shares the original V2
                  SQLite store. Refreshing a page does not delete saved records.
                </p>
                <p className="muted small mt-4">
                  The built-in datasets are synthetic. Uploaded provenance is
                  not verified. There is no authentication, real carrier
                  connection, paid API requirement or claim of commercial
                  effectiveness.
                </p>
                <p className="muted small mt-4">
                  To use the original interface, run{" "}
                  <code>python -m streamlit run app.py</code>. Premium-web
                  priority settings are separate from Streamlit session
                  settings.
                </p>
              </div>
            </Panel>
          </div>
          {data && (
            <Panel
              title="KPI definitions"
              subtitle="Denominators and eligibility match the existing V1 engine."
            >
              <div className="panel-body">
                {Object.entries(data.definitions).map(([name, definition]) => (
                  <p className="muted small mb-4" key={name}>
                    <strong>{name}:</strong> {definition}
                  </p>
                ))}
              </div>
            </Panel>
          )}
        </>
      )}
    </>
  );
}
