import { DashboardWelcomeCard } from './DashboardPage'
import { LLMConfigBanner } from '../components/LLMConfigBanner'
import { useRoleHomeVisited } from '../system/useRoleHomeVisited'

// Generic role-tree home page. All four role trees (advisor / cio /
// compliance / audit) render the same shape per chunk 0.2 §scope_in:
// "Per-role placeholder home page at each tree's root (e.g., /app/advisor
//  shows the advisor's home page placeholder)."
//
// The role-specific UI difference is in the SIDEBAR (per-role configs in
// web/src/config/sidebar/). The home page itself is identical content,
// scoped to whichever role landed here. Per chunk 0.2 §scope_out:
// "The four role trees use the same React app shell component; only the
//  sidebar contents differ per role."
//
// Mount-time T1 emission via useRoleHomeVisited (chunk 0.2 acceptance
// criterion 11).
//
// Cluster 1 chunk 1.3: the LLMConfigBanner renders only for the CIO role
// — first-run + kill-switch awareness — and is a no-op for the other
// three roles.
export function RoleHomePage() {
  useRoleHomeVisited()
  return (
    <div className="p-8 max-w-3xl">
      <LLMConfigBanner />
      <DashboardWelcomeCard />
    </div>
  )
}
