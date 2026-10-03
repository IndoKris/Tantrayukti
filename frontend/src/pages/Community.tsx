import 'leaflet/dist/leaflet.css'

import { useMemo } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip } from 'react-leaflet'

import { getCommunityMap, getCo2Trend, getSatelliteHotspots } from '../api/satellite.ts'
import { AsyncBoundary } from '../components/AsyncBoundary.tsx'
import { ChartFrame, RankedBarChart, StatTile } from '../components/charts.tsx'
import { SERIES } from '../components/chartTokens.ts'
import { useApi } from '../hooks/useApi.ts'

/**
 * Community map, NO2 layer and the CO2 trend.
 *
 * Three things are stated on the page rather than assumed:
 *
 * 1. **NO2 is a tropospheric column density in µmol/m²**, not a surface
 *    concentration. No ppb conversion is shown because none is performed.
 * 2. **Coordinates are rounded to about 100 m** before they ever reach the
 *    browser, so the map cannot resolve to a household.
 * 3. **The values are a static fallback**, not satellite measurements, because
 *    no Earth Engine credentials are configured.
 */

/** Map a value in a range onto a radius, so a marker encodes magnitude by area. */
function radiusFor(value: number, max: number, min = 6, span = 14): number {
  if (!Number.isFinite(value) || max <= 0) return min
  return min + (value / max) * span
}

function MapPanel() {
  const { data, error, loading } = useApi(() => getCommunityMap(30), [])

  const maxNo2 = useMemo(
    () => Math.max(1, ...(data?.no2.results ?? []).map((row) => Number(row.no2_umol_per_m2))),
    [data],
  )
  const maxEnergy = useMemo(
    () => Math.max(1, ...(data?.energy_points ?? []).map((row) => Number(row.total_kwh))),
    [data],
  )

  return (
    <AsyncBoundary loading={loading} error={error} label="community map">
      {data && (
        <div className="flex flex-col gap-3">
          <div className="overflow-hidden rounded-xl border border-(--surface-border)">
            <MapContainer
              center={[21.146, 79.089]}
              zoom={5}
              scrollWheelZoom={false}
              style={{ height: '28rem', width: '100%' }}
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />

              {/* NO2 layer: radius encodes the column density. */}
              {data.no2.results.map((city) => (
                <CircleMarker
                  key={`no2-${city.id}`}
                  center={[Number(city.latitude), Number(city.longitude)]}
                  radius={radiusFor(Number(city.no2_umol_per_m2), maxNo2)}
                  pathOptions={{
                    color: city.is_hotspot ? 'var(--status-critical)' : SERIES.comparison,
                    fillColor: city.is_hotspot ? 'var(--status-critical)' : SERIES.comparison,
                    fillOpacity: 0.35,
                    weight: 2,
                  }}
                >
                  <Tooltip>
                    {city.city}: {city.no2_umol_per_m2} µmol/m²
                    {city.is_hotspot && ' · hotspot'}
                  </Tooltip>
                  <Popup>
                    <strong>
                      {city.city}
                      {city.state && `, ${city.state}`}
                    </strong>
                    <br />
                    NO₂ column: {city.no2_umol_per_m2} µmol/m²
                    <br />
                    <em>{city.unit_note}</em>
                    <br />
                    {city.is_hotspot ? <strong>Hotspot.</strong> : 'Not a hotspot.'}{' '}
                    {city.hotspot_note}
                    <br />
                    <em>{city.source}</em>
                  </Popup>
                </CircleMarker>
              ))}

              {/* Energy layer: your own aggregated consumption points. */}
              {data.energy_points.map((point) => (
                <CircleMarker
                  key={`energy-${point.id}`}
                  center={[Number(point.latitude), Number(point.longitude)]}
                  radius={radiusFor(Number(point.total_kwh), maxEnergy, 8, 16)}
                  pathOptions={{
                    color: SERIES.measured,
                    fillColor: SERIES.measured,
                    fillOpacity: 0.5,
                    weight: 2,
                  }}
                >
                  <Tooltip>
                    {point.label}: {Number(point.total_kwh).toFixed(1)} kWh
                  </Tooltip>
                  <Popup>
                    <strong>{point.label}</strong>
                    <br />
                    {Number(point.total_kwh).toFixed(2)} kWh over {data.window.days} days
                    <br />
                    {point.building_count} building(s)
                    {point.kwh_per_sqm &&
                      ` · ${Number(point.kwh_per_sqm).toFixed(3)} kWh/m²`}
                  </Popup>
                </CircleMarker>
              ))}
            </MapContainer>
          </div>

          {/* Legend: identity is never colour alone, so each entry is labelled. */}
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {[
              { color: SERIES.measured, label: 'Your energy (kWh, radius by magnitude)' },
              { color: SERIES.comparison, label: 'City NO₂ column (µmol/m²)' },
              { color: 'var(--status-critical)', label: 'NO₂ hotspot' },
            ].map((entry) => (
              <li key={entry.label} className="flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="size-3 shrink-0 rounded-full"
                  style={{ backgroundColor: entry.color, opacity: 0.6 }}
                />
                <span className="text-(--surface-muted)">{entry.label}</span>
              </li>
            ))}
          </ul>

          <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-4 text-xs text-(--surface-muted)">
            <p>
              <strong>Units.</strong> {data.no2.unit_note}
            </p>
            <p className="mt-1.5">
              <strong>Privacy.</strong> {data.privacy}
            </p>
          </div>
        </div>
      )}
    </AsyncBoundary>
  )
}

