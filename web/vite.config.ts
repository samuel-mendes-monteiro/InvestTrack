/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The browser only ever calls /api/...: in development Vite forwards it to
// uvicorn on :8000 (dropping the /api prefix the API doesn't have yet), so the
// page and the API share an origin and no CORS is needed. In production the
// same origin comes from FastAPI serving the built files itself.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
