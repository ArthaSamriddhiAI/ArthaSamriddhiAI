import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from '@tanstack/react-router'

import { useAuthStore } from '../auth/store'
import type { Role } from '../auth/types'
import { AppShell } from '../components/AppShell'
import { DevLoginPage } from '../pages/DevLoginPage'
import { RoleHomePage } from '../pages/RoleHomePage'

// Code-based router with the four role-tree subtrees added in chunk 0.2:
//   /app/                       → redirect to /app/<user-role>
//   /app/dev-login              → public login page
//   /app/advisor                → advisor home (advisor only)
//   /app/cio                    → CIO home (CIO only)
//   /app/compliance             → compliance home (compliance only)
//   /app/audit                  → audit home (audit only)
//
// Each role tree's beforeLoad does two checks (per chunk 0.2 §scope_in):
//   1. Authentication — if no user, redirect to /dev-login carrying the
//      requested URL so post-login navigation can resume there.
//   2. Role match — if the user has a different role, redirect to THEIR
//      tree (so an advisor typing /app/cio gets bounced to /app/advisor,
//      not 403'd).
//
// Subsequent clusters add nested routes under each role tree (e.g.,
// cluster 1 will add /app/advisor/investors, /app/advisor/cases). The
// per-tree beforeLoad still applies.

const ROLE_PATHS: Record<Role, string> = {
  advisor: '/advisor',
  cio: '/cio',
  compliance: '/compliance',
  audit: '/audit',
}

interface BeforeLoadCtx {
  location: { href: string }
}

function requireRole(expected: Role) {
  return ({ location }: BeforeLoadCtx) => {
    const user = useAuthStore.getState().user
    if (!user) {
      throw redirect({
        to: '/dev-login',
        search: { redirect: location.href },
      })
    }
    if (user.role !== expected) {
      // Bounce to the user's actual role tree.
      throw redirect({ to: ROLE_PATHS[user.role] })
    }
  }
}

const rootRoute = createRootRoute({
  component: () => <Outlet />,
})

// `/` — chunk 0.1's old root behaviour (auth gate + dashboard) is replaced
// by a pure redirect to the user's role tree. Unauthenticated visitors
// get sent to /dev-login.
const indexRoute = createRoute({
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
    throw redirect({ to: ROLE_PATHS[user.role] })
  },
  // Component never actually renders because beforeLoad always redirects.
  component: () => null,
})

const devLoginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/dev-login',
  validateSearch: (
    search: Record<string, unknown>,
  ): { redirect?: string } => ({
    redirect:
      typeof search.redirect === 'string' ? search.redirect : undefined,
  }),
  component: DevLoginPage,
})

function makeRoleRoute(role: Role) {
  return createRoute({
    getParentRoute: () => rootRoute,
    path: ROLE_PATHS[role],
    beforeLoad: requireRole(role),
    component: () => (
      <AppShell>
        <RoleHomePage />
      </AppShell>
    ),
  })
}

const advisorRoute = makeRoleRoute('advisor')
const cioRoute = makeRoleRoute('cio')
const complianceRoute = makeRoleRoute('compliance')
const auditRoute = makeRoleRoute('audit')

const routeTree = rootRoute.addChildren([
  indexRoute,
  devLoginRoute,
  advisorRoute,
  cioRoute,
  complianceRoute,
  auditRoute,
])

export const router = createRouter({
  routeTree,
  basepath: '/app',
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
