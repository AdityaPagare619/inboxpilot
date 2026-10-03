import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/inboxpilot/',
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 600 },
})
