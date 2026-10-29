"use client";

import { useEffect, useState } from "react";
import {
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
} from "@/components/ui/primitives";
import { useWorkspace } from "@/components/workspace-provider";
import { useAccess } from "@/components/access";
import { useSessionDraft } from "@/lib/session-draft";
import { UploadedOptimization } from "@/components/uploaded-optimization";
import { AllocationResults } from "@/components/optimization-results";
import { api, jsonBody } from "@/lib/utils";
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

export { StrategyTable } from "@/components/optimization-results";
export function Optimization() {
  const user = useAccess();
  const [mode, setMode] = useSessionDraft("optimization-mode", "synthetic");
  return <>{user?.read_only_demo && <div className="notice">Read-only synthetic demo. The allocation below was computed from built-in synthetic inputs. Uploads and online solving are disabled on the server.</div>}
    <Field label="Optimization input mode"><select className="input optimization-mode" disabled={user?.read_only_demo} value={user?.read_only_demo ? "synthetic" : mode} onChange={(event) => setMode(event.target.value)}>
    <option value="synthetic">Synthetic Demo Mode</option><option value="uploaded">Uploaded Data Mode</option>
  </select></Field>{mode === "uploaded" && !user?.read_only_demo ? <UploadedOptimization /> : <SyntheticOptimization />}</>;
}

function SyntheticOptimization() {
  const user = useAccess();
  const { notify } = useWorkspace();
  const [draft, setDraft, draftReady, restored] = useSessionDraft<OptimizationInput>("optimization-synthetic", initial);
  const [run, setRun] = useState<OptimizationRun | null>(null);
  const [previous, setPrevious] = useState<OptimizationRun | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    if (!draftReady) return;
    const controller = new AbortController();
    api<OptimizationRun>("/optimization/runs/latest?input_mode=synthetic", {
      signal: controller.signal,
    })
      .then((value) => {
        setRun(value);
        if (!restored) setDraft(value.request);
      })
      .catch((err) => {
        if (
          err.name !== "AbortError" &&
          !err.message.startsWith("No optimization run")
        )
          setError(err.message);
      });
    return () => controller.abort();
  }, [draftReady]);
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
      notify(
        `Allocation evaluated: ${result.results["Optimized Allocation"].status}. Run saved locally.`,
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const unapplied = run && JSON.stringify(run.request) !== JSON.stringify(draft);
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
            <Button type="submit" disabled={busy || user?.role === "viewer"}>
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
      {run ? <AllocationResults key={run.run_id} run={run} previous={previous} /> : !busy && <EmptyState title="Ready to evaluate a transportation plan" text="Run the default 12-order synthetic scenario, then adjust budget, deadlines or capacity to inspect feasibility and trade-offs." />}
    </>
  );
}
