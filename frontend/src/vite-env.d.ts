/// <reference types="vite/client" />

/** Environment variables this app reads. Mirrors frontend/.env.example. */
interface ImportMetaEnv {
  /** Base URL of the EcoTrack API, e.g. http://127.0.0.1:8000. No trailing slash. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
