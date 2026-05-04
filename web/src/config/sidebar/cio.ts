import {
  Activity,
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
// LLM Provider settings page. Per chunk 1.3 §scope_in: "Sidebar
// navigation item Settings is visible only to CIO role; clicking takes
// them to settings index with LLM Router as one option." For cluster 1
// the LLM router page is the only settings surface; future clusters add
// firm/user settings under the same /cio/settings tree.
export const CIO_SIDEBAR: SidebarItem[] = [
  { label: 'Construction Pipeline', icon: Layers, enabled: false },
  { label: 'Committee Queue', icon: ClipboardList, enabled: false },
  { label: 'Model Portfolio', icon: PieChart, enabled: false },
  { label: 'Approvals', icon: ClipboardCheck, enabled: false },
  { label: 'Monitoring', icon: Activity, enabled: false },
  {
    label: 'Settings',
    icon: Settings,
    enabled: true,
    href: '/cio/settings/llm-router',
  },
]
