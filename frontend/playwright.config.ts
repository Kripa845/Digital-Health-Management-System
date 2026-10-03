import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end test: starts its own backend (port 8001, separate SQLite database,
 * see backend/scripts/e2e_server.py) and frontend (port 5174), so development
 * data is never touched. Run: npm run test:e2e
 */
const here = path.dirname(fileURLToPath(import.meta.url))
const backend = path.resolve(here, '../backend')
const python = process.env.E2E_PYTHON
  ?? path.join(backend, 'venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  workers: 1,
  fullyParallel: false,
  reporter: [['list']],
  use: { baseURL: 'http://localhost:5174', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `"${python}" "${path.join(backend, 'scripts', 'e2e_server.py')}"`,
      url: 'http://127.0.0.1:8001/healthz/',
      timeout: 180_000,
      reuseExistingServer: false,
    },
    {
      command: 'npx vite --port 5174 --strictPort',
      url: 'http://localhost:5174',
      env: { VITE_PROXY_TARGET: 'http://127.0.0.1:8001' },
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
})
