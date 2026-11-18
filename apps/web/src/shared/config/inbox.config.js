// How the in-app bell behaves. Deployment settings (Vite env), never literals in a component.
const number = (value, fallback) => {
  const n = Number(value)
  return Number.isFinite(n) && n >= 0 ? n : fallback
}

// Seconds between checks for new notifications (0 turns polling off).
export const INBOX_POLL_SECONDS = number(import.meta.env.VITE_INBOX_POLL_SECONDS, 15)
// Notifications fetched per page in the drawer.
export const INBOX_PAGE_SIZE = number(import.meta.env.VITE_INBOX_PAGE_SIZE, 30)
// Most critical, unacknowledged alerts pinned above the page at once.
export const INBOX_PINNED_LIMIT = number(import.meta.env.VITE_INBOX_PINNED_LIMIT, 5)
