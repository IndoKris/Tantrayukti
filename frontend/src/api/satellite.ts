/** Satellite NO2 and community map endpoints (Phase 22). */

import { api } from './client.ts'

export interface CityNo2Row {
  id: number
  city: string
  state: string
  latitude: string
  longitude: string
  /** Tropospheric COLUMN density. Not a surface concentration. */
  no2_umol_per_m2: string
  unit: string
  unit_note: string
  population_millions: string | null
  observed_on: string | null
  source: string
  is_measured: boolean
  anomaly_score: number | null
  is_hotspot: boolean
  hotspot_note: string
}

export interface CommunityPointRow {
  id: number
  latitude: string
  longitude: string
  label: string
  building_count: number
  total_kwh: string
  total_area_sqm: string | null
  kwh_per_sqm: string | null
}

export interface CommunityMapResponse {
  window: { from: string; to: string; days: number }
  privacy: string
  energy_points: CommunityPointRow[]
  no2: { unit: string; unit_note: string; results: CityNo2Row[] }
}

export const getCommunityMap = (days = 30) =>
  api.get<CommunityMapResponse>('/api/community/map/', { params: { days } })

export interface HotspotsResponse {
  status: string
  unit: string
  unit_note: string
  cities_considered: number
  hotspot_count: number
  threshold: {
    rule: string
    median_umol_per_m2: number
    robust_sigma_umol_per_m2: number
    fence_umol_per_m2: number
    fence_sigmas: number
  }
  features: string[]
  hotspots: CityNo2Row[]
  note: string
}

export const getSatelliteHotspots = () =>
  api.get<HotspotsResponse>('/api/satellite-hotspots/')

export const getCityNo2 = () =>
  api.get<{
    unit: string
    unit_note: string
    count: number
    measured_count: number
    provenance_note: string
    results: CityNo2Row[]
  }>('/api/satellite/cities/')

export interface Co2TrendResponse {
  model: string
  unit: string
  fit: {
    slope_per_day: number
    intercept: number
    r2: number | null
    p_value: number
    is_significant: boolean
    alpha: number
    n_days: number
    residual_std: number
    direction: string
  }
  projection: {
    horizon_days: number
    points: { date: string; predicted: number; lower: number; upper: number }[]
  }
  caveats: string[]
}

export const getCo2Trend = () => api.get<Co2TrendResponse>('/api/community/co2-trend/')
