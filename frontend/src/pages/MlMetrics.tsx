import type { ReactNode } from 'react'

import { getMlMetrics } from '../api/insights.ts'
import { AsyncBoundary } from '../components/AsyncBoundary.tsx'
import { useApi } from '../hooks/useApi.ts'

/**
 * ML metrics, read straight from `backend/ml/artifacts/metrics.json`.
 *
 * Nothing on this page is hand-written. The file is produced by
 * `ml/evaluation/evaluate_all.py` and the anomaly evaluation test, which is what
 * makes the project's honesty rule enforceable rather than aspirational: there
 * is exactly one place a number can come from.
 *
 * Regression results are error metrics, never "accuracy".
 *
 * The payload's shape grows as phases add models, so it arrives as
 * unknown-valued JSON and is narrowed here with the small helpers below. That is
 * deliberate: a static type claiming to know the shape would be a promise the
 * compiler cannot keep, and a stale key would render `undefined` silently.
 */

type Json = Record<string, unknown>

/** Narrow a value to a nested object, or undefined. */
function obj(value: unknown): Json | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Json)
    : undefined
}

/** Narrow a value to a string array, or undefined. */
function strings(value: unknown): string[] | undefined {
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string') : undefined
}

/** Render any scalar for display, without pretending to know its type. */
function scalar(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return String(value)
}

function MetricRow({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-(--surface-border)/50 py-1">
      <dt className="text-xs text-(--surface-muted)">{label}</dt>
      <dd className="tabular text-sm font-medium">{scalar(value)}</dd>
    </div>
  )
}

function Caveats({ items }: { items: unknown }) {
  const list = strings(items)
  if (!list?.length) return null
  return (
    <ul className="mt-3 flex flex-col gap-1.5">
      {list.map((item) => (
        <li key={item} className="flex gap-2 text-xs text-(--surface-muted)">
          <span
            aria-hidden="true"
            className="mt-1.5 size-1 shrink-0 rounded-full bg-severity-medium"
          />
          {item}
        </li>
      ))}
    </ul>
  )
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5">
      <h2 className="text-sm font-semibold">{title}</h2>
      {children}
    </div>
  )
}

/** A section that has not been evaluated yet says so, with the reason. */
function NotEvaluated({ section }: { section: Json }) {
  return (
    <p className="mt-2 text-sm text-(--surface-muted)">
      Not evaluated: {scalar(section.reason)}
    </p>
  )
}

function ScoreBlock({ label, score }: { label: string; score: unknown }) {
  const row = obj(score)
  if (!row) return null

  return (
    <div>
      <h3 className="mt-3 text-xs font-semibold tracking-wide uppercase text-(--surface-muted)">
        {label}
      </h3>
      <dl className="mt-1">
        <MetricRow label="MAE (kWh)" value={row.mae} />
        <MetricRow label="RMSE (kWh)" value={row.rmse} />
        <MetricRow label="MAPE (%)" value={row.mape_percent} />
        <MetricRow label="R²" value={row.r2} />
        <MetricRow label="Samples" value={row.n} />
        {Number(row.mape_rows_excluded) > 0 && (
          <MetricRow label="Rows excluded from MAPE" value={row.mape_rows_excluded} />
        )}
      </dl>
    </div>
  )
}

function ForecastPanel({ section }: { section: Json }) {
  if (section.status !== 'evaluated') {
    return (
      <Panel title="24-hour load forecast">
        <NotEvaluated section={section} />
      </Panel>
    )
  }

  const model = obj(section.model) ?? {}
  const oneStep = obj(section.one_step) ?? {}
  const recursive = obj(section.recursive_24h) ?? {}
  const baselines = obj(oneStep.baselines) ?? {}
  const skill = obj(oneStep.skill_vs_baselines) ?? {}

  return (
    <Panel title="24-hour load forecast">
      <p className="mt-1 text-xs text-(--surface-muted)">{scalar(model.architecture)}</p>

      {model.is_fallback === true && (
        <p className="mt-2 rounded-lg border border-severity-medium/40 bg-severity-medium/10 p-2 text-xs">
          <strong>Fallback model.</strong> {scalar(model.backend_note)}
        </p>
      )}

      <ScoreBlock label="One hour ahead" score={oneStep.model} />
      <ScoreBlock
        label="24 hours ahead, recursive (what the dashboard shows)"
        score={recursive.model}
      />

      {Object.keys(baselines).length > 0 && (
        <>
          <h3 className="mt-4 text-xs font-semibold tracking-wide uppercase text-(--surface-muted)">
            Versus naive baselines (one hour ahead)
          </h3>
          <dl className="mt-1">
            {Object.entries(baselines).map(([name, baseline]) => (
              <MetricRow key={name} label={`${name} — MAE`} value={obj(baseline)?.mae} />
            ))}
          </dl>
          <dl className="mt-1">
            {Object.entries(skill).map(([name, entry]) => (
              <MetricRow
                key={name}
                label={`Improvement vs ${name} (MAE %)`}
                value={obj(entry)?.mae_improvement_percent}
              />
            ))}
          </dl>
        </>
      )}

      <Caveats items={section.caveats} />
    </Panel>
  )
}

