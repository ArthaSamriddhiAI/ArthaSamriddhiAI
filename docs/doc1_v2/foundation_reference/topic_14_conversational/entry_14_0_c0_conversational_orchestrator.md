# Foundation Reference Entry 14.0: C0 Conversational Orchestrator

**Topic:** 14 Conversational and Notification
**Entry:** 14.0
**Title:** C0 Conversational Orchestrator
**Status:** Locked partial (cluster 1 ships investor onboarding intent only; other intents accumulate in subsequent clusters)
**Date:** April 2026
**Author:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cross-references In

- FR Entry 10.7 (Canonical Entity Schemas; C0 produces Investor records)
- FR Entry 11.1 (I0 Active Layer; C0 calls enrichment after investor creation)
- FR Entry 16.0 (SmartLLMRouter; C0 calls LLM via the router for intent and slot extraction)
- CP Chunk 1.2 (conversational onboarding chunk)
- Future cluster references (cluster 5 case opening intent; cluster 11 alert response intent; cluster 14 briefing request intent)

## Cross-references Out

- FR Entry 16.0 (SmartLLMRouter; C0's LLM dependency)
- FR Entry 17.1 (JWT/Session; C0 conversations are authenticated)

---

## 1. Purpose

The C0 Conversational Orchestrator is the natural-language interface to Samriddhi AI. Where the form-based UI surfaces require the advisor to navigate to specific routes and fill structured forms, C0 lets the advisor express intent in natural language and have the system handle the specifics. Over the system's lifetime, C0 supports many intents (onboarding, case opening, alert response, briefing, general queries); cluster 1 ships the investor onboarding intent as the first.

C0 in cluster 1 uses a bounded LLM scope (Option 3 from the cluster 1 ideation log §5): real LLM for intent detection on the first message and slot extraction from free-text answers, with a state machine driving the conversation flow. This pattern is production-accurate (a real LLM is doing real natural-language work) and demo-safe (the LLM cannot go off-topic because it only sees scoped intent and extraction prompts).

The architectural principle: C0 is bounded by structure but powered by an LLM. The structure is the state machine that knows what fields it needs to collect and what the next question should be. The power is the LLM that understands free-text input and extracts structured information from it.

## 2. Architecture

### 2.1 Components of C0

C0 has four components:

**Intent Detector.** Receives the user's first message in a conversation and classifies the intent. In cluster 1, the recognised intents are: investor_onboarding, case_opening, alert_response, briefing_request, general_question. Only investor_onboarding is fully implemented; the others return a "not yet implemented" template response. As later clusters ship the corresponding capabilities, the intent detector and dispatcher add real handlers.

**Conversation State Machine.** Once an intent is detected, the state machine takes over conversation flow. For investor_onboarding, the state machine knows it needs to collect the canonical investor fields (per FR Entry 10.7 §2.1) and tracks which fields are still needed. The state machine produces the next prompt to send to the user.

**Slot Extractor.** Receives free-text user responses and extracts structured field values via LLM call. The extractor knows what fields the state machine is currently expecting and prompts the LLM specifically for those fields. The LLM returns structured JSON; if extraction is partial or malformed, the state machine falls back to direct prompts.

**Action Executor.** Once all required fields are collected, the action executor performs the actual operation (creating the investor record, calling I0 enrichment) using the same backend services that the form-based path uses.

### 2.2 Conversation Flow for Investor Onboarding

1. **User initiates.** User opens the C0 chat interface and types: "I want to onboard a new client called Rajesh."

2. **Intent detection.** C0 sends to LLM: a templated prompt asking to classify intent from the candidate set, with the user's message. LLM returns `investor_onboarding`. C0 also extracts any slot information from the first message; in this example, "Rajesh" maps to the partial name field.

3. **State machine starts.** The state machine for investor_onboarding initialises with one slot already filled (name = "Rajesh") and acknowledges this in the next prompt.

4. **Templated next-prompt.** C0 sends user: "Got it. I'll help you onboard Rajesh. What's his email and phone number?" (The state machine bundles related fields in the same prompt where natural.)

5. **Slot extraction.** User types: "rajesh.kumar@example.com and 9876543210". C0 sends to LLM: a prompt asking to extract email and phone from the user's response, returning structured JSON. LLM returns `{"email": "rajesh.kumar@example.com", "phone": "+919876543210"}`. C0 fills the slots.

6. **Continue.** State machine moves to next missing fields. C0 sends: "What's his PAN and age?"

7. **Slot extraction continues.** User responds, C0 extracts via LLM, fills slots.

8. **More fields.** State machine moves through remaining fields: household assignment, risk appetite, time horizon. Each prompt is templated; each user response is parsed via LLM extraction.

9. **Confirmation.** Once all required fields are filled, C0 produces a summary: "Here's what I have for Rajesh: <fields summarised>. Should I create the record?"

10. **Action execution.** User confirms. C0 calls the same investor creation service that the form path uses. I0 enrichment runs. The enriched investor profile is rendered as a card in the chat.

11. **Conclusion.** The conversation transitions to a complete state. The advisor can start a new conversation or return to other surfaces.

### 2.3 LLM Prompts (Cluster 1)

The cluster 1 implementation uses two templated LLM prompts:

**Intent Detection Prompt (issued once at conversation start):**

```
You are an intent classifier for a wealth advisory system.
Classify the following user message as one of these intents:
- investor_onboarding: user wants to add a new client to the system
- case_opening: user wants to open a case for an existing client
- alert_response: user wants to respond to a system alert
- briefing_request: user wants to prepare for a client meeting
- general_question: user has a general question or none of the above

Also extract any field values from the message that map to these onboarding fields:
name, email, phone, pan, age, risk_appetite (aggressive/moderate/conservative),
time_horizon (under_3_years/3_to_5_years/over_5_years).

Return JSON: {"intent": "<intent>", "extracted_fields": {<field>: <value>, ...}}

User message: <user_message>
```

**Slot Extraction Prompt (issued for each user response after intent detection):**

```
You are extracting structured field values from a user's response.
The user is being asked: <current_state_machine_prompt>
The fields expected in this response are: <list_of_fields_with_descriptions>

Field types:
- name: full name string
- email: valid email format
- phone: phone number; default to +91 country code if 10-digit Indian number
- pan: 10-character PAN format
- age: integer 18 to 100
- risk_appetite: one of aggressive, moderate, conservative
- time_horizon: one of under_3_years, 3_to_5_years, over_5_years

Return JSON: {"extracted_fields": {<field>: <value>, ...}, "extraction_confidence": "high|medium|low"}

If extraction is incomplete or ambiguous, set extraction_confidence to medium or low.

User response: <user_response>
```

Both prompts are versioned and stored in C0's skill.md file (per the per-agent skill.md mechanism in Principles §3.4). The skill.md file is the authoring surface for refinements to the prompts; the application code references the skill.md to load current prompt versions.

### 2.4 State Machine Specification (Investor Onboarding)

The state machine for investor onboarding has these states:

**STATE_INTENT_PENDING:** Initial state. Awaits user's first message. On message, runs intent detection. If intent is investor_onboarding, transitions to STATE_COLLECTING_BASICS with any extracted fields pre-populated. If other intent, transitions to "not yet implemented" handling.

**STATE_COLLECTING_BASICS:** Collects name, email, phone, pan, age. Generates prompt for missing fields. On each user response, runs slot extraction. If all basics filled, transitions to STATE_COLLECTING_HOUSEHOLD.

**STATE_COLLECTING_HOUSEHOLD:** Collects household_id (existing or new). The state machine first asks if this is a new client or family member of an existing client. If family member, presents existing households for selection; if new, asks for household name (becomes the household name for a fresh household_id). On completion, transitions to STATE_COLLECTING_PROFILE.

**STATE_COLLECTING_PROFILE:** Collects risk_appetite and time_horizon. These are enum fields; the slot extractor maps free-text responses to enum values (e.g., "he's pretty conservative" maps to risk_appetite=conservative). On completion, transitions to STATE_AWAITING_CONFIRMATION.

**STATE_AWAITING_CONFIRMATION:** Presents the summary of all collected fields and asks for confirmation. User can confirm, edit a specific field, or cancel. On confirmation, transitions to STATE_EXECUTING.

**STATE_EXECUTING:** Calls the investor creation service. Awaits result. On success, transitions to STATE_COMPLETED with the enriched investor profile rendered. On failure (validation error from server, e.g., duplicate PAN that the user previously didn't acknowledge), transitions back to the appropriate collecting state with the error message displayed.

**STATE_COMPLETED:** Conversation is complete. The advisor sees the success card. Can start a new conversation.

The state machine is a small finite state machine; it does not require an LLM to manage transitions. The LLM is invoked only at intent detection and slot extraction; the state machine handles everything else.

## 3. Conversation Persistence

### 3.1 Conversation Storage

Each conversation is stored in the database as a `c0_conversations` row with a related set of `c0_messages` rows. The schema:

```
c0_conversations:
  conversation_id (ULID, primary key)
  user_id (string, references users; the advisor who owns the conversation)
  intent (enum, nullable until intent detected: investor_onboarding, case_opening, ...)
  state (string; current state machine state)
  collected_slots (JSON; the slot values collected so far)
  status (enum: active, completed, abandoned, error)
  started_at (timestamp)
  last_message_at (timestamp)
  completed_at (timestamp, nullable)
  
c0_messages:
  message_id (ULID, primary key)
  conversation_id (string, references c0_conversations, indexed)
  sender (enum: user, system)
  content (string; the message text)
  metadata_json (JSON; structured data: detected intent, extracted slots, LLM call latency, etc.)
  timestamp (timestamp)
```

The schema works on both SQLite and Postgres per the demo-stage database addendum.

### 3.2 Session Scope

In cluster 1, each conversation is session-scoped: the advisor can navigate between the C0 chat surface and other surfaces in the same session, finding the conversation where they left off. When the session ends (logout or 8-hour expiry), the conversation persists in the database but is no longer "current" for the user; starting a new session shows a fresh chat surface, with prior conversations accessible from a "Past Conversations" list (cluster 1 may or may not expose this list visually; see open questions).

### 3.3 Abandoned Conversations

If a conversation is in an active state but no messages have been added for more than 4 hours, the conversation is automatically marked `abandoned` by a background job. Abandoned conversations are preserved in the database for audit but do not appear in the user's active conversation list.

The 4-hour threshold is configurable per deployment.

## 4. UI Surface (Chunk 1.2)

### 4.1 Chat Layout

The C0 chat surface is at `/app/<role>/conversational` (for advisor: `/app/advisor/conversational`). The layout is a standard chat interface:

- Conversation thread: vertical list of messages, oldest at top, newest at bottom. User messages right-aligned with avatar. System messages left-aligned with system avatar (using the firm's accent color).
- Input box: at the bottom, multi-line text input with send button. Enter sends; Shift+Enter inserts a line break.
- Header: shows the conversation's status indicator (active, completed, abandoned), and the detected intent if any.
- Sidebar (collapsible): list of past conversations, sorted by most recent. Tapping a past conversation shows its history (read-only if completed).

### 4.2 System Messages with Rich Content

Some system messages render as structured rich content rather than plain text:

- **Confirmation summary** (STATE_AWAITING_CONFIRMATION): renders as a card with all collected slots listed in a structured layout, plus "Confirm and Create" / "Edit" buttons.
- **Success card** (STATE_COMPLETED): renders as a card showing the enriched investor profile (name, contact, PAN, age, risk_appetite, time_horizon, life_stage badge, liquidity_tier badge), with a button "View Investor".
- **Error card** (state transition with error): renders as a card with the error message and remediation options.

These cards are rendered using the same components that the form-based path uses for inline display, ensuring visual consistency.

### 4.3 Loading States

When the LLM is processing (intent detection or slot extraction), the chat surface shows a "C0 is thinking..." indicator below the most recent user message. The indicator is a simple animated three-dots typing indicator.

LLM calls in cluster 1 typically complete within 1-3 seconds. The indicator manages user expectations during this latency.

## 5. Failure Handling

### 5.1 LLM Provider Unavailable

If the LLM call fails (provider unavailable, API key invalid, rate limit, timeout), C0 falls back to template-driven mode. Specifically:

For intent detection failure: C0 cannot determine intent. Shows the user a notice: "I couldn't fully understand your request. Are you trying to onboard a new client?" with a button "Yes, onboard new client" that hard-codes the intent.

For slot extraction failure: C0 falls back to single-field prompts that the user can answer with structured input. E.g., instead of "What's his email and phone?", asks "What's his email address?" and uses simple regex/format validation rather than LLM extraction.

The fallback notice tells the user: "Conversational understanding is temporarily unavailable; please respond with a single value to each question." The conversation continues; just more verbose.

### 5.2 LLM Returns Malformed Output

If the LLM returns JSON that fails to parse, or extracts a field with an invalid value (e.g., age = "young" instead of a number), the state machine falls back to direct prompting for the failing field with a hint: "I couldn't extract that. Could you tell me the age as a number, e.g., 35?"

### 5.3 User Provides Invalid Field Value

If the user provides a field value that fails validation (e.g., invalid PAN format, age outside range), the state machine displays the validation error and asks the user to provide a correct value: "That doesn't look like a valid PAN. PAN should be 10 characters, e.g., ABCDE1234F."

### 5.4 User Cancels Mid-Conversation

If the user types something like "cancel" or navigates away mid-conversation, the conversation is marked `abandoned` (immediately if the user explicitly cancels; after 4 hours if they navigate away).

## 6. Telemetry

C0 emits T1 telemetry events:

- `c0_conversation_started`: emitted when a new conversation begins. Payload includes conversation_id, user_id.
- `c0_intent_detected`: emitted when intent detection completes. Payload includes conversation_id, intent, llm_latency_ms, llm_provider.
- `c0_slot_extracted`: emitted on each slot extraction. Payload includes conversation_id, fields_extracted, extraction_confidence, llm_latency_ms.
- `c0_state_transitioned`: emitted on state machine transitions. Payload includes conversation_id, from_state, to_state.
- `c0_conversation_completed`: emitted on successful action execution. Payload includes conversation_id, action_taken (e.g., "investor_created"), final_state.
- `c0_conversation_abandoned`: emitted on abandonment. Payload includes conversation_id, abandonment_reason.
- `c0_llm_failure`: emitted on LLM failures. Payload includes conversation_id, failure_type, llm_provider.

These telemetry events feed audit replay and (in future clusters) T2 reflection for prompt and conversation flow improvement.

## 7. Acceptance Criteria for Cluster 1

C0 is considered functional in cluster 1 when:

1. The advisor can open the C0 chat surface from the sidebar and start a new conversation.
2. Typing "I want to onboard a new client" successfully classifies as `investor_onboarding` intent and starts the state machine.
3. The state machine collects all required investor fields through templated prompts and LLM-extracted user responses.
4. The conversation produces an investor record identical to what the form-based path would produce, with I0 enrichment running the same way.
5. The enriched investor profile is rendered as a success card in the chat at completion.
6. LLM provider failures (e.g., API key invalid) trigger the template-fallback mode without breaking the conversation.
7. Invalid user inputs (bad PAN, out-of-range age, etc.) trigger correct error prompts without losing already-collected slots.
8. Conversations persist in the database across navigation; returning to the chat surface mid-conversation shows the conversation in progress.
9. Abandoned conversations (4 hours of inactivity) are correctly marked and don't appear as active.
10. T1 telemetry events fire correctly for all conversation lifecycle events.
11. Past conversations are accessible from the chat sidebar (or future cluster surfaces if cluster 1 defers this UI).

## 8. Open Questions

Whether the past-conversations sidebar list ships in cluster 1 or in a later cluster is open. Working answer: ship a basic past-conversations list in cluster 1 (with conversation_id, intent, status, started_at, click-to-view) because the persistence is in place anyway and surfacing it is small UI work.

Whether C0 should support voice input (speak instead of type) is open. Working answer: deferred. Voice input requires integration with a transcription service and substantial UX work; not in cluster 1 scope.

Whether C0 in cluster 1 should support edit-after-completion (the user said "actually, the email is wrong, change it") is open. Working answer: deferred. Cluster 1 supports edit during STATE_AWAITING_CONFIRMATION (before action execution), but not after. Post-execution edits go through standard investor edit surfaces (which themselves don't ship in cluster 1; advisors can edit via API for now).

The exact tone and personality of C0's prompts is design discretion during implementation. Working answer: friendly-professional, concise, no hedging. Implementation can iterate based on demo feedback.

## 9. Revision History

April 2026 (cluster 1 drafting pass): Initial entry authored. Investor onboarding intent fully specified; other intents reserved as deferred. State machine, prompt templates, persistence schema, failure handling, and telemetry locked.

---

**End of FR Entry 14.0.**