function HotspotPanel() {
  const { data, error, loading } = useApi(() => getSatelliteHotspots(), [])

  const rows = useMemo(
    () =>
      (data?.hotspots ?? []).map((city) => ({
        name: city.city,
        value: Number(city.no2_umol_per_m2),
      })),
    [data],
  )

  return (
    <AsyncBoundary loading={loading} error={error} label="hotspots">
      {data && (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatTile
              label="Cities considered"
              value={data.cities_considered}
              unit=""
              source="Static fallback dataset"
            />
            <StatTile
              label="Hotspots"
              value={data.hotspot_count}
              unit=""
              tone={data.hotspot_count > 0 ? 'warning' : 'good'}
              source="Validated threshold, not a fixed fraction"
            />
            <StatTile
              label="Threshold"
              value={data.threshold.fence_umol_per_m2}
              unit="µmol/m²"
              source={`median ${data.threshold.median_umol_per_m2} + ${data.threshold.fence_sigmas} robust σ`}
            />
          </div>

          <ChartFrame
            title="NO₂ hotspot cities"
            unit="µmol/m² (tropospheric column)"
            series={[{ key: 'value', label: 'NO₂ column', color: 'var(--status-critical)' }]}
            rows={rows}
            xKey="name"
            emptyMessage="No city stands out from the rest — a real answer, not a missing one."
            footnote={
              <>
                <span className="block">{data.threshold.rule}</span>
                <span className="mt-1 block">{data.note}</span>
                <span className="mt-1 block">{data.unit_note}</span>
              </>
            }
          >
            <RankedBarChart
              rows={rows}
              labelKey="name"
              valueKey="value"
              valueLabel="µmol/m²"
              color="var(--status-critical)"
            />
          </ChartFrame>
        </div>
      )}
    </AsyncBoundary>
  )
}

function Co2TrendPanel() {
  const { data, error, loading } = useApi(() => getCo2Trend(), [])

  return (
    <AsyncBoundary loading={loading} error={error} label="CO₂ trend">
      {data && (
        <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5">
          <h2 className="text-sm font-semibold">Grid CO₂ intensity trend</h2>
          <p className="mt-1 text-xs text-(--surface-muted)">{data.unit}</p>

          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
            {[
              { label: 'Direction', value: data.fit.direction },
              { label: 'Slope / day', value: data.fit.slope_per_day },
              { label: 'R²', value: data.fit.r2 },
              {
                label: 'Significant',
                value: `${data.fit.is_significant ? 'yes' : 'no'} (p ${data.fit.p_value})`,
              },
            ].map((row) => (
              <div key={row.label}>
                <dt className="text-xs text-(--surface-muted)">{row.label}</dt>
                <dd className="tabular font-medium">{String(row.value)}</dd>
              </div>
            ))}
          </dl>

          {data.projection.points[0] && (
            <p className="tabular mt-3 text-xs text-(--surface-muted)">
              Next day projected {data.projection.points[0].predicted} [
              {data.projection.points[0].lower}, {data.projection.points[0].upper}] — a
              prediction interval, which widens with distance from the data.
            </p>
          )}

          <ul className="mt-3 flex flex-col gap-1.5">
            {data.caveats.map((caveat) => (
              <li key={caveat} className="flex gap-2 text-xs text-(--surface-muted)">
                <span
                  aria-hidden="true"
                  className="mt-1.5 size-1 shrink-0 rounded-full bg-severity-medium"
                />
                {caveat}
              </li>
            ))}
          </ul>
        </div>
      )}
    </AsyncBoundary>
  )
}

export default function Community() {
  return (
    <section className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Community</h1>
        <p className="mt-1 max-w-prose text-sm text-(--surface-muted)">
          Your consumption on a map alongside satellite-derived NO₂ for 20 cities.
          Coordinates are rounded to roughly 100 m before leaving the server, and NO₂ is
          reported as a tropospheric column in µmol/m² — not a surface concentration.
        </p>
      </div>

      <MapPanel />

      <div className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold tracking-tight">NO₂ hotspots</h2>
        <HotspotPanel />
      </div>

      <div className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold tracking-tight">CO₂ trend</h2>
        <Co2TrendPanel />
      </div>
    </section>
  )
}
