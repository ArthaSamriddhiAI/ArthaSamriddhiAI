import { Activity, BarChart3, Bell, Briefcase, Users } from 'lucide-react'

import { cn } from '../lib/cn'

// Cluster 0 sidebar — generic placeholder per chunk plan §scope_in:
// "sidebar (collapsed default, placeholder navigation items)".
//
// Items are visible but disabled (greyed out, non-clickable). They
// communicate to the advisor what's coming. As subsequent clusters
// ship, items light up.
//
// Chunk 0.2 introduces role-aware sidebar configs (advisor vs cio vs
// compliance vs audit) that replace this generic list. Step 5 ships
// the generic version; step 5+chunk 0.2 swaps it.

interface SidebarItem {
  label: string
  icon: typeof Briefcase
  enabled: boolean
}

const ITEMS: SidebarItem[] = [
  { label: 'Cases', icon: Briefcase, enabled: false },
  { label: 'Investors', icon: Users, enabled: false },
  { label: 'Alerts', icon: Bell, enabled: false },
  { label: 'Monitoring', icon: Activity, enabled: false },
  { label: 'Reports', icon: BarChart3, enabled: false },
]

export function Sidebar() {
  return (
    <aside
      className="w-16 bg-primary flex flex-col items-center gap-2 py-4 shrink-0"
      aria-label="Primary navigation"
    >
      {ITEMS.map((item) => (
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
