import { defineConfig } from 'vite';
export default defineConfig({
  server: { host: '0.0.0.0', strictPort: true, proxy: {
    '/api': { target: process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true, rewrite: path => path.replace(/^\/api/, '') }
  } },
  preview: { host: '0.0.0.0', proxy: {
    '/api': { target: process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true, rewrite: path => path.replace(/^\/api/, '') }
  } },
  build: { rolldownOptions: { output: { codeSplitting: { groups: [{ name: 'mapbox', test: /node_modules\/mapbox-gl/ }] } } } }
});
