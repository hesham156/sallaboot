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
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        // Route vendor libs to dedicated, independently-cached chunks. A
        // function reliably isolates recharts + all its d3-* transitive deps
        // (the heaviest tree) so they don't get merged into the HeroUI chunk.
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return
          if (/recharts|d3-|internmap|victory-vendor/.test(id)) return 'charts'
          if (/@heroui|framer-motion|@react-aria|@react-stately|@react-types/.test(id)) return 'heroui'
          if (/react-router|react-dom|\/react\//.test(id)) return 'react'
        },
      },
    },
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
