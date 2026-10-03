import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <section className="flex flex-col items-start gap-4">
      <p className="text-xs font-semibold tracking-widest text-(--surface-muted) uppercase">
        404
      </p>
      <h1 className="text-2xl font-semibold tracking-tight">This page does not exist</h1>
      <p className="max-w-prose text-sm text-(--surface-muted)">
        The link may be from a later phase of the build that has not been implemented yet.
      </p>
      <Link
        to="/"
        className="rounded-lg bg-eco-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-eco-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-eco-500"
      >
        Back to the dashboard
      </Link>
    </section>
  )
}
