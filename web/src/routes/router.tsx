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
import { InvestorDetailPage } from '../pages/investors/InvestorDetailPage'
import { InvestorListPage } from '../pages/investors/InvestorListPage'
import { NewInvestorPage } from '../pages/investors/NewInvestorPage'
import { RoleHomePage } from '../pages/RoleHomePage'

// Code-based router. Cluster 0 introduced the four role-tree subtrees;
// cluster 1 chunk 1.1 adds nested routes under /advisor for investors:
//   /app/advisor/                       → advisor home (RoleHomePage)
//   /app/advisor/investors              → investor list
//   /app/advisor/investors/new          → new-investor form
//   /app/advisor/investors/$investorId  → investor detail
//
// Each role-tree route now renders <AppShell><Outlet /></AppShell>
// (refactor from cluster 0's <RoleHomePage /> direct render) so child
// routes can fill the main region. Index routes preserve cluster 0's
// home behaviour.

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
      throw redirect({ to: ROLE_PATHS[user.role] })
    }
  }
}

const rootRoute = createRootRoute({
  component: () => <Outlet />,
})

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  beforeLoad: ({ location }) => {
    const user = useAuthStore.getState().user
    if (!user) {
      throw redirect({ to: '/dev-login', search: { redirect: location.href } })
    }
    throw redirect({ to: ROLE_PATHS[user.role] })
  },
  component: () => null,
})

const devLoginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/dev-login',
  validateSearch: (search: Record<string, unknown>): { redirect?: string } => ({
    redirect: typeof search.redirect === 'string' ? search.redirect : undefined,
  }),
  component: DevLoginPage,
})

// ----- Advisor tree (with nested investor routes from chunk 1.1) -----

const advisorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: ROLE_PATHS.advisor,
  beforeLoad: requireRole('advisor'),
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
})

const advisorIndexRoute = createRoute({
  getParentRoute: () => advisorRoute,
  path: '/',
  component: RoleHomePage,
})

const advisorInvestorsListRoute = createRoute({
  getParentRoute: () => advisorRoute,
  path: '/investors',
  component: InvestorListPage,
})

const advisorInvestorsNewRoute = createRoute({
  getParentRoute: () => advisorRoute,
  path: '/investors/new',
  component: NewInvestorPage,
})

const advisorInvestorDetailRoute = createRoute({
  getParentRoute: () => advisorRoute,
  path: '/investors/$investorId',
  component: InvestorDetailPage,
})

// ----- Other role trees (no nested routes in cluster 1) -----

function makeSimpleRoleRoute(role: Role) {
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

const cioRoute = makeSimpleRoleRoute('cio')
const complianceRoute = makeSimpleRoleRoute('compliance')
const auditRoute = makeSimpleRoleRoute('audit')

const routeTree = rootRoute.addChildren([
  indexRoute,
  devLoginRoute,
  advisorRoute.addChildren([
    advisorIndexRoute,
    advisorInvestorsListRoute,
    advisorInvestorsNewRoute,
    advisorInvestorDetailRoute,
  ]),
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
