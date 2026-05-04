import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { Investor } from './investors'
import { apiFetch } from './client'

// Mirrors src/artha/api_v2/c0/schemas.py.

export type ConversationState =
  | 'STATE_INTENT_PENDING'
  | 'STATE_COLLECTING_BASICS'
  | 'STATE_COLLECTING_HOUSEHOLD'
  | 'STATE_COLLECTING_PROFILE'
  | 'STATE_AWAITING_CONFIRMATION'
  | 'STATE_EXECUTING'
  | 'STATE_COMPLETED'
  | 'STATE_ABANDONED'

export type ConversationStatus = 'active' | 'completed' | 'abandoned' | 'error'

export interface MessageRead {
  message_id: string
  sender: 'user' | 'system'
  content: string
  metadata: Record<string, unknown>
  timestamp: string
}

export interface ConversationRead {
  conversation_id: string
  user_id: string
  intent: string | null
  state: ConversationState
  collected_slots: Record<string, unknown>
  status: ConversationStatus
  started_at: string
  last_message_at: string
  completed_at: string | null
  investor_id: string | null
  investor: Investor | null
  messages: MessageRead[]
}

export interface ConversationSummary {
  conversation_id: string
  intent: string | null
  state: ConversationState
  status: ConversationStatus
  started_at: string
  last_message_at: string
  preview: string
}

export class ConversationError extends Error {
  readonly status: number
  readonly problem?: Record<string, unknown>

  constructor(message: string, status: number, problem?: Record<string, unknown>) {
    super(message)
    this.name = 'ConversationError'
    this.status = status
    this.problem = problem
  }
}

async function _readJson<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = (await r.json().catch(() => ({}))) as Record<string, unknown>
    const detail = (body.detail as string | undefined) ?? `Request failed (${r.status})`
    throw new ConversationError(detail, r.status, body)
  }
  return (await r.json()) as T
}

// ---- queries ----

export function useConversationsList() {
  return useQuery<ConversationSummary[]>({
    queryKey: ['conversations'],
    queryFn: async () => {
      const r = await apiFetch('/api/v2/conversations')
      const body = await _readJson<{ conversations: ConversationSummary[] }>(r)
      return body.conversations
    },
  })
}

export function useConversation(conversationId: string | undefined) {
  return useQuery<ConversationRead>({
    queryKey: ['conversations', conversationId],
    enabled: Boolean(conversationId),
    queryFn: async () => {
      const r = await apiFetch(`/api/v2/conversations/${conversationId}`)
      return _readJson<ConversationRead>(r)
    },
  })
}

// ---- mutations ----

export function useStartConversation() {
  const qc = useQueryClient()
  return useMutation<ConversationRead, ConversationError, void>({
    mutationFn: async () => {
      const r = await apiFetch('/api/v2/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      })
      return _readJson<ConversationRead>(r)
    },
    onSuccess: (convo) => {
      qc.setQueryData(['conversations', convo.conversation_id], convo)
      void qc.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}

export function usePostMessage(conversationId: string) {
  const qc = useQueryClient()
  return useMutation<ConversationRead, ConversationError, string>({
    mutationFn: async (content) => {
      const r = await apiFetch(
        `/api/v2/conversations/${conversationId}/messages`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content }),
        },
      )
      return _readJson<ConversationRead>(r)
    },
    onSuccess: (convo) => {
      qc.setQueryData(['conversations', conversationId], convo)
      void qc.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}

export function useConfirmAction(conversationId: string) {
  const qc = useQueryClient()
  return useMutation<ConversationRead, ConversationError, void>({
    mutationFn: async () => {
      const r = await apiFetch(
        `/api/v2/conversations/${conversationId}/confirm`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: '{}',
        },
      )
      return _readJson<ConversationRead>(r)
    },
    onSuccess: (convo) => {
      qc.setQueryData(['conversations', conversationId], convo)
      void qc.invalidateQueries({ queryKey: ['conversations'] })
      void qc.invalidateQueries({ queryKey: ['investors'] })
    },
  })
}

export function useCancelConversation(conversationId: string) {
  const qc = useQueryClient()
  return useMutation<ConversationRead, ConversationError, void>({
    mutationFn: async () => {
      const r = await apiFetch(
        `/api/v2/conversations/${conversationId}/cancel`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: '{}',
        },
      )
      return _readJson<ConversationRead>(r)
    },
    onSuccess: (convo) => {
      qc.setQueryData(['conversations', conversationId], convo)
      void qc.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}
