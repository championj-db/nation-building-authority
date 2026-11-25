import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  timeout: 120_000,
  use: { channel: 'chromium', baseURL: process.env.BASE_URL ?? 'http://localhost:8000', viewport: { width: 1440, height: 900 } },
});
