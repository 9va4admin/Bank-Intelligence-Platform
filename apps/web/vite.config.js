import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/Bank-Intelligence-Platform/',
  server: { port: 4000 },
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
