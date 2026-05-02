import {
  EventStreamContentType,
  fetchEventSource,
} from '@microsoft/fetch-event-source'
import { useEffect } from 'react'

import { useAuthStore } from '../auth/store'

import { useSSEStore } from './store'

// SSE connection lifecycle hook. Mounted once per AppShell instance.
//
// IMPLEMENTATION NOTE — deviation from FR 18.0 §2.1 wording:
// The spec says "the client opens an SSE connection ... with the
// Authorization: Bearer <jwt> header". Native EventSource cannot send
// custom headers. We use @microsoft/fetch-event-source — a maintained
// EventSource shim that uses fetch+streams under the hood and accepts
// custom headers — to honour the Bearer-header contract. The library
// also handles Last-Event-ID / reconnect for free.
//
// Per FR 18.0 §2.7: the connection is authenticated at establishment
// and remains alive across token refreshes. We capture the JWT once
// per effect-run via the auth store; subsequent token rotations don't
// rebuild this connection. We DO re-run the effect when the JWT
// transitions from absent to present (boot recovery completes) or
// from present to absent (logout) — see the dependency array.

export function useSSEConnection(): void {
  const setSSEState = useSSEStore((s) => s.setState)
  const hasJwt = useAuthStore((s) => s.jwt !== null)

  useEffect(() => {
    if (!hasJwt) {
      setSSEState('disconnected')
      return
    }

    const initialJwt = useAuthStore.getState().jwt!
    const controller = new AbortController()
    setSSEState('connecting')

    void fetchEventSource('/api/v2/events/stream', {
      signal: controller.signal,
      headers: { Authorization: `Bearer ${initialJwt}` },
      // Keep the connection alive when the tab is in the background.
      openWhenHidden: true,

      onopen: async (response) => {
        const ct = response.headers.get('content-type') ?? ''
        if (response.ok && ct.startsWith(EventStreamContentType)) {
          // The first onmessage will flip us to 'connected'.
          return
        }
        throw new Error(
          `SSE handshake failed: status=${response.status}, content-type=${ct || 'none'}`,
        )
      },

      onmessage: (event) => {
        let envelope: { event_type?: string; payload?: unknown }
        try {
          envelope = JSON.parse(event.data)
        } catch {
          // Malformed event — ignore rather than break the stream.
          return
        }

        switch (envelope.event_type) {
          case 'connection_established':
          case 'connection_heartbeat':
            setSSEState('connected')
            return

          case 'token_refresh_required':
            // Out-of-band refresh per FR 18.0 §2.7. The refresh updates
            // the JWT in the auth store; this SSE connection itself
            // stays alive (its initial JWT is still trusted by the
            // server for the duration of the connection).
            void triggerOutOfBandRefresh()
            return

          case 'connection_terminating':
            setSSEState('disconnected')
            controller.abort()
            return

          default:
            // Future cluster event types land here. Cluster 0 has no
            // emitters outside connection lifecycle; ignore for now.
            return
        }
      },

      onerror: () => {
        // Returning normally lets the library auto-retry. Throwing
        // would stop reconnects, which we do NOT want for transient
        // network errors.
        setSSEState('reconnecting')
      },

      onclose: () => {
        // The library calls this between retry attempts as well as on
        // intentional close. If the controller was aborted, we already
        // set state to disconnected; otherwise it's a transient close
        // before reconnect.
        if (!controller.signal.aborted) {
          setSSEState('reconnecting')
        }
      },
    }).catch(() => {
      // Final failure (controller aborted or unrecoverable).
      if (controller.signal.aborted) {
        setSSEState('disconnected')
      } else {
        setSSEState('reconnecting')
      }
    })

    return () => {
      controller.abort()
      setSSEState('disconnected')
    }
    // hasJwt dependency: re-run when the user transitions from absent
    // to present (boot recovery, login) or present to absent (logout).
    // Token refresh keeps hasJwt=true → no re-run, connection persists.
  }, [hasJwt, setSSEState])
}

// Helper: out-of-band refresh that doesn't go through the apiFetch
// 401-recovery flow (we already know we want a new JWT).
async function triggerOutOfBandRefresh(): Promise<void> {
  try {
    const response = await fetch('/api/v2/auth/refresh', {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) return
    const body = (await response.json()) as { access_token: string }
    useAuthStore.getState().setAuth(body.access_token)
  } catch {
    // Swallow — the next 401 from a REST call will trigger the normal
    // refresh+redirect flow.
  }
}
