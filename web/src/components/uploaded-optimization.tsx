"use client";
import { useI18n } from "@/lib/i18n/provider";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Badge,
  BusyLabel,
  ErrorState,
  Field,
  PageHeading,
  Panel,
} from "@/components/ui/primitives";
import { useAccess } from "@/components/access";
import { useWorkspace } from "@/components/workspace-provider";
import { AllocationResults } from "@/components/optimization-results";
import { useSessionDraft } from "@/lib/session-draft";
import { api, jsonBody } from "@/lib/utils";
import type { OptimizationRun } from "@/lib/types";

type ImportSummary = {
  import_id: string;
  status: string;
  created_at: string;
  created_by: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
};
type PlanningImport = ImportSummary & {
  confirmation: string;
  record: {
    schema: string;
    policy: string[];
    files: { filename: string; bytes: number; sha256: string }[];
    validation: {
      valid: boolean;
      error_count: number;
      errors: { table: string; row: number; field: string; message: string }[];
      warnings: string[];
      payload: {
        source_label: string;
        data_kind: string;
        declarations: Record<string, Record<string, number>>;
        constraints: Record<string, unknown>;
      } | null;
    };
    row_counts: Record<string, number>;
    tables: Record<string, Record<string, unknown>[]>;
    candidate_preview: {
      individually_eligible?: number;
      candidate_count?: number;
      notice?: string;
      excluded_sample?: {
        shipment_id: string;
        service_id: string;
        rejection_reasons: string;
      }[];
    };
  };
};
const sections = ["shipments", "transport_options", "capacity", "constraints"];

