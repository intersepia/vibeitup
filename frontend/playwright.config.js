import { defineConfig } from '@playwright/test'

const python = process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python'
const baseURL = 'http://127.0.0.1:8010'

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  expect: { timeout: 7000 },
  reporter: 'list',
  use: {
    baseURL,
    reducedMotion: 'reduce',
    viewport: { width: 1440, height: 960 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? {
          executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH,
          args: ['--no-sandbox', '--disable-dev-shm-usage', '--no-zygote'],
        }
      : {},
  },
  webServer: {
    command: `${python} ../scripts/serve_e2e.py`,
    url: `${baseURL}/api/health`,
    timeout: 30000,
    reuseExistingServer: process.env.PLAYWRIGHT_REUSE_SERVER === '1',
  },
})
