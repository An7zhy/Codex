"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Download, FlaskConical } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  EmptyState,
  ErrorState,
  PageHeading,
  Panel,
} from "@/components/ui/primitives";
import { CapacityChart, CostChart, StrategyChart } from "@/components/charts";
import { StrategyTable } from "@/components/optimization";
import {
  useWorkspace,
  WorkspaceBoundary,
} from "@/components/workspace-provider";
import { api, num, percent } from "@/lib/utils";
import type { OptimizationRun } from "@/lib/types";

type Evaluation = {
  summary: Record<string, unknown>;
  comparison: {
    case_name: string;
    priority_score: number | null;
    priority_level: string;
    reference_rationale: string;
  }[];
  weight_sensitivity: {
    profile: string;
    case_name: string;
    priority_score: number | null;
    observed_rank: number | null;
  }[];
};
export function Analytics() {
  const { data } = useWorkspace();
  const [run, setRun] = useState<OptimizationRun | null>(null),
    [error, setError] = useState("");
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null),
    [evaluating, setEvaluating] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api<OptimizationRun>("/optimization/runs/latest", {
      signal: controller.signal,
    })
      .then(setRun)
      .catch((err) => {
        if (
          err.name !== "AbortError" &&
          !err.message.startsWith("No optimization run")
        )
          setError(err.message);
      });
    return () => controller.abort();
  }, []);
  async function evaluate() {
    setEvaluating(true);
    setError("");
    try {
      setEvaluation(await api<Evaluation>("/evaluation"));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setEvaluating(false);
    }
  }
  return (
    <>
      <PageHeading
        title="Performance & scenario analytics"
        description="Separate observed shipment calculations from hypothetical transportation outcomes."
        action={
          run && (
            <Button asChild variant="outline" size="sm">
              <a
                href={`/api/optimization/runs/${run.run_id}/export/comparison`}
                download
              >
                <Download size={13} />
                Strategy CSV
              </a>
            </Button>
          )
        }
      />
      {error && <ErrorState message={error} />}
      <WorkspaceBoundary>
        {data && (
          <div className="dashboard-grid dashboard-grid-equal">
            <Panel
              title="Average shipping cost by mode"
              subtitle="Calculated from valid costs in the active shipment selection"
            >
              <CostChart data={data.charts.costs} />
              <p className="chart-caption">
                No weight/service-level normalization. This chart describes the
                selected shipment records.
              </p>
            </Panel>
            <Panel
              title="Longest completed delays"
              subtitle="Completed deliveries only; overdue In Transit records are excluded."
            >
              {data.charts.delays.length ? (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Shipment</th>
                        <th>Carrier</th>
                        <th>Completed delay</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.charts.delays.slice(0, 6).map((row) => (
                        <tr key={row.shipment_id}>
                          <td>
                            <strong>{row.shipment_id}</strong>
                          </td>
                          <td>{row.carrier}</td>
                          <td>{num(row.delay_hours)} h</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState
                  title="No completed delays"
                  text="Only eligible completed late deliveries enter this ranking."
                />
              )}
            </Panel>
          </div>
        )}
      </WorkspaceBoundary>
      {run ? (
        <>
          <PageHeading
            title="Transportation scenario evaluation"
            description={`Latest locally saved run · ${run.request.count} planning orders · ${run.scenario_count} scenarios · seed ${run.seed}`}
          />
          <div className="notice">
            <FlaskConical size={17} />
            <p>
              All strategies reuse the same lognormal Monte Carlo draws.
              Shipments on a shared service share its delay in a scenario.
              Simulated probabilities depend on invented parameters, not real
              carrier performance.
            </p>
          </div>
          <div className="dashboard-grid dashboard-grid-equal">
            <Panel
              title="Strategy shipping cost"
              subtitle="Only successful solves have a reported shipping cost."
            >
              <StrategyChart run={run} />
            </Panel>
            <Panel
              title="Resource utilization"
              subtitle="Check per-service bottlenecks, not just aggregate capacity."
            >
              <CapacityChart run={run} />
            </Panel>
          </div>
          <Panel
            title="Common-scenario comparison"
            subtitle="All requested orders remain in the all-order on-time denominator."
          >
            <StrategyTable run={run} />
          </Panel>
          <Panel
            className="mt-5"
            title="Expected versus simulated transit"
            subtitle="Optimized Allocation · first 100 assigned orders · scenario 0 is a simulated realization, never a historical actual delivery."
          >
            {run.simulation_details["Optimized Allocation"]?.length ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Shipment</th>
                      <th>Expected</th>
                      <th>Scenario 0</th>
                      <th>Simulated p95</th>
                      <th>Deadline</th>
                      <th>Estimated late probability</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.simulation_details["Optimized Allocation"]
                      .slice(0, 100)
                      .map((row) => (
                        <tr key={row.shipment_id}>
                          <td>
                            <strong>{row.shipment_id}</strong>
                          </td>
                          <td>{num(row.expected_hours)} h</td>
                          <td>
                            {num(row.simulated_transit_hours_scenario_0)} h
                          </td>
                          <td>{num(row.p95_simulated_transit_hours)} h</td>
                          <td>{num(row.deadline_hours)} h</td>
                          <td>{percent(row.estimated_late_probability)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState
                title="No simulated allocation outcomes"
                text="Failed solves and unassigned shipments have no simulated transport realization."
              />
            )}
          </Panel>
          <details className="panel disclosure mt-5">
            <summary>Reproducibility and probability definitions</summary>
            <p>Fingerprint: {run.scenario_fingerprint}</p>
            <p>
              All-order on-time rate: mean count of simulated on-time deliveries
              / all requested orders. Unassigned orders do not count as on time.
              Assigned-only rates have a separate denominator.
            </p>
            <p>
              Expected-time eligibility does not guarantee delivery under random
              variability. The risk objective uses the analytical lognormal
              tail; simulation evaluates that assumption with fixed random
              draws.
            </p>
            <p>
              Total experiment time: {num(run.elapsed_seconds, 3)} s. Timings
              and time-limited solver incumbents may vary by machine.
            </p>
          </details>
        </>
      ) : (
        <Panel title="Transportation scenario evaluation">
          <EmptyState
            title="No optimization experiment saved yet"
            text="Run a transportation scenario to populate strategy comparison and Monte Carlo analytics. No placeholder results are shown."
            action={
              <Button asChild variant="outline">
                <Link href="/app/optimization">Run an optimization</Link>
              </Button>
            }
          />
        </Panel>
      )}
      <Panel
        className="mt-5"
        title="V2 reference-case evaluation"
        subtitle="Independently authored synthetic priority references test rule behavior, not predictive accuracy."
        action={
          <Button
            size="sm"
            variant="outline"
            disabled={evaluating}
            onClick={evaluate}
          >
            {evaluating ? "Evaluating…" : "Run rule evaluation"}
          </Button>
        }
      >
        {evaluation ? (
          <>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Reference case</th>
                    <th>Calculated score</th>
                    <th>Disposition</th>
                    <th>Reference rationale</th>
                  </tr>
                </thead>
                <tbody>
                  {evaluation.comparison.map((row) => (
                    <tr key={row.case_name}>
                      <td>{row.case_name}</td>
                      <td>{num(row.priority_score, 4)}</td>
                      <td>{row.priority_level}</td>
                      <td>{row.reference_rationale}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <details className="disclosure">
              <summary>Reference summary and weight sensitivity</summary>
              <pre>{JSON.stringify(evaluation.summary, null, 2)}</pre>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Weight profile</th>
                      <th>Case</th>
                      <th>Score</th>
                      <th>Rank</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evaluation.weight_sensitivity.map((row, i) => (
                      <tr key={i}>
                        <td>{row.profile}</td>
                        <td>{row.case_name}</td>
                        <td>{num(row.priority_score, 4)}</td>
                        <td>{num(row.observed_rank, 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        ) : (
          <div className="panel-body">
            <p className="muted small">
              Run the original Python evaluation using your current saved
              priority settings. The reference labels are not generated by the
              scoring formula.
            </p>
          </div>
        )}
      </Panel>
    </>
  );
}
