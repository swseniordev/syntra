import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const certDir = join(process.env.LOCALAPPDATA || '', 'Syntra', 'certs');
const certPath = join(certDir, 'local-cert.pem');
const keyPath = join(certDir, 'local-key.pem');
const https = process.env.SYNTRA_HTTP_PREVIEW !== '1' && existsSync(certPath) && existsSync(keyPath)
  ? { cert: readFileSync(certPath), key: readFileSync(keyPath) }
  : undefined;
const apiTarget = process.env.SYNTRA_API_TARGET || 'http://127.0.0.1:8000';
if (!/^http:\/\/127\.0\.0\.1:\d{1,5}$/.test(apiTarget)) {
  throw new Error('SYNTRA_API_TARGET debe ser un puerto HTTP local de 127.0.0.1');
}

export default defineConfig({
  plugins: [react()],
  server: {
    https,
    proxy: { '/api/v1': { target: apiTarget, changeOrigin: false } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts',
    clearMocks: true,
  },
});
