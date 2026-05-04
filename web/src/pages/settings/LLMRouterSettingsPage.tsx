import { Eye, EyeOff, Loader2, Shield, ShieldOff } from 'lucide-react'
import { useEffect, useState } from 'react'

import {
  LLMConfigError,
  type LLMConfigRead,
  type ProviderName,
  type TestConnectionResponse,
  useKillSwitch,
  useLLMConfig,
  useTestConnection,
  useUpdateLLMConfig,
} from '../../api/llm'
import { cn } from '../../lib/cn'

// Per chunk plan §1.3 §scope_in:
// "Settings UI at /app/cio/settings/llm-router:
//   - Provider selection: radio buttons for Mistral and Claude.
//   - API key entry: masked text inputs with show/hide toggle.
//   - Test Connection button: green check / red error inline.
//   - Save button: persists changes; confirmation toast.
//   - Kill switch section: visible toggle with confirmation dialog."
//
// CIO-only — the route guard ensures non-CIO callers never reach this page.

export function LLMRouterSettingsPage() {
  const configQuery = useLLMConfig()
  if (configQuery.isLoading) {
    return (
      <div className="p-8 max-w-3xl flex items-center gap-2 text-sm text-gray-500">
        <Loader2 size={16} className="animate-spin" /> Loading LLM configuration…
      </div>
    )
  }
  if (configQuery.error || !configQuery.data) {
    return (
      <div className="p-8 max-w-3xl">
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load LLM configuration.{' '}
          {configQuery.error instanceof Error ? configQuery.error.message : ''}
        </div>
      </div>
    )
  }
  return <LLMRouterSettingsForm config={configQuery.data} />
}


