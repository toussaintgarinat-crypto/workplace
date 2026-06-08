import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { port: 3000, host: '0.0.0.0' },
  // Polyfills nécessaires pour matrix-js-sdk (utilise des APIs Node dans certains modules)
  define: {
    global: 'globalThis',
  },
  resolve: {
    alias: {
      // matrix-js-sdk importe des modules node — on les redirige vers des shims navigateur
      'node:crypto': 'crypto',
    },
  },
  optimizeDeps: {
    include: ['matrix-js-sdk'],
  },
})
