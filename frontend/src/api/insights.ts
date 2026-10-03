/** Typed endpoints for usage, billing, forecasts, anomalies and comparisons. */

import { api } from './client.ts'

// --- Usage (Phase 8) -----------------------------------------------------------

export interface UsageRow {
  bucket: string
  energy_kwh: string
  energy_wh: string
  mean_power_w: string | null
  peak_power_w: string | null
  min_power_w: string | null
  sample_count: number
}

export interface UsageResponse {
  scope: { kind: string; id: number | null; label: string; area_sqm: string | null; occupancy: number | null }
  window: { from: string; to: string }
  period: string | null
  group_by: string
  metering: { requested: string; applied: string; device_count: number; note: string }
  totals: UsageRow & { first_reading_at: string | null; last_reading_at: string | null }
  results: UsageRow[]
}

export const getUsage = (params: Record<string, string | number | undefined>) =>
  api.get<UsageResponse>('/api/usage/', { params })

// --- Devices (Phase 6) ---------------------------------------------------------

export interface DeviceRow {
  id: number
  name: string
  room_name: string
  kind: string
  status: 'online' | 'offline' | 'never-seen' | 'disabled'
  is_online: boolean
  last_seen_at: string | null
  seconds_since_last_seen: number | null
  reading_count: number
  reported_buffer_count: number | null
  buffered_count: number
}

export const getDevices = () =>
  api.get<{ count: number; results: DeviceRow[] }>('/api/devices/', {
    params: { page_size: 100 },
  })

// --- Forecast (Phase 11) -------------------------------------------------------

export interface ForecastResponse {
  device: { id: number; name: string; room: string; kind: string }
  history: {
    hours: number
    from: string
    to: string
    total_kwh: number
    points: { timestamp: string; energy_kwh: string }[]
  }
  forecast: {
    horizon_hours: number
    unit: string
    total_kwh: number
    peak_kwh: number
    points: { timestamp: string; energy_kwh: number }[]
    model: {
      backend: string
      architecture: string
      is_fallback: boolean
      preset: string
      trained_on: string | null
      trained_on_synthetic: boolean | null
    }
    caveats: string[]
  }
  metrics_source: string
}

export const getForecast = (deviceId: number) =>
  api.get<ForecastResponse>(`/api/forecast/${deviceId}/`)

// --- Billing (Phase 9 / 12) ----------------------------------------------------

export interface SlabLine {
  label: string
  units_kwh: string
  rate_inr_per_kwh: string
  charge_inr: string
  formula: string
}

export interface EstimateResponse {
  energy: { total_kwh: string; peak_power_w: string | null; sample_count: number }
  window_days: number
  metering: { requested: string; applied: string; device_count: number }
  cost: {
    total_kwh: string
    energy_charge_inr: string
    slab_lines: SlabLine[]
    tou_adjustment_inr: string
    tou_lines: { name: string; window: string; multiplier: string; kind: string; units_kwh: string; adjustment_inr: string }[]
    fixed_charge_inr: string
    tax_percent: string
    tax_inr: string
    total_inr: string
    effective_rate_inr_per_kwh: string | null
    tariff: { name: string; is_sample: boolean; source: string }
    notes: string[]
  }
  co2: {
    energy_kwh: string
    kg_co2: string
    formula: string
    factor: {
      kg_co2_per_kwh: string
      name: string
      kind: string
      region: string
      source: string
      is_verified: boolean
      is_fallback: boolean
    }
  }
}

export const getEstimate = (params: Record<string, string | number | undefined>) =>
  api.get<EstimateResponse>('/api/billing/estimate/', { params })

export interface ProjectionResponse {
  projection: {
    month: string
    days_in_month: number
    days_elapsed: string
    days_remaining: string
    consumed_kwh: string
    mean_kwh_per_day: string
    projected_kwh: string
    bill_to_date: EstimateResponse['cost']
    projected_bill: EstimateResponse['cost']
    assumptions: string[]
  }
  co2_to_date: EstimateResponse['co2']
  co2_projected: EstimateResponse['co2']
}

export const getProjection = (params: Record<string, string | number | undefined>) =>
  api.get<ProjectionResponse>('/api/billing/projection/', { params })

