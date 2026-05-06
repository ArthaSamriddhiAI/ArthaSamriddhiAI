import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Per Cluster 0 chunk plan implementation notes:
// - The React bundle is mounted at /app/ on the FastAPI backend
//   (`app.mount("/app", StaticFiles(directory="web/dist", html=True))`),
//   so production builds need a `base: '/app/'` so asset URLs resolve correctly.
// - In development, Vite runs on its own port (5173 by default). The
//   refresh cookie has Path=/api/v2/auth/refresh and SameSite=Strict,
//   which means the cookie is only sent on same-origin requests — so we
//   proxy /api/* through Vite to the FastAPI backend on :8000. From the
//   browser's perspective, requests are same-origin (localhost:5173) and
//   the cookie travels.
//
// We also proxy `^/$` (the landing page route) and `/static` (v1 SPA
// assets) through Vite so dev mirrors production: hitting
// http://localhost:5173/ shows the FastAPI-served `static/landing.html`
// and the "Enter the Platform" button takes the user to /app where the
// Vite-served React app picks up. Without these, dev users would have
// to remember to visit :8000 for the landing and :5173 for the app.
export default defineConfig({
  base: '/app/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // FastAPI APIs (cluster 0+).
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // V1 Alpine SPA + landing page assets (CSS, JS, help/, etc.).
      '/static': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // Landing page at the root path. Regex match prevents this from
      // capturing every request — only exactly "/" forwards to FastAPI;
      // /app/* stays with Vite for HMR.
      '^/$': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
