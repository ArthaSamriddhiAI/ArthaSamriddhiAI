import { create } from 'zustand'

// Per-session SSE connection state. Drives the TopBar status indicator.
//
// State machine:
//   connecting  → initial / during reconnect attempt
//   connected   → connection_established or recent heartbeat received
//   reconnecting → server-initiated close or transient network error;
//                  underlying library is auto-retrying
//   disconnected → controller aborted (logout, terminate signal, unmount)
//
// State transitions are driven by useSSEConnection (the hook). Components
// (SSEStatusIndicator) are read-only consumers.

export type SSEConnectionState =
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'disconnected'

interface SSEStoreState {
  state: SSEConnectionState
  setState: (state: SSEConnectionState) => void
}

export const useSSEStore = create<SSEStoreState>((set) => ({
  state: 'connecting',
  setState: (state) => set({ state }),
}))