// --- Spaces (Phase 5) ----------------------------------------------------------

export interface TreeRoom {
  id: number
  name: string
  kind: string
  kind_display: string
  area_sqm: string | null
  occupancy: number | null
}

export interface TreeFloor {
  id: number
  name: string
  level: number
  total_area_sqm: string | null
  total_occupancy: number
  rooms: TreeRoom[]
}

export interface TreeBuilding {
  id: number
  name: string
  address: string
  total_area_sqm: string | null
  total_occupancy: number
  floors: TreeFloor[]
}

export interface TreeOrganisation {
  id: number
  name: string
  slug: string
  total_area_sqm: string | null
  total_occupancy: number
  buildings: TreeBuilding[]
}

export const getSpaceTree = () =>
  api.get<TreeOrganisation[]>('/api/spaces/organisations/tree/')

// --- Comparisons (Phase 16) ----------------------------------------------------

export interface SpaceComparisonRow {
  kind: string
  id: number
  name: string
  path: string
  energy_kwh: string
  area_sqm: string | null
  occupancy: number | null
  kwh_per_sqm: string | null
  kwh_per_person: string | null
  rank?: number
  excluded_reason?: string
  device_count: number
}

export interface SpaceComparisonResponse {
  scope: { kind: string; id: number }
  compared_level: string
  normalise_by: string
  results: SpaceComparisonRow[]
  excluded: SpaceComparisonRow[]
  notes: string[]
}

export const compareSpaces = (params: Record<string, string | number | undefined>) =>
  api.get<SpaceComparisonResponse>('/api/compare/spaces/', { params })

export interface PeriodComparisonResponse {
  period: string
  label: string
  current: { from: string; to: string; energy_kwh: string; sample_count: number }
  previous: { from: string; to: string; energy_kwh: string; sample_count: number }
  elapsed_fraction: string
  is_partial_period: boolean
  comparable_previous_kwh: string
  change_kwh: string
  change_percent: string | null
  direction: 'up' | 'down' | 'flat'
  notes: string[]
}

export const comparePeriods = (params: Record<string, string | number | undefined>) =>
  api.get<PeriodComparisonResponse>('/api/compare/periods/', { params })

// --- Anomalies, causes, recommendations (Phases 13-15) -------------------------

export interface AnomalyRow {
  id: number
  device: number
  device_name: string
  room_name: string
  detector: string
  detector_display: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  severity_display: string
  window_start: string
  window_end: string
  observed_kwh: string
  expected_kwh: string | null
  excess_kwh: string | null
  score: number | null
  title: string
  evidence: Record<string, unknown>
  state: 'open' | 'acknowledged' | 'resolved' | 'dismissed'
  state_display: string
  is_open: boolean
  acknowledged_by_username: string | null
  resolution_note: string
}

export const getAnomalies = (params: Record<string, string | number | undefined> = {}) =>
  api.get<{ count: number; results: AnomalyRow[] }>('/api/anomalies/', {
    params: { page_size: 100, ...params },
  })

export const acknowledgeAnomaly = (id: number) =>
  api.post<AnomalyRow>(`/api/anomalies/${id}/acknowledge/`)

export const resolveAnomaly = (id: number, note = '') =>
  api.post<AnomalyRow>(`/api/anomalies/${id}/resolve/`, { note })

export const dismissAnomaly = (id: number, note = '') =>
  api.post<AnomalyRow>(`/api/anomalies/${id}/dismiss/`, { note })

export interface CauseRow {
  code: string
  label: string
  confidence: number
  evidence: Record<string, unknown>
  explanation: string
  suggested_action_codes: string[]
}

export interface CausesResponse {
  anomaly_id: number
  detector: string
  severity: string
  causes: CauseRow[]
  top_cause: string | null
  wording: { source: string; llm_requested: boolean; llm_used: boolean; note: string }
}

export const getCauses = (id: number) =>
  api.get<CausesResponse>(`/api/anomalies/${id}/causes/`)

