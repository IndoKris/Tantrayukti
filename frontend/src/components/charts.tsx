import { useId, useMemo, useState, type ReactNode } from 'react'
import { SERIES, STATUS, type ChartRow, type SeriesSpec } from './chartTokens.ts'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

/**
 * Shared chart pieces.
 *
 * Three rules are enforced here rather than left to each page:
 *
 * 1. **A legend is always present for two or more series, and never colour
 *    alone.** Light-mode series-3 sits below 3:1 contrast, so the palette's
 *    relief rule applies - hence the mandatory table view below.
 * 2. **Every chart has a table view.** It is the accessible fallback and the
 *    relief for the contrast warning, not a nice-to-have.
 * 3. **One y-axis, always.** Power (W) and energy (kWh) are different scales
 *    and never share an axis; they get separate charts. Mixing them is both the
 *    classic dual-axis mistake and the kW/kWh confusion this project forbids.
 */

interface ChartFrameProps {
  title: string
  unit: string
  series: readonly SeriesSpec[]
  rows: readonly ChartRow[]
  /** Row key holding the x value. */
  xKey: string
  children: ReactNode
  footnote?: ReactNode
  /** Shown instead of the chart when there is nothing to plot. */
  emptyMessage?: string
}

/**
 * Title, legend, the chart itself, and a toggleable table of the same numbers.
 */
