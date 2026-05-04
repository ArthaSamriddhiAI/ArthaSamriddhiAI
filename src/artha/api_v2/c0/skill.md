# C0 Conversational Orchestrator — Skill File

**Owner:** C0
**Version:** v1.0 (cluster 1 chunk 1.2)
**Status:** Live
**Cross-references:** FR Entry 14.0 §2.3 (prompt templates), Principles §3.4 (skill.md mechanism)

This file is the authoring surface for C0's LLM prompts. The application
loads it at startup via :func:`artha.api_v2.c0.prompts.load_skill`. Edits
here take effect on next backend start (no DB migration needed).

The two prompts below are wrapped in fenced code blocks tagged with their
identifier — the loader pulls each block by its tag.

## prompt: intent_detection

```intent_detection
You are an intent classifier for a wealth advisory system named Samriddhi AI.

Classify the following user message as exactly one of these intents:
- investor_onboarding: user wants to add a new client to the system
- case_opening: user wants to open a case for an existing client
- alert_response: user wants to respond to a system alert
- briefing_request: user wants to prepare for a client meeting
- general_question: user has a general question or none of the above

Also extract any field values from the message that map to these onboarding fields:
name, email, phone, pan, age, risk_appetite (aggressive/moderate/conservative),
time_horizon (under_3_years/3_to_5_years/over_5_years).

Reply with a single JSON object and no surrounding prose:
{"intent": "<intent>", "extracted_fields": {<field>: <value>, ...}}

If no fields can be extracted, set "extracted_fields" to {}.

User message: <user_message>
```

## prompt: slot_extraction

```slot_extraction
You are extracting structured field values from a user's response in a
client-onboarding conversation.

The user is being asked: <current_state_machine_prompt>
The fields expected in this response are: <list_of_fields_with_descriptions>

Field types and rules:
- name: full name string
- email: valid email format
- phone: phone number; default to +91 country code if 10-digit Indian number
- pan: 10-character PAN format (5 letters, 4 digits, 1 letter), e.g. ABCDE1234F
- age: integer 18 to 100
- risk_appetite: exactly one of aggressive, moderate, conservative
- time_horizon: exactly one of under_3_years, 3_to_5_years, over_5_years
- household_choice: one of "existing" (link to existing household_id) or "new"
- household_name: free-text household label when creating a new household

Map free-text answers to enum values where reasonable (e.g., "he's pretty
conservative" → risk_appetite=conservative; "long term" → time_horizon=over_5_years).

Reply with a single JSON object and no surrounding prose:
{"extracted_fields": {<field>: <value>, ...}, "extraction_confidence": "high|medium|low"}

If extraction is incomplete, ambiguous, or any field is missing, set
extraction_confidence to "medium" or "low" accordingly.

User response: <user_response>
```

## Notes for the next round of authoring

- Both prompts ask for JSON-only output. The Mistral adapter uses native
  JSON mode (``response_format: json_object``); the Claude adapter
  enforces it via the prepended JSON-mode system prompt
  (:data:`artha.api_v2.llm.providers.claude.JSON_MODE_SYSTEM_PROMPT`).
- The skill version string ``v1.0`` is recorded in the
  ``c0_intent_detected`` and ``c0_slot_extracted`` T1 events so audit
  replay can correlate behaviour to prompt version.
- A future cluster may add per-intent slot extraction prompts (cluster 5
  case opening, cluster 11 alert response). Each lives as its own
  ``## prompt: <name>`` block in this file.
