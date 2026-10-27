"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  ChartNoAxesCombined,
  Download,
  Play,
  Route,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Badge,
  BusyLabel,
  EmptyState,
  ErrorState,
  Field,
  PageHeading,
  Panel,
  StatusBadge,
} from "@/components/ui/primitives";
import { CapacityChart, StrategyChart } from "@/components/charts";
import { useWorkspace } from "@/components/workspace-provider";
import { api, jsonBody, money, num, percent } from "@/lib/utils";
import type { OptimizationInput, OptimizationRun } from "@/lib/types";

const initial: OptimizationInput = {
  count: 12,
  data_seed: 42,
  budget_percent: 100,
  deadline_shift_hours: 0,
  weight_capacity_percent: 100,
  volume_capacity_percent: 100,
  shipment_capacity_percent: 100,
  allow_unassigned: false,
  unassigned_penalty_usd: 100000,
  cost_weight: 30,
  time_weight: 30,
  risk_weight: 40,
  scenario_count: 2000,
  seed: 2026,
  time_limit_seconds: 5,
};

export function StrategyTable({ run }: { run: OptimizationRun }) {
  return (
    <>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Solver status</th>
              <th>Shipping cost</th>
              <th>Simulated on-time</th>
              <th>Unassigned</th>
              <th>Allocation time</th>
            </tr>
          </thead>
          <tbody>
            {run.summary.map((row) => (
              <tr key={row.strategy}>
                <td>
                  <strong>{row.strategy}</strong>
                </td>
                <td>
                  <StatusBadge value={row.status} />
                </td>
                <td>{money(row.total_shipping_cost_usd, 2)}</td>
                <td>{percent(row.simulated_on_time_rate_all_orders)}</td>
                <td>{num(row.unassigned_orders, 0)}</td>
                <td>{num(row.allocation_seconds, 3)} s</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!run.summary.every((row) => row.same_full_fulfillment_comparison) && (
        <div className="notice notice-amber mx-5">
          <p>
            No savings or benefit claim is made: at least one strategy lacks a
            fully assigned feasible plan. Compare fulfillment and feasibility
            first.
          </p>
        </div>
      )}
    </>
  );
}
export function Optimization() {
  const { notify } = useWorkspace();
  const [draft, setDraft] = useState<OptimizationInput>(initial),
    [run, setRun] = useState<OptimizationRun | null>(null);
  const [previous, setPrevious] = useState<OptimizationRun | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [candidateOrder, setCandidateOrder] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api<OptimizationRun>("/optimization/runs/latest", {
      signal: controller.signal,
    })
      .then((value) => {
        setRun(value);
        setDraft(value.request);
      })
      .catch((err) => {
        if (
          err.name !== "AbortError" &&
          !err.message.startsWith("No optimization run")
        )
          setError(err.message);
      });
    return () => controller.abort();
  }, []);
  function edit(key: keyof OptimizationInput, value: number | boolean) {
    setDraft((old) => ({ ...old, [key]: value }));
  }
  function numberField(
    label: string,
    key: keyof OptimizationInput,
    min: number,
    max: number,
    step = "any",
  ) {
    return (
      <Field label={label} key={key}>
        <input
          className="input"
          type="number"
          required
          min={min}
          max={max}
          step={step}
          value={Number(draft[key])}
          onChange={(e) => edit(key, Number(e.target.value))}
        />
      </Field>
    );
  }
  async function solve(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<OptimizationRun>(
        "/optimization/runs",
        jsonBody(draft),
      );
      setPrevious(run);
      setRun(result);
      setCandidateOrder("");
      notify(
        `Allocation evaluated: ${result.results["Optimized Allocation"].status}. Run saved locally.`,
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const result = run?.results["Optimized Allocation"],
    summary = run?.summary.find(
      (row) => row.strategy === "Optimized Allocation",
    );
  const feasible = result && ["OPTIMAL", "FEASIBLE"].includes(result.status);
  const unapplied =
    run && JSON.stringify(run.request) !== JSON.stringify(draft);
  const ids = [
    ...new Set(run?.candidate_checks.map((row) => row.shipment_id) ?? []),
  ].sort();
  const selected = ids.includes(candidateOrder)
    ? candidateOrder
    : (ids[0] ?? "");
  return (
    <>
      <PageHeading
        title="Transportation optimization"
        description="Allocate shared capacity. Make cost, time and risk trade-offs explicit."
        action={<Badge tone="blue">V3 · Synthetic planning sandbox</Badge>}
      />
      <div className="notice">
        <Route size={16} />
        <p>
          Planning inputs are fictional and independent of the shipment dataset
          above. Prices, availability and transit distributions are assumptions.
          No booking or live routing is performed.
        </p>
      </div>
      <Panel
        title="Define the planning scenario"
        subtitle="Hard constraints are applied before cost, time and simulated reliability preferences."
      >
        <form onSubmit={solve}>
          <div className="form-section">
            <div className="form-grid">
              <Field label="Synthetic planning orders">
                <select
                  className="input"
                  value={draft.count}
                  onChange={(e) => edit("count", Number(e.target.value))}
                >
                  {[12, 100, 500, 0].map((n) => (
                    <option value={n} key={n}>
                      {n} orders
                    </option>
                  ))}
                </select>
              </Field>
              {numberField("Budget allowance (%)", "budget_percent", 0, 150)}
              {numberField(
                "Deadline shift (hours)",
                "deadline_shift_hours",
                -400,
                400,
              )}
            </div>
            <p className="muted small mt-4">
              Budget is a percentage of the sum of each order’s most expensive
              synthetic option. Expected arrival must meet the deadline, even
              when the optimizer prefers lower cost.
            </p>
          </div>
          <div className="form-section">
            <h3>Shared service capacities</h3>
            <div className="form-grid">
              {numberField(
                "Weight capacity (%)",
                "weight_capacity_percent",
                0,
                200,
              )}
              {numberField(
                "Volume capacity (%)",
                "volume_capacity_percent",
                0,
                200,
              )}
              {numberField(
                "Shipment slots (%)",
                "shipment_capacity_percent",
                0,
                200,
              )}
            </div>
          </div>
          <div className="form-section">
            <h3>Optimization preferences</h3>
            <div className="form-grid">
              {numberField("Cost weight", "cost_weight", 0, 100)}
              {numberField("Time weight", "time_weight", 0, 100)}
              {numberField("Simulated risk weight", "risk_weight", 0, 100)}
            </div>
            <label className="checkbox-field mt-5">
              <input
                type="checkbox"
                checked={draft.allow_unassigned}
                onChange={(e) => edit("allow_unassigned", e.target.checked)}
              />
              Allow unassigned orders with an explicit penalty
            </label>
          </div>
          <details className="disclosure">
            <summary>Simulation and solver settings</summary>
            <div className="form-grid mt-5">
              {numberField(
                "Planning data seed",
                "data_seed",
                0,
                2 ** 32 - 1,
                "1",
              )}
              {numberField("Monte Carlo seed", "seed", 0, 2 ** 32 - 1, "1")}
              {numberField(
                "Monte Carlo scenarios",
                "scenario_count",
                100,
                10000,
                "1",
              )}
              {numberField(
                "Solver limit per strategy (seconds)",
                "time_limit_seconds",
                0.1,
                10,
              )}
              {numberField(
                "Unassigned penalty (virtual USD)",
                "unassigned_penalty_usd",
                0,
                1e6,
              )}
            </div>
          </details>
          <div className="form-actions">
            <p>
              {unapplied
                ? "Draft differs from the saved run below. Run again to apply it."
                : "All three strategies share constraints and random scenarios."}
            </p>
            <Button type="submit" disabled={busy}>
              <BusyLabel busy={busy}>
                <Play size={14} />
                Run optimization
              </BusyLabel>
            </Button>
          </div>
        </form>
      </Panel>
      {error && <ErrorState message={error} />}
      {busy && (
        <div className="notice" role="status">
          Solving three strategies and evaluating common Monte Carlo scenarios.
          Up to {draft.time_limit_seconds * 3} seconds of solver search.
        </div>
      )}
      {run && result && summary ? (
        <>
          <PageHeading
            title="Applied allocation"
            description={`${run.request.count} orders · budget ${money(run.constraints.budget_usd, 2)} · seed ${run.seed} · ${run.scenario_count} scenarios`}
            action={
              <Button asChild variant="outline" size="sm">
                <Link href="/app/analytics">
                  Explore analytics <ArrowUpRight size={14} />
                </Link>
              </Button>
            }
          />
          <div className="notice">
            <ChartNoAxesCombined size={15} />
            <p>
              <strong>{result.status}</strong> —{" "}
              {result.status === "OPTIMAL"
                ? "Minimum proved for the integer-rounded model and applied assumptions."
                : result.status === "FEASIBLE"
                  ? "A valid allocation was found; optimality was not proved."
                  : result.status === "UNKNOWN"
                    ? "No returned solution or infeasibility proof. Increase the solve limit before drawing a conclusion."
                    : "No actionable allocation returned under these constraints."}
            </p>
          </div>
          {result.diagnostics.map((message) => (
            <div className="notice notice-amber" key={message}>
              {message}
            </div>
          ))}
          <div className="kpi-grid">
            {[
              ["Assigned orders", num(summary.assigned_orders, 0)],
              ["Unassigned orders", num(summary.unassigned_orders, 0)],
              ["Shipping cost", money(summary.total_shipping_cost_usd)],
              [
                "Simulated on-time",
                percent(summary.simulated_on_time_rate_all_orders),
              ],
            ].map(([label, value]) => (
              <div className="kpi" key={label}>
                <div className="kpi-label">{label}</div>
                <strong>{value}</strong>
                <small>
                  {label.includes("on-time")
                    ? "All requested orders in the denominator"
                    : "Applied combined-objective allocation"}
                </small>
              </div>
            ))}
          </div>
          <Panel
            title="Strategy comparison"
            subtitle="Lowest Cost and Fastest Delivery are constrained OR-Tools baselines."
          >
            <StrategyTable run={run} />
          </Panel>
          <div className="toolbar-actions">
            <Button asChild variant="outline" size="sm">
              <a
                href={`/api/optimization/runs/${run.run_id}/export/allocation`}
                download
              >
                <Download size={12} />
                Allocation CSV
              </a>
            </Button>
            <Button asChild variant="outline" size="sm">
              <a
                href={`/api/optimization/runs/${run.run_id}/export/json`}
                download
              >
                <Download size={12} />
                Replayable JSON
              </a>
            </Button>
            <Button asChild variant="ghost" size="sm">
              <a
                href={`/api/optimization/runs/${run.run_id}/export/comparison`}
                download
              >
                Strategy CSV
              </a>
            </Button>
          </div>
          {feasible && (
            <>
              <Panel
                title="Recommended batch assignments"
                subtitle={`Showing the first 100 of ${result.assignments.length} assignments. Export CSV for the complete plan.`}
              >
                {result.assignments.length ? (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Shipment</th>
                          <th>Shared service</th>
                          <th>Cost</th>
                          <th>Expected / deadline</th>
                          <th>Assumed late risk</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.assignments.slice(0, 100).map((row) => (
                          <tr key={row.shipment_id}>
                            <td>
                              <strong>{row.shipment_id}</strong>
                            </td>
                            <td>{row.service_id}</td>
                            <td>{money(row.cost_usd, 2)}</td>
                            <td>
                              {num(row.expected_hours)} /{" "}
                              {num(row.deadline_hours)} h
                            </td>
                            <td>{percent(row.assumed_late_probability)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState
                    title={
                      run.request.count
                        ? "No orders assigned"
                        : "Empty planning scenario"
                    }
                    text={
                      run.request.count
                        ? "The optional unassignment mode accepted an unfilled plan. These orders are not counted as on-time deliveries."
                        : "No demand was submitted. On-time rates have no denominator and remain N/A."
                    }
                  />
                )}
              </Panel>
              <div className="dashboard-grid dashboard-grid-equal mt-5">
                <Panel
                  title="Shared capacity utilization"
                  subtitle="Weight, volume and shipment slots by service"
                >
                  <CapacityChart run={run} />
                </Panel>
                <Panel
                  title="Cost trade-offs"
                  subtitle="Shipping spend excludes virtual unassignment penalties"
                >
                  <StrategyChart run={run} />
                </Panel>
              </div>
            </>
          )}
          <Panel
            title="Single-order eligibility"
            subtitle="Local recommendations do not reserve shared capacity and are not complete batch allocations."
          >
            <div className="panel-body">
              <Field label="Planning shipment">
                <select
                  className="input"
                  value={selected}
                  onChange={(e) => setCandidateOrder(e.target.value)}
                >
                  {ids.map((id) => (
                    <option key={id}>{id}</option>
                  ))}
                </select>
              </Field>
            </div>
            {selected ? (
              <>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Candidate service</th>
                        <th>Cost</th>
                        <th>Expected time</th>
                        <th>Eligibility</th>
                        <th>Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {run.candidate_checks
                        .filter((row) => row.shipment_id === selected)
                        .map((row) => (
                          <tr key={row.service_id}>
                            <td>{row.service_id}</td>
                            <td>{money(row.cost_usd, 2)}</td>
                            <td>{num(row.expected_hours)} h</td>
                            <td>
                              <Badge tone={row.eligible ? "green" : "red"}>
                                {row.eligible ? "Eligible" : "Excluded"}
                              </Badge>
                            </td>
                            <td>
                              {row.rejection_reasons ||
                                "Individual hard checks passed"}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
                <div className="panel-body mt-5">
                  {run.local_recommendations
                    ?.filter((row) => row.shipment_id === selected)
                    .map((row) => (
                      <p className="muted small" key={row.strategy}>
                        {row.strategy}:{" "}
                        {row.service_id ?? "No eligible candidate"}
                      </p>
                    ))}
                </div>
              </>
            ) : (
              <EmptyState
                title="No candidates"
                text="An empty demand set has no single-order options to compare."
              />
            )}
          </Panel>
          {previous && (
            <Panel
              className="mt-5"
              title="What changed from the previous run?"
              subtitle="These are separate what-if scenarios. Changed demand or assumptions do not establish a causal benefit."
            >
              <div className="panel-body">
                <p className="muted small">
                  Previous: budget {money(previous.constraints.budget_usd)},
                  weights {previous.request.cost_weight}/
                  {previous.request.time_weight}/{previous.request.risk_weight}.
                  Current: budget {money(run.constraints.budget_usd)}, weights{" "}
                  {run.request.cost_weight}/{run.request.time_weight}/
                  {run.request.risk_weight}.
                </p>
                <p className="muted small">
                  Common scenario fingerprint{" "}
                  {previous.scenario_fingerprint === run.scenario_fingerprint
                    ? "matches"
                    : "differs"}
                  . Identical normalized weights or a stable optimum can produce
                  unchanged results.
                </p>
              </div>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Applied run</th>
                      <th>Combined strategy status</th>
                      <th>Shipping cost</th>
                      <th>Simulated on-time</th>
                      <th>Unassigned</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ["Previous", previous],
                      ["Current", run],
                    ].map(([label, value]) => {
                      const scenario = value as OptimizationRun;
                      const metrics = scenario.summary.find(
                        (row) => row.strategy === "Optimized Allocation",
                      )!;
                      return (
                        <tr key={String(label)}>
                          <td>{String(label)}</td>
                          <td>
                            <StatusBadge value={metrics.status} />
                          </td>
                          <td>{money(metrics.total_shipping_cost_usd, 2)}</td>
                          <td>
                            {percent(metrics.simulated_on_time_rate_all_orders)}
                          </td>
                          <td>{num(metrics.unassigned_orders, 0)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
        </>
      ) : (
        !busy && (
          <EmptyState
            title="Ready to evaluate a transportation plan"
            text="Run the default 12-order synthetic scenario, then adjust budget, deadlines or capacity to inspect feasibility and trade-offs."
          />
        )
      )}
    </>
  );
}
