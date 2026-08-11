// In web-sb-only there is no auth gate — all routes are accessible
export default function RequireAuth({ children }) {
  return children
}
