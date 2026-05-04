import { Loader2, MessageSquarePlus } from 'lucide-react'

import {
  type ConversationSummary,
  useConversationsList,
} from '../../../api/conversations'
import { cn } from '../../../lib/cn'

// Per FR Entry 14.0 §4.1 + §8 working-answer:
//
//   "ship a basic past-conversations list in cluster 1 (with conversation_id,
//    intent, status, started_at, click-to-view) because the persistence is
//    in place anyway and surfacing it is small UI work."
//
// Cluster 1 ships exactly that — collapsible-ish sidebar that highlights
// the active conversation and offers a "New conversation" CTA.

interface Props {
  selectedId: string | null
  onSelect(id: string): void
  onStartNew(): void
  isStartingNew: boolean
}


export function ConversationsSidebar({
  selectedId,
  onSelect,
  onStartNew,
  isStartingNew,
}: Props) {
  const list = useConversationsList()

  return (
    <aside className="w-72 shrink-0 border-r border-gray-200 bg-white flex flex-col">
      <div className="px-4 py-3 border-b border-gray-200">
        <button
          type="button"
          onClick={onStartNew}
          disabled={isStartingNew}
          className={cn(
            'w-full inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-white',
            'disabled:cursor-not-allowed disabled:opacity-60',
          )}
          style={{ backgroundColor: 'var(--color-primary)' }}
        >
          {isStartingNew ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <MessageSquarePlus size={14} />
          )}
          New conversation
        </button>
      </div>
      <div className="flex-1 overflow-auto py-2">
        {list.isLoading && (
          <div className="px-4 text-xs text-gray-500">Loading…</div>
        )}
        {list.error && (
          <div className="px-4 text-xs text-red-600">
            Failed to load past conversations.
          </div>
        )}
        {(list.data ?? []).map((c) => (
          <SidebarRow
            key={c.conversation_id}
            row={c}
            active={c.conversation_id === selectedId}
            onClick={() => onSelect(c.conversation_id)}
          />
        ))}
        {!list.isLoading && (list.data ?? []).length === 0 && (
          <div className="px-4 text-xs text-gray-400 mt-2">
            No past conversations yet.
          </div>
        )}
      </div>
    </aside>
  )
}


function SidebarRow({
  row,
  active,
  onClick,
}: {
  row: ConversationSummary
  active: boolean
  onClick: () => void
}) {
  const subtitle = row.intent ? row.intent.replace(/_/g, ' ') : 'unclassified'
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'w-full text-left px-4 py-2.5 transition-colors',
        active ? 'bg-gray-100' : 'hover:bg-gray-50',
      )}
    >
      <div className="text-sm text-gray-900 truncate">
        {row.preview || '(empty conversation)'}
      </div>
      <div className="text-xs text-gray-500 capitalize mt-0.5">
        {subtitle} · {row.status}
      </div>
    </button>
  )
}
