import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/gaussian-render': { target: 'ws://127.0.0.1:8041', ws: true },
      '/gaussian-api': 'http://127.0.0.1:8030',
      '/gaussian-ws': { target: 'ws://127.0.0.1:8030', ws: true },
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
