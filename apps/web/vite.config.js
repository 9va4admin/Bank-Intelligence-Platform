import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/Bank-Intelligence-Platform/',
  server: {
    port: 4000,
    // Dev only: forward API calls to the local dev auth server so the login
    // flow is same-origin (cookies just work, no CORS). Start it with:
    //   uvicorn apps.api.dev_auth_server:app --port 8010
    //
    // Target is 127.0.0.1, not localhost: uvicorn binds IPv4-only by default,
    // but on machines running Docker Desktop / WSL2, "localhost" can resolve
    // to ::1 first, silently routing to whatever else is on that port over
    // IPv6 instead of a clean connection error. Port 8010 (not 9000) avoids
    // the well-known collision with YugabyteDB's default tserver web UI port.
    proxy: {
      '/v1': { target: 'http://127.0.0.1:8010', changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.js',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json'],
      exclude: ['src/main.jsx', 'src/test-setup.js', '**/*.config.*'],
    },
  },
})
