import { useState } from 'react'

import {
  acknowledgeAnomaly,
  dismissAnomaly,
  getAnomalies,
  getCauses,
  getDevices,
  getRecommendations,
  injectDemoFault,
  resolveAnomaly,
  type AnomalyRow,
} from '../api/insights.ts'
import { AsyncBoundary } from '../components/AsyncBoundary.tsx'
import { SeverityChip } from '../components/charts.tsx'
import { useAuth } from '../auth/context.ts'
import { useApi } from '../hooks/useApi.ts'

function when(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })
}

/** Ranked causes with the evidence behind each. */
function CauseCard({ anomalyId }: { anomalyId: number }) {
  const { data, error, loading } = useApi(() => getCauses(anomalyId), [anomalyId])

  return (
    <AsyncBoundary loading={loading} error={error} label="causes">
      {data && (
        <div className="flex flex-col gap-3">
          <h4 className="text-xs font-semibold tracking-wide uppercase text-(--surface-muted)">
            Likely cause
          </h4>
          <ol className="flex flex-col gap-3">
            {data.causes.map((cause, index) => (
              <li
                key={cause.code}
                className="rounded-lg border border-(--surface-border) bg-(--surface) p-3"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-sm font-medium">
                    {index === 0 && (
                      <span className="mr-1.5 rounded bg-eco-600 px-1.5 py-0.5 text-xs text-white">
                        most likely
                      </span>
                    )}
                    {cause.label}
                  </p>
                  <span className="tabular text-xs text-(--surface-muted)">
                    confidence {cause.confidence}
                  </span>
                </div>
                <p className="mt-1.5 text-sm text-(--surface-muted)">{cause.explanation}</p>

                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-(--surface-muted)">
                    Evidence
                  </summary>
                  <dl className="mt-1.5 grid grid-cols-1 gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
                    {Object.entries(cause.evidence).map(([key, value]) => (
                      <div key={key} className="flex gap-1.5">
                        <dt className="text-(--surface-muted)">{key}:</dt>
                        <dd className="tabular">{String(value)}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              </li>
            ))}
          </ol>
          <p className="text-xs text-(--surface-muted)">{data.wording.note}</p>
        </div>
      )}
    </AsyncBoundary>
  )
}

/** Actions with kWh / ₹ / kg CO₂ saved per month, plus the formula behind each. */
function RecommendationCard({ anomalyId }: { anomalyId: number }) {
  const { data, error, loading } = useApi(() => getRecommendations(anomalyId), [anomalyId])

  return (
    <AsyncBoundary loading={loading} error={error} label="recommendations">
      {data && (
        <div className="flex flex-col gap-3">
          <h4 className="text-xs font-semibold tracking-wide uppercase text-(--surface-muted)">
            What to do about it
          </h4>

          {data.actions.length === 0 ? (
            <p className="text-sm text-(--surface-muted)">
              No action in the catalogue applies to this anomaly.
            </p>
          ) : (
            <ul className="flex flex-col gap-3">
              {data.actions.map((action) => (
                <li
                  key={action.code}
                  className="rounded-lg border border-(--surface-border) bg-(--surface) p-3"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <p className="text-sm font-medium">{action.title}</p>
                    <span className="text-xs text-(--surface-muted)">
                      {action.effort} effort · {action.confidence} confidence
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-(--surface-muted)">{action.detail}</p>

                  <div className="mt-2 grid grid-cols-3 gap-2">
                    {[
                      { label: 'kWh/month', value: Number(action.savings.kwh_per_month).toFixed(1) },
                      {
                        label: '₹/month',
                        value:
                          action.savings.inr_per_month === null
                            ? '—'
                            : Number(action.savings.inr_per_month).toFixed(0),
                      },
                      {
                        label: 'kg CO₂/month',
                        value:
                          action.savings.kg_co2_per_month === null
                            ? '—'
                            : Number(action.savings.kg_co2_per_month).toFixed(1),
                      },
                    ].map((metric) => (
                      <div
                        key={metric.label}
                        className="rounded-md border border-(--surface-border) p-2 text-center"
                      >
                        <p className="tabular text-base font-semibold text-eco-600">
                          {metric.value}
                        </p>
                        <p className="text-xs text-(--surface-muted)">{metric.label}</p>
                      </div>
                    ))}
                  </div>

                  {action.payback_months !== null && (
                    <p className="mt-2 tabular text-xs text-(--surface-muted)">
                      Payback {action.payback_months} months on an assumed
                      ₹{action.capital_cost_inr} outlay.
                    </p>
                  )}

                  <details className="mt-2">
                    <summary className="cursor-pointer text-xs text-(--surface-muted)">
                      How this was calculated
                    </summary>
                    <p className="mt-1.5 tabular rounded bg-(--surface-raised) p-2 font-mono text-xs">
                      {action.formula}
                    </p>
                    <ul className="mt-1.5 list-disc pl-4 text-xs text-(--surface-muted)">
                      {action.assumptions.map((assumption) => (
                        <li key={assumption}>{assumption}</li>
                      ))}
                    </ul>
                    <p className="mt-1.5 text-xs text-(--surface-muted)">{action.caveat}</p>
                  </details>
                </li>
              ))}
            </ul>
          )}

          {data.actions.length > 1 && (
            <p className="tabular text-xs text-(--surface-muted)">
              If all applied: {Number(data.totals_if_all_applied.kwh_per_month).toFixed(1)} kWh,
              ₹{Number(data.totals_if_all_applied.inr_per_month).toFixed(0)},{' '}
              {Number(data.totals_if_all_applied.kg_co2_per_month).toFixed(1)} kg CO₂ per month.{' '}
              {data.totals_if_all_applied.note}
            </p>
          )}
        </div>
      )}
    </AsyncBoundary>
  )
}

function AnomalyCard({ anomaly, onChanged }: { anomaly: AnomalyRow; onChanged: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const { can } = useAuth()

  async function act(action: (id: number) => Promise<unknown>) {
    setBusy(true)
    try {
      await action(anomaly.id)
      onChanged()
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityChip severity={anomaly.severity} />
            <span className="text-xs text-(--surface-muted)">{anomaly.detector_display}</span>
            <span className="text-xs text-(--surface-muted)">· {anomaly.state_display}</span>
          </div>
          <p className="mt-1.5 text-sm font-medium">{anomaly.title}</p>
          <p className="tabular mt-0.5 text-xs text-(--surface-muted)">
            {anomaly.device_name} · {anomaly.room_name} · {when(anomaly.window_start)}
            {anomaly.excess_kwh && ` · +${Number(anomaly.excess_kwh).toFixed(2)} kWh over expected`}
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
            className="rounded-lg border border-(--surface-border) px-2.5 py-1 text-xs font-medium transition-colors hover:text-(--surface-text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500"
          >
            {expanded ? 'Hide' : 'Cause and fix'}
          </button>
          {can('manager') && anomaly.state === 'open' && (
            <button
              type="button"
              disabled={busy}
              onClick={() => act(acknowledgeAnomaly)}
              className="rounded-lg border border-(--surface-border) px-2.5 py-1 text-xs font-medium disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500"
            >
              Acknowledge
            </button>
          )}
          {can('manager') && anomaly.is_open && (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={() => act((id) => resolveAnomaly(id, 'Resolved from the dashboard'))}
                className="rounded-lg bg-eco-600 px-2.5 py-1 text-xs font-medium text-white disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500"
              >
                Resolve
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => act((id) => dismissAnomaly(id, 'Not a problem'))}
                className="rounded-lg border border-(--surface-border) px-2.5 py-1 text-xs font-medium text-(--surface-muted) disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500"
              >
                Dismiss
              </button>
            </>
          )}
        </div>
      </div>

      {expanded && (
        <div className="mt-4 grid grid-cols-1 gap-5 border-t border-(--surface-border) pt-4 lg:grid-cols-2">
          <CauseCard anomalyId={anomaly.id} />
          <RecommendationCard anomalyId={anomaly.id} />
        </div>
      )}
    </li>
  )
}

const DEMO_FAULTS = [
  { value: 'night_load', label: 'Night load' },
  { value: 'baseload_jump', label: 'Baseload jump' },
  { value: 'device_left_on', label: 'Device left on' },
] as const

/** Injects a fault, runs detection, and shows the whole chain end to end. */
function DemoMode({ onChanged }: { onChanged: () => void }) {
  const devices = useApi(() => getDevices(), [])
  const [fault, setFault] = useState<string>('night_load')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const { can } = useAuth()

  if (!can('manager')) return null

  const deviceId = devices.data?.results[0]?.id ?? null

  async function run() {
    if (deviceId === null) return
    setBusy(true)
    setResult(null)
    setFailure(null)
    try {
      const response = await injectDemoFault(deviceId, fault)
      setResult(
        `Injected ${response.fault_injected} into ${response.device.name}: ` +
          `${response.readings_written} readings written, ` +
          `${response.detection.findings} finding(s), ` +
          `${response.chain.length} anomaly chain(s) built.`,
      )
      onChanged()
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-xl border border-dashed border-(--surface-border) bg-(--surface-raised) p-5">
      <h2 className="text-sm font-semibold">Demo mode</h2>
      <p className="mt-1 max-w-prose text-sm text-(--surface-muted)">
        Inject a synthetic fault into a device&apos;s history, run detection, and see the full
        chain: anomaly → ranked cause → recommendation with savings. Every reading written is
        tagged <code className="font-mono">source=simulator</code>, so demo data stays
        distinguishable from real telemetry.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {DEMO_FAULTS.map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() => setFault(item.value)}
            aria-pressed={fault === item.value}
            className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500 ${
              fault === item.value
                ? 'border-eco-600 bg-eco-600/10 text-(--surface-text)'
                : 'border-(--surface-border) text-(--surface-muted) hover:text-(--surface-text)'
            }`}
          >
            {item.label}
          </button>
        ))}
        <button
          type="button"
          onClick={run}
          disabled={busy || deviceId === null}
          className="rounded-lg bg-eco-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-eco-700 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500"
        >
          {busy ? 'Running…' : 'Run demo'}
        </button>
      </div>

      {deviceId === null && !devices.loading && (
        <p className="mt-2 text-xs text-severity-medium">
          No device available. Register one first.
        </p>
      )}
      {result && <p className="mt-2 text-xs text-eco-600">{result}</p>}
      {failure && <p className="mt-2 text-xs text-severity-high">{failure}</p>}
    </div>
  )
}

function AnomalyFeed() {
  const [openOnly, setOpenOnly] = useState(true)
  const { data, error, loading, reload } = useApi(
    () => getAnomalies(openOnly ? { open: 'true' } : {}),
    [openOnly],
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold tracking-tight">
          Anomalies{data ? ` (${data.count})` : ''}
        </h2>
        <div className="flex gap-1.5">
          <button
            type="button"
            onClick={() => setOpenOnly(true)}
            aria-pressed={openOnly}
            className={`rounded-lg border px-2.5 py-1 text-xs font-medium ${
              openOnly
                ? 'border-eco-600 bg-eco-600/10'
                : 'border-(--surface-border) text-(--surface-muted)'
            }`}
          >
            Open only
          </button>
          <button
            type="button"
            onClick={() => setOpenOnly(false)}
            aria-pressed={!openOnly}
            className={`rounded-lg border px-2.5 py-1 text-xs font-medium ${
              !openOnly
                ? 'border-eco-600 bg-eco-600/10'
                : 'border-(--surface-border) text-(--surface-muted)'
            }`}
          >
            All
          </button>
          <button
            type="button"
            onClick={reload}
            className="rounded-lg border border-(--surface-border) px-2.5 py-1 text-xs font-medium text-(--surface-muted)"
          >
            Refresh
          </button>
        </div>
      </div>

      <DemoMode onChanged={reload} />

      <AsyncBoundary loading={loading} error={error} label="anomalies">
        {!data?.results.length ? (
          <p className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5 text-sm text-(--surface-muted)">
            No {openOnly ? 'open ' : ''}anomalies. That is the healthy state — detection
            raises nothing on a clean period rather than always filling a quota.
          </p>
        ) : (
          <ul className="flex flex-col gap-3">
            {data.results.map((anomaly) => (
              <AnomalyCard key={anomaly.id} anomaly={anomaly} onChanged={reload} />
            ))}
          </ul>
        )}
      </AsyncBoundary>
    </div>
  )
}

export default function Insights() {
  return (
    <section className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Insights</h1>
        <p className="mt-1 max-w-prose text-sm text-(--surface-muted)">
          Abnormal usage detected automatically, the likely cause with its evidence, and
          specific actions with estimated savings. Model error metrics are on the{' '}
          <a
            href="/insights/metrics"
            className="underline decoration-dotted underline-offset-2 hover:text-(--surface-text)"
          >
            ML metrics page
          </a>
          .
        </p>
      </div>

      <AnomalyFeed />
    </section>
  )
}