export function ChartFrame({
  title,
  unit,
  series,
  rows,
  xKey,
  children,
  footnote,
  emptyMessage = 'No data for this window yet.',
}: ChartFrameProps) {
  const [showTable, setShowTable] = useState(false)
  const tableId = useId()

  return (
    <figure className="m-0 flex flex-col gap-3 rounded-xl border border-(--surface-border) bg-(--surface-raised) p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <figcaption className="text-sm font-semibold">
          {title} <span className="font-normal text-(--surface-muted)">({unit})</span>
        </figcaption>
        <button
          type="button"
          onClick={() => setShowTable((value) => !value)}
          aria-expanded={showTable}
          aria-controls={tableId}
          className="rounded-lg border border-(--surface-border) px-2 py-1 text-xs font-medium text-(--surface-muted) transition-colors hover:text-(--surface-text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500"
        >
          {showTable ? 'Show chart' : 'Show table'}
        </button>
      </div>

      {series.length > 1 && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1">
          {series.map((item) => (
            <li key={item.key} className="flex items-center gap-1.5 text-xs">
              <span
                aria-hidden="true"
                className="h-0.5 w-4 shrink-0 rounded-full"
                style={
                  item.dashed
                    ? {
                        backgroundImage: `repeating-linear-gradient(90deg, ${item.color} 0 4px, transparent 4px 7px)`,
                      }
                    : { backgroundColor: item.color }
                }
              />
              <span className="text-(--surface-muted)">{item.label}</span>
            </li>
          ))}
        </ul>
      )}

      {rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-(--surface-muted)">{emptyMessage}</p>
      ) : showTable ? (
        <div id={tableId} className="max-h-80 overflow-auto">
          <table className="w-full text-left text-xs tabular">
            <thead className="sticky top-0 bg-(--surface-raised)">
              <tr className="border-b border-(--surface-border)">
                <th className="py-1.5 pr-3 font-medium">{xKey}</th>
                {series.map((item) => (
                  <th key={item.key} className="py-1.5 pr-3 font-medium">
                    {item.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index} className="border-b border-(--surface-border)/50">
                  <td className="py-1 pr-3 text-(--surface-muted)">{String(row[xKey])}</td>
                  {series.map((item) => (
                    <td key={item.key} className="py-1 pr-3">
                      {formatValue(row[item.key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div id={tableId} className="h-64 w-full">
          {children}
        </div>
      )}

      {footnote && <p className="text-xs text-(--surface-muted)">{footnote}</p>}
    </figure>
  )
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  const asNumber = Number(value)
  return Number.isFinite(asNumber) ? asNumber.toFixed(3) : String(value)
}

interface TooltipEntry {
  dataKey: string
  name: string
  value: unknown
  color: string
}

interface ChartTooltipProps {
  active?: boolean
  payload?: TooltipEntry[]
  label?: string | number
}

/** Tooltip styled against the surface tokens rather than Recharts' defaults. */
function ChartTooltip({ active, payload, label }: ChartTooltipProps) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-(--surface-border) bg-(--surface-raised) px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-medium">{label}</p>
      {payload.map((entry) => (
        <p key={entry.dataKey} className="flex items-center gap-1.5 tabular">
          <span
            aria-hidden="true"
            className="size-2 shrink-0 rounded-full"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-(--surface-muted)">{entry.name}:</span>
          <span className="font-medium">{formatValue(entry.value)}</span>
        </p>
      ))}
    </div>
  )
}

const axisStyle = { fill: 'var(--axis-ink)', fontSize: 11 }

/** Multi-series line chart with a crosshair tooltip. One y-axis only. */
export function LineSeriesChart({
  rows,
  xKey,
  series,
}: {
  rows: readonly ChartRow[]
  xKey: string
  series: readonly SeriesSpec[]
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={rows as ChartRow[]} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
        <CartesianGrid stroke="var(--grid-line)" strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey={xKey} tick={axisStyle} tickLine={false} axisLine={false} minTickGap={24} />
        <YAxis tick={axisStyle} tickLine={false} axisLine={false} width={48} />
        <Tooltip content={<ChartTooltip />} cursor={{ stroke: 'var(--axis-ink)', strokeWidth: 1 }} />
        {series.map((item) => (
          <Line
            key={item.key}
            type="monotone"
            dataKey={item.key}
            name={item.label}
            stroke={item.color}
            strokeWidth={2}
            strokeDasharray={item.dashed ? '5 4' : undefined}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface-raised)' }}
            connectNulls={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

/** Horizontal bar chart for ranked comparisons. 4px rounded data-ends. */
export function RankedBarChart({
  rows,
  labelKey,
  valueKey,
  valueLabel,
  color = SERIES.measured,
}: {
  rows: readonly ChartRow[]
  labelKey: string
  valueKey: string
  valueLabel: string
  color?: string
}) {
  const data = useMemo(() => rows.map((row) => ({ ...row })), [rows])

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 16, bottom: 0, left: 8 }}
        barCategoryGap={6}
      >
        <CartesianGrid stroke="var(--grid-line)" strokeDasharray="2 4" horizontal={false} />
        <XAxis type="number" tick={axisStyle} tickLine={false} axisLine={false} />
        <YAxis
          type="category"
          dataKey={labelKey}
          tick={axisStyle}
          tickLine={false}
          axisLine={false}
          width={120}
        />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: 'var(--grid-line)', opacity: 0.4 }} />
        <Bar dataKey={valueKey} name={valueLabel} fill={color} radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

/**
 * A single headline number. The form heuristic says one value is a stat tile,
 * not a chart.
 *
 * `unit` is always a separate muted span, so a kWh figure can never be read as
 * kW. `source` is required for any derived figure, because the project's honesty
 * rule says a number must say where it came from.
 */
export function StatTile({
  label,
  value,
  unit,
  source,
  tone = 'neutral',
}: {
  label: string
  value: string | number | null | undefined
  unit: string
  source?: ReactNode
  tone?: 'neutral' | 'good' | 'warning'
}) {
  const valueColor =
    tone === 'good'
      ? 'text-eco-600'
      : tone === 'warning'
        ? 'text-severity-medium'
        : 'text-(--surface-text)'

  return (
    <div className="flex flex-col gap-1 rounded-xl border border-(--surface-border) bg-(--surface-raised) p-4">
      <p className="text-xs text-(--surface-muted)">{label}</p>
      <p className={`tabular text-2xl font-semibold tracking-tight ${valueColor}`}>
        {value === null || value === undefined ? '—' : value}{' '}
        <span className="text-sm font-normal text-(--surface-muted)">{unit}</span>
      </p>
      {source && <p className="text-xs leading-snug text-(--surface-muted)">{source}</p>}
    </div>
  )
}

/** Severity chip. Status colour plus an always-present label, never colour alone. */
export function SeverityChip({ severity }: { severity: string }) {
  const color = STATUS[severity as keyof typeof STATUS] ?? SERIES.other
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-(--surface-border) px-2 py-0.5 text-xs font-medium">
      <span aria-hidden="true" className="size-2 rounded-full" style={{ backgroundColor: color }} />
      {severity}
    </span>
  )
}
