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
import { AdaptersPage } from '../pages/admin/AdaptersPage'
import { AdminLandingPage } from '../pages/admin/AdminLandingPage'
import { FreshnessPage } from '../pages/admin/FreshnessPage'
import { IndustryReportsPage } from '../pages/admin/IndustryReportsPage'
import { InstrumentsPage } from '../pages/admin/InstrumentsPage'
import { MacroSnapshotsPage } from '../pages/admin/MacroSnapshotsPage'
import { SebiCategoriesPage } from '../pages/admin/SebiCategoriesPage'
import { SnapshotsPage } from '../pages/admin/SnapshotsPage'
import { StagingPage } from '../pages/admin/StagingPage'
import { CaseDetailPage } from '../pages/cases/CaseDetailPage'
import { CaseListPage } from '../pages/cases/CaseListPage'
import { NewCasePage } from '../pages/cases/NewCasePage'
import { ConversationalPage } from '../pages/conversational/ConversationalPage'
import { DevLoginPage } from '../pages/DevLoginPage'
import { InvestorDetailPage } from '../pages/investors/InvestorDetailPage'
import { InvestorListPage } from '../pages/investors/InvestorListPage'
import { NewInvestorPage } from '../pages/investors/NewInvestorPage'
import { AmendMandatePage } from '../pages/mandates/AmendMandatePage'
import { AmendmentReviewPage } from '../pages/mandates/AmendmentReviewPage'
import { NewMandatePage } from '../pages/mandates/NewMandatePage'
import { PendingAmendmentsPage } from '../pages/mandates/PendingAmendmentsPage'
import { CellDetailPage } from '../pages/model-portfolio/CellDetailPage'
import { ModelPortfolioInstrumentsPage } from '../pages/model-portfolio/InstrumentsPage'
import { PreferredMatrixPage } from '../pages/model-portfolio/PreferredMatrixPage'
import { RoleHomePage } from '../pages/RoleHomePage'
import { LLMRouterSettingsPage } from '../pages/settings/LLMRouterSettingsPage'

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

// Cluster 1 chunk 1.2 — advisor's C0 conversational onboarding surface.
const advisorConversationalRoute = createRoute({
  getParentRoute: () => advisorRoute,
  path: '/conversational',
  component: ConversationalPage,
})

// Cluster 2 chunk 2.1 — advisor's mandate creation form.
const advisorMandateNewRoute = createRoute({
  getParentRoute: () => advisorRoute,
  path: '/investors/$investorId/mandate/new',
  component: NewMandatePage,
})

// Cluster 2 chunk 2.3 — advisor's amendment editor.
const advisorMandateAmendRoute = createRoute({
  getParentRoute: () => advisorRoute,
  path: '/investors/$investorId/mandate/amend',
  component: AmendMandatePage,
})

// Cluster 4 chunk 4.2 — advisor read-only model-portfolio tag editing.
const advisorModelPortfolioInstrumentsRoute = createRoute({
  getParentRoute: () => advisorRoute,
  path: '/model-portfolio/instruments',
  component: () => <ModelPortfolioInstrumentsPage readOnly={true} backTo="/" />,
})

// Cluster 4 chunk 4.3 — advisor read-only preferred portfolio matrix.
const advisorModelPortfolioPreferredRoute = createRoute({
  getParentRoute: () => advisorRoute,
  path: '/model-portfolio/preferred',
  component: () => (
    <PreferredMatrixPage
      backTo="/"
      cellPathPrefix="/advisor/model-portfolio/preferred"
    />
  ),
})

const advisorModelPortfolioCellRoute = createRoute({
  getParentRoute: () => advisorRoute,
  path: '/model-portfolio/preferred/$riskProfile/$horizon',
  component: () => (
    <CellDetailPage
      readOnly={true}
      matrixPath="/advisor/model-portfolio/preferred"
    />
  ),
})

// Cluster 5 chunk 5.5 — advisor case list / detail / new-case form.
const advisorCasesListRoute = createRoute({
  getParentRoute: () => advisorRoute,
  path: '/cases',
  component: CaseListPage,
})

const advisorCasesNewRoute = createRoute({
  getParentRoute: () => advisorRoute,
  path: '/cases/new',
  component: NewCasePage,
  validateSearch: (search: Record<string, unknown>) => ({
    investorId: typeof search.investorId === 'string' ? search.investorId : undefined,
  }),
})

const advisorCaseDetailRoute = createRoute({
  getParentRoute: () => advisorRoute,
  path: '/cases/$caseId',
  component: CaseDetailPage,
})

// ----- CIO tree (with nested settings routes from chunk 1.3) -----

const cioRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: ROLE_PATHS.cio,
  beforeLoad: requireRole('cio'),
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
})

const cioIndexRoute = createRoute({
  getParentRoute: () => cioRoute,
  path: '/',
  component: RoleHomePage,
})

// Cluster 1 chunk 1.3 — CIO-only Settings → LLM Router page (FR 16.0 §6).
const cioSettingsLlmRouterRoute = createRoute({
  getParentRoute: () => cioRoute,
  path: '/settings/llm-router',
  component: LLMRouterSettingsPage,
})

// Cluster 2 chunk 2.3 — CIO pending-amendments queue + review surface.
const cioPendingAmendmentsRoute = createRoute({
  getParentRoute: () => cioRoute,
  path: '/pending-amendments',
  component: PendingAmendmentsPage,
})

