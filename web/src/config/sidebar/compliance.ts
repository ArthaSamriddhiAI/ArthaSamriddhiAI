import { BookOpen, FileBarChart, ShieldCheck } from 'lucide-react'

import type { SidebarItem } from './types'

// Per chunk plan §scope_in (chunk 0.2):
// "Compliance sidebar: Override Audit, Rule Corpus, Telemetry (all
//  disabled placeholders)."
export const COMPLIANCE_SIDEBAR: SidebarItem[] = [
  { label: 'Override Audit', icon: ShieldCheck, enabled: false },
  { label: 'Rule Corpus', icon: BookOpen, enabled: false },
  { label: 'Telemetry', icon: FileBarChart, enabled: false },
]
