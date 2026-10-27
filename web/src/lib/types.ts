export type Shipment = {
  source_row: number;
  shipment_id: string;
  origin: string;
  destination: string;
  carrier: string;
  transport_mode: string;
  status: string;
  planned_delivery: string | null;
  actual_delivery: string | null;
  shipping_cost: number | null;
  included_in_analysis: boolean;
  delay_hours: number | null;
  overdue_hours: number | null;
  exception_types: string;
  is_exception: boolean;
  is_overdue: boolean;
  is_delayed: boolean;
  actionable: boolean;
  priority_score: number | null;
  priority_level: string;
  coverage_percent: number;
  explanation: string;
  missing_information: string;
  priority_details_json: string;
  data_quality_issues: string;
  cost_assessment: string;
};
export type PriorityConfig = {
  weights: Record<string, number>;
  urgency_window_hours: number;
  delay_scale_hours: number;
  financial_scale_usd: number;
  value_scale_usd: number;
  dependency_scale: number;
  medium_threshold: number;
  high_threshold: number;
};
export type Dataset = {
  dataset_id: string;
  name: string;
  synthetic: boolean;
  as_of: string;
  created_at: string;
};
export type Workspace = {
  dataset: Dataset;
  as_of: string;
  cutoff: string;
  kpis: Record<string, number | null>;
  definitions: Record<string, string>;
  total_rows: number;
  offset: number;
  limit: number;
  shipments: Shipment[];
  exceptions: Shipment[];
  exception_count: number;
  issues: {
    source_row: number;
    shipment_id: string;
    field: string;
    code: string;
    severity: string;
    message: string;
    raw_value: string;
  }[];
  issue_count: number;
  filters: { carrier: string[]; transport_mode: string[]; status: string[] };
  charts: {
    statuses: { status: string; count: number }[];
    carriers: {
      carrier: string;
      eligible_deliveries: number;
      on_time_rate_pct: number | null;
    }[];
    costs: { transport_mode: string; mean: number; count: number }[];
    routes: { origin: string; destination: string; shipments: number }[];
    delays: { shipment_id: string; carrier: string; delay_hours: number }[];
  };
  priority_config: PriorityConfig;
};
export type Assumption = {
  action: string;
  additional_cost: number;
  remaining_hours: number;
  assumed_available: boolean;
  notes: string;
};
export type Comparison = {
  action: string;
  estimated_additional_cost_usd: number;
  assumed_remaining_hours: number;
  assumed_available: boolean;
  scenario_arrival_utc: string | null;
  estimated_delay_hours: number | null;
  deadline_impact: string;
  key_assumptions: string;
};
export type DecisionResult = {
  shipment_id: string;
  comparison: Comparison[];
  cutoff: string;
  deadline: string | null;
  deadline_source: string;
  similar_cases: CaseRecord[];
};
export type CaseRecord = {
  case_id: string;
  shipment_id: string;
  exception_type: string;
  selected_action: string;
  estimated_cost: number | null;
  actual_cost: number | null;
  estimated_delay: number | null;
  actual_delay: number | null;
  resolution_status: string;
  resolution_notes: string;
  created_at: string;
  version: number;
};
export type OptimizationInput = {
  count: number;
  data_seed: number;
  budget_percent: number;
  deadline_shift_hours: number;
  weight_capacity_percent: number;
  volume_capacity_percent: number;
  shipment_capacity_percent: number;
  allow_unassigned: boolean;
  unassigned_penalty_usd: number;
  cost_weight: number;
  time_weight: number;
  risk_weight: number;
  scenario_count: number;
  seed: number;
  time_limit_seconds: number;
};
export type Allocation = {
  shipment_id: string;
  service_id: string;
  cost_usd: number;
  expected_hours: number;
  deadline_hours: number;
  assumed_late_probability: number;
  weight_kg: number;
  volume_m3: number;
};
export type StrategySummary = {
  strategy: string;
  status: string;
  assigned_orders: number | null;
  unassigned_orders: number | null;
  total_shipping_cost_usd: number | null;
  simulated_on_time_rate_all_orders: number | null;
  simulated_on_time_rate_assigned: number | null;
  allocation_seconds: number;
  weight_utilization: number | null;
  volume_utilization: number | null;
  slot_utilization: number | null;
  same_full_fulfillment_comparison: boolean;
  simulated_late_probability_assigned: number | null;
  mean_simulated_delay_hours_assigned: number | null;
  p95_total_delay_hours: number | null;
  on_time_rate_monte_carlo_se: number | null;
};
export type OptimizationRun = {
  run_id: string;
  created_at: string;
  request: OptimizationInput;
  provenance: string;
  local_recommendations: {
    shipment_id: string;
    strategy: string;
    service_id: string | null;
    explanation: string;
    value: number | null;
  }[];
  summary: StrategySummary[];
  seed: number;
  scenario_count: number;
  scenario_fingerprint: string;
  elapsed_seconds: number;
  constraints: { budget_usd: number; allow_unassigned: boolean };
  preferences: { cost: number; time: number; risk: number };
  candidate_checks: {
    shipment_id: string;
    service_id: string;
    eligible: boolean;
    rejection_reasons: string;
    cost_usd: number;
    expected_hours: number;
    assumed_late_probability: number;
    balanced_score: number | null;
  }[];
  results: Record<
    string,
    {
      status: string;
      assignments: Allocation[];
      diagnostics: string[];
      unassigned_ids: string[];
      objective_value_integer_units: number | null;
      best_bound_integer_units: number | null;
      capacity: {
        service_id: string;
        weight_utilization: number | null;
        volume_utilization: number | null;
        slot_utilization: number | null;
      }[];
    }
  >;
  simulation_details: Record<
    string,
    {
      shipment_id: string;
      expected_hours: number;
      deadline_hours: number;
      simulated_transit_hours_scenario_0: number;
      estimated_late_probability: number;
      p95_simulated_transit_hours: number;
    }[]
  >;
};
