import { Activity, Bell, Briefcase, MessageCircle, Users } from 'lucide-react'

import type { SidebarItem } from './types'

// Per chunk plan §scope_in (chunk 0.2):
// "Advisor sidebar: Cases, Investors, Alerts, Monitoring (all disabled placeholders)."
//
// Cluster 1 chunk 1.1 lit up "Investors" → /app/advisor/investors.
// Cluster 1 chunk 1.2 adds "Conversational" → /app/advisor/conversational
// (per FR Entry 14.0 §4.1 + chunk plan §scope_in: "Sidebar navigation item
// 'Conversational' lights up for advisor role"). Future chunks light up
// the remaining placeholders (Cases, Alerts, Monitoring).
export const ADVISOR_SIDEBAR: SidebarItem[] = [
  { label: 'Cases', icon: Briefcase, enabled: false },
  {
    label: 'Investors',
    icon: Users,
    enabled: true,
    href: '/advisor/investors',
  },
  {
    label: 'Conversational',
    icon: MessageCircle,
    enabled: true,
    href: '/advisor/conversational',
  },
  { label: 'Alerts', icon: Bell, enabled: false },
  { label: 'Monitoring', icon: Activity, enabled: false },
]
