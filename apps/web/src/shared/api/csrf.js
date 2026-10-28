// The CSRF token the login flow keeps in sessionStorage; state-changing API calls (POST, PUT, DELETE) must send it.
export function csrfHeader() {
  try {
    const token = sessionStorage.getItem('astra-csrf')
    return token ? { 'X-CSRF-Token': token } : {}
  } catch {
    return {}
  }
}
