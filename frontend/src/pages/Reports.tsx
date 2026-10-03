import { useState } from 'react'

import { comparePeriods, getProjection } from '../api/insights.ts'
import { ActivityLog } from '../components/ActivityLog.tsx'
import { AsyncBoundary } from '../components/AsyncBoundary.tsx'
import { ChartFrame, RankedBarChart, StatTile } from '../components/charts.tsx'
import { SERIES } from '../components/chartTokens.ts'
import { useApi } from '../hooks/useApi.ts'

const PERIODS = [
  { value: 'day', label: 'Today vs yesterday' },
  { value: 'same_weekday_last_week', label: 'Same weekday last week' },
  { value: 'week', label: 'This week vs last' },
  { value: 'month', label: 'This month vs last' },
] as const

function PeriodComparison() {
  const [period, setPeriod] = useState<string>('day')
  const { data, error, loading } = useApi(() => comparePeriods({ period }), [period])

  const rows = data
    ? [
        { label: 'Previous', value: Number(data.comparable_previous_kwh) },
        { label: 'Current', value: Number(data.current.energy_kwh) },
      ]
    : []

  const arrow = data?.direction === 'up' ? '▲' : data?.direction === 'down' ? '▼' : '='
  const tone =
    data?.direction === 'up'
      ? 'text-severity-high'
      : data?.direction === 'down'
        ? 'text-eco-600'
        : 'text-(--surface-muted)'

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-(--surface-muted)">Compare:</span>
        {PERIODS.map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() => setPeriod(item.value)}
            aria-pressed={period === item.value}
            className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500 ${
              period === item.value
                ? 'border-eco-600 bg-eco-600/10 text-(--surface-text)'
                : 'border-(--surface-border) text-(--surface-muted) hover:text-(--surface-text)'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <AsyncBoundary loading={loading} error={error} label="period comparison">
        {data && (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <StatTile
                label="Current period"
                value={Number(data.current.energy_kwh).toFixed(2)}
                unit="kWh"
                source={`${data.current.sample_count} readings`}
              />
              <StatTile
                label={data.is_partial_period ? 'Previous, pro-rated' : 'Previous period'}
                value={Number(data.comparable_previous_kwh).toFixed(2)}
                unit="kWh"
                source={
                  data.is_partial_period
                    ? `Raw ${Number(data.previous.energy_kwh).toFixed(2)} kWh × ${(
                        Number(data.elapsed_fraction) * 100
                      ).toFixed(0)}% elapsed`
                    : `${data.previous.sample_count} readings`
                }
              />
              <div className="flex flex-col gap-1 rounded-xl border border-(--surface-border) bg-(--surface-raised) p-4">
                <p className="text-xs text-(--surface-muted)">Change</p>
                <p className={`tabular text-2xl font-semibold tracking-tight ${tone}`}>
                  <span aria-hidden="true">{arrow}</span>{' '}
                  {data.change_percent === null
                    ? '—'
                    : `${Number(data.change_percent).toFixed(1)}%`}
                </p>
                <p className="tabular text-xs text-(--surface-muted)">
                  {Number(data.change_kwh) >= 0 ? '+' : ''}
                  {Number(data.change_kwh).toFixed(2)} kWh · {data.direction}
                </p>
              </div>
            </div>

            <ChartFrame
              title={data.label}
              unit="kWh"
              series={[{ key: 'value', label: 'Energy', color: SERIES.measured }]}
              rows={rows}
              xKey="label"
              emptyMessage="No readings in either period."
              footnote={data.notes.map((note) => (
                <span key={note} className="block">
                  {note}
                </span>
              ))}
            >
              <RankedBarChart rows={rows} labelKey="label" valueKey="value" valueLabel="kWh" />
            </ChartFrame>
          </>
        )}
      </AsyncBoundary>
    </div>
  )
}

function BillProjection() {
  const { data, error, loading } = useApi(() => getProjection({}), [])

  return (
    <AsyncBoundary loading={loading} error={error} label="bill projection">
      {data && (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile
              label={`Consumed, ${data.projection.month}`}
              value={Number(data.projection.consumed_kwh).toFixed(2)}
              unit="kWh"
              source={`${data.projection.days_elapsed} of ${data.projection.days_in_month} days`}
            />
            <StatTile
              label="Projected month total"
              value={Number(data.projection.projected_kwh).toFixed(2)}
              unit="kWh"
              source={`${Number(data.projection.mean_kwh_per_day).toFixed(2)} kWh/day held flat`}
            />
            <StatTile
              label="Bill to date"
              value={Number(data.projection.bill_to_date.total_inr).toFixed(2)}
              unit="₹"
              source={
                data.projection.bill_to_date.tariff.is_sample
                  ? 'Sample tariff rates'
                  : data.projection.bill_to_date.tariff.name
              }
            />
            <StatTile
              label="Projected bill"
              value={Number(data.projection.projected_bill.total_inr).toFixed(2)}
              unit="₹"
              tone="warning"
              source="Includes the monthly fixed charge"
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <StatTile
              label="CO₂ to date"
              value={Number(data.co2_to_date.kg_co2).toFixed(2)}
              unit="kg"
              source={`Factor ${data.co2_to_date.factor.kg_co2_per_kwh} kg/kWh · ${
                data.co2_to_date.factor.is_verified ? 'verified' : 'unverified'
              }`}
            />
            <StatTile
              label="CO₂ projected"
              value={Number(data.co2_projected.kg_co2).toFixed(2)}
              unit="kg"
              source={data.co2_projected.formula}
            />
          </div>

          <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5">
            <h3 className="text-sm font-semibold">What this projection assumes</h3>
            <ul className="mt-2 flex flex-col gap-1.5 text-xs text-(--surface-muted)">
              {data.projection.assumptions.map((assumption) => (
                <li key={assumption} className="flex gap-2">
                  <span aria-hidden="true" className="mt-1.5 size-1 shrink-0 rounded-full bg-eco-400" />
                  {assumption}
                </li>
              ))}
            </ul>
          </div>

          {data.projection.projected_bill.slab_lines.length > 0 && (
            <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5">
              <h3 className="text-sm font-semibold">Projected energy charge, slab by slab</h3>
              <ul className="mt-2 flex flex-col gap-1 text-xs tabular text-(--surface-muted)">
                {data.projection.projected_bill.slab_lines.map((line) => (
                  <li key={line.label}>{line.formula}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-(--surface-muted)">
                Fixed charge ₹{data.projection.projected_bill.fixed_charge_inr} · tax{' '}
                {data.projection.projected_bill.tax_percent}% (₹
                {data.projection.projected_bill.tax_inr}) · total ₹
                {data.projection.projected_bill.total_inr}
              </p>
            </div>
          )}
        </div>
      )}
    </AsyncBoundary>
  )
}

export default function Reports() {
  return (
    <section className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Reports</h1>
        <p className="mt-1 max-w-prose text-sm text-(--surface-muted)">
          Period-over-period comparison and a month-end bill projection. An incomplete
          period is pro-rated, so a month that is half over does not look like a saving.
        </p>
      </div>

      <div className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold tracking-tight">Period comparison</h2>
        <PeriodComparison />
      </div>

      <div className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold tracking-tight">Bill estimate and projection</h2>
        <BillProjection />
      </div>

      <div className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold tracking-tight">Activity log</h2>
        <p className="max-w-prose text-sm text-(--surface-muted)">
          Transport, home energy, diet, shopping and waste. These entries are
          self-reported, so they are tagged unverified and kept separate from metered
          telemetry.
        </p>
        <ActivityLog />
      </div>
    </section>
  )
}