function LLMRouterSettingsForm({ config }: { config: LLMConfigRead }) {
  const [activeProvider, setActiveProvider] = useState<ProviderName>(
    (config.active_provider ?? 'mistral') as ProviderName,
  )
  const [mistralKey, setMistralKey] = useState('')
  const [claudeKey, setClaudeKey] = useState('')
  const [showMistralKey, setShowMistralKey] = useState(false)
  const [showClaudeKey, setShowClaudeKey] = useState(false)
  const [savedToast, setSavedToast] = useState(false)
  const [confirmKillSwitch, setConfirmKillSwitch] = useState(false)
  const [testResult, setTestResult] = useState<TestConnectionResponse | null>(null)

  const updateMutation = useUpdateLLMConfig()
  const testMutation = useTestConnection()
  const killSwitchMutation = useKillSwitch()

  // Reset key inputs after the saved-toast disappears so the CIO doesn't
  // accidentally re-submit the same plaintext on a subsequent save.
  useEffect(() => {
    if (!savedToast) return
    const t = window.setTimeout(() => setSavedToast(false), 3000)
    return () => window.clearTimeout(t)
  }, [savedToast])

  const handleSave = () => {
    setTestResult(null)
    updateMutation.mutate(
      {
        active_provider: activeProvider,
        mistral_api_key: mistralKey || undefined,
        claude_api_key: claudeKey || undefined,
      },
      {
        onSuccess: () => {
          setMistralKey('')
          setClaudeKey('')
          setSavedToast(true)
        },
      },
    )
  }

  const handleTestConnection = () => {
    setTestResult(null)
    const apiKey =
      activeProvider === 'mistral'
        ? mistralKey || undefined
        : claudeKey || undefined
    testMutation.mutate(
      { provider: activeProvider, api_key: apiKey },
      { onSuccess: (r) => setTestResult(r) },
    )
  }

  const validationCode =
    updateMutation.error instanceof LLMConfigError
      ? updateMutation.error.code
      : undefined

  return (
    <div className="p-8 max-w-3xl">
      <h1 className="text-2xl font-semibold text-gray-900">LLM Provider</h1>
      <p className="text-sm text-gray-500 mt-1">
        Choose which LLM powers conversational features. API keys are stored
        encrypted at rest; only the first four characters are shown after saving.
      </p>

      {savedToast && (
        <div className="mt-4 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          LLM configuration saved.
        </div>
      )}

      {/* ---------- provider + keys ---------- */}
      <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-4">
          Active Provider
        </h2>
        <div className="space-y-3">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="radio"
              name="active_provider"
              value="mistral"
              checked={activeProvider === 'mistral'}
              onChange={() => setActiveProvider('mistral')}
              className="mt-1"
            />
            <div>
              <div className="text-sm font-medium text-gray-900">Mistral</div>
              <div className="text-xs text-gray-500">
                Free tier with reasonable quality. Default for demos.
              </div>
            </div>
          </label>
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="radio"
              name="active_provider"
              value="claude"
              checked={activeProvider === 'claude'}
              onChange={() => setActiveProvider('claude')}
              className="mt-1"
            />
            <div>
              <div className="text-sm font-medium text-gray-900">Claude</div>
              <div className="text-xs text-gray-500">
                Higher-quality reasoning. Anthropic API charges per call.
              </div>
            </div>
          </label>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4">
          <ApiKeyField
            label="Mistral API Key"
            placeholder={
              config.mistral_api_key_masked
                ? `Currently set: ${config.mistral_api_key_masked} (enter a new key to replace)`
                : 'Enter Mistral API key…'
            }
            value={mistralKey}
            show={showMistralKey}
            onChange={setMistralKey}
            onToggleShow={() => setShowMistralKey((v) => !v)}
            errorCode={
              validationCode === 'missing_mistral_api_key' ? validationCode : undefined
            }
          />
          <ApiKeyField
            label="Claude API Key"
            placeholder={
              config.claude_api_key_masked
                ? `Currently set: ${config.claude_api_key_masked} (enter a new key to replace)`
                : 'Enter Claude API key…'
            }
            value={claudeKey}
            show={showClaudeKey}
            onChange={setClaudeKey}
            onToggleShow={() => setShowClaudeKey((v) => !v)}
            errorCode={
              validationCode === 'missing_claude_api_key' ? validationCode : undefined
            }
          />
        </div>

        {testResult && <TestResultRow result={testResult} />}

        {updateMutation.error && !validationCode && (
          <div className="mt-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {updateMutation.error.message}
          </div>
        )}

        <div className="mt-6 flex gap-3">
          <button
            type="button"
            onClick={handleTestConnection}
            disabled={testMutation.isPending}
            className={cn(
              'rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700',
              'hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50',
            )}
          >
            {testMutation.isPending ? 'Testing…' : 'Test Connection'}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={updateMutation.isPending}
            className={cn(
              'rounded-md px-5 py-2 text-sm font-medium text-white shadow-sm',
              'disabled:cursor-not-allowed disabled:opacity-50',
            )}
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            {updateMutation.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </section>

      {/* ---------- status ---------- */}
      <section className="mt-6 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="text-base font-semibold text-gray-900 mb-3">Status</h2>
        <dl className="grid grid-cols-2 gap-y-2 text-sm">
          <dt className="text-gray-500">Configured</dt>
          <dd className="text-gray-900 font-medium">
            {config.is_configured ? 'Yes' : 'No'}
          </dd>
          <dt className="text-gray-500">Active provider</dt>
          <dd className="text-gray-900 font-medium">
            {config.active_provider ?? '—'}
          </dd>
          <dt className="text-gray-500">Default Mistral model</dt>
          <dd className="text-gray-900 font-mono text-xs">
            {config.default_mistral_model}
          </dd>
          <dt className="text-gray-500">Default Claude model</dt>
          <dd className="text-gray-900 font-mono text-xs">
            {config.default_claude_model}
          </dd>
          <dt className="text-gray-500">Rate limit</dt>
          <dd className="text-gray-900 font-medium">
            {config.rate_limit_calls_per_minute} calls/minute
          </dd>
          <dt className="text-gray-500">Request timeout</dt>
          <dd className="text-gray-900 font-medium">
            {config.request_timeout_seconds} seconds
          </dd>
          <dt className="text-gray-500">Last updated</dt>
          <dd className="text-gray-900">
            {config.updated_at
              ? new Date(config.updated_at).toLocaleString()
              : '—'}
            {config.updated_by ? ` · by ${config.updated_by}` : ''}
          </dd>
        </dl>
      </section>

      {/* ---------- kill switch ---------- */}
      <section
        className={cn(
          'mt-6 rounded-lg border p-6 shadow-sm',
          config.kill_switch_active
            ? 'border-red-300 bg-red-50'
            : 'border-gray-200 bg-white',
        )}
      >
        <div className="flex items-start gap-3">
          {config.kill_switch_active ? (
            <ShieldOff size={20} className="text-red-600 mt-0.5" />
          ) : (
            <Shield size={20} className="text-gray-700 mt-0.5" />
          )}
          <div className="flex-1">
            <h2 className="text-base font-semibold text-gray-900">
              Kill switch
            </h2>
            <p className="text-sm text-gray-700 mt-1">
              {config.kill_switch_active
                ? 'All LLM calls are halted firm-wide. C0 conversational features are disabled.'
                : 'When activated, all LLM calls fail immediately. Use only in emergencies (security incident, cost overrun).'}
            </p>

            {confirmKillSwitch && (
              <div className="mt-3 rounded-md border border-yellow-300 bg-yellow-50 p-3">
                <p className="text-sm text-yellow-900">
                  Activate the kill switch? All LLM calls firm-wide will fail
                  until you deactivate it.
                </p>
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      killSwitchMutation.mutate('activate', {
                        onSuccess: () => setConfirmKillSwitch(false),
                      })
                    }}
                    className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700"
                  >
                    Activate kill switch
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmKillSwitch(false)}
                    className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <div className="mt-3 flex gap-2">
              {config.kill_switch_active ? (
                <button
                  type="button"
                  onClick={() => killSwitchMutation.mutate('deactivate')}
                  disabled={killSwitchMutation.isPending}
                  className={cn(
                    'rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white',
                    'hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-50',
                  )}
                >
                  {killSwitchMutation.isPending
                    ? 'Deactivating…'
                    : 'Deactivate kill switch'}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmKillSwitch(true)}
                  disabled={killSwitchMutation.isPending || confirmKillSwitch}
                  className={cn(
                    'rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700',
                    'hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50',
                  )}
                >
                  Activate kill switch…
                </button>
              )}
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------


const apiKeyInputClass = cn(
  'w-full rounded-md border border-gray-300 px-3 py-2 text-sm font-mono pr-10',
  'focus:outline-none focus:ring-2 focus:ring-offset-1',
)


function ApiKeyField({
  label,
  placeholder,
  value,
  show,
  onChange,
  onToggleShow,
  errorCode,
}: {
  label: string
  placeholder: string
  value: string
  show: boolean
  onChange: (v: string) => void
  onToggleShow: () => void
  errorCode?: string
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">
        {label}
      </label>
      <div className="relative">
        <input
          type={show ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={apiKeyInputClass}
          autoComplete="new-password"
        />
        <button
          type="button"
          onClick={onToggleShow}
          className="absolute inset-y-0 right-0 flex items-center px-3 text-gray-500 hover:text-gray-700"
          aria-label={show ? 'Hide key' : 'Show key'}
        >
          {show ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      </div>
      {errorCode && (
        <p className="mt-1 text-xs text-red-600">
          {label} required for the selected provider.
        </p>
      )}
    </div>
  )
}


function TestResultRow({ result }: { result: TestConnectionResponse }) {
  return (
    <div
      className={cn(
        'mt-4 rounded-md border px-4 py-3 text-sm',
        result.success
          ? 'border-green-200 bg-green-50 text-green-800'
          : 'border-red-200 bg-red-50 text-red-700',
      )}
    >
      <div className="font-medium">
        {result.success
          ? `Connection successful (${result.provider})`
          : `Connection failed (${result.provider})`}
      </div>
      <div className="mt-1 text-xs">{result.detail}</div>
      {result.latency_ms != null && (
        <div className="mt-1 text-xs opacity-75">
          Latency: {result.latency_ms} ms
        </div>
      )}
    </div>
  )
}
