"use client";
import { useI18n } from "@/lib/i18n/provider";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
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
  const { t } = useI18n();
  const requestedRun = useSearchParams().get("run_id");
  const { data } = useWorkspace();
  const [run, setRun] = useState<OptimizationRun | null>(null),
    [error, setError] = useState("");
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null),
    [evaluating, setEvaluating] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setRun(null);
    setError("");
    api<OptimizationRun>(
      requestedRun
        ? `/optimization/runs/${encodeURIComponent(requestedRun)}`
        : "/optimization/runs/latest",
      {
        signal: controller.signal,
      },
    )
      .then(setRun)
      .catch((err) => {
        if (
          err.name !== "AbortError" &&
          (requestedRun || !err.message.startsWith("No optimization run"))
        )
          setError(err.message);
      });
    return () => controller.abort();
  }, [requestedRun]);
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
        title={t("Performance & scenario analytics")}
        description={t(
          "Separate observed shipment calculations from hypothetical transportation outcomes.",
        )}
        action={
          run && (
            <Button asChild variant="outline" size="sm">
              <a
                href={`/api/optimization/runs/${run.run_id}/export/comparison`}
                download
              >
                <Download size={13} />
                {t("Strategy CSV")}
              </a>
            </Button>
          )
        }
      />
      {error && <ErrorState message={t(error)} />}
      <WorkspaceBoundary>
        {data && (
          <div className="dashboard-grid dashboard-grid-equal">
            <Panel
              title={t("Average shipping cost by mode")}
              subtitle={t(
                "Calculated from valid costs in the active shipment selection",
              )}
            >
              <CostChart data={data.charts.costs} />
              <p className="chart-caption">
                {t(
                  "No weight/service-level normalization. This chart describes the selected shipment records.",
                )}
              </p>
            </Panel>
            <Panel
              title={t("Longest completed delays")}
              subtitle={t(
                "Completed deliveries only; overdue In Transit records are excluded.",
              )}
            >
              {data.charts.delays.length ? (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>{t("Shipment")}</th>
                        <th>{t("Carrier")}</th>
                        <th>{t("Completed delay")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.charts.delays.slice(0, 6).map((row) => (
                        <tr key={row.shipment_id}>
                          <td>
                            <strong>{row.shipment_id}</strong>
                          </td>
                          <td>{row.carrier}</td>
                          <td>
                            {t(num(row.delay_hours))} {t(" h")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState
                  title={t("No completed delays")}
                  text={t(
                    "Only eligible completed late deliveries enter this ranking.",
                  )}
                />
              )}
            </Panel>
          </div>
        )}
      </WorkspaceBoundary>
      {run ? (
        <>
          <PageHeading
            title={t("Transportation scenario evaluation")}
            description={t(
              run.input_mode === "uploaded"
                ? `Uploaded plan · ${run.request.count} orders · ${run.source_info?.source_label}`
                : `Latest locally saved run · ${run.request.count} planning orders · ${run.scenario_count} scenarios · seed ${run.seed}`,
            )}
          />
          <div className="notice">
            <FlaskConical size={17} />
            <p>
              {run.input_mode === "uploaded" ? (
                <>
                  {t(
                    "Uploaded estimates, quotes and capacity are user declarations, not independently verified by this app. Reliability is not estimated and no Monte Carlo is run. Import: ",
                  )}
                  {run.planning_import?.import_id}.
                </>
              ) : (
                <>
                  {t(
                    "All strategies reuse the same lognormal Monte Carlo draws. Shipments on a shared service share its delay in a scenario. Simulated probabilities depend on invented parameters, not real carrier performance.",
                  )}
                </>
              )}
            </p>
          </div>
          <div className="dashboard-grid dashboard-grid-equal">
            <Panel
              title={t("Strategy shipping cost")}
              subtitle={t(
                "Only successful solves have a reported shipping cost.",
              )}
            >
              <StrategyChart run={run} />
            </Panel>
            <Panel
              title={t("Resource utilization")}
              subtitle={t(
                "Check per-service bottlenecks, not just aggregate capacity.",
              )}
            >
              <CapacityChart run={run} />
            </Panel>
          </div>
          <Panel
            title={t(
              run.input_mode === "uploaded"
                ? "Uploaded-input strategy comparison"
                : "Common-scenario comparison",
            )}
            subtitle={t(
              run.input_mode === "uploaded"
                ? "Same user-provided expected-time constraints; reliability not estimated."
                : "All requested orders remain in the all-order on-time denominator.",
            )}
          >
            <StrategyTable run={run} />
          </Panel>
          {run.input_mode !== "uploaded" ? (
            <>
              <Panel
                className="mt-5"
                title={t("Expected versus simulated transit")}
                subtitle={t(
                  "Optimized Allocation · first 100 assigned orders · scenario 0 is a simulated realization, never a historical actual delivery.",
                )}
              >
                {run.simulation_details["Optimized Allocation"]?.length ? (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>{t("Shipment")}</th>
                          <th>{t("Expected")}</th>
                          <th>{t("Scenario 0")}</th>
                          <th>{t("Simulated p95")}</th>
                          <th>{t("Deadline")}</th>
                          <th>{t("Estimated late probability")}</th>
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
                              <td>
                                {t(num(row.expected_hours))} {t(" h")}
                              </td>
                              <td>
                                {t(num(row.simulated_transit_hours_scenario_0))}{" "}
                                {t(" h")}
                              </td>
                              <td>
                                {t(num(row.p95_simulated_transit_hours))}{" "}
                                {t(" h")}
                              </td>
                              <td>
                                {t(num(row.deadline_hours))} {t(" h")}
                              </td>
                              <td>
                                {t(percent(row.estimated_late_probability))}
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState
                    title={t("No simulated allocation outcomes")}
                    text={t(
                      "Failed solves and unassigned shipments have no simulated transport realization.",
                    )}
                  />
                )}
              </Panel>
              <details className="panel disclosure mt-5">
                <summary>
                  {t("Reproducibility and probability definitions")}
                </summary>
                <p>
                  {t("Fingerprint: ")}
                  {t(run.scenario_fingerprint)}
                </p>
                <p>
                  {t(
                    "All-order on-time rate: mean count of simulated on-time deliveries / all requested orders. Unassigned orders do not count as on time. Assigned-only rates have a separate denominator.",
                  )}
                </p>
                <p>
                  {t(
                    "Expected-time eligibility does not guarantee delivery under random variability. The risk objective uses the analytical lognormal tail; simulation evaluates that assumption with fixed random draws.",
                  )}
                </p>
                <p>
                  {t("Total experiment time: ")}
                  {t(num(run.elapsed_seconds, 3))}{" "}
                  {t(
                    " s. Timings and time-limited solver incumbents may vary by machine.",
                  )}
                </p>
              </details>
            </>
          ) : (
            <Panel className="mt-5" title={t("Input sources and limitations")}>
              <div className="panel-body">
                <p>{t(run.provenance)}</p>
                <p>{t(run.source_info?.reliability)}</p>
                <p>
                  {t("Planning start: ")}
                  {t(run.source_info?.planning_start)}
                </p>
                <p>
                  {t("Source input fingerprint: ")}
                  {t(run.scenario_fingerprint)}
                </p>
                <pre className="planning-preview-json">
                  {JSON.stringify(run.source_info?.declarations, null, 2)}
                </pre>
                <p>
                  {t(
                    "User-verified flags are declarations with source references, not independent audit. All results retain their import ID and assumptions.",
                  )}
                </p>
              </div>
            </Panel>
          )}
        </>
      ) : (
        <Panel title={t("Transportation scenario evaluation")}>
          <EmptyState
            title={t("No optimization experiment saved yet")}
            text={t(
              "Run a transportation scenario to populate strategy comparison and Monte Carlo analytics. No placeholder results are shown.",
            )}
            action={
              <Button asChild variant="outline">
                <Link href="/app/optimization">{t("Run an optimization")}</Link>
              </Button>
            }
          />
        </Panel>
      )}
      <Panel
        className="mt-5"
        title={t("V2 reference-case evaluation")}
        subtitle={t(
          "Independently authored synthetic priority references test rule behavior, not predictive accuracy.",
        )}
        action={
          <Button
            size="sm"
            variant="outline"
            disabled={evaluating}
            onClick={evaluate}
          >
            {t(evaluating ? "Evaluating…" : "Run rule evaluation")}
          </Button>
        }
      >
        {evaluation ? (
          <>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>{t("Reference case")}</th>
                    <th>{t("Calculated score")}</th>
                    <th>{t("Disposition")}</th>
                    <th>{t("Reference rationale")}</th>
                  </tr>
                </thead>
                <tbody>
                  {evaluation.comparison.map((row) => (
                    <tr key={row.case_name}>
                      <td>{t(row.case_name)}</td>
                      <td>{t(num(row.priority_score, 4))}</td>
                      <td>{t(row.priority_level)}</td>
                      <td>{t(row.reference_rationale)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <details className="disclosure">
              <summary>{t("Reference summary and weight sensitivity")}</summary>
              <pre>{JSON.stringify(evaluation.summary, null, 2)}</pre>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>{t("Weight profile")}</th>
                      <th>{t("Case")}</th>
                      <th>{t("Score")}</th>
                      <th>{t("Rank")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evaluation.weight_sensitivity.map((row, i) => (
                      <tr key={i}>
                        <td>{t(row.profile)}</td>
                        <td>{t(row.case_name)}</td>
                        <td>{t(num(row.priority_score, 4))}</td>
                        <td>{t(num(row.observed_rank, 0))}</td>
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
              {t(
                "Run the original Python evaluation using your current saved priority settings. The reference labels are not generated by the scoring formula.",
              )}
            </p>
          </div>
        )}
      </Panel>
    </>
  );
}
