import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    allowedHosts: ['.e2b.app', 'localhost', '127.0.0.1'],
    proxy: {
      // Browser requests always stay on the same origin. Preserve Host for CSRF checks.
      '/api': { target: process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  preview: {
    host: '0.0.0.0',
    allowedHosts: ['.e2b.app', 'localhost', '127.0.0.1'],
    proxy: {
      '/api': { target: process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
})
