import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  timeout: 180_000,
  use: { channel: process.env.PW_CHANNEL ?? 'chromium', baseURL: process.env.BASE_URL ?? 'http://localhost:8000', viewport: { width: 1440, height: 900 } },
});