export interface ActionRow {
  code: string
  title: string
  detail: string
  effort: string
  confidence: string
  savings: {
    kwh_per_month: string
    inr_per_month: string | null
    kg_co2_per_month: string | null
  }
  formula: string
  assumptions: string[]
  capital_cost_inr: string | null
  payback_months: number | null
  pricing: Record<string, unknown>
  caveat: string
}

export interface RecommendationsResponse {
  anomaly_id: number
  linked_causes: string[]
  actions: ActionRow[]
  totals_if_all_applied: {
    kwh_per_month: string
    inr_per_month: string
    kg_co2_per_month: string
    note: string
  }
}

export const getRecommendations = (id: number) =>
  api.get<RecommendationsResponse>(`/api/anomalies/${id}/recommendations/`)

export const runDetection = (device: number, days = 14) =>
  api.post<{ created: number; updated: number; findings: number }>(
    '/api/anomalies/detect/',
    { device, days },
  )

export interface DemoResponse {
  demo: true
  fault_injected: string
  device: { id: number; name: string }
  readings_written: number
  hours_simulated: number
  detection: { created: number; updated: number; findings: number }
  chain: {
    anomaly: AnomalyRow
    causes: CausesResponse
    recommendations: RecommendationsResponse
  }[]
  note: string
}

export const injectDemoFault = (device: number, fault: string, days = 10) =>
  api.post<DemoResponse>('/api/demo/inject-fault/', { device, fault, days })

// --- ML metrics (Phase 11/12/13) ------------------------------------------------

/**
 * `metrics.json` verbatim.
 *
 * Typed as unknown-valued rather than `any`: its shape grows as phases add
 * models, and the metrics page narrows each section it renders. Pretending to
 * know the shape statically would be a lie the compiler could not catch.
 */
export type MetricsPayload = Record<string, unknown>

export const getMlMetrics = () => api.get<MetricsPayload>('/api/ml/metrics/')

// --- Activity logging (Phase 20) ------------------------------------------------

export interface ActivityFactor {
  id: number
  category: string
  category_display: string
  key: string
  label: string
  quantity_unit: string
  kg_co2_per_unit: string
  source: string
  is_verified: boolean
}

export interface ActivityEntryRow {
  id: number
  factor: number
  factor_label: string
  category: string
  category_display: string
  quantity: string
  quantity_unit: string
  occurred_on: string
  note: string
  kg_co2: string
  factor_snapshot: string
  factor_source: string
  formula: string
  is_verified: boolean
}

export interface ActivityReport {
  window: { from: string; to: string }
  total_kg_co2: string
  entry_count: number
  categories: {
    category: string
    label: string
    kg_co2: string
    entry_count: number
    share_percent: string | null
    factor_sources: string[]
  }[]
  top_emitters: {
    id: number
    label: string
    category: string
    occurred_on: string
    quantity: string
    quantity_unit: string
    kg_co2: string
    formula: string
  }[]
  budget: {
    kg_co2_per_month: string
    used_kg_co2: string
    remaining_kg_co2: string
    used_percent: string | null
    over_budget: boolean
  } | null
  caveats: string[]
}

export const getActivityFactors = () =>
  api.get<{ count: number; results: ActivityFactor[] }>('/api/activity/factors/', {
    params: { page_size: 100 },
  })

export const getActivityEntries = (params: Record<string, string | number | undefined> = {}) =>
  api.get<{ count: number; results: ActivityEntryRow[] }>('/api/activity/entries/', {
    params: { page_size: 50, ...params },
  })

export const createActivityEntry = (body: {
  factor: number
  quantity: string
  occurred_on: string
  note?: string
}) => api.post<ActivityEntryRow>('/api/activity/entries/', body)

export const deleteActivityEntry = (id: number) =>
  api.delete<void>(`/api/activity/entries/${id}/`)

export const getActivityReport = (params: Record<string, string | number | undefined> = {}) =>
  api.get<ActivityReport>('/api/activity/report/', { params })

export const getActivityBudget = () =>
  api.get<{ kg_co2_per_month: string | null }>('/api/activity/budget/')

export const setActivityBudget = (kg_co2_per_month: string) =>
  api.put<{ kg_co2_per_month: string }>('/api/activity/budget/', { kg_co2_per_month })
