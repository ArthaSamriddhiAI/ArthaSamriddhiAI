import { FileBarChart, History } from 'lucide-react'

import type { SidebarItem } from './types'

// Per chunk plan §scope_in (chunk 0.2):
// "Audit sidebar: Case Replay, Telemetry Browser (all disabled placeholders)."
export const AUDIT_SIDEBAR: SidebarItem[] = [
  { label: 'Case Replay', icon: History, enabled: false },
  { label: 'Telemetry Browser', icon: FileBarChart, enabled: false },
]
