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
export default defineConfig({
  base: '/app/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
