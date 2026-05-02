import { create } from 'zustand'

import type { JWTClaims, User } from './types'

// In-memory only auth store per Cluster 0 Dev-Mode Addendum §3.3:
// "receives the JWT, stores it in memory, redirects to the user's role tree".
//
// The JWT is *not* persisted to localStorage / sessionStorage. On page
// refresh the JWT is gone but the HttpOnly refresh cookie (set by the
// backend) is still present, so a single POST /api/v2/auth/refresh on
// app boot reissues a JWT and the user stays signed in (chunk 0.1
// acceptance criterion 13).

interface AuthState {
  jwt: string | null
  user: User | null
  setAuth: (jwt: string) => void
  clearAuth: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  jwt: null,
  user: null,
  setAuth: (jwt) => {
    const claims = parseJwtClaims(jwt)
    set({
      jwt,
      user: {
        user_id: claims.sub,
        firm_id: claims.firm_id,
        role: claims.role,
        email: claims.email,
        name: claims.name,
        session_id: claims.session_id,
      },
    })
  },
  clearAuth: () => set({ jwt: null, user: null }),
}))

// Decode a JWT's payload without verifying the signature. The signature
// has already been verified by the backend; the frontend only needs the
// claim values for UI use. Browser environments don't have a built-in
// base64url decoder so we convert to standard base64 first.
export function parseJwtClaims(jwt: string): JWTClaims {
  const segments = jwt.split('.')
  if (segments.length !== 3) {
    throw new Error('Malformed JWT: expected three dot-separated segments.')
  }
  const payload = segments[1]
  const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4)
  const decoded = atob(padded.replace(/-/g, '+').replace(/_/g, '/'))
  return JSON.parse(decoded) as JWTClaims
}
