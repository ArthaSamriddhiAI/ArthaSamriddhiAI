import { Link } from '@tanstack/react-router'
import { AlertCircle, ShieldOff } from 'lucide-react'

import { useLLMConfig, useLLMStatus } from '../api/llm'
import { useAuthStore } from '../auth/store'

// First-run banner per FR Entry 16.0 §4.3 + chunk plan §1.3 §scope_in:
// "First-run banner on CIO home tree: visible until LLM provider is
//  configured; links to the settings page."
//
// Renders only for the CIO role; other roles never see it.
//
// Also doubles as the kill-switch visibility flag — when the kill switch
// is active, a different banner surfaces so the CIO can't forget to flip
// it back.

export function LLMConfigBanner() {
  const role = useAuthStore((s) => s.user?.role)
  const status = useLLMStatus({ enabled: role === 'cio' })
  // Pull config so we can also surface the kill-switch state inline. The
  // CIO already has read perm so this is cheap; non-CIOs hit the early
  // return below before the query runs.
  const config = useLLMConfig()

  if (role !== 'cio') return null
  // Don't flash a banner before the first response; if anything errors,
  // also stay silent so the home tree isn't littered with red.
  if (status.isLoading || status.isError) return null

  // Kill switch wins — it's a louder operational signal than first-run.
  if (config.data?.kill_switch_active) {
    return (
      <div className="mb-4 rounded-md border border-red-300 bg-red-50 px-4 py-3">
        <div className="flex items-start gap-3">
          <ShieldOff size={18} className="text-red-600 mt-0.5" />
          <div className="flex-1 text-sm">
            <div className="font-semibold text-red-900">
              LLM kill switch is active
            </div>
            <div className="text-red-800">
              All LLM calls firm-wide are halted. Conversational features are
              disabled until you deactivate the switch.
            </div>
            <Link
              to="/settings/llm-router"
              className="mt-1 inline-block text-xs font-medium text-red-700 hover:text-red-800 underline"
            >
              Manage kill switch →
            </Link>
          </div>
        </div>
      </div>
    )
  }

  if (status.data?.is_configured) return null

  return (
    <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 px-4 py-3">
      <div className="flex items-start gap-3">
        <AlertCircle size={18} className="text-amber-700 mt-0.5" />
        <div className="flex-1 text-sm">
          <div className="font-semibold text-amber-900">
            LLM provider not configured
          </div>
          <div className="text-amber-800">
            Configure your LLM provider to enable conversational features.
          </div>
          <Link
            to="/settings/llm-router"
            className="mt-1 inline-block text-xs font-medium text-amber-800 hover:text-amber-900 underline"
          >
            Open Settings → LLM Provider
          </Link>
        </div>
      </div>
    </div>
  )
}
