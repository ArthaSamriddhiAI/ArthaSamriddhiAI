# Foundation Reference Entry 16.0: SmartLLMRouter Overview

**Topic:** 16 LLM Provider Strategy
**Entry:** 16.0
**Title:** SmartLLMRouter Overview
**Status:** Locked (cluster 1)
**Date:** April 2026
**Author:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cross-references In

- FR Entry 14.0 (C0 Conversational Orchestrator; C0 is the first LLM consumer)
- CP Chunk 1.3 (SmartLLMRouter settings UI)
- All future LLM-consuming components (E1 through E7 evidence agents, S1 synthesis, IC1 sub-roles, A1 challenge layer)

## Cross-references Out

- Principles §6.0 (LLM provider strategy; this entry implements the platform-toggle decision)
- Principles §3.4 (skill.md per agent mechanism; agents reference SmartLLMRouter for LLM access)

---

## 1. Purpose

The SmartLLMRouter is the system's centralised LLM access governance layer. Every LLM call from any component (C0 in cluster 1; E1 through E7 evidence agents in clusters 5-6; S1, IC1, A1 in clusters 7 and 9; future LLM-reasoning components) goes through the SmartLLMRouter. The router handles provider selection, API key management, rate limiting, retries, kill-switch behaviour, and (in v2) per-agent tiering and provider failover.

In cluster 1, the SmartLLMRouter ships with platform-level provider selection: the firm chooses Mistral (free, default) or Claude (paid) at the deployment level, and all LLM calls route to the selected provider. Per-agent tiering and multi-provider failover are deferred to v2.

The router exists for two reasons. First, centralisation: rather than every component owning its own provider client, retry logic, and rate limit handling, those concerns are handled once by the router. Second, governance: the router is the single point where LLM behaviour is observable, controllable, and audit-traceable. The principles document calls this out as a real architectural component, not a thin abstraction.

## 2. Architecture

### 2.1 Router Components

The SmartLLMRouter has four components in cluster 1:

**Provider Configuration.** The current provider selection (Mistral or Claude) and the API keys for each provider. Stored encrypted at rest in the deployment's database (the `llm_provider_config` table). Editable via the settings UI (chunk 1.3, FR Entry 16.0 §6).

**Provider Adapters.** Per-provider HTTP client implementations that translate the router's internal API into the provider's native API. Mistral adapter calls Mistral's chat completions endpoint; Claude adapter calls Anthropic's Messages API. Both adapters expose the same internal interface to the router.

**Call Executor.** The runtime component that takes a router call (prompt + caller identity + parameters), looks up the active provider, calls the provider adapter, handles retries and timeouts, returns the result. The executor is responsible for ensuring every call is observable and audited.

**Telemetry Emitter.** Every LLM call emits a T1 event (per principles document). The telemetry emitter ensures call latency, provider, prompt length, response length, and any failure modes are captured.

### 2.2 Internal API

The router's internal API for LLM calls is uniform across providers:

```python
class LLMCallRequest:
    caller_id: str  # which component is making the call (e.g., "c0_intent_detector")
    prompt: str  # the system + user prompt as a single string, or structured messages
    messages: Optional[list[Message]]  # alternative to prompt; structured turn list
    max_tokens: int  # defaults to provider-appropriate value
    temperature: float  # defaults to 0.0 for deterministic extraction tasks
    response_format: str  # "text" or "json"; affects how the call is constructed

class LLMCallResponse:
    content: str  # the model's response
    provider: str  # which provider was used (mistral, claude)
    model: str  # which specific model was used
    tokens_used: int
    latency_ms: int
    request_id: str  # for audit trace
```

C0's intent detector calls this with `caller_id="c0_intent_detector"`, the templated intent prompt, `temperature=0.0`, `response_format="json"`. The router selects the provider, makes the call, returns the response. C0 parses the JSON and continues.

### 2.3 Provider Selection

Cluster 1 implements platform-level provider selection. The deployment has one active provider at any time (Mistral or Claude); all LLM calls route to that provider. Switching providers requires the CIO to update the configuration via the settings UI; the change takes effect immediately for subsequent calls.

The provider can be switched without restarting the application. The router holds a reference to the configured provider that updates on configuration changes.

## 3. Provider Adapters

### 3.1 Mistral Adapter

Mistral is the cluster 1 default provider for demo stage. The adapter:

