import react from '@vitejs/plugin-react-swc';
import { resolve } from 'path';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  server: { fs: { allow: [resolve(import.meta.dirname, '../..')] } },
  plugins: [react()],
  resolve: {
    alias: {
      '@': resolve(import.meta.dirname, 'src'),
      'react/jsx-dev-runtime': resolve(import.meta.dirname, 'node_modules/react/jsx-dev-runtime.js'),
      'react/jsx-runtime': resolve(import.meta.dirname, 'node_modules/react/jsx-runtime.js'),
      react: resolve(import.meta.dirname, 'node_modules/react/index.js'),
      '@testing-library/react': resolve(import.meta.dirname, 'node_modules/@testing-library/react/dist/index.js'),
      '@testing-library/user-event': resolve(import.meta.dirname, 'node_modules/@testing-library/user-event/dist/esm/index.js'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['src/**/*.{test,spec}.{ts,tsx}', '../../tests/cockpit/**/*.{test,spec}.{ts,tsx}'],
    exclude: ['node_modules', 'dist'],
    setupFiles: ['./src/__tests__/setup.ts'],
  },
});
