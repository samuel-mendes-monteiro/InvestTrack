/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API lives under /api. In development Vite forwards /api to uvicorn on
// :8000, so the page and the API share an origin (no CORS, and the session
// cookie is same-site). In production FastAPI serves the built files itself.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        // API_URL points the proxy at another API, e.g. one on a demo database.
        target: process.env.API_URL ?? 'http://localhost:8000',
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
