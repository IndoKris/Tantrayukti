import type { ReactNode } from 'react'

interface PagePlaceholderProps {
  title: string
  /** Which phase of CLAUDE-plan.md fills this page in. */
  phase: string
  description: string
  /** What this page will show once built. */
  planned: readonly string[]
  children?: ReactNode
}

/**
 * Shared shell for a route that is routed and styled but not yet implemented.
 *
 * It states which phase builds the page, so an empty page is never mistaken for
 * a finished one during the demo.
 */
export function PagePlaceholder({
  title,
  phase,
  description,
  planned,
  children,
}: PagePlaceholderProps) {
  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <span className="rounded-full border border-(--surface-border) px-2.5 py-1 text-xs font-medium text-(--surface-muted)">
          {phase}
        </span>
      </div>

      <p className="max-w-prose text-sm text-(--surface-muted)">{description}</p>

      {children}

      <div className="rounded-xl border border-dashed border-(--surface-border) bg-(--surface-raised) p-5">
        <h2 className="text-sm font-semibold">Planned for this page</h2>
        <ul className="mt-3 flex flex-col gap-2">
          {planned.map((item) => (
            <li key={item} className="flex gap-2 text-sm text-(--surface-muted)">
              <span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-eco-400" />
              {item}
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
