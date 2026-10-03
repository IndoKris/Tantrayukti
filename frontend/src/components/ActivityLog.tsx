import { useMemo, useState, type FormEvent } from 'react'

import {
  createActivityEntry,
  deleteActivityEntry,
  getActivityEntries,
  getActivityFactors,
  getActivityReport,
  setActivityBudget,
} from '../api/insights.ts'
import { useApi } from '../hooks/useApi.ts'
import { AsyncBoundary } from './AsyncBoundary.tsx'
import { ChartFrame, RankedBarChart, StatTile } from './charts.tsx'
import { SERIES } from './chartTokens.ts'

/**
 * Manual activity logging across the five categories, plus the report.
 *
 * Two things are surfaced deliberately rather than tucked away:
 *
 * - **Every entry is self-reported**, so the UI says so and shows the factor's
 *   source. Phase 21 excludes these from the leaderboard; presenting them with
 *   the same authority as metered telemetry would be misleading.
 * - **Every figure shows its formula**, so a category total can be traced back
 *   to quantity × factor.
 */

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

interface FactorOption {
  id: number
  label: string
  quantity_unit: string
}

function EntryForm({ onLogged }: { onLogged: () => void }) {
  const factors = useApi(() => getActivityFactors(), [])
  const [factorId, setFactorId] = useState<string>('')
  const [quantity, setQuantity] = useState('')
  const [occurredOn, setOccurredOn] = useState(today())
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  const factorRows = factors.data?.results

  /** Grouped into optgroups by category, so the five categories stay visible. */
  const grouped = useMemo(() => {
    const map = new Map<string, FactorOption[]>()
    for (const factor of factorRows ?? []) {
      const list = map.get(factor.category_display) ?? []
      list.push({ id: factor.id, label: factor.label, quantity_unit: factor.quantity_unit })
      map.set(factor.category_display, list)
    }
    return [...map.entries()]
  }, [factorRows])

  const selected = factors.data?.results.find((item) => String(item.id) === factorId)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!factorId || !quantity) return

    setBusy(true)
    setMessage(null)
    setFailure(null)
    try {
      const entry = await createActivityEntry({
        factor: Number(factorId),
        quantity,
        occurred_on: occurredOn,
        note,
      })
      setMessage(entry.formula)
      setQuantity('')
      setNote('')
      onLogged()
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const fieldClass =
    'w-full rounded-lg border border-(--surface-border) bg-(--surface) px-3 py-2 text-sm text-(--surface-text) focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-eco-500'

  return (
    <AsyncBoundary loading={factors.loading} error={factors.error} label="activity types">
      <form
        onSubmit={submit}
        className="flex flex-col gap-3 rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5"
      >
        <h3 className="text-sm font-semibold">Log an activity</h3>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="activity-factor" className="text-xs font-medium">
              Activity
            </label>
            <select
              id="activity-factor"
              required
              value={factorId}
              onChange={(event) => setFactorId(event.target.value)}
              className={fieldClass}
            >
              <option value="">Choose…</option>
              {grouped.map(([category, items]) => (
                <optgroup key={category} label={category}>
                  {items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label} ({item.quantity_unit})
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="activity-quantity" className="text-xs font-medium">
              Quantity{selected && ` (${selected.quantity_unit})`}
            </label>
            <input
              id="activity-quantity"
              type="number"
              min="0"
              step="0.001"
              required
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              className={fieldClass}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="activity-date" className="text-xs font-medium">
              Date
            </label>
            <input
              id="activity-date"
              type="date"
              required
              max={today()}
              value={occurredOn}
              onChange={(event) => setOccurredOn(event.target.value)}
              className={fieldClass}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="activity-note" className="text-xs font-medium">
              Note (optional)
            </label>
            <input
              id="activity-note"
              type="text"
              maxLength={200}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              className={fieldClass}
            />
          </div>
        </div>

        {selected && (
          <p className="text-xs text-(--surface-muted)">
            Factor {selected.kg_co2_per_unit} kg CO₂e per {selected.quantity_unit}.{' '}
            <span className="text-severity-medium">Unverified estimate</span> —{' '}
            {selected.source}
          </p>
        )}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={busy || !factorId || !quantity}
            className="rounded-lg bg-eco-600 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-eco-700 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500"
          >
            {busy ? 'Saving…' : 'Log it'}
          </button>
          {message && <p className="tabular text-xs text-eco-600">{message}</p>}
          {failure && (
            <p role="alert" className="text-xs text-severity-high">
              {failure}
            </p>
          )}
        </div>
      </form>
    </AsyncBoundary>
  )
}

function BudgetControl({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)

  async function save() {
    if (!value) return
    setBusy(true)
    try {
      await setActivityBudget(value)
      onSaved()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="budget" className="text-xs font-medium">
          Monthly CO₂e budget (kg)
        </label>
        <input
          id="budget"
          type="number"
          min="0"
          step="0.01"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          className="w-40 rounded-lg border border-(--surface-border) bg-(--surface) px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-eco-500"
        />
      </div>
      <button
        type="button"
        onClick={save}
        disabled={busy || !value}
        className="rounded-lg border border-(--surface-border) px-3 py-2 text-xs font-medium disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500"
      >
        {busy ? 'Saving…' : 'Set budget'}
      </button>
    </div>
  )
}

export function ActivityLog() {
  const [nonce, setNonce] = useState(0)
  const reload = () => setNonce((value) => value + 1)

  const report = useApi(() => getActivityReport(), [nonce])
  const entries = useApi(() => getActivityEntries(), [nonce])

  const categoryRows = useMemo(
    () =>
      (report.data?.categories ?? [])
        .filter((row) => Number(row.kg_co2) > 0)
        .map((row) => ({ name: row.label, value: Number(row.kg_co2) })),
    [report.data],
  )

  async function remove(id: number) {
    await deleteActivityEntry(id)
    reload()
  }

  return (
    <div className="flex flex-col gap-5">
      <EntryForm onLogged={reload} />

      <AsyncBoundary loading={report.loading} error={report.error} label="activity report">
        {report.data && (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <StatTile
                label="Logged this month"
                value={Number(report.data.total_kg_co2).toFixed(2)}
                unit="kg CO₂e"
                source={`${report.data.entry_count} self-reported entries`}
              />
              {report.data.budget ? (
                <>
                  <StatTile
                    label="Budget"
                    value={Number(report.data.budget.kg_co2_per_month).toFixed(0)}
                    unit="kg CO₂e"
                    source={
                      report.data.budget.used_percent
                        ? `${Number(report.data.budget.used_percent).toFixed(0)}% used`
                        : undefined
                    }
                  />
                  <StatTile
                    label={report.data.budget.over_budget ? 'Over budget by' : 'Remaining'}
                    value={Math.abs(Number(report.data.budget.remaining_kg_co2)).toFixed(2)}
                    unit="kg CO₂e"
                    tone={report.data.budget.over_budget ? 'warning' : 'good'}
                  />
                </>
              ) : (
                <div className="rounded-xl border border-dashed border-(--surface-border) bg-(--surface-raised) p-4 sm:col-span-2">
                  <p className="text-xs text-(--surface-muted)">
                    No monthly budget set yet.
                  </p>
                  <div className="mt-2">
                    <BudgetControl onSaved={reload} />
                  </div>
                </div>
              )}
            </div>

            <ChartFrame
              title="Emissions by category, this month"
              unit="kg CO₂e"
              series={[{ key: 'value', label: 'kg CO₂e', color: SERIES.comparison }]}
              rows={categoryRows}
              xKey="name"
              emptyMessage="Nothing logged this month yet."
              footnote={report.data.caveats.map((caveat) => (
                <span key={caveat} className="block">
                  {caveat}
                </span>
              ))}
            >
              <RankedBarChart
                rows={categoryRows}
                labelKey="name"
                valueKey="value"
                valueLabel="kg CO₂e"
                color={SERIES.comparison}
              />
            </ChartFrame>

            {report.data.top_emitters.length > 0 && (
              <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5">
                <h3 className="text-sm font-semibold">Top emitters</h3>
                <ul className="mt-2 flex flex-col gap-1.5">
                  {report.data.top_emitters.map((row) => (
                    <li key={row.id} className="tabular text-xs text-(--surface-muted)">
                      <span className="font-medium text-(--surface-text)">{row.label}</span> ·{' '}
                      {row.occurred_on} · {row.formula}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <a
                href="/api/activity/report.csv"
                className="rounded-lg border border-(--surface-border) px-3 py-2 text-xs font-medium transition-colors hover:text-(--surface-text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500"
              >
                Export CSV
              </a>
              <span className="text-xs text-(--surface-muted)">
                Includes the formula and factor source for every row, so the export is
                auditable rather than a bare total.
              </span>
            </div>
          </>
        )}
      </AsyncBoundary>

      <AsyncBoundary loading={entries.loading} error={entries.error} label="entries">
        {entries.data && entries.data.results.length > 0 && (
          <div className="rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5">
            <h3 className="text-sm font-semibold">Recent entries</h3>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-left text-xs tabular">
                <thead>
                  <tr className="border-b border-(--surface-border)">
                    <th className="py-1.5 pr-3 font-medium">Date</th>
                    <th className="py-1.5 pr-3 font-medium">Activity</th>
                    <th className="py-1.5 pr-3 font-medium">Quantity</th>
                    <th className="py-1.5 pr-3 font-medium">kg CO₂e</th>
                    <th className="py-1.5 pr-3 font-medium">Verified</th>
                    <th className="py-1.5 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {entries.data.results.map((row) => (
                    <tr key={row.id} className="border-b border-(--surface-border)/50">
                      <td className="py-1 pr-3 text-(--surface-muted)">{row.occurred_on}</td>
                      <td className="py-1 pr-3">{row.factor_label}</td>
                      <td className="py-1 pr-3">
                        {Number(row.quantity).toFixed(2)} {row.quantity_unit}
                      </td>
                      <td className="py-1 pr-3 font-medium">{Number(row.kg_co2).toFixed(2)}</td>
                      <td className="py-1 pr-3 text-(--surface-muted)">no</td>
                      <td className="py-1">
                        <button
                          type="button"
                          onClick={() => remove(row.id)}
                          className="text-(--surface-muted) underline decoration-dotted hover:text-severity-high"
                        >
                          delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </AsyncBoundary>
    </div>
  )
}
