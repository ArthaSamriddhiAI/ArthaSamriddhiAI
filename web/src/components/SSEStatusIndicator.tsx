import { useSSEStore, type SSEConnectionState } from '../sse/store'
import { cn } from '../lib/cn'

// 3-state visual per chunk plan §scope_in:
//   green  = connected and heartbeating
//   yellow = reconnecting
//   red    = disconnected
//
// "Connecting" (initial) renders as yellow + pulse so the user sees
// something is happening. The dot's title attribute carries the human-
// readable label for accessibility / hover.

const STATE_STYLE: Record<
  SSEConnectionState,
  { color: string; label: string; pulse: boolean }
> = {
  connecting: { color: 'bg-yellow-500', label: 'Connecting…', pulse: true },
  connected: { color: 'bg-green-500', label: 'Connected', pulse: false },
  reconnecting: {
    color: 'bg-yellow-500',
    label: 'Reconnecting…',
    pulse: true,
  },
  disconnected: { color: 'bg-red-500', label: 'Disconnected', pulse: false },
}

export function SSEStatusIndicator() {
  const state = useSSEStore((s) => s.state)
  const { color, label, pulse } = STATE_STYLE[state]
  return (
    <div
      className={cn(
        'w-2.5 h-2.5 rounded-full',
        color,
        pulse && 'animate-pulse',
      )}
      title={`Real-time channel: ${label}`}
      aria-label={`Real-time connection: ${label}`}
      role="status"
    />
  )
}
