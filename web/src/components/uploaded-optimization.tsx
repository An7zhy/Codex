"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge, BusyLabel, ErrorState, Field, PageHeading, Panel } from "@/components/ui/primitives";
import { useAccess } from "@/components/access";
import { useWorkspace } from "@/components/workspace-provider";
import { AllocationResults } from "@/components/optimization-results";
import { useSessionDraft } from "@/lib/session-draft";
import { api, jsonBody } from "@/lib/utils";
import type { OptimizationRun } from "@/lib/types";

type ImportSummary = { import_id: string; status: string; created_at: string; created_by: string; confirmed_by: string | null; confirmed_at: string | null };
type PlanningImport = ImportSummary & { confirmation: string; record: {
  schema: string; policy: string[]; files: { filename: string; bytes: number; sha256: string }[];
  validation: { valid: boolean; error_count: number; errors: { table: string; row: number; field: string; message: string }[]; warnings: string[]; payload: { source_label: string; data_kind: string; declarations: Record<string, Record<string, number>>; constraints: Record<string, unknown> } | null };
  row_counts: Record<string, number>; tables: Record<string, Record<string, unknown>[]>;
  candidate_preview: { individually_eligible?: number; candidate_count?: number; notice?: string; excluded_sample?: { shipment_id: string; service_id: string; rejection_reasons: string }[] };
} };
const sections = ["shipments", "transport_options", "capacity", "constraints"];

