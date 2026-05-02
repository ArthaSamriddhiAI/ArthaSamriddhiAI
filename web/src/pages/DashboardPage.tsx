import { useAuthStore } from '../auth/store'
import { RoleBadge } from '../components/RoleBadge'
import { SSEStatusIndicator } from '../components/SSEStatusIndicator'
import { useFirmInfo } from '../firm/useFirmInfo'
import { useSSEStore } from '../sse/store'

// Cluster 0 chunk 0.1 placeholder dashboard per chunk plan §scope_in:
// "Placeholder dashboard page rendering: user's display name, role badge
//  (using firm's accent color), firm display name, "Welcome to Samriddhi AI"
//  line, SSE connection status indicator with three states (connected/
//  heartbeating, reconnecting, disconnected)."
//
// Chunk 0.2 swaps in role-tree home pages (one per role) but the content
// stays the same shape — name + role + firm + welcome + SSE indicator.
// We extract the inner block as <DashboardWelcomeCard/> so chunk 0.2 can
// reuse it without copy-paste.

export function DashboardPage() {
  return (
    <div className="p-8 max-w-3xl">
      <DashboardWelcomeCard />
    </div>
  )
}

export function DashboardWelcomeCard() {
  const user = useAuthStore((s) => s.user)
  const firm = useFirmInfo()
  const sseState = useSSEStore((s) => s.state)

  if (!user) return null

  return (
    <section className="rounded-lg border border-gray-200 bg-white shadow-sm p-8">
      <h1 className="text-2xl font-semibold text-gray-900 mb-1">
        Welcome to Samriddhi AI
      </h1>
      {firm.data && (
        <p className="text-sm text-gray-500 mb-6">
          {firm.data.firm_display_name}
          <span className="text-gray-300 mx-2">·</span>
          {firm.data.regulatory_jurisdiction}
        </p>
      )}

      <div className="flex items-center gap-3 mb-8">
        <span className="text-lg text-gray-900">{user.name}</span>
        <RoleBadge role={user.role} />
      </div>

      <div className="flex items-center gap-3 text-sm text-gray-600">
        <SSEStatusIndicator />
        <span>
          Real-time channel:{' '}
          <span className="font-medium text-gray-900">{sseState}</span>
        </span>
      </div>
    </section>
  )
}
