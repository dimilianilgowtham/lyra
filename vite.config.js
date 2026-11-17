import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    port: 3000,
    open: false,
    proxy: {
      // Proxy NVIDIA NIM API calls to bypass CORS in development
      '/nvidia-api': {
        target: 'https://integrate.api.nvidia.com',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/nvidia-api/, ''),
        secure: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          // React core — tiny, loads first
          'vendor-react': ['react', 'react-dom'],
          // Framer Motion — animation lib, separate chunk
          'vendor-framer': ['framer-motion'],
          // Document processing — only needed when files are uploaded
          'vendor-docs': ['mammoth', 'xlsx', 'pdfjs-dist'],
          // Markdown rendering
          'vendor-md': ['marked', 'dompurify'],
        },
      },
    },
  },
  optimizeDeps: {
    // Pre-bundle critical path dependencies for faster dev cold start
    include: ['react', 'react-dom', 'framer-motion'],
  },
})
