import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'url'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'

// Mirror the build-time-injected frontend version from vite.config.ts so
// tests that touch useAppVersion / AppFooter / AboutDialog don't blow up on
// the undefined global.
const frontendPkg = JSON.parse(
  readFileSync(
    resolve(dirname(fileURLToPath(import.meta.url)), 'package.json'),
    'utf-8',
  ),
)

export default defineConfig({
  plugins: [vue()],
  define: {
    __SHERPA_FRONTEND_VERSION__: JSON.stringify(frontendPkg.version),
  },
  test: {
    globals: true,
    environment: 'happy-dom',
    setupFiles: ['./src/test/setup.ts'],
    // Vitest defaults catch e2e/*.spec.ts — those are Playwright specs
    // (driven by `npm run test:e2e`) and cannot be imported by vitest.
    // Restrict the vitest glob to src/ so the unit-test suite is
    // independently runnable and safe to gate in CI.
    include: ['src/**/*.{test,spec}.{js,ts,vue}'],
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      exclude: [
        'node_modules/',
        'src/test/',
        '**/*.d.ts',
        '**/*.config.*',
        '**/mockData',
        '**/.{eslintrc,prettierrc}.js',
      ],
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
})
