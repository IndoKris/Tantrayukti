import App from '../App.tsx'
import '../index.css'

/**
 * The original Vite starter page, preserved verbatim at /welcome.
 *
 * `App.tsx` and `App.css` are untouched from before the EcoTrack build; the
 * `.starter-shell` wrapper supplies the column layout that `index.css` used to
 * apply to `#root` directly (see AUDIT.md C9).
 */
export default function Welcome() {
  return (
    <div className="starter-shell">
      <App />
    </div>
  )
}
