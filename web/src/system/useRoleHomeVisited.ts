import { useEffect, useRef } from 'react'

import { apiFetch } from '../api/client'

// Fires `POST /api/v2/system/role-home-visited` on mount. The backend
// emits the `role_home_visited` T1 event from the user's JWT-resolved
// identity (so the audit source can't be spoofed client-side).
//
// Per chunk 0.2 acceptance criterion 11: each role-tree home page
// emits the event once per visit. We use a ref to guard against
// React 19 StrictMode's double-mount in development.
export function useRoleHomeVisited(): void {
  const fired = useRef(false)
  useEffect(() => {
    if (fired.current) return
    fired.current = true
    void apiFetch('/api/v2/system/role-home-visited', { method: 'POST' })
  }, [])
}
