import { useMemo, useState } from 'react'

import {
  getDevices,
  getEstimate,
  getForecast,
  getUsage,
  type DeviceRow,
} from '../api/insights.ts'
import { AsyncBoundary } from '../components/AsyncBoundary.tsx'
import { ChartFrame, LineSeriesChart, StatTile } from '../components/charts.tsx'
import { SERIES, type SeriesSpec } from '../components/chartTokens.ts'
import { useApi } from '../hooks/useApi.ts'

/** Local hour label, e.g. "14:00". Buckets arrive as offset-aware ISO strings. */
function hourLabel(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : `${String(date.getHours()).padStart(2, '0')}:00`
}

function statusTone(status: DeviceRow['status']): string {
  return (
    {
      online: 'bg-eco-500',
      offline: 'bg-severity-high',
      'never-seen': 'bg-(--surface-muted)',
      disabled: 'bg-(--surface-muted)',
    }[status] ?? 'bg-(--surface-muted)'
  )
}

function DeviceBadges({ onSelect, selected }: { onSelect: (id: number) => void; selected: number | null }) {
  const { data, error, loading } = useApi(() => getDevices(), [])

  return (
    <AsyncBoundary loading={loading} error={error} label="devices">
      {!data?.results.length ? (
        <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5 text-sm text-(--surface-muted)">
          No devices registered yet. Register one, or post simulated telemetry:
          <pre className="mt-2 overflow-x-auto rounded-lg bg-(--surface) p-3 font-mono text-xs">
            python simulator/run.py --days 2 --post --register --username demo --password ...
          </pre>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold">Devices</h2>
          <ul className="flex flex-wrap gap-2">
            {data.results.map((device) => (
              <li key={device.id}>
                <button
                  type="button"
                  onClick={() => onSelect(device.id)}
                  aria-pressed={selected === device.id}
                  title={
                    device.last_seen_at
                      ? `Last seen ${device.last_seen_at}`
                      : 'Never reported'
                  }
                  className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500 ${
                    selected === device.id
                      ? 'border-eco-600 bg-eco-600/10 text-(--surface-text)'
                      : 'border-(--surface-border) text-(--surface-muted) hover:text-(--surface-text)'
                  }`}
                >
                  <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${statusTone(device.status)}`} />
                  <span className="font-medium">{device.name}</span>
                  {/* Status is always written out, never colour alone. */}
                  <span>· {device.status}</span>
                  <span className="tabular">· {device.reading_count}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </AsyncBoundary>
  )
}

/** Hourly energy for the last 24 h, with the 24 h forecast continuing from it. */
function LoadChart({ deviceId }: { deviceId: number | null }) {
  const usage = useApi(
    () => getUsage({ period: 'hour', device: deviceId ?? undefined }),
    [deviceId],
  )
  const forecast = useApi(
    () => (deviceId === null ? Promise.resolve(null) : getForecast(deviceId)),
    [deviceId],
  )

  const series: SeriesSpec[] = [
    { key: 'measured', label: 'Measured', color: SERIES.measured },
    { key: 'forecast', label: 'Forecast (24 h)', color: SERIES.forecast, dashed: true },
  ]

  const rows = useMemo(() => {
    const measured = (usage.data?.results ?? []).map((row) => ({
      hour: hourLabel(row.bucket),
      measured: Number(row.energy_kwh),
      forecast: null as number | null,
    }))

    const predicted = (forecast.data?.forecast.points ?? []).map((point) => ({
      hour: hourLabel(point.timestamp),
      measured: null as number | null,
      forecast: Number(point.energy_kwh),
    }))

    // Join the forecast onto the last measured point so the lines meet rather
    // than leaving a visual gap at the boundary.
    if (measured.length && predicted.length) {
      predicted.unshift({
        hour: measured[measured.length - 1].hour,
        measured: null,
        forecast: measured[measured.length - 1].measured,
      })
    }

    return [...measured, ...predicted]
  }, [usage.data, forecast.data])

  const model = forecast.data?.forecast.model

  return (
    <AsyncBoundary loading={usage.loading} error={usage.error} label="usage">
      <ChartFrame
        title="Hourly energy and 24-hour forecast"
        unit="kWh per hour"
        series={series}
        rows={rows}
        xKey="hour"
        footnote={
          <>
            {usage.data && (
              <>
                Metering: <strong>{usage.data.metering.applied}</strong> across{' '}
                {usage.data.metering.device_count} device(s). A whole-space mains meter
                supersedes the appliance meters beneath it, so energy is not double counted.
              </>
            )}
            {forecast.error && (
              <>
                {' '}
                Forecast unavailable:{' '}
                {forecast.error instanceof Error ? forecast.error.message : 'unknown error'}.
              </>
            )}
            {model && (
              <>
                {' '}
                Forecast from <strong>{model.backend}</strong>
                {model.is_fallback && ' (fallback model, not the specified LSTM)'}; error
                metrics live in <code className="font-mono">metrics.json</code>, shown on the
                Insights page. Produced recursively, so later hours are less reliable.
              </>
            )}
          </>
        }
      >
        <LineSeriesChart rows={rows} xKey="hour" series={series} />
      </ChartFrame>
    </AsyncBoundary>
  )
}

/** Energy, cost and CO2 for the last 24 h. Every figure names its source. */
function HeadlineTiles({ deviceId }: { deviceId: number | null }) {
  const { data, error, loading } = useApi(
    () => getEstimate({ device: deviceId ?? undefined }),
    [deviceId],
  )

  return (
    <AsyncBoundary loading={loading} error={error} label="cost and CO₂">
      {data && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile
            label="Energy, last 24 h"
            value={Number(data.energy.total_kwh).toFixed(2)}
            unit="kWh"
            source={`${data.energy.sample_count} readings · metering ${data.metering.applied}`}
          />
          <StatTile
            label="Peak power"
            value={data.energy.peak_power_w ? Number(data.energy.peak_power_w).toFixed(0) : null}
            unit="W"
            source="Instantaneous maximum, not energy"
          />
          <StatTile
            label="Estimated cost"
            value={Number(data.cost.total_inr).toFixed(2)}
            unit="₹"
            tone="warning"
            source={
              <>
                {data.cost.tariff.name}
                {data.cost.tariff.is_sample && (
                  <strong className="text-severity-medium"> · sample rates</strong>
                )}
              </>
            }
          />
          <StatTile
            label="CO₂"
            value={Number(data.co2.kg_co2).toFixed(2)}
            unit="kg"
            source={
              <>
                Factor {data.co2.factor.kg_co2_per_kwh} kg/kWh ·{' '}
                {data.co2.factor.is_verified ? 'verified' : 'unverified'}
                {data.co2.factor.is_fallback && ' default'}
              </>
            }
          />
        </div>
      )}
    </AsyncBoundary>
  )
}

/** The factor's full provenance, which the plan requires to be visible. */
function FactorProvenance({ deviceId }: { deviceId: number | null }) {
  const { data } = useApi(() => getEstimate({ device: deviceId ?? undefined }), [deviceId])
  if (!data) return null

  return (
    <details className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-4 text-sm">
      <summary className="cursor-pointer text-sm font-semibold">
        Where these cost and CO₂ numbers come from
      </summary>
      <dl className="mt-3 flex flex-col gap-3 text-xs">
        <div>
          <dt className="font-medium">CO₂ formula</dt>
          <dd className="tabular text-(--surface-muted)">{data.co2.formula}</dd>
        </div>
        <div>
          <dt className="font-medium">Emission factor source</dt>
          <dd className="text-(--surface-muted)">{data.co2.factor.source}</dd>
        </div>
        <div>
          <dt className="font-medium">Tariff source</dt>
          <dd className="text-(--surface-muted)">{data.cost.tariff.source}</dd>
        </div>
        {data.cost.slab_lines.length > 0 && (
          <div>
            <dt className="font-medium">Energy charge breakdown</dt>
            <dd className="text-(--surface-muted)">
              <ul className="mt-1 flex flex-col gap-0.5">
                {data.cost.slab_lines.map((line) => (
                  <li key={line.label} className="tabular">
                    {line.formula}
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        )}
        {data.cost.notes.length > 0 && (
          <div>
            <dt className="font-medium">Notes</dt>
            <dd className="text-(--surface-muted)">
              <ul className="mt-1 list-disc pl-4">
                {data.cost.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </dd>
          </div>
        )}
      </dl>
    </details>
  )
}

export default function Dashboard() {
  const [deviceId, setDeviceId] = useState<number | null>(null)

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-xs text-(--surface-muted)">
          {deviceId === null ? 'All visible devices' : `Device #${deviceId}`}
        </p>
      </div>

      <DeviceBadges onSelect={(id) => setDeviceId((current) => (current === id ? null : id))} selected={deviceId} />
      <HeadlineTiles deviceId={deviceId} />
      <LoadChart deviceId={deviceId} />
      <FactorProvenance deviceId={deviceId} />
    </section>
  )
}
