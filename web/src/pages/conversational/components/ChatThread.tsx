import { useEffect, useRef } from 'react'

import type { ConversationRead, MessageRead } from '../../../api/conversations'
import { cn } from '../../../lib/cn'

import { ConfirmationCard } from './ConfirmationCard'
import { SuccessCard } from './SuccessCard'

// Per FR Entry 14.0 §4.1 — chat thread layout. User messages right-aligned,
// system messages left-aligned. Some system messages render as rich
// content cards (confirmation summary, success state) instead of plain
// text. Cluster 1 picks the card by inspecting the metadata flag the
// backend stamps on the message: `card === "success"`. The confirmation
// card is selected by conversation state instead — it always renders the
// LATEST summary, not whichever message body might have shipped earlier.

interface Props {
  conversation: ConversationRead
  isThinking: boolean
}

export function ChatThread({ conversation, isThinking }: Props) {
  const ref = useRef<HTMLDivElement | null>(null)

  // Auto-scroll on new messages so the user always sees the latest reply.
  useEffect(() => {
    if (!ref.current) return
    ref.current.scrollTop = ref.current.scrollHeight
  }, [conversation.messages.length, isThinking])

  const lastSystemIndex = findLastSystemIndex(conversation.messages)

  return (
    <div
      ref={ref}
      className="flex-1 overflow-auto px-6 py-4 bg-gray-50"
      aria-label="Conversation thread"
    >
      <div className="max-w-3xl mx-auto space-y-4">
        {conversation.messages.map((m, i) => (
          <MessageRow
            key={m.message_id}
            message={m}
            // Render the success card only on the latest system message
            // that's tagged as the success card — earlier ones (if any)
            // fall through to plain text.
            renderSuccessCard={
              i === lastSystemIndex
              && m.metadata?.card === 'success'
              && conversation.investor != null
            }
            conversation={conversation}
          />
        ))}
        {/* Confirmation card pinned beneath the thread when state is awaiting */}
        {conversation.state === 'STATE_AWAITING_CONFIRMATION' && (
          <ConfirmationCard conversation={conversation} />
        )}
        {isThinking && <ThinkingIndicator />}
      </div>
    </div>
  )
}


function findLastSystemIndex(messages: MessageRead[]): number {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].sender === 'system') return i
  }
  return -1
}


function MessageRow({
  message,
  renderSuccessCard,
  conversation,
}: {
  message: MessageRead
  renderSuccessCard: boolean
  conversation: ConversationRead
}) {
  if (message.sender === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-lg px-4 py-2 text-sm text-white shadow-sm whitespace-pre-line"
          style={{ backgroundColor: 'var(--color-primary)' }}>
          {message.content}
        </div>
      </div>
    )
  }

  // System message
  if (renderSuccessCard && conversation.investor) {
    return <SuccessCard investor={conversation.investor} />
  }

  const isFallback = message.metadata?.fallback_mode === true
  return (
    <div className="flex justify-start">
      <div
        className={cn(
          'max-w-[75%] rounded-lg px-4 py-2 text-sm shadow-sm whitespace-pre-line',
          isFallback
            ? 'bg-amber-50 text-amber-900 border border-amber-200'
            : 'bg-white text-gray-900 border border-gray-200',
        )}
      >
        {message.content}
      </div>
    </div>
  )
}


function ThinkingIndicator() {
  // Three-dot animation. Tailwind's animate-pulse is good enough for
  // cluster 1 — a future cluster can swap in a custom keyframe.
  return (
    <div className="flex justify-start">
      <div className="rounded-lg px-4 py-2 text-sm bg-white border border-gray-200 text-gray-500">
        <span className="inline-flex items-center gap-1">
          <span className="font-medium">C0 is thinking</span>
          <span className="flex gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-gray-400 animate-pulse"></span>
            <span
              className="h-1.5 w-1.5 rounded-full bg-gray-400 animate-pulse"
              style={{ animationDelay: '120ms' }}
            ></span>
            <span
              className="h-1.5 w-1.5 rounded-full bg-gray-400 animate-pulse"
              style={{ animationDelay: '240ms' }}
            ></span>
          </span>
        </span>
      </div>
    </div>
  )
}
