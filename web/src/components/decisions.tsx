"use client";
import { useI18n } from "@/lib/i18n/provider";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  Download,
  History,
  Save,
  ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  BusyLabel,
  EmptyState,
  ErrorState,
  Field,
  PageHeading,
  Panel,
  StatusBadge,
} from "@/components/ui/primitives";
import {
  WorkspaceBoundary,
  useExceptionQueue,
  useWorkspace,
} from "@/components/workspace-provider";
import { api, jsonBody, money, num } from "@/lib/utils";
import type { Assumption, CaseRecord, DecisionResult } from "@/lib/types";
import { useAccess } from "@/components/access";
import { useSessionDraft } from "@/lib/session-draft";

export function DecisionNav({ history = false }: { history?: boolean }) {
  const { t } = useI18n();
  return (
    <nav className="subnav" aria-label={t("Decision Center views")}>
      <Link href="/app/decisions" className={history ? "" : "active"}>
        {t("Scenario comparison")}
      </Link>
      <Link href="/app/decisions/history" className={history ? "active" : ""}>
        {t("Handling history")}
      </Link>
    </nav>
  );
}
type ScenarioState = {
  draft: Assumption[];
  applied: Assumption[] | null;
  result: DecisionResult | null;
  action?: string;
  exceptionType?: string;
  notes?: string;
};
export function Decisions() {
  const { t, tExact } = useI18n();
  const user = useAccess();
  const { data, datasetId, asOf, notify } = useWorkspace();
  const params = useSearchParams();
  const [queuePage, setQueuePage] = useSessionDraft("decision-page", 0),
    [search, setSearch] = useSessionDraft(
      "decision-search",
      params.get("shipment") ?? "",
    );
  const queue = useExceptionQueue(queuePage, true, search, 50);
  const [defaults, setDefaults] = useState<Assumption[]>([]),
    [selected, setSelected] = useSessionDraft("decision-selected", "");
  const [states, setStates] = useSessionDraft<Record<string, ScenarioState>>(
    "decision-scenarios",
    {},
    (value) =>
      Object.values(value as Record<string, ScenarioState>).every(
        (state) =>
          Array.isArray(state?.draft) &&
          state.draft.length === 3 &&
          state.draft.every(
            (item) =>
              typeof item?.action === "string" &&
              typeof item?.remaining_hours === "number" &&
              typeof item?.additional_cost === "number",
          ) &&
          (state.result === null ||
            (Array.isArray(state.result?.comparison) &&
              typeof state.result?.comparison_token === "string")),
      ),
  );
  const [busy, setBusy] = useState(false),
    [saving, setSaving] = useState(false),
    [error, setError] = useState("");
  const active = queue.items;
  useEffect(() => {
    api<Assumption[]>("/decisions/defaults")
      .then(setDefaults)
      .catch((err) => setError(err.message));
  }, []);
  useEffect(() => {
    if (!data || !queue.items.length) return;
    const available = queue.items;
    const requested = params.get("shipment");
    setSelected((old) =>
      available.some((row) => row.shipment_id === old)
        ? old
        : (available.find((row) => row.shipment_id === requested)
            ?.shipment_id ??
          available[0]?.shipment_id ??
          ""),
    );
  }, [data, params, queue.items]);
  const row = active.find((item) => item.shipment_id === selected);
  const key = `${datasetId}:${asOf}:${selected}`;
  const current: ScenarioState = states[key] ?? {
    draft: defaults,
    applied: null,
    result: null,
  };
  const action = current.action ?? "",
    notes = current.notes ?? "";
  const exceptionType =
    current.exceptionType ?? row?.exception_types.split("; ")[0] ?? "";
  function updateChoice(
    field: "action" | "notes" | "exceptionType",
    value: string,
  ) {
    setStates((old) => ({
      ...old,
      [key]: { ...(old[key] ?? current), [field]: value },
    }));
  }
  const setAction = (value: string) => updateChoice("action", value);
  const setNotes = (value: string) => updateChoice("notes", value);
  const setExceptionType = (value: string) =>
    updateChoice("exceptionType", value);
  useEffect(() => {
    setError("");
  }, [key]);
  const appliedAction =
    (current.result?.comparison.some(
      (item) => item.action === action && item.assumed_available,
    )
      ? action
      : "") ||
    current.result?.comparison.find((item) => item.assumed_available)?.action ||
    "";
  function edit(
    index: number,
    property: keyof Assumption,
    value: string | number | boolean,
  ) {
    setStates((old) => {
      const state = old[key] ?? {
        draft: defaults,
        applied: null,
        result: null,
      };
      return {
        ...old,
        [key]: {
          ...state,
          draft: state.draft.map((item, i) =>
            i === index ? { ...item, [property]: value } : item,
          ),
        },
      };
    });
  }
  async function compare(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const assumptions = structuredClone(current.draft);
    try {
      const result = await api<DecisionResult>(
        "/decisions/compare",
        jsonBody({
          dataset_id: datasetId,
          as_of: asOf,
          shipment_id: selected,
          assumptions,
        }),
      );
      setStates((old) => ({
        ...old,
        [key]: { ...(old[key] ?? current), applied: assumptions, result },
      }));
      notify(`Scenario comparison applied for ${selected}.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!current.applied || !current.result) return;
    setSaving(true);
    setError("");
    try {
      const saved = await api<CaseRecord>(
        "/cases",
        jsonBody({
          dataset_id: datasetId,
          as_of: asOf,
          shipment_id: selected,
          assumptions: current.applied,
          comparison_token: current.result.comparison_token,
          selected_action: appliedAction,
          exception_type: exceptionType,
          resolution_notes: notes,
        }),
      );
      notify(`Decision saved to local history for ${saved.shipment_id}.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }
  const unapplied =
    current.applied &&
    JSON.stringify(current.applied) !== JSON.stringify(current.draft);
  return (
    <>
      <PageHeading
        title={t("Decision Center")}
        description={t(
          "Compare the alternatives. Know the assumptions. Record the choice.",
        )}
        action={
          <Button asChild variant="outline" size="sm">
            <Link href="/app/decisions/history">
              <History size={13} />
              {t("Handling history")}
            </Link>
          </Button>
        }
      />
      <DecisionNav />
      <p className="muted small">
        {t(
          "Drafts and applied comparisons are restored in this browser tab for your account. A changed server context still requires recomparison before saving.",
        )}
      </p>
      <div className="filters">
        <input
          aria-label={t("Find active exception ID")}
          className="input"
          placeholder={t("Search all active shipment IDs")}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setQueuePage(0);
          }}
        />
        <Button
          variant="outline"
          disabled={!queuePage || queue.loading}
          onClick={() => setQueuePage((v) => v - 1)}
        >
          {t("Previous active page")}
        </Button>
        <span>
          {t(queue.total)} {t(" active exceptions · page ")}
          {t(queuePage + 1)}
        </span>
        <Button
          variant="outline"
          disabled={(queuePage + 1) * 50 >= queue.total || queue.loading}
          onClick={() => setQueuePage((v) => v + 1)}
        >
          {t("Next active page")}
        </Button>
      </div>
      {queue.error && <ErrorState message={t(queue.error)} />}
      <WorkspaceBoundary>
        {data && (
          <>
            {active.length ? (
              <>
                <Panel
                  title={t("Select an active exception")}
                  subtitle={t(
                    "Only retained In Transit exceptions without a reported actual delivery are actionable.",
                  )}
                >
                  <div className="panel-body">
                    <Field label={t("Shipment for decision review")}>
                      <select
                        className="input"
                        value={selected}
                        onChange={(e) => setSelected(e.target.value)}
                      >
                        {[...active]
                          .sort((a, b) =>
                            a.shipment_id.localeCompare(b.shipment_id),
                          )
                          .map((item) => (
                            <option
                              key={item.source_row}
                              value={item.shipment_id}
                            >
                              {item.shipment_id} — {item.origin.split(",")[0]}
                              {t(" ")}
                              {t("to ")}
                              {item.destination.split(",")[0]}
                            </option>
                          ))}
                      </select>
                    </Field>
                    {row && (
                      <div className="explanation-block">
                        <h3>
                          {row.shipment_id}
                          {t(" ")}
                          <StatusBadge
                            value={
                              current.result?.priority_level ??
                              row.priority_level
                            }
                          />
                        </h3>
                        <p>
                          {t("Priority score: ")}
                          {t(
                            num(
                              current.result
                                ? current.result.priority_score
                                : row.priority_score,
                              4,
                            ),
                          )}
                          .{t(" ")}
                          {t(current.result?.explanation ?? row.explanation)}
                        </p>
                        {(current.result?.missing_information ??
                          row.missing_information) && (
                          <p>
                            <strong>{t("Missing information:")}</strong>
                            {t(" ")}
                            {t(
                              current.result?.missing_information ??
                                row.missing_information,
                            )}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                </Panel>
                <div className="notice notice-amber">
                  <ShieldCheck size={16} />
                  <p>
                    {t(
                      "Simulation only. Additional cost, remaining transit time and availability are independent assumptions. A higher price does not imply faster delivery. No live rate, ETA or service commitment is requested.",
                    )}
                  </p>
                </div>
                {error && <ErrorState message={t(error)} />}
                <form onSubmit={compare}>
                  <div className="scenario-grid">
                    {current.draft.map((option, i) => {
                      const result = current.result?.comparison.find(
                        (item) => item.action === option.action,
                      );
                      return (
                        <section className="scenario-card" key={option.action}>
                          <h3>{t(option.action)}</h3>
                          <Field
                            label={t(`${option.action}: additional cost (USD)`)}
                          >
                            <input
                              className="input"
                              type="number"
                              min="0"
                              max="1000000000"
                              required
                              step="any"
                              value={option.additional_cost}
                              onChange={(e) =>
                                edit(
                                  i,
                                  "additional_cost",
                                  Number(e.target.value),
                                )
                              }
                            />
                          </Field>
                          <Field label={t(`${option.action}: remaining hours`)}>
                            <input
                              className="input"
                              type="number"
                              min="0"
                              max="87600"
                              required
                              step="any"
                              value={option.remaining_hours}
                              onChange={(e) =>
                                edit(
                                  i,
                                  "remaining_hours",
                                  Number(e.target.value),
                                )
                              }
                            />
                          </Field>
                          <label className="checkbox-field">
                            <input
                              type="checkbox"
                              checked={option.assumed_available}
                              onChange={(e) =>
                                edit(i, "assumed_available", e.target.checked)
                              }
                            />
                            {t("Assume available in this scenario")}
                          </label>
                          <Field label={t(`${option.action}: key assumptions`)}>
                            <textarea
                              className="input"
                              required
                              maxLength={2000}
                              value={tExact(option.notes)}
                              onChange={(e) => edit(i, "notes", e.target.value)}
                            />
                          </Field>
                          {result && (
                            <div className="scenario-result">
                              <strong>
                                {t(
                                  money(
                                    result.estimated_additional_cost_usd,
                                    2,
                                  ),
                                )}
                              </strong>
                              <p>{t(result.deadline_impact)}</p>
                              <p>
                                {t("Applied remaining time:")}
                                {t(" ")}
                                {t(num(result.assumed_remaining_hours))}{" "}
                                {t(" h")}
                                <br />
                                {t("Scenario arrival:")}
                                {t(" ")}
                                {t(
                                  result.scenario_arrival_utc ?? "Unavailable",
                                )}
                              </p>
                            </div>
                          )}
                        </section>
                      );
                    })}
                  </div>
                  <div className="form-actions">
                    <p>
                      {t(
                        unapplied
                          ? "Draft edits are not applied. Displayed results and saved cases use the last comparison."
                          : "Recalculate to apply all three scenario assumptions together.",
                      )}
                    </p>
                    <Button
                      type="submit"
                      disabled={
                        busy || !defaults.length || user?.read_only_demo
                      }
                    >
                      <BusyLabel busy={busy}>
                        {t("Compare scenarios")}
                      </BusyLabel>
                    </Button>
                  </div>
                </form>
                {current.result && (
                  <>
                    <div className="notice">
                      <p>
                        {t("Scenario starts at ")}
                        {current.result.cutoff}
                        {t(". Deadline source: ")}
                        {t(current.result.deadline_source)}
                        {t(". Deadline:")}
                        {t(" ")}
                        {t(
                          current.result.deadline ?? "Insufficient information",
                        )}
                        .
                      </p>
                    </div>
                    <Panel
                      title={t("Record the handling decision")}
                      subtitle={t(
                        "Saving uses the applied comparison. Unchanged repeated saves reuse the same case.",
                      )}
                    >
                      <form onSubmit={save}>
                        <div className="form-section form-grid">
                          <Field label={t("Selected action")}>
                            <select
                              className="input"
                              value={appliedAction}
                              onChange={(e) => setAction(e.target.value)}
                            >
                              {current.result.comparison
                                .filter((item) => item.assumed_available)
                                .map((item) => (
                                  <option key={item.action} value={item.action}>
                                    {t(item.action)}
                                  </option>
                                ))}
                            </select>
                          </Field>
                          <Field label={t("Exception type for history")}>
                            <select
                              className="input"
                              value={exceptionType}
                              onChange={(e) => setExceptionType(e.target.value)}
                            >
                              {row?.exception_types.split("; ").map((type) => (
                                <option key={type} value={type}>
                                  {t(type)}
                                </option>
                              ))}
                            </select>
                          </Field>
                          <Field label={t("Decision notes")}>
                            <textarea
                              className="input"
                              maxLength={4000}
                              value={notes}
                              onChange={(e) => setNotes(e.target.value)}
                              placeholder={t("Why was this option selected?")}
                            />
                          </Field>
                        </div>
                        <div className="form-actions">
                          <p>
                            {t(
                              "Actual outcomes remain unknown until you enter them in history.",
                            )}
                          </p>
                          <Button
                            type="submit"
                            disabled={
                              saving ||
                              !appliedAction ||
                              user?.role === "viewer"
                            }
                          >
                            <Save size={14} />
                            <BusyLabel busy={saving}>
                              {t("Save decision")}
                            </BusyLabel>
                          </Button>
                        </div>
                      </form>
                    </Panel>
                    <Panel
                      className="mt-5"
                      title={t("Past similar cases")}
                      subtitle={t(
                        "Exact directional route, transport mode and primary exception type; this shipment is excluded.",
                      )}
                    >
                      {current.result.similar_cases.length ? (
                        <HistoryTable rows={current.result.similar_cases} />
                      ) : (
                        <EmptyState
                          title={t("No comparable cases yet")}
                          text={t(
                            "Saved handling decisions will appear here when the deterministic matching fields agree. Matches are not predictions.",
                          )}
                        />
                      )}
                    </Panel>
                  </>
                )}
              </>
            ) : (
              <EmptyState
                title={t("No active transport exception")}
                text={t(
                  "Choose Synthetic Demo Data, clear filters, or upload In Transit orders with operational exceptions. Completed records remain available in Shipments.",
                )}
                action={
                  <Button asChild variant="outline">
                    <Link href="/app/shipments">
                      {t("Inspect shipments ")}
                      <ArrowUpRight size={14} />
                    </Link>
                  </Button>
                }
              />
            )}
          </>
        )}
      </WorkspaceBoundary>
    </>
  );
}

function HistoryTable({
  rows,
  select,
}: {
  rows: CaseRecord[];
  select?: (row: CaseRecord) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>{t("Shipment")}</th>
            <th>{t("Action")}</th>
            <th>{t("Estimate / actual cost")}</th>
            <th>{t("Estimate / actual delay")}</th>
            <th>{t("Status")}</th>
            {select && <th>{t("Update")}</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.case_id}>
              <td>
                <strong>{row.shipment_id}</strong>
                <span className="cell-sub">{t(row.exception_type)}</span>
              </td>
              <td>{t(row.selected_action)}</td>
              <td>
                {t(money(row.estimated_cost, 2))}
                <span className="cell-sub">
                  {t("Actual: ")}
                  {t(money(row.actual_cost, 2))}
                </span>
              </td>
              <td>
                {t(num(row.estimated_delay))} {t(" h")}
                <span className="cell-sub">
                  {t("Actual: ")}
                  {t(num(row.actual_delay))} {t(" h")}
                </span>
              </td>
              <td>
                <StatusBadge value={row.resolution_status} />
              </td>
              {select && (
                <td>
                  <button
                    className="text-button"
                    onClick={() => select(row)}
                    aria-label={t(`Update case ${row.shipment_id}`)}
                  >
                    <ArrowUpRight size={15} />
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function HandlingHistory() {
  const { t } = useI18n();
  const user = useAccess();
  const { notify } = useWorkspace();
  const [rows, setRows] = useState<CaseRecord[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [filter, setFilter] = useSessionDraft("history-status-filter", ""),
    [shipment, setShipment, filterReady] = useSessionDraft(
      "history-shipment-filter",
      "",
    );
  const [page, setPage] = useSessionDraft("history-page", 0);
  const [selected, setSelected] = useSessionDraft<CaseRecord | null>(
      "history-selected",
      null,
      (value) =>
        !!(value as CaseRecord)?.case_id &&
        Number.isInteger((value as CaseRecord)?.version),
    ),
    [actualCost, setActualCost] = useSessionDraft("history-actual-cost", ""),
    [actualDelay, setActualDelay] = useSessionDraft("history-actual-delay", "");
  const [status, setStatus] = useSessionDraft("history-edit-status", "Open"),
    [notes, setNotes] = useSessionDraft("history-edit-notes", "");
  async function load() {
    setBusy(true);
    setError("");
    try {
      setRows(
        await api<CaseRecord[]>(
          `/cases?${new URLSearchParams({ resolution_status: filter, shipment_id: shipment, offset: String(page * 200), limit: "200" })}`,
        ),
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (filterReady) void load();
  }, [filter, page, filterReady]); // exact text filter is explicitly applied below
  function select(row: CaseRecord) {
    setSelected(row);
    setStatus(row.resolution_status);
    setNotes(row.resolution_notes);
    setActualCost(row.actual_cost?.toString() ?? "");
    setActualDelay(row.actual_delay?.toString() ?? "");
  }
  async function update(event: React.FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const updated = await api<CaseRecord>(`/cases/${selected.case_id}`, {
        ...jsonBody({
          resolution_status: status,
          actual_cost: actualCost === "" ? null : Number(actualCost),
          actual_delay: actualDelay === "" ? null : Number(actualDelay),
          resolution_notes: notes,
          expected_version: selected.version,
        }),
        method: "PATCH",
      });
      select(updated);
      await load();
      notify("Handling outcome updated in SQLite.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        title={t("Handling history")}
        description={t(
          "A persistent record of choices, estimates and observed outcomes.",
        )}
        action={
          <Button asChild variant="outline" size="sm">
            <a href="/api/cases/export" download>
              <Download size={13} />
              {t("Export history")}
            </a>
          </Button>
        }
      />
      <DecisionNav history />
      <form
        className="filters"
        onSubmit={(e) => {
          e.preventDefault();
          if (page) setPage(0);
          else void load();
        }}
      >
        <input
          aria-label={t("History shipment ID")}
          placeholder={t("Exact shipment ID")}
          className="input"
          value={shipment}
          onChange={(e) => setShipment(e.target.value)}
        />
        <select
          className="input"
          aria-label={t("History status filter")}
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value);
            setPage(0);
          }}
        >
          <option value="">{t("All statuses")}</option>
          {["Open", "In Progress", "Resolved", "Cancelled"].map((value) => (
            <option key={value} value={value}>
              {t(value)}
            </option>
          ))}
        </select>
        <Button type="submit" size="sm" variant="outline" disabled={busy}>
          {t("Apply filters")}
        </Button>
      </form>
      {error && <ErrorState message={t(error)} retry={load} />}
      <Panel
        title={t("Saved decisions")}
        subtitle={t(
          `Persistent SQLite history. Page ${page + 1} (up to 200 records); CSV exports the complete organization history.`,
        )}
      >
        {rows.length ? (
          <HistoryTable
            rows={rows}
            select={user?.role === "viewer" ? undefined : select}
          />
        ) : (
          <EmptyState
            title={t(busy ? "Loading local cases" : "No saved cases match")}
            text={t(
              "Save an applied scenario in Decision Center, or change the history filters.",
            )}
          />
        )}
      </Panel>
      <div className="form-actions">
        <Button
          variant="outline"
          disabled={busy || !page}
          onClick={() => setPage((v) => v - 1)}
        >
          {t("Previous history page")}
        </Button>
        <Button
          variant="outline"
          disabled={busy || rows.length < 200}
          onClick={() => setPage((v) => v + 1)}
        >
          {t("Next history page")}
        </Button>
      </div>
      {selected && user?.role !== "viewer" && (
        <Panel
          className="mt-5"
          title={t(`Update ${selected.shipment_id}`)}
          subtitle={t(
            `Case version ${selected.version}. A concurrent update is rejected until you reload the record.`,
          )}
        >
          <form onSubmit={update}>
            <div className="form-section form-grid">
              <Field label={t("Resolution status")}>
                <select
                  className="input"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  {["Open", "In Progress", "Resolved", "Cancelled"].map(
                    (value) => (
                      <option key={value} value={value}>
                        {t(value)}
                      </option>
                    ),
                  )}
                </select>
              </Field>
              <Field
                label={t("Actual additional cost (USD)")}
                hint={t("Leave blank if unknown.")}
              >
                <input
                  className="input"
                  type="number"
                  min="0"
                  max="1000000000"
                  step="any"
                  value={actualCost}
                  onChange={(e) => setActualCost(e.target.value)}
                />
              </Field>
              <Field
                label={t("Actual delay (hours)")}
                hint={t("Leave blank if unknown.")}
              >
                <input
                  className="input"
                  type="number"
                  min="0"
                  max="1000000000"
                  step="any"
                  value={actualDelay}
                  onChange={(e) => setActualDelay(e.target.value)}
                />
              </Field>
              <Field label={t("Resolution notes")}>
                <textarea
                  className="input"
                  maxLength={4000}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </Field>
            </div>
            <div className="form-actions">
              <Button type="submit" disabled={busy}>
                <BusyLabel busy={busy}>{t("Save outcome")}</BusyLabel>
              </Button>
            </div>
          </form>
        </Panel>
      )}
    </>
  );
}
