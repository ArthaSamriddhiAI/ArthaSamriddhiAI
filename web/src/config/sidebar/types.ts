import type { LucideIcon } from 'lucide-react'

// Per-role sidebar item.
//
// Cluster 0 chunk 0.2 ships every item DISABLED — they communicate
// what's coming. Each subsequent cluster that ships a real surface
// flips the matching item's `enabled` to true and points `href` at
// the route.
export interface SidebarItem {
  label: string
  icon: LucideIcon
  enabled: boolean
  href?: string
}
