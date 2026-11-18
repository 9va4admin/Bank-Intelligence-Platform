// How the alerting screens behave. Deployment settings (Vite env), never literals in a component.
const number = (value, fallback) => {
  const n = Number(value)
  return Number.isFinite(n) && n >= 0 ? n : fallback
}

// Seconds between automatic refreshes of the incident, delivery and on-call screens (0 turns refreshing off).
export const ALERTING_REFRESH_SECONDS = number(import.meta.env.VITE_ALERTING_REFRESH_SECONDS, 30)
// Rows per page in the incident and delivery lists.
export const ALERTING_PAGE_SIZE = number(import.meta.env.VITE_ALERTING_PAGE_SIZE, 50)
