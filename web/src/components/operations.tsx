"use client";
import { useI18n } from "@/lib/i18n/provider";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Box,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Download,
  Filter,
  Search,
  ShieldAlert,
  Truck,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Badge,
  EmptyState,
  PageHeading,
  Panel,
  StatusBadge,
} from "@/components/ui/primitives";
import { CarrierChart, CostChart, StatusChart } from "@/components/charts";
import {
  useWorkspace,
  WorkspaceBoundary,
  useExceptionQueue,
} from "@/components/workspace-provider";
import { money, num, percent } from "@/lib/utils";
import type { Shipment, Workspace } from "@/lib/types";

export function KpiRail({ data }: { data: Workspace }) {
  const { t } = useI18n();
  const k = data.kpis;
  const entries = [
    {
      label: "Total shipments",
      value: num(k.total_shipments, 0),
      detail: `${k.excluded_rows} source rows excluded`,
      icon: Box,
      title: data.definitions["Total Shipments"],
    },
    {
      label: "On-time delivery",
      value: percent(k.on_time_delivery_rate),
      detail: `${k.eligible_deliveries} eligible completed deliveries`,
      icon: Truck,
      title: data.definitions["On-Time Delivery Rate"],
    },
    {
      label: "Overdue in transit",
      value: num(k.overdue_shipments, 0),
      detail: "Open shipments past their planned delivery",
      icon: Clock3,
      title: data.definitions["Overdue Shipments"],
    },
    {
      label: "Total shipping cost",
      value: money(k.total_shipping_cost, 2),
      detail: `${k.cost_eligible_shipments} valid costs · USD`,
      icon: ArrowUpRight,
      title: data.definitions["Total Shipping Cost"],
    },
  ];
  return (
    <>
      <div className="kpi-grid">
        {entries.map((entry) => (
          <div className="kpi" key={entry.label} title={t(entry.title)}>
            <div className="kpi-label">
              {t(entry.label)}
              <entry.icon size={15} strokeWidth={1.5} />
            </div>
            <strong
              className={entry.label.includes("Overdue") ? "kpi-accent" : ""}
            >
              {t(entry.value)}
            </strong>
            <small>{t(entry.detail)}</small>
          </div>
        ))}
      </div>
      <div className="secondary-stats">
        <span>
          {t("Delivered")}
          <strong>{t(num(k.delivered_shipments, 0))}</strong>
        </span>
        <span>
          {t("Average completed delay")}
          <strong>
            {t(num(k.average_delay_hours))} {t(" h")}
          </strong>
        </span>
        <span>
          {t("Cost anomalies")}
          <strong>{t(num(k.cost_anomalies, 0))}</strong>
        </span>
        <span>
          {t("Quality findings")}
          <strong>{t(data.issue_count)}</strong>
        </span>
      </div>
    </>
  );
}
export function Filters() {
  const { t } = useI18n();
  const { filters, setFilter, data, clearFilters } = useWorkspace();
  return (
    <div className="filters">
      <label className="search-field">
        <Search size={15} />
        <input
          aria-label={t("Search shipment ID")}
          className="input"
          placeholder={t("Search shipment ID…")}
          value={filters.q}
          onChange={(e) => setFilter("q", e.target.value)}
        />
      </label>
      <select
        className="input"
        aria-label={t("Filter carrier")}
        value={filters.carrier}
        onChange={(e) => setFilter("carrier", e.target.value)}
      >
        <option value="">{t("All carriers")}</option>
        {data?.filters.carrier.map((v) => (
          <option key={v} value={v}>
            {t(v)}
          </option>
        ))}
      </select>
      <select
        className="input"
        aria-label={t("Filter transport mode")}
        value={filters.mode}
        onChange={(e) => setFilter("mode", e.target.value)}
      >
        <option value="">{t("All modes")}</option>
        {data?.filters.transport_mode.map((v) => (
          <option key={v} value={v}>
            {t(v)}
          </option>
        ))}
      </select>
      <select
        className="input"
        aria-label={t("Filter shipment status")}
        value={filters.status}
        onChange={(e) => setFilter("status", e.target.value)}
      >
        <option value="">{t("All statuses")}</option>
        {data?.filters.status.map((v) => (
          <option key={v} value={v}>
            {t(v)}
          </option>
        ))}
      </select>
      {(filters.q || filters.carrier || filters.mode || filters.status) && (
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("Clear filters")}
          onClick={clearFilters}
        >
          <X size={15} />
        </Button>
      )}
    </div>
  );
}
function ExceptionRows({
  rows,
  compact = false,
}: {
  rows: Shipment[];
  compact?: boolean;
}) {
  const { t } = useI18n();
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>{t("Shipment")}</th>
            <th>{t("Route")}</th>
            <th>{t("Exception")}</th>
            <th>{t("Priority")}</th>
            {!compact && <th>{t("Score")}</th>}
            <th>
              <span className="sr-only">{t("Action")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.source_row}>
              <td>
                <strong>{row.shipment_id || t("Missing ID")}</strong>
                <span className="cell-sub">{row.carrier}</span>
              </td>
              <td className="route-cell">
                {row.origin.split(",")[0]}
                <span className="cell-sub">
                  {t("to ")}
                  {row.destination.split(",")[0]}
                </span>
              </td>
              <td>
                {t(row.exception_types.split("; ")[0])}
                <span className="cell-sub">
                  {t(
                    row.overdue_hours != null
                      ? `${num(row.overdue_hours)} h overdue`
                      : row.delay_hours != null
                        ? `${num(row.delay_hours)} h completed delay`
                        : "Review data quality",
                  )}
                </span>
              </td>
              <td>
                <StatusBadge value={row.priority_level} />
              </td>
              {!compact && <td>{t(num(row.priority_score, 4))}</td>}
              <td>
                {row.actionable ? (
                  <Link
                    className="text-button"
                    href={`/app/decisions?shipment=${encodeURIComponent(row.shipment_id)}`}
                    aria-label={t(`Review ${row.shipment_id}`)}
                  >
                    <ArrowUpRight size={15} />
                  </Link>
                ) : (
                  <span className="cell-sub">{t("Review only")}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Overview() {
  const { t } = useI18n();
  const { data, query } = useWorkspace();
  return (
    <WorkspaceBoundary>
      {data && (
        <>
          <PageHeading
            title={t("Operational overview")}
            description={t(
              "A clearer picture of performance, exceptions and the next decision.",
            )}
            action={
              <Button asChild variant="outline" size="sm">
                <a href={`/api/exports/report?${query}`} download>
                  <Download size={13} />
                  {t("English report")}
                </a>
              </Button>
            }
          />
          <KpiRail data={data} />
          <div className="dashboard-grid">
            <Panel
              title={t("Carrier delivery performance")}
              subtitle={t(
                "On-time deliveries among eligible completed shipments",
              )}
              action={<Badge>{t("Measured snapshot")}</Badge>}
            >
              {data.charts.carriers.some(
                (item) => item.eligible_deliveries > 0,
              ) ? (
                <CarrierChart data={data.charts.carriers} />
              ) : (
                <EmptyState
                  title={t("No eligible completed deliveries")}
                  text={t(
                    "Delivered orders need valid planned and actual dates for this comparison.",
                  )}
                />
              )}
              <p className="chart-caption">
                {t(
                  "In-transit shipments are excluded from this denominator. Carrier names in the demo are fictional.",
                )}
              </p>
            </Panel>
            <Panel
              title={t("Shipment status")}
              subtitle={t("Reported status across retained orders")}
            >
              <StatusChart
                data={data.charts.statuses}
                total={data.kpis.total_shipments ?? 0}
              />
            </Panel>
          </div>
          <div className="dashboard-grid">
            <Panel
              title={t("Exceptions needing attention")}
              subtitle={t(
                `${data.exception_count} records with operational or data-quality findings`,
              )}
              action={
                <Link href="/app/exceptions" className="text-button">
                  {t("View all ")}
                  <ArrowRight size={13} />
                </Link>
              }
            >
              {data.exceptions.length ? (
                <ExceptionRows rows={data.exceptions.slice(0, 5)} compact />
              ) : (
                <EmptyState
                  title={t("No exceptions in this selection")}
                  text={t(
                    "Adjust the dataset or filters to explore another operational snapshot.",
                  )}
                />
              )}
            </Panel>
            <Panel
              title={t("Directional lane mix")}
              subtitle={t("Calculated from the selected orders")}
            >
              <div className="route-distribution">
                {data.charts.routes.slice(0, 5).map((row) => (
                  <div
                    className="route-item"
                    key={`${row.origin}-${row.destination}`}
                  >
                    <p>
                      {row.origin.split(",")[0]}
                      {t(" ")}
                      <span aria-hidden="true">→</span>
                      {t(" ")}
                      {row.destination.split(",")[0]}
                    </p>
                    <span>{t(row.shipments)}</span>
                    <div className="route-bar">
                      <i
                        style={{
                          width: `${(row.shipments / Math.max(1, data.charts.routes[0]?.shipments ?? 1)) * 100}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}
                {!data.charts.routes.length && (
                  <EmptyState
                    title={t("No lanes to show")}
                    text={t(
                      "Upload shipment records to calculate the lane mix.",
                    )}
                  />
                )}
              </div>
            </Panel>
          </div>
          <details className="panel disclosure">
            <summary>
              {t("Metric definitions and snapshot assumptions")}
            </summary>
            {Object.entries(data.definitions).map(([name, definition]) => (
              <p key={name}>
                <strong>{t(name)}:</strong> {t(definition)}
              </p>
            ))}
            <p>
              {t("Analysis cutoff: ")}
              {data.cutoff}
              {t(
                ". Changing the analysis day does not reconstruct historical statuses.",
              )}
            </p>
          </details>
        </>
      )}
    </WorkspaceBoundary>
  );
}

export function Shipments() {
  const { t } = useI18n();
  const { data, query, filters, setFilter } = useWorkspace();
  const [quality, setQuality] = useState(false),
    [expanded, setExpanded] = useState<number | null>(null);
  return (
    <>
      <PageHeading
        title={t("Shipment workspace")}
        description={t(
          "Inspect the source, refine your view, and keep every data-quality issue visible.",
        )}
        action={
          <Button asChild variant="outline" size="sm">
            <a href={`/api/exports/shipments?${query}`} download>
              <Download size={13} />
              {t("Export CSV")}
            </a>
          </Button>
        }
      />
      <Filters />
      <WorkspaceBoundary>
        {data && (
          <>
            <div className="secondary-stats">
              <span>
                {t("Selected source rows")}
                <strong>{t(data.total_rows)}</strong>
              </span>
              <span>
                {t("Retained unique shipments")}
                <strong>{t(data.kpis.total_shipments)}</strong>
              </span>
              <span>
                {t("Quality findings")}
                <strong>{t(data.issue_count)}</strong>
              </span>
              <button
                className="text-button"
                onClick={() => setQuality((v) => !v)}
              >
                {t(quality ? "Show shipments" : "Inspect data quality")}
              </button>
            </div>
            <Panel
              title={t(quality ? "Data quality findings" : "Shipment register")}
              subtitle={t(
                quality
                  ? `Showing up to 500 of ${data.issue_count} findings. Full findings are available in the CSV export.`
                  : "Invalid field values remain available for review; duplicate IDs keep their first occurrence.",
              )}
              action={
                quality && (
                  <a
                    className="text-button"
                    href={`/api/exports/quality?${query}`}
                    download
                  >
                    {t("Export findings ")}
                    <Download size={12} />
                  </a>
                )
              }
            >
              {quality ? (
                data.issues.length ? (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>{t("Row")}</th>
                          <th>{t("Shipment")}</th>
                          <th>{t("Field")}</th>
                          <th>{t("Finding")}</th>
                          <th>{t("Raw value")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.issues.map((row, i) => (
                          <tr key={i}>
                            <td>{row.source_row}</td>
                            <td>{row.shipment_id || t("Missing ID")}</td>
                            <td>{row.field}</td>
                            <td>{t(row.message)}</td>
                            <td>{row.raw_value || t("Empty")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState
                    title={t("No quality findings")}
                    text={t(
                      "The selected records passed the implemented field-level checks.",
                    )}
                  />
                )
              ) : data.shipments.length ? (
                <>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>{t("Shipment")}</th>
                          <th>{t("Origin / destination")}</th>
                          <th>{t("Carrier / mode")}</th>
                          <th>{t("Reported status")}</th>
                          <th>{t("Cost (USD)")}</th>
                          <th>{t("Assessment")}</th>
                          <th>{t("Details")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.shipments.map((row) => (
                          <tr key={row.source_row}>
                            <td>
                              <strong>
                                {row.shipment_id || t("Missing ID")}
                              </strong>
                              <span className="cell-sub">
                                {t("Source row ")}
                                {row.source_row}
                              </span>
                            </td>
                            <td className="route-cell">
                              {row.origin}
                              <span className="cell-sub">
                                {row.destination}
                              </span>
                            </td>
                            <td>
                              {row.carrier}
                              <span className="cell-sub">
                                {t(row.transport_mode)}
                              </span>
                            </td>
                            <td>
                              <StatusBadge value={row.status} />
                            </td>
                            <td>{t(money(row.shipping_cost, 2))}</td>
                            <td>
                              {row.included_in_analysis ? (
                                row.exception_types ? (
                                  <Badge tone="amber">{t("Exception")}</Badge>
                                ) : (
                                  <Badge tone="green">
                                    {t("No rule finding")}
                                  </Badge>
                                )
                              ) : (
                                <Badge>{t("Excluded")}</Badge>
                              )}
                            </td>
                            <td>
                              <button
                                className="text-button"
                                onClick={() =>
                                  setExpanded((old) =>
                                    old === row.source_row
                                      ? null
                                      : row.source_row,
                                  )
                                }
                                aria-label={t(
                                  `Inspect source row ${row.source_row}`,
                                )}
                              >
                                <ArrowUpRight size={15} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="table-footer">
                    <span>
                      {t(filters.offset + 1)}–
                      {t(
                        Math.min(filters.offset + data.limit, data.total_rows),
                      )}
                      {t(" ")}
                      {t("of ")}
                      {t(data.total_rows)} {t(" source rows")}
                    </span>
                    <div>
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={filters.offset === 0}
                        aria-label={t("Previous shipment page")}
                        onClick={() =>
                          setFilter(
                            "offset",
                            Math.max(0, filters.offset - data.limit),
                          )
                        }
                      >
                        <ChevronLeft size={16} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={
                          filters.offset + data.limit >= data.total_rows
                        }
                        aria-label={t("Next shipment page")}
                        onClick={() =>
                          setFilter("offset", filters.offset + data.limit)
                        }
                      >
                        <ChevronRight size={16} />
                      </Button>
                    </div>
                  </div>
                </>
              ) : (
                <EmptyState
                  title={t("No matching shipments")}
                  text={t(
                    "Clear filters or upload a table with shipment rows. Header-only tables are supported.",
                  )}
                />
              )}
            </Panel>
            {expanded != null &&
              data.shipments.find((row) => row.source_row === expanded) && (
                <div className="explanation-block">
                  <h3>{t("Source record details")}</h3>
                  {[
                    data.shipments.find((row) => row.source_row === expanded)!,
                  ].map((row) => (
                    <div key={row.source_row}>
                      <p>
                        {t("Planned delivery:")}
                        {t(" ")}
                        {t(row.planned_delivery ?? "Missing / invalid")}
                      </p>
                      <p>
                        {t("Actual delivery:")}
                        {t(" ")}
                        {t(row.actual_delivery ?? "Not reported / invalid")}
                      </p>
                      <p>
                        {t("Cost assessment: ")}
                        {t(row.cost_assessment)}
                      </p>
                      <p>
                        {t("Quality findings: ")}
                        {t(row.data_quality_issues || "None")}
                      </p>
                      <p>
                        {t("Priority: ")}
                        {t(row.priority_level)}.{t(" ")}
                        {t(row.missing_information)}
                      </p>
                    </div>
                  ))}
                </div>
              )}
          </>
        )}
      </WorkspaceBoundary>
    </>
  );
}

export function Exceptions() {
  const { t } = useI18n();
  const { data, query } = useWorkspace();
  const [page, setPage] = useState(0),
    [selected, setSelected] = useState("");
  useEffect(() => {
    setPage(0);
  }, [data]);
  const queue = useExceptionQueue(page);
  const selectedRow = queue.items.find(
    (row) => `${row.source_row}` === selected,
  );
  return (
    <>
      <PageHeading
        title={t("Exception intelligence")}
        description={t(
          "Explainable priorities, with a separate lane for missing evidence.",
        )}
        action={
          <Button asChild variant="outline" size="sm">
            <a href={`/api/exports/priority?${query}`} download>
              <Download size={13} />
              {t("Priority CSV")}
            </a>
          </Button>
        }
      />
      <Filters />
      {queue.error && <p role="alert">{t(queue.error)}</p>}
      <WorkspaceBoundary>
        {data && (
          <>
            <div className="kpi-grid">
              {[
                [
                  "Active transport exceptions",
                  queue.items.filter((row) => row.actionable).length,
                ],
                [
                  "High priority",
                  queue.items.filter((row) => row.priority_level === "High")
                    .length,
                ],
                [
                  "Information needed",
                  queue.items.filter(
                    (row) => row.priority_level === "Insufficient information",
                  ).length,
                ],
                [
                  "Review only",
                  queue.items.filter(
                    (row) => row.priority_level === "Review only",
                  ).length,
                ],
              ].map(([label, value]) => (
                <div className="kpi" key={String(label)}>
                  <div className="kpi-label">
                    {t(label)}
                    <ShieldAlert size={14} />
                  </div>
                  <strong>{t(value)}</strong>
                  <small>{t("Within the displayed exception queue")}</small>
                </div>
              ))}
            </div>
            <Panel
              title={t("Prioritized exception queue")}
              subtitle={t(
                `Showing page ${page + 1} of ${queue.total} findings. Completed delays remain separate from active overdue shipments.`,
              )}
              action={
                <Button asChild size="sm" variant="ghost">
                  <Link href="/app/settings">
                    <Filter size={12} />
                    {t("Scoring settings")}
                  </Link>
                </Button>
              }
            >
              {queue.items.length ? (
                <>
                  <ExceptionRows rows={queue.items} />
                  <div className="table-footer">
                    <span>
                      {t(page * 20 + 1)}–
                      {t(Math.min(page * 20 + 20, queue.total))} {t("of ")}
                      {t(" ")}
                      {t(queue.total)}
                    </span>
                    <div>
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={page === 0}
                        aria-label={t("Previous exception page")}
                        onClick={() => setPage((v) => v - 1)}
                      >
                        <ChevronLeft size={16} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={(page + 1) * 20 >= queue.total}
                        aria-label={t("Next exception page")}
                        onClick={() => setPage((v) => v + 1)}
                      >
                        <ChevronRight size={16} />
                      </Button>
                    </div>
                  </div>
                </>
              ) : (
                <EmptyState
                  title={t("No exceptions in this selection")}
                  text={t(
                    "The implemented rules found no operational or data-quality exceptions for these records.",
                  )}
                />
              )}
            </Panel>
            <div className="explanation-block">
              <h3>{t("Inspect a priority rationale")}</h3>
              <select
                className="input"
                aria-label={t("Exception rationale shipment")}
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
              >
                <option value="">
                  {t("Select a shipment to inspect its evidence")}
                </option>
                {queue.items.map((row) => (
                  <option key={row.source_row} value={row.source_row}>
                    {row.shipment_id || t("Missing ID")} —{" "}
                    {t(row.priority_level)}
                  </option>
                ))}
              </select>
              {selectedRow && (
                <>
                  <p style={{ marginTop: 14 }}>{t(selectedRow.explanation)}</p>
                  {selectedRow.missing_information && (
                    <p>
                      <strong>{t("Missing information:")}</strong>
                      {t(" ")}
                      {t(selectedRow.missing_information)}
                    </p>
                  )}
                  <p>
                    {t("Known-input coverage:")}
                    {t(" ")}
                    {t(percent(selectedRow.coverage_percent / 100))}
                    {t(". Score:")}
                    {t(" ")}
                    {t(num(selectedRow.priority_score, 4))}.
                  </p>
                </>
              )}
            </div>
            <div className="notice">
              <ShieldAlert size={15} />
              <p>
                {t(
                  "Priority is a triage rule, not a loss prediction. Missing inputs are not zero-filled. Shipment value alone does not establish financial loss.",
                )}
              </p>
            </div>
          </>
        )}
      </WorkspaceBoundary>
    </>
  );
}
