"use client";

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
  return (
    <nav className="subnav" aria-label="Decision Center views">
      <Link href="/app/decisions" className={history ? "" : "active"}>
        Scenario comparison
      </Link>
      <Link href="/app/decisions/history" className={history ? "active" : ""}>
        Handling history
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
  const user = useAccess();
  const { data, datasetId, asOf, notify } = useWorkspace();
  const params = useSearchParams();
  const [queuePage, setQueuePage] = useSessionDraft("decision-page", 0), [search, setSearch] = useSessionDraft("decision-search", params.get("shipment") ?? "");
  const queue = useExceptionQueue(queuePage, true, search, 50);
  const [defaults, setDefaults] = useState<Assumption[]>([]),
    [selected, setSelected] = useSessionDraft("decision-selected", "");
  const [states, setStates] = useSessionDraft<Record<string, ScenarioState>>("decision-scenarios", {}, (value) => Object.values(value as Record<string, ScenarioState>).every((state) =>
    Array.isArray(state?.draft) && state.draft.length === 3 && state.draft.every((item) => typeof item?.action === "string" && typeof item?.remaining_hours === "number" && typeof item?.additional_cost === "number") &&
    (state.result === null || (Array.isArray(state.result?.comparison) && typeof state.result?.comparison_token === "string"))));
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
  const action = current.action ?? "", notes = current.notes ?? "";
  const exceptionType = current.exceptionType ?? row?.exception_types.split("; ")[0] ?? "";
  function updateChoice(field: "action" | "notes" | "exceptionType", value: string) {
    setStates((old) => ({ ...old, [key]: { ...(old[key] ?? current), [field]: value } }));
  }
  const setAction = (value: string) => updateChoice("action", value);
  const setNotes = (value: string) => updateChoice("notes", value);
  const setExceptionType = (value: string) => updateChoice("exceptionType", value);
  useEffect(() => { setError(""); }, [key]);
  const appliedAction =
    (current.result?.comparison.some((item) => item.action === action && item.assumed_available) ? action : "") ||
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
        title="Decision Center"
        description="Compare the alternatives. Know the assumptions. Record the choice."
        action={
          <Button asChild variant="outline" size="sm">
            <Link href="/app/decisions/history">
              <History size={13} />
              Handling history
            </Link>
          </Button>
        }
      />
      <DecisionNav />
      <p className="muted small">Drafts and applied comparisons are restored in this browser tab for your account. A changed server context still requires recomparison before saving.</p>
      <div className="filters">
        <input aria-label="Find active exception ID" className="input" placeholder="Search all active shipment IDs" value={search} onChange={(e) => { setSearch(e.target.value); setQueuePage(0); }} />
        <Button variant="outline" disabled={!queuePage || queue.loading} onClick={() => setQueuePage((v) => v - 1)}>Previous active page</Button>
        <span>{queue.total} active exceptions · page {queuePage + 1}</span>
        <Button variant="outline" disabled={(queuePage + 1) * 50 >= queue.total || queue.loading} onClick={() => setQueuePage((v) => v + 1)}>Next active page</Button>
      </div>
      {queue.error && <ErrorState message={queue.error} />}
      <WorkspaceBoundary>
        {data && (
          <>
            {active.length ? (
              <>
                <Panel
                  title="Select an active exception"
                  subtitle="Only retained In Transit exceptions without a reported actual delivery are actionable."
                >
                  <div className="panel-body">
                    <Field label="Shipment for decision review">
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
                              {item.shipment_id} — {item.origin.split(",")[0]}{" "}
                              to {item.destination.split(",")[0]}
                            </option>
                          ))}
                      </select>
                    </Field>
                    {row && (
                      <div className="explanation-block">
                        <h3>
                          {row.shipment_id}{" "}
                          <StatusBadge value={current.result?.priority_level ?? row.priority_level} />
                        </h3>
                        <p>
                          Priority score: {num(current.result ? current.result.priority_score : row.priority_score, 4)}.{" "}
                          {current.result?.explanation ?? row.explanation}
                        </p>
                        {(current.result?.missing_information ?? row.missing_information) && (
                          <p>
                            <strong>Missing information:</strong>{" "}
                            {current.result?.missing_information ?? row.missing_information}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                </Panel>
                <div className="notice notice-amber">
                  <ShieldCheck size={16} />
                  <p>
                    Simulation only. Additional cost, remaining transit time and
                    availability are independent assumptions. A higher price
                    does not imply faster delivery. No live rate, ETA or service
                    commitment is requested.
                  </p>
                </div>
                {error && <ErrorState message={error} />}
                <form onSubmit={compare}>
                  <div className="scenario-grid">
                    {current.draft.map((option, i) => {
                      const result = current.result?.comparison.find(
                        (item) => item.action === option.action,
                      );
                      return (
                        <section className="scenario-card" key={option.action}>
                          <h3>{option.action}</h3>
                          <Field
                            label={`${option.action}: additional cost (USD)`}
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
                          <Field label={`${option.action}: remaining hours`}>
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
                            Assume available in this scenario
                          </label>
                          <Field label={`${option.action}: key assumptions`}>
                            <textarea
                              className="input"
                              required
                              maxLength={2000}
                              value={option.notes}
                              onChange={(e) => edit(i, "notes", e.target.value)}
                            />
                          </Field>
                          {result && (
                            <div className="scenario-result">
                              <strong>
                                {money(result.estimated_additional_cost_usd, 2)}
                              </strong>
                              <p>{result.deadline_impact}</p>
                              <p>
                                Applied remaining time:{" "}
                                {num(result.assumed_remaining_hours)} h<br />
                                Scenario arrival:{" "}
                                {result.scenario_arrival_utc ?? "Unavailable"}
                              </p>
                            </div>
                          )}
                        </section>
                      );
                    })}
                  </div>
                  <div className="form-actions">
                    <p>
                      {unapplied
                        ? "Draft edits are not applied. Displayed results and saved cases use the last comparison."
                        : "Recalculate to apply all three scenario assumptions together."}
                    </p>
                    <Button type="submit" disabled={busy || !defaults.length}>
                      <BusyLabel busy={busy}>Compare scenarios</BusyLabel>
                    </Button>
                  </div>
                </form>
                {current.result && (
                  <>
                    <div className="notice">
                      <p>
                        Scenario starts at {current.result.cutoff}. Deadline
                        source: {current.result.deadline_source}. Deadline:{" "}
                        {current.result.deadline ?? "Insufficient information"}.
                      </p>
                    </div>
                    <Panel
                      title="Record the handling decision"
                      subtitle="Saving uses the applied comparison. Unchanged repeated saves reuse the same case."
                    >
                      <form onSubmit={save}>
                        <div className="form-section form-grid">
                          <Field label="Selected action">
                            <select
                              className="input"
                              value={appliedAction}
                              onChange={(e) => setAction(e.target.value)}
                            >
                              {current.result.comparison
                                .filter((item) => item.assumed_available)
                                .map((item) => (
                                  <option key={item.action}>
                                    {item.action}
                                  </option>
                                ))}
                            </select>
                          </Field>
                          <Field label="Exception type for history">
                            <select
                              className="input"
                              value={exceptionType}
                              onChange={(e) => setExceptionType(e.target.value)}
                            >
                              {row?.exception_types.split("; ").map((type) => (
                                <option key={type}>{type}</option>
                              ))}
                            </select>
                          </Field>
                          <Field label="Decision notes">
                            <textarea
                              className="input"
                              maxLength={4000}
                              value={notes}
                              onChange={(e) => setNotes(e.target.value)}
                              placeholder="Why was this option selected?"
                            />
                          </Field>
                        </div>
                        <div className="form-actions">
                          <p>
                            Actual outcomes remain unknown until you enter them
                            in history.
                          </p>
                          <Button
                            type="submit"
                            disabled={saving || !appliedAction || user?.role === "viewer"}
                          >
                            <Save size={14} />
                            <BusyLabel busy={saving}>Save decision</BusyLabel>
                          </Button>
                        </div>
                      </form>
                    </Panel>
                    <Panel
                      className="mt-5"
                      title="Past similar cases"
                      subtitle="Exact directional route, transport mode and primary exception type; this shipment is excluded."
                    >
                      {current.result.similar_cases.length ? (
                        <HistoryTable rows={current.result.similar_cases} />
                      ) : (
                        <EmptyState
                          title="No comparable cases yet"
                          text="Saved handling decisions will appear here when the deterministic matching fields agree. Matches are not predictions."
                        />
                      )}
                    </Panel>
                  </>
                )}
              </>
            ) : (
              <EmptyState
                title="No active transport exception"
                text="Choose Synthetic Demo Data, clear filters, or upload In Transit orders with operational exceptions. Completed records remain available in Shipments."
                action={
                  <Button asChild variant="outline">
                    <Link href="/app/shipments">
                      Inspect shipments <ArrowUpRight size={14} />
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
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Shipment</th>
            <th>Action</th>
            <th>Estimate / actual cost</th>
            <th>Estimate / actual delay</th>
            <th>Status</th>
            {select && <th>Update</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.case_id}>
              <td>
                <strong>{row.shipment_id}</strong>
                <span className="cell-sub">{row.exception_type}</span>
              </td>
              <td>{row.selected_action}</td>
              <td>
                {money(row.estimated_cost, 2)}
                <span className="cell-sub">
                  Actual: {money(row.actual_cost, 2)}
                </span>
              </td>
              <td>
                {num(row.estimated_delay)} h
                <span className="cell-sub">
                  Actual: {num(row.actual_delay)} h
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
                    aria-label={`Update case ${row.shipment_id}`}
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
  const user = useAccess();
  const { notify } = useWorkspace();
  const [rows, setRows] = useState<CaseRecord[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [filter, setFilter] = useSessionDraft("history-status-filter", ""),
    [shipment, setShipment, filterReady] = useSessionDraft("history-shipment-filter", "");
  const [page, setPage] = useSessionDraft("history-page", 0);
  const [selected, setSelected] = useSessionDraft<CaseRecord | null>("history-selected", null, (value) => !!(value as CaseRecord)?.case_id && Number.isInteger((value as CaseRecord)?.version)),
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
        title="Handling history"
        description="A persistent record of choices, estimates and observed outcomes."
        action={
          <Button asChild variant="outline" size="sm">
            <a href="/api/cases/export" download>
              <Download size={13} />
              Export history
            </a>
          </Button>
        }
      />
      <DecisionNav history />
      <form
        className="filters"
        onSubmit={(e) => {
          e.preventDefault();
          if (page) setPage(0); else void load();
        }}
      >
        <input
          aria-label="History shipment ID"
          placeholder="Exact shipment ID"
          className="input"
          value={shipment}
          onChange={(e) => setShipment(e.target.value)}
        />
        <select
          className="input"
          aria-label="History status filter"
          value={filter}
          onChange={(e) => { setFilter(e.target.value); setPage(0); }}
        >
          <option value="">All statuses</option>
          {["Open", "In Progress", "Resolved", "Cancelled"].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
        <Button type="submit" size="sm" variant="outline" disabled={busy}>
          Apply filters
        </Button>
      </form>
      {error && <ErrorState message={error} retry={load} />}
      <Panel
        title="Saved decisions"
        subtitle={`Persistent SQLite history. Page ${page + 1} (up to 200 records); CSV exports the complete organization history.`}
      >
        {rows.length ? (
          <HistoryTable rows={rows} select={user?.role === "viewer" ? undefined : select} />
        ) : (
          <EmptyState
            title={busy ? "Loading local cases" : "No saved cases match"}
            text="Save an applied scenario in Decision Center, or change the history filters."
          />
        )}
      </Panel>
      <div className="form-actions"><Button variant="outline" disabled={busy || !page} onClick={() => setPage((v) => v - 1)}>Previous history page</Button>
        <Button variant="outline" disabled={busy || rows.length < 200} onClick={() => setPage((v) => v + 1)}>Next history page</Button></div>
      {selected && user?.role !== "viewer" && (
        <Panel
          className="mt-5"
          title={`Update ${selected.shipment_id}`}
          subtitle={`Case version ${selected.version}. A concurrent update is rejected until you reload the record.`}
        >
          <form onSubmit={update}>
            <div className="form-section form-grid">
              <Field label="Resolution status">
                <select
                  className="input"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  {["Open", "In Progress", "Resolved", "Cancelled"].map(
                    (value) => (
                      <option key={value}>{value}</option>
                    ),
                  )}
                </select>
              </Field>
              <Field
                label="Actual additional cost (USD)"
                hint="Leave blank if unknown."
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
                label="Actual delay (hours)"
                hint="Leave blank if unknown."
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
              <Field label="Resolution notes">
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
                <BusyLabel busy={busy}>Save outcome</BusyLabel>
              </Button>
            </div>
          </form>
        </Panel>
      )}
    </>
  );
}
