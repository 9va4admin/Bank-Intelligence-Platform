import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/Bank-Intelligence-Platform/',
  server: {
    port: 4000,
    // Dev only: forward API calls to the local dev auth server so the login
    // flow is same-origin (cookies just work, no CORS). Start it with:
    //   uvicorn apps.api.dev_auth_server:app --port 8000
    proxy: {
      '/v1': { target: 'http://localhost:8000', changeOrigin: true },
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
