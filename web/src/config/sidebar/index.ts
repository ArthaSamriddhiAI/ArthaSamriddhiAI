import type { Role } from '../../auth/types'

import { ADVISOR_SIDEBAR } from './advisor'
import { AUDIT_SIDEBAR } from './audit'
import { CIO_SIDEBAR } from './cio'
import { COMPLIANCE_SIDEBAR } from './compliance'
import type { SidebarItem } from './types'

// Single lookup table the Sidebar component reads. Adding a new role-
// scoped surface in a future cluster means flipping the matching item
// in the corresponding config file from `enabled: false` to `true` and
// pointing `href` at its TanStack Router route.
export const SIDEBAR_BY_ROLE: Record<Role, SidebarItem[]> = {
  advisor: ADVISOR_SIDEBAR,
  cio: CIO_SIDEBAR,
  compliance: COMPLIANCE_SIDEBAR,
  audit: AUDIT_SIDEBAR,
}

export type { SidebarItem }
