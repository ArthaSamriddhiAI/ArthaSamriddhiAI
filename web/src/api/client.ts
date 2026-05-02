import { useAuthStore } from '../auth/store'

// Single fetch wrapper that handles:
// 1. Attaching Authorization: Bearer <jwt> from the auth store.
// 2. Sending credentials (the refresh cookie) for cross-fetch use.
// 3. On 401, attempting one silent refresh via POST /api/v2/auth/refresh,
//    storing the new JWT, and retrying the original request once.
// 4. If refresh also fails, clearing auth state so the route guard kicks
//    the user back to /dev-login.
//
// Implements the React-side half of FR 17.1 §2.3 (refresh flow) and the
// "auto-refresh on 401, retry once" pattern in the Cluster 0 chunk plan
// step-5 scope.

export class AuthFailedError extends Error {
  constructor(message = 'Authentication failed; refresh exhausted.') {
    super(message)
    this.name = 'AuthFailedError'
  }
}

interface ApiFetchOptions extends RequestInit {
  // Set true to skip the auto-refresh-on-401 dance. Used by the refresh
  // call itself to avoid infinite recursion.
  skipRefresh?: boolean
}

export async function apiFetch(
  input: string,
  init: ApiFetchOptions = {},
): Promise<Response> {
  const { skipRefresh, ...rest } = init
  const headers = new Headers(rest.headers)
  const jwt = useAuthStore.getState().jwt
  if (jwt && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${jwt}`)
  }
  const response = await fetch(input, {
    ...rest,
    headers,
    credentials: 'include',
  })

  if (response.status !== 401 || skipRefresh) {
    return response
  }

  // Try a single refresh and retry.
  const refreshed = await tryRefresh()
  if (!refreshed) {
    useAuthStore.getState().clearAuth()
    return response // caller sees the original 401
  }

  const retryHeaders = new Headers(rest.headers)
  retryHeaders.set('Authorization', `Bearer ${refreshed}`)
  return fetch(input, {
    ...rest,
    headers: retryHeaders,
    credentials: 'include',
  })
}

async function tryRefresh(): Promise<string | null> {
  try {
    const response = await fetch('/api/v2/auth/refresh', {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) {
      return null
    }
    const body = (await response.json()) as { access_token: string }
    useAuthStore.getState().setAuth(body.access_token)
    return body.access_token
  } catch {
    return null
  }
}

// Boot-time helper: try to recover a session from the refresh cookie on
// app mount. Returns true if a session was recovered, false otherwise.
// Used so that page refresh keeps the user signed in (chunk 0.1 crit 13).
export async function tryBootRefresh(): Promise<boolean> {
  return (await tryRefresh()) !== null
}
