import type { Role } from '../auth/types'
import { cn } from '../lib/cn'

// Role pill rendered with the firm's --color-accent for visible firm
// branding (chunk 0.1 acceptance criterion 7).

const ROLE_LABEL: Record<Role, string> = {
  advisor: 'Advisor',
  cio: 'CIO',
  compliance: 'Compliance',
  audit: 'Audit',
}

export function RoleBadge({
  role,
  size = 'md',
}: {
  role: Role
  size?: 'sm' | 'md'
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full font-medium text-white',
        size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-1 text-xs',
        'tracking-wide uppercase',
      )}
      style={{ backgroundColor: 'var(--color-accent)' }}
    >
      {ROLE_LABEL[role]}
    </span>
  )
}
