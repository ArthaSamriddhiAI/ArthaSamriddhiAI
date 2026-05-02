import { LogOut } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { apiFetch } from '../api/client'
import { useAuthStore } from '../auth/store'
import type { User } from '../auth/types'
import { cn } from '../lib/cn'

interface Props {
  user: User
}

// Hand-rolled dropdown to avoid pulling in @radix-ui/react-dropdown-menu
// for cluster 0. Radix can be added when the second dropdown shows up
// (likely cluster 1 — investor pickers, etc.).

export function UserMenu({ user }: Props) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const clearAuth = useAuthStore((s) => s.clearAuth)

  // Close on outside click.
  useEffect(() => {
    if (!open) return
    const handler = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const handleLogout = async () => {
    setOpen(false)
    // Best-effort backend logout (revokes the session + clears the
    // refresh cookie). Even if it fails, we still clear the local store
    // so the route guard kicks the user back to /dev-login.
    try {
      await apiFetch('/api/v2/auth/logout', { method: 'POST' })
    } catch {
      // Network / server unreachable — local-only logout still works.
    }
    clearAuth()
  }

  const initials = user.name
    .split(' ')
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase()

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-label="User menu"
        aria-expanded={open}
        className={cn(
          'flex items-center gap-2 rounded-md px-2 py-1.5 transition-colors',
          'hover:bg-gray-100',
        )}
      >
        <div
          className="w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-medium"
          style={{ backgroundColor: 'var(--color-accent)' }}
        >
          {initials}
        </div>
        <div className="text-left hidden sm:block">
          <div className="text-sm font-medium text-gray-900">{user.name}</div>
          <div className="text-xs text-gray-500">{user.email}</div>
        </div>
      </button>
      {open && (
        <div
          role="menu"
          className={cn(
            'absolute right-0 top-full mt-2 w-48 rounded-md border border-gray-200',
            'bg-white shadow-lg py-1 z-50',
          )}
        >
          <button
            type="button"
            role="menuitem"
            onClick={handleLogout}
            className={cn(
              'w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700',
              'hover:bg-gray-100',
            )}
          >
            <LogOut size={16} aria-hidden="true" />
            Log out
          </button>
        </div>
      )}
    </div>
  )
}
