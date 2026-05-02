import { Activity, Bell, Briefcase, Users } from 'lucide-react'

import type { SidebarItem } from './types'

// Per chunk plan §scope_in (chunk 0.2):
// "Advisor sidebar: Cases, Investors, Alerts, Monitoring (all disabled placeholders)."
export const ADVISOR_SIDEBAR: SidebarItem[] = [
  { label: 'Cases', icon: Briefcase, enabled: false },
  { label: 'Investors', icon: Users, enabled: false },
  { label: 'Alerts', icon: Bell, enabled: false },
  { label: 'Monitoring', icon: Activity, enabled: false },
]