function EmissionModelPanel({ section }: { section: Json }) {
  if (section.status !== 'evaluated') {
    return (
      <Panel title="Hourly grid emission factor (random forest)">
        <NotEvaluated section={section} />
      </Panel>
    )
  }

  const cv = obj(section.cross_validation) ?? {}

  return (
    <Panel title="Hourly grid emission factor (random forest)">
      <dl className="mt-2">
        <MetricRow
          label="Cross-validation"
          value={`${scalar(cv.strategy)} · ${scalar(cv.n_splits)} folds`}
        />
        <MetricRow label="Mean CV MAE (kg CO₂/kWh)" value={cv.mean_mae} />
        <MetricRow label="Train-mean baseline MAE" value={cv.mean_baseline_mae} />
      </dl>
      <p className="mt-2 text-xs text-(--surface-muted)">{scalar(cv.why)}</p>
      <Caveats items={section.caveats} />
    </Panel>
  )
}

function TrendPanel({ section }: { section: Json }) {
  if (section.status !== 'evaluated') {
    return (
      <Panel title="CO₂ trend with prediction interval">
        <NotEvaluated section={section} />
      </Panel>
    )
  }

  const fit = obj(section.fit) ?? {}

  return (
    <Panel title="CO₂ trend with prediction interval">
      <dl className="mt-2">
        <MetricRow label="Slope per day" value={fit.slope_per_day} />
        <MetricRow label="Direction" value={fit.direction} />
        <MetricRow label="R²" value={fit.r2} />
        <MetricRow label="p-value" value={fit.p_value} />
        <MetricRow label="Statistically significant" value={fit.is_significant} />
        <MetricRow label="Days fitted" value={fit.n_days} />
      </dl>
      <Caveats items={section.caveats} />
    </Panel>
  )
}

const SCENARIO_COLUMNS = [
  { key: 'precision', label: 'Precision' },
  { key: 'recall', label: 'Recall' },
  { key: 'f1', label: 'F1' },
  { key: 'true_positives', label: 'TP' },
  { key: 'false_positives', label: 'FP' },
  { key: 'false_negatives', label: 'FN' },
] as const

function AnomalyPanel({ section }: { section: Json }) {
  if (section.status !== 'evaluated') {
    return (
      <Panel title="Anomaly detection, scored against injected faults">
        <NotEvaluated section={section} />
      </Panel>
    )
  }

  const scenarios = obj(section.scenarios) ?? {}

  return (
    <Panel title="Anomaly detection, scored against injected faults">
      <p className="mt-1 text-xs text-(--surface-muted)">
        {scalar(section.data)} · {scalar(section.labels)}
      </p>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-xs tabular">
          <thead>
            <tr className="border-b border-(--surface-border)">
              <th className="py-1.5 pr-3 font-medium">Scenario</th>
              {SCENARIO_COLUMNS.map((column) => (
                <th key={column.key} className="py-1.5 pr-3 font-medium">
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(scenarios).map(([name, raw]) => {
              const row = obj(raw) ?? {}
              return (
                <tr key={name} className="border-b border-(--surface-border)/50">
                  <td className="py-1 pr-3 text-(--surface-muted)">{name}</td>
                  {SCENARIO_COLUMNS.map((column) => (
                    <td key={column.key} className="py-1 pr-3">
                      {scalar(row[column.key])}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <Caveats items={section.caveats} />
    </Panel>
  )
}

export default function MlMetrics() {
  const { data, error, loading } = useApi(() => getMlMetrics(), [])

  const forecast = obj(data?.load_forecast)
  const emission = obj(data?.emission_factor_model)
  const trend = obj(data?.co2_trend)
  const anomaly = obj(data?.anomaly_detection)

  return (
    <section className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">ML metrics</h1>
        <p className="mt-1 max-w-prose text-sm text-(--surface-muted)">
          Read directly from{' '}
          <code className="font-mono">backend/ml/artifacts/metrics.json</code>, produced by
          the evaluation code. Nothing here is hand-written, and regression results are
          reported as error, never as accuracy.
        </p>
      </div>

      <AsyncBoundary loading={loading} error={error} label="ML metrics">
        {data && (
          <div className="flex flex-col gap-4">
            <p className="text-xs text-(--surface-muted)">
              Generated {scalar(data.generated_at)} by{' '}
              <code className="font-mono">{scalar(data.generated_by)}</code>
            </p>

            {forecast && <ForecastPanel section={forecast} />}
            {emission && <EmissionModelPanel section={emission} />}
            {trend && <TrendPanel section={trend} />}
            {anomaly && <AnomalyPanel section={anomaly} />}

            {typeof data.honesty_note === 'string' && (
              <p className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-4 text-xs text-(--surface-muted)">
                {data.honesty_note}
              </p>
            )}
          </div>
        )}
      </AsyncBoundary>
    </section>
  )
}
