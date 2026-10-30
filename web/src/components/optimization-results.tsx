"use client";
import { useI18n } from "@/lib/i18n/provider";
import Link from "next/link";
import { ArrowUpRight, ChartNoAxesCombined, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Badge,
  EmptyState,
  Field,
  PageHeading,
  Panel,
  StatusBadge,
} from "@/components/ui/primitives";
import { CapacityChart, StrategyChart } from "@/components/charts";
import { useSessionDraft } from "@/lib/session-draft";
import { money, num, percent } from "@/lib/utils";
import type { OptimizationRun } from "@/lib/types";

export function StrategyTable({ run }: { run: OptimizationRun }) {
  const { t } = useI18n();
  return (
    <>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>{t("Strategy")}</th>
              <th>{t("Solver status")}</th>
              <th>{t("Shipping cost")}</th>
              <th>
                {t(
                  run.input_mode === "uploaded"
                    ? "Reliability estimate"
                    : "Simulated on-time",
                )}
              </th>
              <th>{t("Unassigned")}</th>
              <th>{t("Allocation time")}</th>
            </tr>
          </thead>
          <tbody>
            {run.summary.map((row) => (
              <tr key={row.strategy}>
                <td>
                  <strong>{t(row.strategy)}</strong>
                </td>
                <td>
                  <StatusBadge value={row.status} />
                </td>
                <td>{t(money(row.total_shipping_cost_usd, 2))}</td>
                <td>
                  {t(
                    run.input_mode === "uploaded"
                      ? "Not estimated"
                      : percent(row.simulated_on_time_rate_all_orders),
                  )}
                </td>
                <td>{t(num(row.unassigned_orders, 0))}</td>
                <td>
                  {t(num(row.allocation_seconds, 3))} {t(" s")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!run.summary.every((row) => row.same_full_fulfillment_comparison) && (
        <div className="notice notice-amber mx-5">
          <p>
            {t(
              "No savings or benefit claim is made: at least one strategy lacks a fully assigned feasible plan. Compare fulfillment and feasibility first.",
            )}
          </p>
        </div>
      )}
    </>
  );
}

export function AllocationResults({
  run,
  previous = null,
}: {
  run: OptimizationRun;
  previous?: OptimizationRun | null;
}) {
  const { t } = useI18n();
  const [candidateOrder, setCandidateOrder] = useSessionDraft(
    `planning-order:${run.run_id}`,
    "",
  );
  const uploaded = run.input_mode === "uploaded";
  const result = run?.results["Optimized Allocation"],
    summary = run?.summary.find(
      (row) => row.strategy === "Optimized Allocation",
    );
  const feasible = result && ["OPTIMAL", "FEASIBLE"].includes(result.status);
  const ids = [
    ...new Set(run?.candidate_checks.map((row) => row.shipment_id) ?? []),
  ].sort();
  const selected = ids.includes(candidateOrder)
    ? candidateOrder
    : (ids[0] ?? "");
  return (
    <>
      {run && result && summary ? (
        <>
          {uploaded && (
            <div className="notice">
              <p>
                <strong>{t(run.provenance)}</strong>
                <br />
                {t("Source: ")}
                {t(run.source_info?.source_label)}
                {t(
                  ". No independent verification or reliability prediction. Quotes, expected transit and capacity are user declarations. Import: ",
                )}
                {run.planning_import?.import_id}.
              </p>
            </div>
          )}
          <PageHeading
            title={t("Applied allocation")}
            description={t(
              uploaded
                ? `${run.request.count} uploaded orders · budget ${money(run.constraints.budget_usd, 2)} · expected-time constraints only`
                : `${run.request.count} orders · budget ${money(run.constraints.budget_usd, 2)} · seed ${run.seed} · ${run.scenario_count} scenarios`,
            )}
            action={
              <Button asChild variant="outline" size="sm">
                <Link href={`/app/analytics?run_id=${run.run_id}`}>
                  {t("Explore analytics ")}
                  <ArrowUpRight size={14} />
                </Link>
              </Button>
            }
          />
          <div className="notice">
            <ChartNoAxesCombined size={15} />
            <p>
              <strong>{t(result.status)}</strong> —{t(" ")}
              {t(
                result.status === "OPTIMAL"
                  ? "Minimum proved for the integer-rounded model and applied assumptions."
                  : result.status === "FEASIBLE"
                    ? "A valid allocation was found; optimality was not proved."
                    : result.status === "UNKNOWN"
                      ? "No returned solution or infeasibility proof. Increase the solve limit before drawing a conclusion."
                      : "No actionable allocation returned under these constraints.",
              )}
            </p>
          </div>
          {result.diagnostics.map((message) => (
            <div className="notice notice-amber" key={message}>
              {t(message)}
            </div>
          ))}
          <div className="kpi-grid">
            {[
              ["Assigned orders", num(summary.assigned_orders, 0)],
              ["Unassigned orders", num(summary.unassigned_orders, 0)],
              ["Shipping cost", money(summary.total_shipping_cost_usd)],
              [
                uploaded ? "Reliability estimate" : "Simulated on-time",
                uploaded
                  ? "Not estimated"
                  : percent(summary.simulated_on_time_rate_all_orders),
              ],
            ].map(([label, value]) => (
              <div className="kpi" key={label}>
                <div className="kpi-label">{t(label)}</div>
                <strong>{t(value)}</strong>
                <small>
                  {t(
                    label.includes("on-time")
                      ? "All requested orders in the denominator"
                      : "Applied combined-objective allocation",
                  )}
                </small>
              </div>
            ))}
          </div>
          <Panel
            title={t("Strategy comparison")}
            subtitle={t(
              "Lowest Cost and Fastest Delivery are constrained OR-Tools baselines.",
            )}
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
                {t("Allocation CSV")}
              </a>
            </Button>
            <Button asChild variant="outline" size="sm">
              <a
                href={`/api/optimization/runs/${run.run_id}/export/json`}
                download
              >
                <Download size={12} />
                {t(uploaded ? "Input & results JSON" : "Replayable JSON")}
              </a>
            </Button>
            <Button asChild variant="ghost" size="sm">
              <a
                href={`/api/optimization/runs/${run.run_id}/export/comparison`}
                download
              >
                {t("Strategy CSV")}
              </a>
            </Button>
          </div>
          {feasible && (
            <>
              <Panel
                title={t("Recommended batch assignments")}
                subtitle={t(
                  `Showing the first 100 of ${result.assignments.length} assignments. Export CSV for the complete plan.`,
                )}
              >
                {result.assignments.length ? (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>{t("Shipment")}</th>
                          <th>{t("Shared service")}</th>
                          <th>{t("Cost")}</th>
                          <th>{t("Expected / deadline")}</th>
                          <th>
                            {t(
                              uploaded
                                ? "Reliability estimate"
                                : "Assumed late risk",
                            )}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.assignments.slice(0, 100).map((row) => (
                          <tr key={row.shipment_id}>
                            <td>
                              <strong>{row.shipment_id}</strong>
                            </td>
                            <td>{row.service_id}</td>
                            <td>{t(money(row.cost_usd, 2))}</td>
                            <td>
                              {t(num(row.expected_hours))} /{t(" ")}
                              {t(num(row.deadline_hours))} {t(" h")}
                            </td>
                            <td>
                              {t(
                                uploaded
                                  ? "Not estimated"
                                  : percent(row.assumed_late_probability),
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState
                    title={t(
                      run.request.count
                        ? "No orders assigned"
                        : "Empty planning scenario",
                    )}
                    text={t(
                      run.request.count
                        ? "The optional unassignment mode accepted an unfilled plan. These orders are not counted as on-time deliveries."
                        : "No demand was submitted. On-time rates have no denominator and remain N/A.",
                    )}
                  />
                )}
              </Panel>
              <div className="dashboard-grid dashboard-grid-equal mt-5">
                <Panel
                  title={t("Shared capacity utilization")}
                  subtitle={t("Weight, volume and shipment slots by service")}
                >
                  <CapacityChart run={run} />
                </Panel>
                <Panel
                  title={t("Cost trade-offs")}
                  subtitle={t(
                    "Shipping spend excludes virtual unassignment penalties",
                  )}
                >
                  <StrategyChart run={run} />
                </Panel>
              </div>
            </>
          )}
          <Panel
            title={t("Single-order eligibility")}
            subtitle={t(
              "Local recommendations do not reserve shared capacity and are not complete batch allocations.",
            )}
          >
            <div className="panel-body">
              <Field label={t("Planning shipment")}>
                <select
                  className="input"
                  value={selected}
                  onChange={(e) => setCandidateOrder(e.target.value)}
                >
                  {ids.map((id) => (
                    <option key={id} value={id}>
                      {id}
                    </option>
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
                        <th>{t("Candidate service")}</th>
                        <th>{t("Cost")}</th>
                        <th>{t("Expected time")}</th>
                        <th>{t("Eligibility")}</th>
                        <th>{t("Reason")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {run.candidate_checks
                        .filter((row) => row.shipment_id === selected)
                        .map((row) => (
                          <tr key={row.service_id}>
                            <td>{row.service_id}</td>
                            <td>{t(money(row.cost_usd, 2))}</td>
                            <td>
                              {t(num(row.expected_hours))} {t(" h")}
                            </td>
                            <td>
                              <Badge tone={row.eligible ? "green" : "red"}>
                                {t(row.eligible ? "Eligible" : "Excluded")}
                              </Badge>
                            </td>
                            <td>
                              {t(
                                row.rejection_reasons ||
                                  "Individual hard checks passed",
                              )}
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
                        {t(row.strategy)}:{t(" ")}
                        {row.service_id ?? t("No eligible candidate")}
                      </p>
                    ))}
                </div>
              </>
            ) : (
              <EmptyState
                title={t("No candidates")}
                text={t(
                  "An empty demand set has no single-order options to compare.",
                )}
              />
            )}
          </Panel>
          {previous && (
            <Panel
              className="mt-5"
              title={t("What changed from the previous run?")}
              subtitle={t(
                "These are separate what-if scenarios. Changed demand or assumptions do not establish a causal benefit.",
              )}
            >
              <div className="panel-body">
                <p className="muted small">
                  {t("Previous: budget ")}
                  {t(money(previous.constraints.budget_usd))}
                  {t(", weights ")}
                  {previous.request.cost_weight}/{previous.request.time_weight}/
                  {previous.request.risk_weight}
                  {t(". Current: budget ")}
                  {t(money(run.constraints.budget_usd))}
                  {t(", weights ")}
                  {t(" ")}
                  {run.request.cost_weight}/{run.request.time_weight}/
                  {run.request.risk_weight}.
                </p>
                <p className="muted small">
                  {t("Common scenario fingerprint")}
                  {t(" ")}
                  {t(
                    previous.scenario_fingerprint === run.scenario_fingerprint
                      ? "matches"
                      : "differs",
                  )}
                  {t(
                    ". Identical normalized weights or a stable optimum can produce unchanged results.",
                  )}
                </p>
              </div>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>{t("Applied run")}</th>
                      <th>{t("Combined strategy status")}</th>
                      <th>{t("Shipping cost")}</th>
                      <th>{t("Simulated on-time")}</th>
                      <th>{t("Unassigned")}</th>
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
                          <td>{t(String(label))}</td>
                          <td>
                            <StatusBadge value={metrics.status} />
                          </td>
                          <td>
                            {t(money(metrics.total_shipping_cost_usd, 2))}
                          </td>
                          <td>
                            {t(
                              percent(
                                metrics.simulated_on_time_rate_all_orders,
                              ),
                            )}
                          </td>
                          <td>{t(num(metrics.unassigned_orders, 0))}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
        </>
      ) : null}
    </>
  );
}
