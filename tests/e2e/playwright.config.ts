import {defineConfig, devices} from '@playwright/test';
export default defineConfig({
  testDir: '.', testMatch: '*.spec.ts', timeout: 120_000,
  expect: {timeout: 90_000}, fullyParallel: false, workers: 1,
  forbidOnly: !!process.env.CI, retries: 0,
  reporter: [['list'], ['junit', {outputFile: '../../test-results/browser.xml'}]],
  outputDir: '../../test-results/browser-artifacts',
  use: {
    baseURL: process.env.TEST_BASE_URL || 'http://localhost:8081',
    trace: 'off', video: 'off', screenshot: 'only-on-failure',
    launchOptions: {chromiumSandbox: true},
  },
  projects: [
    {name: 'desktop-chromium', use: {...devices['Desktop Chrome'], viewport: {width: 1440, height: 1000}}},
    {name: 'mobile-chromium', use: {...devices['Pixel 7'], viewport: {width: 390, height: 844}}},
  ],
});
