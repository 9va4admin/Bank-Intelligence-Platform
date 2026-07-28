import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'
import fs from 'fs'

const __filename = fileURLToPath(import.meta.url)
const __dirname  = dirname(__filename)

// Serve real cheque scans from demo/112/ at /demo-cheques/<filename>
const demoCheques = {
  name: 'demo-cheques-middleware',
  configureServer(server) {
    server.middlewares.use('/demo-cheques', (req, res, next) => {
      const name     = decodeURIComponent((req.url || '').replace(/^\//, ''))
      const filePath = join(__dirname, '../../demo/112', name)
      if (name && fs.existsSync(filePath)) {
        res.setHeader('Content-Type', 'image/jpeg')
        res.setHeader('Cache-Control', 'public, max-age=86400')
        fs.createReadStream(filePath).pipe(res)
      } else {
        next()
      }
    })
  },
}

export default defineConfig({
  plugins: [react(), demoCheques],
  base: '/Bank-Intelligence-Platform/',
  server: {
    port: 4000,
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
