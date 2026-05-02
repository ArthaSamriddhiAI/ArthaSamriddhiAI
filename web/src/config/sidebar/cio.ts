import {
  Activity,
  ClipboardCheck,
  ClipboardList,
  Layers,
  PieChart,
} from 'lucide-react'

import type { SidebarItem } from './types'

// Per chunk plan §scope_in (chunk 0.2):
// "CIO sidebar: Construction Pipeline, Committee Queue, Model Portfolio,
//  Approvals, Monitoring (all disabled placeholders)."
export const CIO_SIDEBAR: SidebarItem[] = [
  { label: 'Construction Pipeline', icon: Layers, enabled: false },
  { label: 'Committee Queue', icon: ClipboardList, enabled: false },
  { label: 'Model Portfolio', icon: PieChart, enabled: false },
  { label: 'Approvals', icon: ClipboardCheck, enabled: false },
  { label: 'Monitoring', icon: Activity, enabled: false },
]
