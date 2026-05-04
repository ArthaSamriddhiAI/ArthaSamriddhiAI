import { Send } from 'lucide-react'
import { useEffect, useState } from 'react'

import {
  useConversation,
  usePostMessage,
  useStartConversation,
} from '../../api/conversations'
import { cn } from '../../lib/cn'

import { ChatThread } from './components/ChatThread'
import { ConversationsSidebar } from './components/ConversationsSidebar'

// Per chunk plan §1.2 §scope_in:
//   "C0 chat UI at /app/<role>/conversational:
//     - Standard chat layout: thread on top, input box at bottom.
//     - Send button + Enter-to-send.
//     - 'C0 is thinking…' typing indicator during LLM calls.
//     - Past conversations sidebar (collapsible)."
//
// Cluster 1 ships the advisor flow only; the route guard ensures only the
// advisor reaches this page. The shell layout is left unchanged
// (AppShell renders sidebar + topbar above this page).
//
// Persistence is server-side: the active conversation_id lives in
// component state for the duration of the session; navigating away and
// back resumes via the conversations list.

export function ConversationalPage() {
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  const startMutation = useStartConversation()
  const conversationQuery = useConversation(activeConversationId ?? undefined)
  const postMessage = usePostMessage(activeConversationId ?? '')

  // On mount, allocate a fresh conversation if none is selected. This
  // matches FR Entry 14.0 §3.2: "starting a new session shows a fresh
  // chat surface, with prior conversations accessible from a 'Past
  // Conversations' list".
  useEffect(() => {
    if (activeConversationId !== null) return
    if (startMutation.isPending) return
    startMutation.mutate(undefined, {
      onSuccess: (convo) => setActiveConversationId(convo.conversation_id),
    })
    // We deliberately depend only on the gate variables; mutate() is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeConversationId, startMutation.isPending])

  const conversation = conversationQuery.data ?? null
  const status = conversation?.status ?? 'active'
  const isTerminalStatus = status !== 'active'
  const isThinking = postMessage.isPending

  const handleSend = () => {
    if (!activeConversationId) return
    const trimmed = draft.trim()
    if (!trimmed) return
    setDraft('')
    postMessage.mutate(trimmed)
  }

  const handleStartNew = () => {
    setActiveConversationId(null)
    setDraft('')
  }

  return (
    <div className="h-full flex">
      <ConversationsSidebar
        selectedId={activeConversationId}
        onSelect={(id) => {
          setActiveConversationId(id)
          setDraft('')
        }}
        onStartNew={handleStartNew}
        isStartingNew={startMutation.isPending}
      />
      <div className="flex-1 flex flex-col min-w-0">
        <ChatHeader conversation={conversation} />
        {conversation ? (
          <ChatThread conversation={conversation} isThinking={isThinking} />
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-gray-500">
            {startMutation.isPending
              ? 'Starting conversation…'
              : 'Select a conversation or start a new one.'}
          </div>
        )}
        {isTerminalStatus ? (
          <TerminalBanner status={status} onStartNew={handleStartNew} />
        ) : (
          <ChatInput
            value={draft}
            onChange={setDraft}
            onSend={handleSend}
            disabled={!activeConversationId || isThinking}
          />
        )}
      </div>
    </div>
  )
}


function ChatHeader({
  conversation,
}: {
  conversation: import('../../api/conversations').ConversationRead | null
}) {
  if (!conversation) {
    return (
      <header className="h-12 border-b border-gray-200 bg-white px-6 flex items-center text-sm text-gray-500">
        Conversational onboarding
      </header>
    )
  }
  const intentLabel = conversation.intent
    ? conversation.intent.replace(/_/g, ' ')
    : 'detecting intent…'
  return (
    <header className="h-12 border-b border-gray-200 bg-white px-6 flex items-center justify-between">
      <div className="text-sm text-gray-700">
        <span className="font-medium">Conversational onboarding</span>
        <span className="mx-2 text-gray-300">·</span>
        <span className="capitalize text-gray-500">{intentLabel}</span>
      </div>
      <StatusPill status={conversation.status} />
    </header>
  )
}


function StatusPill({ status }: { status: string }) {
  const cls = cn(
    'inline-block rounded-full px-2 py-0.5 text-xs font-medium',
    status === 'active' && 'bg-blue-100 text-blue-800',
    status === 'completed' && 'bg-green-100 text-green-800',
    status === 'abandoned' && 'bg-gray-100 text-gray-700',
    status === 'error' && 'bg-red-100 text-red-700',
  )
  return <span className={cls}>{status}</span>
}


function ChatInput({
  value,
  onChange,
  onSend,
  disabled,
}: {
  value: string
  onChange: (v: string) => void
  onSend: () => void
  disabled: boolean
}) {
  return (
    <div className="border-t border-gray-200 bg-white px-6 py-3">
      <div className="max-w-3xl mx-auto flex gap-2 items-end">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            // Per chunk plan §scope_in: Enter sends, Shift+Enter newline.
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              if (!disabled) onSend()
            }
          }}
          disabled={disabled}
          placeholder="Tell C0 what you want to do — e.g., onboard a new client called Rajesh"
          rows={2}
          className={cn(
            'flex-1 resize-none rounded-md border border-gray-300 px-3 py-2 text-sm',
            'focus:outline-none focus:ring-2 focus:ring-offset-1',
            'disabled:bg-gray-50 disabled:cursor-not-allowed',
          )}
        />
        <button
          type="button"
          onClick={onSend}
          disabled={disabled || !value.trim()}
          aria-label="Send message"
          className={cn(
            'inline-flex items-center gap-1 rounded-md px-4 py-2 text-sm font-medium text-white',
            'disabled:cursor-not-allowed disabled:opacity-50',
          )}
          style={{ backgroundColor: 'var(--color-primary)' }}
        >
          <Send size={14} />
          Send
        </button>
      </div>
    </div>
  )
}


function TerminalBanner({
  status,
  onStartNew,
}: {
  status: string
  onStartNew: () => void
}) {
  return (
    <div className="border-t border-gray-200 bg-gray-50 px-6 py-3">
      <div className="max-w-3xl mx-auto flex items-center justify-between">
        <div className="text-sm text-gray-600">
          {status === 'completed'
            ? 'Conversation complete — the investor record has been created.'
            : status === 'abandoned'
              ? 'Conversation cancelled.'
              : 'Conversation ended.'}
        </div>
        <button
          type="button"
          onClick={onStartNew}
          className="rounded-md px-3 py-1.5 text-xs font-medium text-white shadow-sm"
          style={{ backgroundColor: 'var(--color-primary)' }}
        >
          Start a new conversation
        </button>
      </div>
    </div>
  )
}
