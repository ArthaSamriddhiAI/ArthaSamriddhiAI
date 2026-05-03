import { Link } from '@tanstack/react-router'

import { useAuthStore } from '../auth/store'
import { SIDEBAR_BY_ROLE, type SidebarItem } from '../config/sidebar'
import { cn } from '../lib/cn'

// Role-aware sidebar (chunk 0.2). Reads the user's role from the auth
// store and renders the per-role config from `web/src/config/sidebar/`.
//
// Items with `enabled: true` AND `href` set render as TanStack Router
// links; items still in placeholder mode render as disabled buttons.
// Cluster 1 chunk 1.1 lights up "Investors" for advisor with
// href="/advisor/investors".

export function Sidebar() {
  const role = useAuthStore((s) => s.user?.role)
  if (!role) {
    return <aside className="w-16 bg-primary shrink-0" aria-hidden="true" />
  }
  const items = SIDEBAR_BY_ROLE[role]
  return (
    <aside
      className="w-16 bg-primary flex flex-col items-center gap-2 py-4 shrink-0"
      aria-label="Primary navigation"
    >
      {items.map((item) => (
        <SidebarButton key={item.label} item={item} />
      ))}
    </aside>
  )
}

const buttonClassEnabled = cn(
  'w-12 h-12 rounded-md flex items-center justify-center transition-colors',
  'text-white/60 hover:bg-white/10 hover:text-white cursor-pointer',
)

const buttonClassDisabled = cn(
  'w-12 h-12 rounded-md flex items-center justify-center transition-colors',
  'text-white/60 cursor-not-allowed opacity-40',
)

function SidebarButton({ item }: { item: SidebarItem }) {
  const Icon = item.icon
  if (item.enabled && item.href) {
    return (
      <Link
        to={item.href}
        title={item.label}
        aria-label={item.label}
        className={buttonClassEnabled}
        activeOptions={{ exact: false }}
        // active styling: a small left-side accent bar visible when route matches
        activeProps={{ className: cn(buttonClassEnabled, 'bg-white/15 text-white') }}
      >
        <Icon size={20} aria-hidden="true" />
      </Link>
    )
  }
  return (
    <button
      type="button"
      disabled
      title={`${item.label} (coming soon)`}
      aria-label={item.label}
      className={buttonClassDisabled}
    >
      <Icon size={20} aria-hidden="true" />
    </button>
  )
}
