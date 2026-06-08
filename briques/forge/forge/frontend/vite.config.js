import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  esbuild: {
    loader: 'jsx',
    include: /src\/.*\.[jt]sx?$/,
  },
  optimizeDeps: {
    esbuildOptions: {
      loader: { '.js': 'jsx' },
    },
  },
  server: {
    port: 3000,
    hmr: { port: 3000 },
    proxy: {
      // S136 cutover : dev proxy repointé sur le strangler Python (core:8600).
      // WS natifs (S134) servis par core ; HTTP résiduel proxy-fié vers le Bun.
      '/api/ws': {
        target: 'ws://localhost:8600',
        changeOrigin: true,
        ws: true,
      },
      '/api/voice/realtime': {
        target: 'ws://localhost:8600',
        changeOrigin: true,
        ws: true,
      },
      '/api': {
        target: 'http://localhost:8600',
        changeOrigin: true,
      },
    },
  },
})