export function UploadedOptimization() {
  const { t } = useI18n();
  const user = useAccess(),
    { notify } = useWorkspace();
  const [selectedId, setSelectedId, ready] = useSessionDraft(
    "planning-import-selection",
    "",
  );
  const [format, setFormat] = useSessionDraft("planning-upload-format", "xlsx");
  const [runId, setRunId] = useSessionDraft("planning-last-run", "");
  const [files, setFiles] = useState<Record<string, File>>({});
  const [imports, setImports] = useState<ImportSummary[]>([]);
  const [preview, setPreview] = useState<PlanningImport | null>(null);
  const [run, setRun] = useState<OptimizationRun | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [acknowledged, setAcknowledged] = useState(false);
  const canWrite = user?.role !== "viewer";
  async function reloadImports() {
    setImports(await api<ImportSummary[]>("/planning/imports"));
  }
  useEffect(() => {
    void reloadImports().catch((err) => setError(err.message));
  }, []);
  useEffect(() => {
    if (!ready) return;
    setPreview(null);
    setAcknowledged(false);
    setError("");
    if (selectedId)
      api<PlanningImport>(`/planning/imports/${selectedId}`)
        .then(setPreview)
        .catch((err) => setError(err.message));
  }, [selectedId, ready]);
  useEffect(() => {
    if (!ready || !runId) return;
    api<OptimizationRun>(`/optimization/runs/${runId}`)
      .then(setRun)
      .catch(() => {
        setRunId("");
      });
  }, [ready, runId]);
  async function upload(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    const names = format === "xlsx" ? ["workbook"] : sections;
    if (names.some((name) => !files[name])) {
      setError("Select every required file first.");
      return;
    }
    if (
      names.reduce((total, name) => total + files[name].size, 0) >=
      20 * 1024 * 1024 - 8192
    ) {
      setError(
        "Files plus multipart overhead must fit the shared 20 MiB budget.",
      );
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      names.forEach((name) => form.append(name, files[name]));
      const value = await api<PlanningImport>("/planning/imports/preview", {
        method: "POST",
        body: form,
      });
      setSelectedId(value.import_id);
      setPreview(value);
      setAcknowledged(false);
      await reloadImports();
      notify(
        value.record.validation.valid
          ? "Input preview saved. Review and confirm before solving."
          : "Validation failed. The import record retains the issues; correct the files and preview again.",
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<PlanningImport>(
        `/planning/imports/${preview.import_id}/confirm`,
        jsonBody({ confirmation: preview.confirmation, acknowledged }),
      );
      setPreview(result);
      await reloadImports();
      notify(
        "Planning input confirmed and frozen with source/actor references.",
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function solve() {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<OptimizationRun>(
        "/planning/runs",
        jsonBody({ import_id: preview.import_id }),
      );
      setRun(result);
      setRunId(result.run_id);
      notify(
        `Uploaded plan evaluated: ${result.results["Optimized Allocation"].status}.`,
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        title={t("Uploaded transportation inputs")}
        description={t(
          "Validate your orders, quotes and shared capacity before using the existing V3 optimizer.",
        )}
        action={<Badge>{t("Uploaded Data Mode")}</Badge>}
      />
      <div className="notice notice-amber">
        <p>
          {t(
            "This planning import is independent of the V1/V2 shipment dataset in the top bar. User-provided does not mean independently verified. This mode uses expected times and quoted costs only. No historical distribution is supplied: ",
          )}
          <strong>{t("reliability is not estimated")}</strong>
          {t("; no Monte Carlo or carrier on-time prediction is shown.")}
        </p>
      </div>
      <Panel
        title={t("Import contract and editable templates")}
        subtitle={t(
          "USD, kg, m3 and h only; full ISO timestamps with Z or an offset. No automatic currency, unit or local-time inference.",
        )}
      >
        <div className="panel-body">
          <div className="toolbar-actions">
            <Button asChild variant="outline">
              <a href="/api/planning/templates/xlsx?count=2" download>
                {t("Excel template · 2 synthetic orders")}
              </a>
            </Button>
            <Button asChild variant="outline">
              <a href="/api/planning/templates/xlsx?count=100" download>
                {t("100-order synthetic workbook")}
              </a>
            </Button>
            {sections.map((name) => (
              <a
                className="text-button"
                key={name}
                href={`/api/planning/templates/${name}?count=2`}
                download
              >
                {t(name)} {t(" CSV template")}
              </a>
            ))}
            <a className="text-button" href="/api/planning/contract" download>
              {t("Field definitions and rules JSON")}
            </a>
          </div>
          <p className="muted small">
            {t(
              "Templates contain labeled synthetic examples. Shared service capacity is declared once, not once per order. All shipments share planning_start; every use of a service must have the same expected transit duration. Mark quote/time/capacity as estimate or user_verified and supply references; the app does not verify those declarations.",
            )}
          </p>
          <form onSubmit={upload}>
            <Field label={t("Planning file format")}>
              <select
                className="input"
                value={format}
                onChange={(event) => {
                  setFormat(event.target.value);
                  setFiles({});
                }}
              >
                <option value="xlsx">
                  {t("One Excel workbook (four sheets)")}
                </option>
                <option value="csv">{t("Four CSV files")}</option>
              </select>
            </Field>
            <div className="form-grid">
              {(format === "xlsx" ? ["workbook"] : sections).map((name) => (
                <Field
                  label={t(`Planning ${name} file`)}
                  key={`${format}:${name}`}
                >
                  <input
                    className="input"
                    type="file"
                    accept={format === "xlsx" ? ".xlsx" : ".csv"}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      setFiles((old) => {
                        const next = { ...old };
                        if (file) next[name] = file;
                        else delete next[name];
                        return next;
                      });
                    }}
                  />
                </Field>
              ))}
            </div>
            <p className="muted small">
              {t(
                "Preview records are saved on the server. Selected browser files are not cached; return to the stored preview after navigation or refresh.",
              )}
            </p>
            <Button type="submit" disabled={busy || !canWrite}>
              <BusyLabel busy={busy}>{t("Preview planning inputs")}</BusyLabel>
            </Button>
          </form>
        </div>
      </Panel>
      {error && <ErrorState message={t(error)} />}
      <Panel
        className="mt-5"
        title={t("Import records")}
        subtitle={t(
          "Source hashes, uploader, confirmation and immutable input snapshot are kept in this organization instance.",
        )}
      >
        <div className="panel-body">
          <Field label={t("Stored planning import")}>
            <select
              className="input"
              value={selectedId}
              onChange={(event) => setSelectedId(event.target.value)}
            >
              <option value="">{t("Select a planning import")}</option>
              {imports.map((item) => (
                <option key={item.import_id} value={item.import_id}>
                  {item.created_at.slice(0, 19)} · {t(item.status)} ·{" "}
                  {item.import_id.slice(0, 8)} · {item.created_by}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {preview && (
          <div className="panel-body" aria-label={t("Planning input preview")}>
            <p>
              <strong>{t(preview.status)}</strong> {t(" · import ")}
              {preview.import_id} {t(" · created by ")}
              {preview.created_by}
              {t(
                preview.confirmed_by
                  ? ` · confirmed by ${preview.confirmed_by}`
                  : "",
              )}
            </p>
            <p>
              {Object.entries(preview.record.row_counts)
                .map(([name, count]) => `${t(name)}: ${count}`)
                .join(" · ")}
            </p>
            <p>
              {t("Validation errors: ")}
              <strong>{t(preview.record.validation.error_count)}</strong>
              {t(". First ")}
              {t(preview.record.validation.errors.length)} {t(" shown.")}
            </p>
            {preview.record.validation.errors.length > 0 && (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>{t("Table / record")}</th>
                      <th>{t("Field")}</th>
                      <th>{t("Correction needed")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.record.validation.errors.map((row, index) => (
                      <tr key={index}>
                        <td>
                          {t(row.table)} · {t(row.row)}
                        </td>
                        <td>{row.field}</td>
                        <td>{t(row.message)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {preview.record.validation.warnings.map((message) => (
              <p key={message} className="notice notice-amber">
                {t(message)}
              </p>
            ))}
            {preview.record.validation.payload && (
              <div className="toolbar-actions">
                {Object.entries(
                  preview.record.validation.payload.declarations,
                ).map(([kind, counts]) => (
                  <Badge key={kind}>
                    {t(kind)}: {t(counts.estimate)} {t(" estimates · ")}
                    {t(counts.user_verified)} {t(" user-declared verified")}
                  </Badge>
                ))}
              </div>
            )}
            {preview.record.policy.map((rule) => (
              <p className="muted small" key={rule}>
                {t(rule)}
              </p>
            ))}
            {preview.record.validation.valid && (
              <p>
                {t(preview.record.candidate_preview.individually_eligible)}{" "}
                {t(" of ")}
                {t(preview.record.candidate_preview.candidate_count)}{" "}
                {t(" candidates pass individual checks. ")}
                {t(preview.record.candidate_preview.notice)}
              </p>
            )}
            <details className="disclosure">
              <summary>
                {t("Input preview, declarations and source hashes")}
              </summary>
              <pre className="planning-preview-json">
                {JSON.stringify(
                  {
                    files: preview.record.files,
                    declarations:
                      preview.record.validation.payload?.declarations,
                    constraints: preview.record.validation.payload?.constraints,
                    tables: Object.fromEntries(
                      Object.entries(preview.record.tables).map(
                        ([name, rows]) => [name, rows.slice(0, 5)],
                      ),
                    ),
                    exclusions:
                      preview.record.candidate_preview.excluded_sample,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
            <div className="toolbar-actions">
              <a
                className="text-button"
                href={`/api/planning/imports/${preview.import_id}/export/json`}
                download
              >
                {t("Import audit JSON")}
              </a>
              {user?.role === "admin" && (
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={async () => {
                    if (
                      !window.confirm(
                        t(
                          "Delete this planning import and its linked runs? Separate backups are not deleted.",
                        ),
                      )
                    )
                      return;
                    setBusy(true);
                    try {
                      await api(`/planning/imports/${preview.import_id}`, {
                        method: "DELETE",
                      });
                      setSelectedId("");
                      setRun(null);
                      setRunId("");
                      await reloadImports();
                    } catch (err) {
                      setError((err as Error).message);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  {t("Delete planning import")}
                </Button>
              )}
            </div>
            {preview.status === "previewed" && (
              <>
                <label className="checkbox-field">
                  <input
                    type="checkbox"
                    checked={acknowledged}
                    onChange={(event) => setAcknowledged(event.target.checked)}
                  />
                  {t(
                    "I reviewed the exact inputs, USD/units/timezones, shared capacity and no-reliability policy.",
                  )}
                </label>
                <Button
                  disabled={busy || !acknowledged || !canWrite}
                  onClick={confirm}
                >
                  {t("Confirm planning inputs")}
                </Button>
              </>
            )}
            {preview.status === "confirmed" && (
              <Button disabled={busy || !canWrite} onClick={solve}>
                <BusyLabel busy={busy}>{t("Solve uploaded plan")}</BusyLabel>
              </Button>
            )}
          </div>
        )}
      </Panel>
      {busy && (
        <p className="notice" role="status">
          {t(
            "Validating or solving the selected input. Server budgets apply; a solve worker is stopped after 45 seconds.",
          )}
        </p>
      )}
      {run &&
        (run.planning_import?.import_id === selectedId ? (
          <AllocationResults key={run.run_id} run={run} />
        ) : (
          <p className="notice">
            {t(
              "The last saved allocation belongs to a different import. Solve this confirmed input to display its own results.",
            )}
          </p>
        ))}
    </>
  );
}