const cioAmendmentReviewRoute = createRoute({
  getParentRoute: () => cioRoute,
  path: '/pending-amendments/$versionId',
  component: AmendmentReviewPage,
})

// Cluster 4 chunk 4.2 — CIO model-portfolio tag editing surface.
const cioModelPortfolioInstrumentsRoute = createRoute({
  getParentRoute: () => cioRoute,
  path: '/model-portfolio/instruments',
  component: () => <ModelPortfolioInstrumentsPage readOnly={false} backTo="/" />,
})

// Cluster 4 chunk 4.3 — CIO preferred portfolio matrix + cell detail.
const cioModelPortfolioPreferredRoute = createRoute({
  getParentRoute: () => cioRoute,
  path: '/model-portfolio/preferred',
  component: () => (
    <PreferredMatrixPage
      backTo="/"
      cellPathPrefix="/cio/model-portfolio/preferred"
    />
  ),
})

const cioModelPortfolioCellRoute = createRoute({
  getParentRoute: () => cioRoute,
  path: '/model-portfolio/preferred/$riskProfile/$horizon',
  component: () => (
    <CellDetailPage
      readOnly={false}
      matrixPath="/cio/model-portfolio/preferred"
    />
  ),
})

// Cluster 5 chunk 5.5 — CIO case list / detail / new-case form.
// CIO sees firm-wide cases + the decision form when status=awaiting_decision.
const cioCasesListRoute = createRoute({
  getParentRoute: () => cioRoute,
  path: '/cases',
  component: CaseListPage,
})

const cioCasesNewRoute = createRoute({
  getParentRoute: () => cioRoute,
  path: '/cases/new',
  component: NewCasePage,
  validateSearch: (search: Record<string, unknown>) => ({
    investorId: typeof search.investorId === 'string' ? search.investorId : undefined,
  }),
})

const cioCaseDetailRoute = createRoute({
  getParentRoute: () => cioRoute,
  path: '/cases/$caseId',
  component: CaseDetailPage,
})

// ----- Audit tree (cluster 3 chunk 3.4 admin surface) -----

const auditRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: ROLE_PATHS.audit,
  beforeLoad: requireRole('audit'),
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
})

const auditIndexRoute = createRoute({
  getParentRoute: () => auditRoute,
  path: '/',
  component: AdminLandingPage,
})

const auditFreshnessRoute = createRoute({
  getParentRoute: () => auditRoute,
  path: '/freshness',
  component: FreshnessPage,
})

const auditAdaptersRoute = createRoute({
  getParentRoute: () => auditRoute,
  path: '/adapters',
  component: AdaptersPage,
})

const auditStagingRoute = createRoute({
  getParentRoute: () => auditRoute,
  path: '/staging',
  component: StagingPage,
})

const auditSnapshotsRoute = createRoute({
  getParentRoute: () => auditRoute,
  path: '/snapshots',
  component: SnapshotsPage,
})

const auditInstrumentsRoute = createRoute({
  getParentRoute: () => auditRoute,
  path: '/instruments',
  component: InstrumentsPage,
})

const auditMacroSnapshotsRoute = createRoute({
  getParentRoute: () => auditRoute,
  path: '/macro-snapshots',
  component: MacroSnapshotsPage,
})

const auditIndustryReportsRoute = createRoute({
  getParentRoute: () => auditRoute,
  path: '/industry-reports',
  component: IndustryReportsPage,
})

const auditSebiCategoriesRoute = createRoute({
  getParentRoute: () => auditRoute,
  path: '/sebi-categories',
  component: SebiCategoriesPage,
})

// ----- Compliance tree (no nested routes yet) -----

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

const complianceRoute = makeSimpleRoleRoute('compliance')

const routeTree = rootRoute.addChildren([
  indexRoute,
  devLoginRoute,
  advisorRoute.addChildren([
    advisorIndexRoute,
    advisorInvestorsListRoute,
    advisorInvestorsNewRoute,
    advisorInvestorDetailRoute,
    advisorConversationalRoute,
    advisorMandateNewRoute,
    advisorMandateAmendRoute,
    advisorModelPortfolioInstrumentsRoute,
    advisorModelPortfolioPreferredRoute,
    advisorModelPortfolioCellRoute,
    advisorCasesListRoute,
    advisorCasesNewRoute,
    advisorCaseDetailRoute,
  ]),
  cioRoute.addChildren([
    cioIndexRoute,
    cioSettingsLlmRouterRoute,
    cioPendingAmendmentsRoute,
    cioAmendmentReviewRoute,
    cioModelPortfolioInstrumentsRoute,
    cioModelPortfolioPreferredRoute,
    cioModelPortfolioCellRoute,
    cioCasesListRoute,
    cioCasesNewRoute,
    cioCaseDetailRoute,
  ]),
  complianceRoute,
  auditRoute.addChildren([
    auditIndexRoute,
    auditFreshnessRoute,
    auditAdaptersRoute,
    auditStagingRoute,
    auditSnapshotsRoute,
    auditInstrumentsRoute,
    auditMacroSnapshotsRoute,
    auditIndustryReportsRoute,
    auditSebiCategoriesRoute,
  ]),
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