export function UploadedOptimization() {
  const user = useAccess(), { notify } = useWorkspace();
  const [selectedId, setSelectedId, ready] = useSessionDraft("planning-import-selection", "");
  const [format, setFormat] = useSessionDraft("planning-upload-format", "xlsx");
  const [runId, setRunId] = useSessionDraft("planning-last-run", "");
  const [files, setFiles] = useState<Record<string, File>>({});
  const [imports, setImports] = useState<ImportSummary[]>([]);
  const [preview, setPreview] = useState<PlanningImport | null>(null);
  const [run, setRun] = useState<OptimizationRun | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [acknowledged, setAcknowledged] = useState(false);
  const canWrite = user?.role !== "viewer";
  async function reloadImports() { setImports(await api<ImportSummary[]>("/planning/imports")); }
  useEffect(() => { void reloadImports().catch((err) => setError(err.message)); }, []);
  useEffect(() => {
    if (!ready) return;
    setPreview(null); setAcknowledged(false); setError("");
    if (selectedId) api<PlanningImport>(`/planning/imports/${selectedId}`).then(setPreview).catch((err) => setError(err.message));
  }, [selectedId, ready]);
  useEffect(() => {
    if (!ready || !runId) return;
    api<OptimizationRun>(`/optimization/runs/${runId}`).then(setRun).catch(() => { setRunId(""); });
  }, [ready, runId]);
  async function upload(event: React.FormEvent) {
    event.preventDefault(); setError("");
    const names = format === "xlsx" ? ["workbook"] : sections;
    if (names.some((name) => !files[name])) { setError("Select every required file first."); return; }
    if (names.reduce((total, name) => total + files[name].size, 0) >= 20 * 1024 * 1024 - 8192) { setError("Files plus multipart overhead must fit the shared 20 MiB budget."); return; }
    setBusy(true);
    try {
      const form = new FormData(); names.forEach((name) => form.append(name, files[name]));
      const value = await api<PlanningImport>("/planning/imports/preview", { method: "POST", body: form });
      setSelectedId(value.import_id); setPreview(value); setAcknowledged(false);
      await reloadImports(); notify(value.record.validation.valid ? "Input preview saved. Review and confirm before solving." : "Validation failed. The import record retains the issues; correct the files and preview again.");
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }
  async function confirm() {
    if (!preview) return;
    setBusy(true); setError("");
    try {
      const result = await api<PlanningImport>(`/planning/imports/${preview.import_id}/confirm`, jsonBody({ confirmation: preview.confirmation, acknowledged }));
      setPreview(result); await reloadImports(); notify("Planning input confirmed and frozen with source/actor references.");
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }
  async function solve() {
    if (!preview) return;
    setBusy(true); setError("");
    try {
      const result = await api<OptimizationRun>("/planning/runs", jsonBody({ import_id: preview.import_id }));
      setRun(result); setRunId(result.run_id); notify(`Uploaded plan evaluated: ${result.results["Optimized Allocation"].status}.`);
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }
  return <>
    <PageHeading title="Uploaded transportation inputs" description="Validate your orders, quotes and shared capacity before using the existing V3 optimizer." action={<Badge>Uploaded Data Mode</Badge>} />
    <div className="notice notice-amber"><p>This planning import is independent of the V1/V2 shipment dataset in the top bar. User-provided does not mean independently verified. This mode uses expected times and quoted costs only. No historical distribution is supplied: <strong>reliability is not estimated</strong>; no Monte Carlo or carrier on-time prediction is shown.</p></div>
    <Panel title="Import contract and editable templates" subtitle="USD, kg, m3 and h only; full ISO timestamps with Z or an offset. No automatic currency, unit or local-time inference.">
      <div className="panel-body"><div className="toolbar-actions">
        <Button asChild variant="outline"><a href="/api/planning/templates/xlsx?count=2" download>Excel template · 2 synthetic orders</a></Button>
        <Button asChild variant="outline"><a href="/api/planning/templates/xlsx?count=100" download>100-order synthetic workbook</a></Button>
        {sections.map((name) => <a className="text-button" key={name} href={`/api/planning/templates/${name}?count=2`} download>{name} CSV template</a>)}
        <a className="text-button" href="/api/planning/contract" download>Field definitions and rules JSON</a>
      </div><p className="muted small">Templates contain labeled synthetic examples. Shared service capacity is declared once, not once per order. All shipments share planning_start; every use of a service must have the same expected transit duration. Mark quote/time/capacity as estimate or user_verified and supply references; the app does not verify those declarations.</p>
      <form onSubmit={upload}>
        <Field label="Planning file format"><select className="input" value={format} onChange={(event) => { setFormat(event.target.value); setFiles({}); }}><option value="xlsx">One Excel workbook (four sheets)</option><option value="csv">Four CSV files</option></select></Field>
        <div className="form-grid">{(format === "xlsx" ? ["workbook"] : sections).map((name) => <Field label={`Planning ${name} file`} key={`${format}:${name}`}><input className="input" type="file" accept={format === "xlsx" ? ".xlsx" : ".csv"} onChange={(event) => { const file = event.target.files?.[0]; setFiles((old) => { const next = { ...old }; if (file) next[name] = file; else delete next[name]; return next; }); }} /></Field>)}</div>
        <p className="muted small">Preview records are saved on the server. Selected browser files are not cached; return to the stored preview after navigation or refresh.</p>
        <Button type="submit" disabled={busy || !canWrite}><BusyLabel busy={busy}>Preview planning inputs</BusyLabel></Button>
      </form></div>
    </Panel>
    {error && <ErrorState message={error} />}
    <Panel className="mt-5" title="Import records" subtitle="Source hashes, uploader, confirmation and immutable input snapshot are kept in this organization instance.">
      <div className="panel-body"><Field label="Stored planning import"><select className="input" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}><option value="">Select a planning import</option>{imports.map((item) => <option key={item.import_id} value={item.import_id}>{item.created_at.slice(0,19)} · {item.status} · {item.import_id.slice(0,8)} · {item.created_by}</option>)}</select></Field></div>
      {preview && <div className="panel-body" aria-label="Planning input preview">
        <p><strong>{preview.status}</strong> · import {preview.import_id} · created by {preview.created_by}{preview.confirmed_by ? ` · confirmed by ${preview.confirmed_by}` : ""}</p>
        <p>{Object.entries(preview.record.row_counts).map(([name,count]) => `${name}: ${count}`).join(" · ")}</p>
        <p>Validation errors: <strong>{preview.record.validation.error_count}</strong>. First {preview.record.validation.errors.length} shown.</p>
        {preview.record.validation.errors.length > 0 && <div className="table-scroll"><table><thead><tr><th>Table / record</th><th>Field</th><th>Correction needed</th></tr></thead><tbody>{preview.record.validation.errors.map((row,index) => <tr key={index}><td>{row.table} · {row.row}</td><td>{row.field}</td><td>{row.message}</td></tr>)}</tbody></table></div>}
        {preview.record.validation.warnings.map((message) => <p key={message} className="notice notice-amber">{message}</p>)}
        {preview.record.validation.payload && <div className="toolbar-actions">{Object.entries(preview.record.validation.payload.declarations).map(([kind, counts]) => <Badge key={kind}>{kind}: {counts.estimate} estimates · {counts.user_verified} user-declared verified</Badge>)}</div>}
        {preview.record.policy.map((rule) => <p className="muted small" key={rule}>{rule}</p>)}
        {preview.record.validation.valid && <p>{preview.record.candidate_preview.individually_eligible} of {preview.record.candidate_preview.candidate_count} candidates pass individual checks. {preview.record.candidate_preview.notice}</p>}
        <details className="disclosure"><summary>Input preview, declarations and source hashes</summary><pre className="planning-preview-json">{JSON.stringify({ files: preview.record.files, declarations: preview.record.validation.payload?.declarations, constraints: preview.record.validation.payload?.constraints, tables: Object.fromEntries(Object.entries(preview.record.tables).map(([name,rows]) => [name, rows.slice(0,5)])), exclusions: preview.record.candidate_preview.excluded_sample }, null, 2)}</pre></details>
        <div className="toolbar-actions"><a className="text-button" href={`/api/planning/imports/${preview.import_id}/export/json`} download>Import audit JSON</a>
          {user?.role === "admin" && <Button variant="ghost" disabled={busy} onClick={async () => { if (!window.confirm("Delete this planning import and its linked runs? Separate backups are not deleted.")) return; setBusy(true); try { await api(`/planning/imports/${preview.import_id}`, { method: "DELETE" }); setSelectedId(""); setRun(null); setRunId(""); await reloadImports(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); } }}>Delete planning import</Button>}
        </div>
        {preview.status === "previewed" && <><label className="checkbox-field"><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />I reviewed the exact inputs, USD/units/timezones, shared capacity and no-reliability policy.</label><Button disabled={busy || !acknowledged || !canWrite} onClick={confirm}>Confirm planning inputs</Button></>}
        {preview.status === "confirmed" && <Button disabled={busy || !canWrite} onClick={solve}><BusyLabel busy={busy}>Solve uploaded plan</BusyLabel></Button>}
      </div>}
    </Panel>
    {busy && <p className="notice" role="status">Validating or solving the selected input. Server budgets apply; a solve worker is stopped after 45 seconds.</p>}
    {run && (run.planning_import?.import_id === selectedId ? <AllocationResults key={run.run_id} run={run} /> : <p className="notice">The last saved allocation belongs to a different import. Solve this confirmed input to display its own results.</p>)}
  </>;
}
