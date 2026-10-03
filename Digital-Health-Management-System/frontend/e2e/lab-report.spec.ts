import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test, type Page } from '@playwright/test'

// Fake reports for the fake e2e patient (Asha Gurung, PAT-0E2E0001); see
// backend/samples/lab_reports/make_samples.py and `manage.py seed_e2e`.
const SAMPLES = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../backend/samples/lab_reports')

test.describe.configure({ mode: 'serial' })

async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Username').fill('e2e.patient')
  await page.getByLabel('Password', { exact: true }).fill(process.env.E2E_PATIENT_PASSWORD ?? 'Kathmandu-Lab-2026')
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/patient\/dashboard/)
}

async function upload(page: Page, file: string) {
  await page.goto('/patient/lab-reports/upload')
  await page.getByTestId('file-input').setInputFiles(path.join(SAMPLES, file))
  await page.getByRole('button', { name: /upload and read/i }).click()
}

test('matching report → confirm → dashboard shows the new values', async ({ page }) => {
  await login(page)
  await expect(page.getByRole('region', { name: 'Haemoglobin' })).toContainText('Not recorded yet')

  await upload(page, 'report_match.pdf')
  await expect(page).toHaveURL(/\/patient\/lab-reports\/\d+\/confirm/)
  await expect(page.getByLabel('Haemoglobin')).toHaveValue('12.8')
  await expect(page.getByLabel('Total Cholesterol')).toHaveValue('201.08')   // 5.2 mmol/L converted

  await page.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page).toHaveURL(/\/patient\/dashboard/)
  await expect(page.getByRole('region', { name: 'Haemoglobin' })).toContainText('12.80')
  await expect(page.getByRole('region', { name: 'Total Cholesterol' })).toContainText('201.08')
  await expect(page.getByRole('region', { name: 'Blood Sugar (Random)' })).toContainText('142')
})

test('mismatched report → error shown, dashboard unchanged', async ({ page }) => {
  await login(page)
  const hb = page.getByRole('region', { name: 'Haemoglobin' })
  await expect(hb).toContainText('12.80')

  await upload(page, 'report_mismatch.pdf')
  await expect(page.getByRole('alert')).toContainText('Patient ID does not match this account')

  await page.goto('/patient/dashboard')
  await expect(hb).toContainText('12.80')
  await expect(page.getByRole('region', { name: 'Total Cholesterol' })).toContainText('201.08')
})
