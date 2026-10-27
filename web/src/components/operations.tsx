"use client";

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
} from "@/components/workspace-provider";
import { money, num, percent } from "@/lib/utils";
import type { Shipment, Workspace } from "@/lib/types";

export function KpiRail({ data }: { data: Workspace }) {
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
          <div className="kpi" key={entry.label} title={entry.title}>
            <div className="kpi-label">
              {entry.label}
              <entry.icon size={15} strokeWidth={1.5} />
            </div>
            <strong
              className={entry.label.includes("Overdue") ? "kpi-accent" : ""}
            >
              {entry.value}
            </strong>
            <small>{entry.detail}</small>
          </div>
        ))}
      </div>
      <div className="secondary-stats">
        <span>
          Delivered<strong>{num(k.delivered_shipments, 0)}</strong>
        </span>
        <span>
          Average completed delay<strong>{num(k.average_delay_hours)} h</strong>
        </span>
        <span>
          Cost anomalies<strong>{num(k.cost_anomalies, 0)}</strong>
        </span>
        <span>
          Quality findings<strong>{data.issue_count}</strong>
        </span>
      </div>
    </>
  );
}
export function Filters() {
  const { filters, setFilter, data, clearFilters } = useWorkspace();
  return (
    <div className="filters">
      <label className="search-field">
        <Search size={15} />
        <input
          aria-label="Search shipment ID"
          className="input"
          placeholder="Search shipment ID…"
          value={filters.q}
          onChange={(e) => setFilter("q", e.target.value)}
        />
      </label>
      <select
        className="input"
        aria-label="Filter carrier"
        value={filters.carrier}
        onChange={(e) => setFilter("carrier", e.target.value)}
      >
        <option value="">All carriers</option>
        {data?.filters.carrier.map((v) => (
          <option key={v}>{v}</option>
        ))}
      </select>
      <select
        className="input"
        aria-label="Filter transport mode"
        value={filters.mode}
        onChange={(e) => setFilter("mode", e.target.value)}
      >
        <option value="">All modes</option>
        {data?.filters.transport_mode.map((v) => (
          <option key={v}>{v}</option>
        ))}
      </select>
      <select
        className="input"
        aria-label="Filter shipment status"
        value={filters.status}
        onChange={(e) => setFilter("status", e.target.value)}
      >
        <option value="">All statuses</option>
        {data?.filters.status.map((v) => (
          <option key={v}>{v}</option>
        ))}
      </select>
      {(filters.q || filters.carrier || filters.mode || filters.status) && (
        <Button
          variant="ghost"
          size="icon"
          aria-label="Clear filters"
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
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Shipment</th>
            <th>Route</th>
            <th>Exception</th>
            <th>Priority</th>
            {!compact && <th>Score</th>}
            <th>
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.source_row}>
              <td>
                <strong>{row.shipment_id || "Missing ID"}</strong>
                <span className="cell-sub">{row.carrier}</span>
              </td>
              <td className="route-cell">
                {row.origin.split(",")[0]}
                <span className="cell-sub">
                  to {row.destination.split(",")[0]}
                </span>
              </td>
              <td>
                {row.exception_types.split("; ")[0]}
                <span className="cell-sub">
                  {row.overdue_hours != null
                    ? `${num(row.overdue_hours)} h overdue`
                    : row.delay_hours != null
                      ? `${num(row.delay_hours)} h completed delay`
                      : "Review data quality"}
                </span>
              </td>
              <td>
                <StatusBadge value={row.priority_level} />
              </td>
              {!compact && <td>{num(row.priority_score, 4)}</td>}
              <td>
                {row.actionable ? (
                  <Link
                    className="text-button"
                    href={`/app/decisions?shipment=${encodeURIComponent(row.shipment_id)}`}
                    aria-label={`Review ${row.shipment_id}`}
                  >
                    <ArrowUpRight size={15} />
                  </Link>
                ) : (
                  <span className="cell-sub">Review only</span>
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
  const { data, query } = useWorkspace();
  return (
    <WorkspaceBoundary>
      {data && (
        <>
          <PageHeading
            title="Operational overview"
            description="A clearer picture of performance, exceptions and the next decision."
            action={
              <Button asChild variant="outline" size="sm">
                <a href={`/api/exports/report?${query}`} download>
                  <Download size={13} />
                  English report
                </a>
              </Button>
            }
          />
          <KpiRail data={data} />
          <div className="dashboard-grid">
            <Panel
              title="Carrier delivery performance"
              subtitle="On-time deliveries among eligible completed shipments"
              action={<Badge>Measured snapshot</Badge>}
            >
              {data.charts.carriers.some(
                (item) => item.eligible_deliveries > 0,
              ) ? (
                <CarrierChart data={data.charts.carriers} />
              ) : (
                <EmptyState
                  title="No eligible completed deliveries"
                  text="Delivered orders need valid planned and actual dates for this comparison."
                />
              )}
              <p className="chart-caption">
                In-transit shipments are excluded from this denominator. Carrier
                names in the demo are fictional.
              </p>
            </Panel>
            <Panel
              title="Shipment status"
              subtitle="Reported status across retained orders"
            >
              <StatusChart
                data={data.charts.statuses}
                total={data.kpis.total_shipments ?? 0}
              />
            </Panel>
          </div>
          <div className="dashboard-grid">
            <Panel
              title="Exceptions needing attention"
              subtitle={`${data.exception_count} records with operational or data-quality findings`}
              action={
                <Link href="/app/exceptions" className="text-button">
                  View all <ArrowRight size={13} />
                </Link>
              }
            >
              {data.exceptions.length ? (
                <ExceptionRows rows={data.exceptions.slice(0, 5)} compact />
              ) : (
                <EmptyState
                  title="No exceptions in this selection"
                  text="Adjust the dataset or filters to explore another operational snapshot."
                />
              )}
            </Panel>
            <Panel
              title="Directional lane mix"
              subtitle="Calculated from the selected orders"
            >
              <div className="route-distribution">
                {data.charts.routes.slice(0, 5).map((row) => (
                  <div
                    className="route-item"
                    key={`${row.origin}-${row.destination}`}
                  >
                    <p>
                      {row.origin.split(",")[0]}{" "}
                      <span aria-hidden="true">→</span>{" "}
                      {row.destination.split(",")[0]}
                    </p>
                    <span>{row.shipments}</span>
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
                    title="No lanes to show"
                    text="Upload shipment records to calculate the lane mix."
                  />
                )}
              </div>
            </Panel>
          </div>
          <details className="panel disclosure">
            <summary>Metric definitions and snapshot assumptions</summary>
            {Object.entries(data.definitions).map(([name, definition]) => (
              <p key={name}>
                <strong>{name}:</strong> {definition}
              </p>
            ))}
            <p>
              Analysis cutoff: {data.cutoff}. Changing the analysis day does not
              reconstruct historical statuses.
            </p>
          </details>
        </>
      )}
    </WorkspaceBoundary>
  );
}

export function Shipments() {
  const { data, query, filters, setFilter } = useWorkspace();
  const [quality, setQuality] = useState(false),
    [expanded, setExpanded] = useState<number | null>(null);
  return (
    <>
      <PageHeading
        title="Shipment workspace"
        description="Inspect the source, refine your view, and keep every data-quality issue visible."
        action={
          <Button asChild variant="outline" size="sm">
            <a href={`/api/exports/shipments?${query}`} download>
              <Download size={13} />
              Export CSV
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
                Selected source rows<strong>{data.total_rows}</strong>
              </span>
              <span>
                Retained unique shipments
                <strong>{data.kpis.total_shipments}</strong>
              </span>
              <span>
                Quality findings<strong>{data.issue_count}</strong>
              </span>
              <button
                className="text-button"
                onClick={() => setQuality((v) => !v)}
              >
                {quality ? "Show shipments" : "Inspect data quality"}
              </button>
            </div>
            <Panel
              title={quality ? "Data quality findings" : "Shipment register"}
              subtitle={
                quality
                  ? `Showing up to 500 of ${data.issue_count} findings. Full findings are available in the CSV export.`
                  : "Invalid field values remain available for review; duplicate IDs keep their first occurrence."
              }
              action={
                quality && (
                  <a
                    className="text-button"
                    href={`/api/exports/quality?${query}`}
                    download
                  >
                    Export findings <Download size={12} />
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
                          <th>Row</th>
                          <th>Shipment</th>
                          <th>Field</th>
                          <th>Finding</th>
                          <th>Raw value</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.issues.map((row, i) => (
                          <tr key={i}>
                            <td>{row.source_row}</td>
                            <td>{row.shipment_id || "Missing ID"}</td>
                            <td>{row.field}</td>
                            <td>{row.message}</td>
                            <td>{row.raw_value || "Empty"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState
                    title="No quality findings"
                    text="The selected records passed the implemented field-level checks."
                  />
                )
              ) : data.shipments.length ? (
                <>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Shipment</th>
                          <th>Origin / destination</th>
                          <th>Carrier / mode</th>
                          <th>Reported status</th>
                          <th>Cost (USD)</th>
                          <th>Assessment</th>
                          <th>Details</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.shipments.map((row) => (
                          <tr key={row.source_row}>
                            <td>
                              <strong>{row.shipment_id || "Missing ID"}</strong>
                              <span className="cell-sub">
                                Source row {row.source_row}
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
                                {row.transport_mode}
                              </span>
                            </td>
                            <td>
                              <StatusBadge value={row.status} />
                            </td>
                            <td>{money(row.shipping_cost, 2)}</td>
                            <td>
                              {row.included_in_analysis ? (
                                row.exception_types ? (
                                  <Badge tone="amber">Exception</Badge>
                                ) : (
                                  <Badge tone="green">No rule finding</Badge>
                                )
                              ) : (
                                <Badge>Excluded</Badge>
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
                                aria-label={`Inspect source row ${row.source_row}`}
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
                      {filters.offset + 1}–
                      {Math.min(filters.offset + data.limit, data.total_rows)}{" "}
                      of {data.total_rows} source rows
                    </span>
                    <div>
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={filters.offset === 0}
                        aria-label="Previous shipment page"
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
                        aria-label="Next shipment page"
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
                  title="No matching shipments"
                  text="Clear filters or upload a table with shipment rows. Header-only tables are supported."
                />
              )}
            </Panel>
            {expanded != null &&
              data.shipments.find((row) => row.source_row === expanded) && (
                <div className="explanation-block">
                  <h3>Source record details</h3>
                  {[
                    data.shipments.find((row) => row.source_row === expanded)!,
                  ].map((row) => (
                    <div key={row.source_row}>
                      <p>
                        Planned delivery:{" "}
                        {row.planned_delivery ?? "Missing / invalid"}
                      </p>
                      <p>
                        Actual delivery:{" "}
                        {row.actual_delivery ?? "Not reported / invalid"}
                      </p>
                      <p>Cost assessment: {row.cost_assessment}</p>
                      <p>
                        Quality findings: {row.data_quality_issues || "None"}
                      </p>
                      <p>
                        Priority: {row.priority_level}.{" "}
                        {row.missing_information}
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
  const { data, query } = useWorkspace();
  const [page, setPage] = useState(0),
    [selected, setSelected] = useState("");
  useEffect(() => {
    setPage(0);
  }, [data]);
  const selectedRow = data?.exceptions.find(
    (row) => `${row.source_row}` === selected,
  );
  return (
    <>
      <PageHeading
        title="Exception intelligence"
        description="Explainable priorities, with a separate lane for missing evidence."
        action={
          <Button asChild variant="outline" size="sm">
            <a href={`/api/exports/priority?${query}`} download>
              <Download size={13} />
              Priority CSV
            </a>
          </Button>
        }
      />
      <Filters />
      <WorkspaceBoundary>
        {data && (
          <>
            <div className="kpi-grid">
              {[
                [
                  "Active transport exceptions",
                  data.exceptions.filter((row) => row.actionable).length,
                ],
                [
                  "High priority",
                  data.exceptions.filter((row) => row.priority_level === "High")
                    .length,
                ],
                [
                  "Information needed",
                  data.exceptions.filter(
                    (row) => row.priority_level === "Insufficient information",
                  ).length,
                ],
                [
                  "Review only",
                  data.exceptions.filter(
                    (row) => row.priority_level === "Review only",
                  ).length,
                ],
              ].map(([label, value]) => (
                <div className="kpi" key={String(label)}>
                  <div className="kpi-label">
                    {label}
                    <ShieldAlert size={14} />
                  </div>
                  <strong>{value}</strong>
                  <small>Within the displayed exception queue</small>
                </div>
              ))}
            </div>
            <Panel
              title="Prioritized exception queue"
              subtitle={`Showing up to 500 of ${data.exception_count} findings. Completed delays remain separate from active overdue shipments.`}
              action={
                <Button asChild size="sm" variant="ghost">
                  <Link href="/app/settings">
                    <Filter size={12} />
                    Scoring settings
                  </Link>
                </Button>
              }
            >
              {data.exceptions.length ? (
                <>
                  <ExceptionRows
                    rows={data.exceptions.slice(page * 20, page * 20 + 20)}
                  />
                  <div className="table-footer">
                    <span>
                      {page * 20 + 1}–
                      {Math.min(page * 20 + 20, data.exceptions.length)} of{" "}
                      {data.exceptions.length}
                    </span>
                    <div>
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={page === 0}
                        aria-label="Previous exception page"
                        onClick={() => setPage((v) => v - 1)}
                      >
                        <ChevronLeft size={16} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={(page + 1) * 20 >= data.exceptions.length}
                        aria-label="Next exception page"
                        onClick={() => setPage((v) => v + 1)}
                      >
                        <ChevronRight size={16} />
                      </Button>
                    </div>
                  </div>
                </>
              ) : (
                <EmptyState
                  title="No exceptions in this selection"
                  text="The implemented rules found no operational or data-quality exceptions for these records."
                />
              )}
            </Panel>
            <div className="explanation-block">
              <h3>Inspect a priority rationale</h3>
              <select
                className="input"
                aria-label="Exception rationale shipment"
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
              >
                <option value="">
                  Select a shipment to inspect its evidence
                </option>
                {data.exceptions.map((row) => (
                  <option key={row.source_row} value={row.source_row}>
                    {row.shipment_id || "Missing ID"} — {row.priority_level}
                  </option>
                ))}
              </select>
              {selectedRow && (
                <>
                  <p style={{ marginTop: 14 }}>{selectedRow.explanation}</p>
                  {selectedRow.missing_information && (
                    <p>
                      <strong>Missing information:</strong>{" "}
                      {selectedRow.missing_information}
                    </p>
                  )}
                  <p>
                    Known-input coverage:{" "}
                    {percent(selectedRow.coverage_percent / 100)}. Score:{" "}
                    {num(selectedRow.priority_score, 4)}.
                  </p>
                </>
              )}
            </div>
            <div className="notice">
              <ShieldAlert size={15} />
              <p>
                Priority is a triage rule, not a loss prediction. Missing inputs
                are not zero-filled. Shipment value alone does not establish
                financial loss.
              </p>
            </div>
          </>
        )}
      </WorkspaceBoundary>
    </>
  );
}
