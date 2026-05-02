import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from '@tanstack/react-router'

import { useAuthStore } from '../auth/store'
import { AppShell } from '../components/AppShell'
import { DashboardPage } from '../pages/DashboardPage'
import { DevLoginPage } from '../pages/DevLoginPage'

// Code-based router. The TanStack Router CLI / file-based routing is an
// option for later when the route count grows; cluster 0 has two routes
// (`/` and `/dev-login`) so code-based is plenty.
//
// Auth gate via `beforeLoad`: any route that isn't /dev-login redirects
// to /dev-login when the auth store has no user. After login the user
// is sent back to the originally-requested URL (carried in `?redirect=`).

const rootRoute = createRootRoute({
  component: () => <Outlet />,
})

const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  beforeLoad: ({ location }) => {
    const user = useAuthStore.getState().user
    if (!user) {
      throw redirect({
        to: '/dev-login',
        search: { redirect: location.href },
      })
    }
  },
  component: () => (
    <AppShell>
      <DashboardPage />
    </AppShell>
  ),
})

const devLoginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/dev-login',
  // Allow `?redirect=...` to pass through; we don't validate it strictly
  // because the beforeLoad on the dashboard already gates access.
  validateSearch: (
    search: Record<string, unknown>,
  ): { redirect?: string } => ({
    redirect:
      typeof search.redirect === 'string' ? search.redirect : undefined,
  }),
  component: DevLoginPage,
})

const routeTree = rootRoute.addChildren([dashboardRoute, devLoginRoute])

export const router = createRouter({
  routeTree,
  // Vite config sets `base: '/app/'`; the FastAPI mount serves the bundle
  // at /app/. Tell the router to treat /app as the root so internal
  // route paths ('/', '/dev-login') resolve correctly.
  basepath: '/app',
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