- Calls Mistral's chat completions endpoint at `https://api.mistral.ai/v1/chat/completions`.
- Default model: `mistral-small-latest` (the free-tier model with reasonable quality for cluster 1's intent and extraction work).
- Authenticates via Bearer token using the configured Mistral API key.
- Supports JSON response format via the `response_format` parameter.
- Maps Mistral's response structure to the router's `LLMCallResponse` schema.

The Mistral free tier has rate limits (specific quotas vary; the adapter respects them via the rate limiter component). For cluster 1 demo usage with one user at a time, free tier limits are not constraining.

### 3.2 Claude Adapter

Claude is the cluster 1 paid provider option, used when the firm wants higher-quality LLM reasoning. The adapter:

- Calls Anthropic's Messages API at `https://api.anthropic.com/v1/messages`.
- Default model: `claude-sonnet-4-5-20250929` (Sonnet for cost-effectiveness on cluster 1's bounded tasks; Opus is reserved for higher-stakes reasoning in later clusters via per-agent tiering, deferred to v2).
- Authenticates via x-api-key header using the configured Claude API key.
- Supports JSON response format via prompt instruction (Anthropic's API doesn't have a structured response_format parameter; the adapter prompts for JSON and validates the response).
- Maps Anthropic's response structure to the router's `LLMCallResponse` schema.

Claude usage incurs cost per the Anthropic pricing schedule. The deployment's API key is used; cost goes to the firm's Anthropic account.

### 3.3 Adding Future Providers

The adapter pattern supports adding new providers without changing the router internals or the consuming components. To add a future provider (e.g., a self-hosted LLM, a different commercial provider):

1. Implement a new adapter conforming to the same internal interface.
2. Register the adapter in the router's provider registry.
3. Add the provider option to the settings UI.
4. Document the new adapter in this entry's revision history.

The bounded scope of the adapter pattern (just translation between the router's API and the provider's API) keeps the addition cost low.

## 4. Configuration Management

### 4.1 Configuration Storage

The provider configuration lives in the `llm_provider_config` table:

```
llm_provider_config:
  config_id (string, primary key; effectively a singleton row per deployment, but versioned for audit)
  active_provider (enum: mistral, claude)
  mistral_api_key_encrypted (binary; encrypted with deployment-level encryption key)
  claude_api_key_encrypted (binary; encrypted with deployment-level encryption key)
  default_mistral_model (string; default: mistral-small-latest)
  default_claude_model (string; default: claude-sonnet-4-5-20250929)
  rate_limit_calls_per_minute (integer; default 60)
  request_timeout_seconds (integer; default 30)
  updated_at (timestamp)
  updated_by (string, references users)
```

API keys are encrypted at rest using AES-256-GCM with the deployment-level encryption key. The encryption key itself is in the deployment's environment configuration (not in the database). On each LLM call, the router decrypts the key in memory, makes the call, and the key never enters logs.

### 4.2 Configuration Changes

The settings UI (chunk 1.3) is the canonical path for configuration changes. CIO-only access. The flow:

1. CIO navigates to settings page.
2. Selects active provider (Mistral or Claude).
3. Enters or updates API keys.
4. Clicks "Test Connection" to validate the API key works (router makes a small test call with a trivial prompt; success or failure is shown inline).
5. Clicks "Save".
6. Configuration is persisted; T1 emits `llm_provider_configuration_changed` event.

The configuration change takes effect immediately for subsequent LLM calls.

### 4.3 First-Run Configuration

On first run after deployment, no provider is configured. Any LLM call will fail with a clear error: "LLM provider not configured. Please configure in Settings > LLM Provider before using conversational features."

A first-run banner on the CIO's home tree prompts: "Configure your LLM provider to enable conversational features → Settings > LLM Provider." The banner persists until configuration is complete.

C0 (chunk 1.2) handles unconfigured-provider gracefully: the conversation surface is accessible but any user message produces an error response: "LLM features are not configured for this deployment. Please contact your CIO to enable them."

## 5. Rate Limiting and Retry

### 5.1 Per-Provider Rate Limiting

The router enforces a per-deployment rate limit on calls to each provider, defaulting to 60 calls per minute. This is well below either provider's actual rate limits but provides safety against runaway loops or buggy components that might burst-call.

The rate limiter uses a token bucket algorithm. When the bucket is depleted, calls block until tokens are available. For cluster 1 demo usage, the rate limit will rarely be reached.

### 5.2 Retry Logic

LLM calls that fail with a retriable error (rate limit error from provider, transient network failure, 5xx server error) are retried with exponential backoff: 1 second, 2 seconds, 4 seconds, then give up. Three retry attempts maximum.

Calls that fail with a non-retriable error (4xx errors other than 429, malformed responses, authentication failures) are returned immediately to the caller as an error.

### 5.3 Timeouts

Each LLM call has a 30-second timeout (configurable). If the provider doesn't respond within 30 seconds, the call is aborted and treated as a failure. C0's slot extraction is typically sub-3-second; the 30-second ceiling is a safety net for unusually long generation tasks (more relevant in later clusters with reasoning agents).

## 6. Telemetry

The router emits T1 events for every LLM call:

`llm_call_initiated`: emitted at the start of an LLM call. Payload: caller_id, provider, model, prompt_token_count_estimate, request_id.

`llm_call_completed`: emitted on successful completion. Payload: request_id, latency_ms, response_token_count, total_tokens.

`llm_call_failed`: emitted on failure (after retries exhausted). Payload: request_id, failure_type (rate_limit, timeout, auth_error, provider_error, malformed_response), provider.

`llm_provider_configuration_changed`: emitted on config changes. Payload: previous_provider, new_provider, changed_by.

These events feed audit replay (cluster 15) and operational metrics (Doc 4 Operations).

## 7. Kill Switch

The router supports a kill-switch mechanism for emergency LLM disablement. If the firm needs to halt all LLM calls (security incident, cost overrun, provider outage requiring manual intervention), an admin can flip a kill-switch flag in the configuration. With the kill switch active, all LLM calls fail immediately with a "kill switch active" error. C0 falls back to template-driven mode; future LLM-consuming agents handle the kill switch per their own degraded-mode behaviour.

The kill switch is a deployment-level configuration, accessible via an admin endpoint or via the settings UI (with an explicit confirmation dialog given the impact). Activation and deactivation are T1-logged.

## 8. Future Capabilities (Deferred)

Several capabilities are deferred to v2 or beyond, but documented here for architectural completeness:

**Per-agent tiering.** Different agents may use different model tiers (Opus for high-stakes synthesis, Sonnet for evidence agents, Haiku for orchestration). The router will support this via per-caller tier configuration. Cluster 1 implements platform-level tier (one model per provider); per-agent tiering comes later.

**Multi-provider failover.** When the primary provider is unavailable, automatic failover to a secondary provider (with the firm's consent). Cluster 1 has no failover; provider unavailability degrades to template fallback in C0.

**Cost monitoring and budgets.** Real-time cost tracking with configurable per-month budgets that trigger alerts or kill-switch. Cluster 1 captures token counts in T1 telemetry but does not aggregate or alert.

**Prompt caching.** For prompts that repeat (intent detection prompt, the templated portions), Anthropic's prompt caching can reduce cost and latency. Deferred until cost optimisation matters.

**Quality monitoring.** Tracking which provider produces better outputs for which task types, surfaced for tuning decisions. Deferred until enough call history accumulates.

## 9. Acceptance Criteria for Cluster 1

The SmartLLMRouter is considered functional in cluster 1 when:

1. C0's intent detection and slot extraction calls successfully route through the router.
2. Provider selection (Mistral or Claude) via the settings UI takes effect for subsequent calls.
3. API keys are stored encrypted and decrypted only at call time.
4. The "Test Connection" button correctly validates API keys against the selected provider.
5. Rate limiting prevents bursts above the configured threshold.
6. Retries on retriable errors work as specified (3 attempts, exponential backoff).
7. Timeouts on slow provider responses are enforced.
8. The kill switch correctly halts all LLM calls when activated.
9. T1 telemetry captures all LLM lifecycle events with correct payloads.
10. First-run handling: unconfigured deployments produce clear error messages and the CIO sees the configuration banner.

## 10. Open Questions

Whether the rate limit default (60 calls per minute) should be tunable per-deployment via the settings UI is open. Working answer: hardcoded in cluster 1; expose in a future cluster if firms need different defaults.

Whether kill-switch activation should require dual approval (CIO + compliance) is open. Working answer: single CIO approval is enough for demo stage; production may require dual approval for high-stakes ops.

Whether to support a "preview mode" where calls are stubbed (return canned responses) for development without consuming API budget is open. Working answer: not in cluster 1; if needed for development, a separate test mode can be added later.

## 11. Revision History

April 2026 (cluster 1 drafting pass): Initial entry authored. Platform-level toggle, two providers (Mistral, Claude), settings UI integration, rate limiting, retries, kill switch, telemetry all locked. Per-agent tiering and multi-provider failover reserved as deferred.

---

**End of FR Entry 16.0.**
