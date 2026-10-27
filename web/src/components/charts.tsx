"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import type { Workspace, OptimizationRun } from "@/lib/types";
import { num } from "@/lib/utils";

const colors = ["#6497f2", "#d7ae6c", "#7abeb0", "#aa93d6", "#8a9fbf"];
const axis = { fill: "#8396b5", fontSize: 9 };
export function CarrierChart({
  data,
}: {
  data: Workspace["charts"]["carriers"];
}) {
  return (
    <div className="chart-box">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data.filter((row) => row.on_time_rate_pct != null)}
          margin={{ top: 15, right: 25, left: -18, bottom: 10 }}
          barSize={30}
        >
          <CartesianGrid
            stroke="#263248"
            vertical={false}
            strokeDasharray="2 5"
          />
          <XAxis
            dataKey="carrier"
            tick={axis}
            tickFormatter={(value) => String(value).replace("Demo ", "")}
            axisLine={false}
            tickLine={false}
            interval={0}
          />
          <YAxis
            domain={[0, 100]}
            tick={axis}
            tickFormatter={(value) => `${value}%`}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            cursor={{ fill: "#1b2c46" }}
            formatter={(value) => [
              `${num(Number(value))}%`,
              "On-time delivery",
            ]}
          />
          <Bar
            isAnimationActive={false}
            dataKey="on_time_rate_pct"
            fill="#6497f2"
            radius={[3, 3, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
export function StatusChart({
  data,
  total,
}: {
  data: Workspace["charts"]["statuses"];
  total: number;
}) {
  return (
    <div className="donut-wrap">
      <div className="donut-chart">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              isAnimationActive={false}
              data={data}
              dataKey="count"
              nameKey="status"
              innerRadius="65%"
              outerRadius="82%"
              paddingAngle={3}
              stroke="none"
            >
              {data.map((_, i) => (
                <Cell fill={colors[i % colors.length]} key={i} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
        <div className="donut-center">
          <strong>{total}</strong>
          <span>Shipments</span>
        </div>
      </div>
      <div className="donut-legend">
        {data.map((row, i) => (
          <div key={row.status}>
            <i style={{ background: colors[i % colors.length] }} />
            <span>{row.status}</span>
            <strong>{row.count}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}
export function CostChart({ data }: { data: Workspace["charts"]["costs"] }) {
  return (
    <div className="chart-box">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          margin={{ top: 15, left: -8, right: 20, bottom: 10 }}
          barSize={35}
        >
          <CartesianGrid
            stroke="#263248"
            vertical={false}
            strokeDasharray="2 5"
          />
          <XAxis
            dataKey="transport_mode"
            tick={axis}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={axis}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => `$${Number(v) / 1000}k`}
          />
          <Tooltip
            cursor={{ fill: "#1b2c46" }}
            formatter={(value) => [
              `$${num(Number(value), 2)}`,
              "Average shipping cost",
            ]}
          />
          <Bar
            isAnimationActive={false}
            dataKey="mean"
            fill="#83b9ae"
            radius={[3, 3, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
export function StrategyChart({ run }: { run: OptimizationRun }) {
  const data = run.summary
    .filter((row) => row.total_shipping_cost_usd != null)
    .map((row) => ({
      ...row,
      name: row.strategy.replace(" Delivery", "").replace(" Allocation", ""),
    }));
  return (
    <div className="chart-box">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          margin={{ top: 15, left: 3, right: 20, bottom: 5 }}
          barSize={38}
        >
          <CartesianGrid
            stroke="#263248"
            vertical={false}
            strokeDasharray="2 5"
          />
          <XAxis dataKey="name" tick={axis} tickLine={false} axisLine={false} />
          <YAxis
            tick={axis}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `$${Number(v) / 1000}k`}
          />
          <Tooltip
            formatter={(v) => [`$${num(Number(v), 2)}`, "Shipping cost"]}
            cursor={{ fill: "#1b2c46" }}
          />
          <Bar
            isAnimationActive={false}
            dataKey="total_shipping_cost_usd"
            radius={[3, 3, 0, 0]}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={colors[i]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
export function CapacityChart({ run }: { run: OptimizationRun }) {
  const data = run.results["Optimized Allocation"].capacity.map((row) => ({
    ...row,
    service: row.service_id.replace("SYN-", ""),
  }));
  return (
    <div className="chart-box">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          margin={{ top: 15, left: -15, right: 20, bottom: 5 }}
        >
          <CartesianGrid
            stroke="#263248"
            vertical={false}
            strokeDasharray="2 5"
          />
          <XAxis
            dataKey="service"
            tick={{ ...axis, fontSize: 8 }}
            tickFormatter={(value) =>
              String(value)
                .replace("PRIORITY", "Pri")
                .replace("REGULAR", "Reg")
                .replace("ECONOMY", "Eco")
            }
            tickLine={false}
            axisLine={false}
            interval={0}
          />
          <YAxis
            domain={[0, 1]}
            tick={axis}
            tickFormatter={(v) => `${Number(v) * 100}%`}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            formatter={(v) => `${(Number(v) * 100).toFixed(1)}%`}
            cursor={{ fill: "#1b2c46" }}
          />
          <Bar
            isAnimationActive={false}
            dataKey="weight_utilization"
            name="Weight"
            fill="#6497f2"
            radius={[2, 2, 0, 0]}
          />
          <Bar
            isAnimationActive={false}
            dataKey="volume_utilization"
            name="Volume"
            fill="#83b9ae"
            radius={[2, 2, 0, 0]}
          />
          <Bar
            isAnimationActive={false}
            dataKey="slot_utilization"
            name="Slots"
            fill="#ba9ad8"
            radius={[2, 2, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
