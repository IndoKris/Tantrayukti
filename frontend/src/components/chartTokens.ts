/**
 * Chart colour roles and series typing.
 *
 * Separate from `charts.tsx` because that file must export only components for
 * React Fast Refresh to work.
 *
 * The hexes behind these variables come from the validated reference palette and
 * were checked with the palette validator against this project's own surfaces:
 * light (#ffffff) CVD ΔE 9.2 / normal ΔE 24.0, dark (#1e293b) CVD ΔE 9.4 /
 * normal ΔE 20.9 — all checks pass. Three slots is the documented cap for
 * all-pairs forms; a fourth series folds into `other` rather than inventing a hue.
 */

export const SERIES = {
  measured: 'var(--series-1)',
  forecast: 'var(--series-2)',
  comparison: 'var(--series-3)',
  other: 'var(--series-other)',
} as const

/** Status colours are fixed, never themed, and never double as a series. */
export const STATUS = {
  low: 'var(--status-good)',
  medium: 'var(--status-warning)',
  high: 'var(--status-serious)',
  critical: 'var(--status-critical)',
} as const

export interface SeriesSpec {
  /** Data key in each row. */
  key: string
  /** Human label, used in the legend, the tooltip and the table header. */
  label: string
  color: string
  /** Dashed marks read as "projected" without relying on hue. */
  dashed?: boolean
}

export type ChartRow = Record<string, unknown>
