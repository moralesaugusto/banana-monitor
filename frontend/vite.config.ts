/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // Backend defaults to HTTPS with a self-signed cert (see
      // backend/app/tls.py) - `secure: false` tells the proxy to trust it.
      '/api': {
        target: 'https://127.0.0.1:8000',
        // The backend refuses cross-origin POSTs; the proxy rewrites Host to the target, so the Origin must match it.
        headers: { Origin: 'https://127.0.0.1:8000' },
        changeOrigin: true,
        secure: false,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
})
