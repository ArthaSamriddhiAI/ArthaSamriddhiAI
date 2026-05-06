import {
  Activity,
  Briefcase,
  ClipboardCheck,
  ClipboardList,
  Layers,
  PieChart,
  Settings,
} from 'lucide-react'

import type { SidebarItem } from './types'

// Per chunk plan §scope_in (chunk 0.2):
// "CIO sidebar: Construction Pipeline, Committee Queue, Model Portfolio,
//  Approvals, Monitoring (all disabled placeholders)."
//
// Cluster 1 chunk 1.3 adds a CIO-only "Settings" item pointing at the
// LLM Provider settings page.
//
// Cluster 2 chunk 2.3 lights up "Approvals" → /cio/pending-amendments
// (the CIO's mandate-amendment queue + side-by-side diff review surface).
// Future clusters extend Approvals to other governance queues.
export const CIO_SIDEBAR: SidebarItem[] = [
  // Cluster 5 chunk 5.5: Cases firm-wide for the CIO (decision authority).
  { label: 'Cases', icon: Briefcase, enabled: true, href: '/cio/cases' },
  { label: 'Construction Pipeline', icon: Layers, enabled: false },
  { label: 'Committee Queue', icon: ClipboardList, enabled: false },
  { label: 'Model Portfolio', icon: PieChart, enabled: false },
  {
    label: 'Approvals',
    icon: ClipboardCheck,
    enabled: true,
    href: '/cio/pending-amendments',
  },
  { label: 'Monitoring', icon: Activity, enabled: false },
  {
    label: 'Settings',
    icon: Settings,
    enabled: true,
    href: '/cio/settings/llm-router',
  },
]
