import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  build: {
    outDir: '../backend/admin-dist',
    emptyOutDir: true,
  },
  server: {
    port: 3000,
    proxy: {
      '/admin': { target: 'http://localhost:8000', changeOrigin: true },
      '/auth':  { target: 'http://localhost:8000', changeOrigin: true },
      '/env-check': { target: 'http://localhost:8000', changeOrigin: true },
      '/webhook':   { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
