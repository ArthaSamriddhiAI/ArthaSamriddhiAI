import { useAuthStore } from '../auth/store'
import { SIDEBAR_BY_ROLE, type SidebarItem } from '../config/sidebar'
import { cn } from '../lib/cn'

// Role-aware sidebar (chunk 0.2). Reads the user's role from the auth
// store and renders the per-role config from `web/src/config/sidebar/`.
//
// Items are visible but disabled (greyed out, non-clickable) for cluster 0.
// They communicate to the user what's coming. As subsequent clusters
// ship surfaces, the matching items light up.
//
// If for any reason the user is missing (not yet authenticated, weird
// race), the sidebar renders nothing rather than crashing — the auth
// gate will redirect to /dev-login on next render.

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

function SidebarButton({ item }: { item: SidebarItem }) {
  const Icon = item.icon
  return (
    <button
      type="button"
      disabled={!item.enabled}
      title={item.enabled ? item.label : `${item.label} (coming soon)`}
      aria-label={item.label}
      className={cn(
        'w-12 h-12 rounded-md flex items-center justify-center transition-colors',
        'text-white/60',
        item.enabled
          ? 'hover:bg-white/10 hover:text-white cursor-pointer'
          : 'cursor-not-allowed opacity-40',
      )}
    >
      <Icon size={20} aria-hidden="true" />
    </button>
  )
}
