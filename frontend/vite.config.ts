import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const rootDir = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Patients' and doctors' phones are often not up to date: older iPhones (Safari before
  // 16.4) cannot parse class static blocks and showed a blank page. Translate newer syntax
  // down for them; Array.prototype.at is polyfilled in main.tsx.
  build: {
    target: ['es2020', 'safari15', 'chrome87', 'firefox78', 'edge88'],
  },
  resolve: {
    alias: {
      '@': path.resolve(rootDir, './src'),
    },
  },
  server: {
    port: 5173,
    // VITE_PROXY_TARGET lets the end-to-end tests point at their own backend.
    proxy: {
      '/api': { target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true },
      '/media': { target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
