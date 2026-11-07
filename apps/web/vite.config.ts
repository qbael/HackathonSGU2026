import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { assetsInlineLimit: 0 },
  server: {
    host: '127.0.0.1',
    port: Number(process.env.PORT) || 5173,
    strictPort: false,
    proxy: {
      '/api': { target: 'http://127.0.0.1:5080', changeOrigin: false },
    },
  },
});
