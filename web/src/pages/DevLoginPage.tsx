import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { apiFetch } from '../api/client'
import { useAuthStore } from '../auth/store'
import { cn } from '../lib/cn'

// Dev-mode addendum §3.3: a simple page that lists the YAML test users
// and lets the developer pick one. On submit, POST /api/v2/auth/dev-login,
// store the JWT in memory, and navigate to the dashboard.
//
// "The UI does not need polish. It is a developer-facing affordance, not
//  a product surface" — addendum §3.3.

interface DevUser {
  user_id: string
  name: string
  role: string
}

interface DevUsersResponse {
  users: DevUser[]
}

export function DevLoginPage() {
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)
  const [selected, setSelected] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const usersQuery = useQuery<DevUsersResponse>({
    queryKey: ['dev-users'],
    queryFn: async () => {
      const response = await apiFetch('/api/v2/auth/dev-users')
      if (!response.ok) {
        throw new Error(`Failed to load test users (${response.status}).`)
      }
      return response.json() as Promise<DevUsersResponse>
    },
  })

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!selected || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      const response = await apiFetch('/api/v2/auth/dev-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: selected }),
      })
      if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        throw new Error(body.detail ?? `Login failed (${response.status}).`)
      }
      const body = (await response.json()) as {
        access_token: string
        redirect_url: string
      }
      setAuth(body.access_token)
      // Chunk 0.2 — backend computed the role-tree home for us
      // (e.g., /app/advisor). Strip the /app basepath since the
      // router treats /app as root.
      const target = body.redirect_url.replace(/^\/app/, '') || '/'
      navigate({ to: target })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 p-6">
      <div
        className={cn(
          'w-full max-w-md rounded-lg border border-gray-200 bg-white shadow-sm p-8',
        )}
      >
        <h1 className="text-xl font-semibold text-gray-900 mb-1">
          Demo sign-in
        </h1>
        <p className="text-sm text-gray-600 mb-6">
          Internal demo build. Pick a test user to continue.
        </p>

        {usersQuery.isLoading && (
          <div className="text-sm text-gray-500">Loading test users…</div>
        )}
        {usersQuery.isError && (
          <div className="text-sm text-red-600">
            Could not load test users:{' '}
            {usersQuery.error instanceof Error
              ? usersQuery.error.message
              : 'unknown error'}
          </div>
        )}

        {usersQuery.data && (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="user-select"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Test user
              </label>
              <select
                id="user-select"
                value={selected}
                onChange={(event) => setSelected(event.target.value)}
                disabled={submitting}
                className={cn(
                  'w-full rounded-md border border-gray-300 px-3 py-2 text-sm',
                  'focus:outline-none focus:ring-2 focus:ring-offset-1',
                )}
                style={{ '--tw-ring-color': 'var(--color-accent)' } as React.CSSProperties}
              >
                <option value="">Select a user…</option>
                {usersQuery.data.users.map((user) => (
                  <option key={user.user_id} value={user.user_id}>
                    {user.name} — {user.role}
                  </option>
                ))}
              </select>
            </div>

            {error && (
              <div className="text-sm text-red-600 rounded-md bg-red-50 px-3 py-2">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={!selected || submitting}
              className={cn(
                'w-full rounded-md py-2 text-sm font-medium text-white transition-opacity',
                'disabled:cursor-not-allowed disabled:opacity-50',
              )}
              style={{ backgroundColor: 'var(--color-primary)' }}
            >
              {submitting ? 'Signing in…' : 'Log in'}
            </button>
          </form>
        )}

        <p className="mt-6 text-xs text-gray-400 text-center">
          Stub auth — production OIDC swaps in during the production-readiness
          phase.
        </p>
      </div>
    </div>
  )
}
