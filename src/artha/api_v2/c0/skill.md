# C0 Conversational Orchestrator — Skill File

**Owner:** C0
**Version:** v1.2 (cluster 5 chunk 5.3 — added case_opening intent slots)
**Status:** Live
**Cross-references:** FR Entry 14.0 §2.3 (prompt templates), FR Entry 14.0 Cluster 2 Revision Note (mandate_creation intent), Principles §3.4 (skill.md mechanism)

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
- mandate_creation: user wants to set up an investment policy mandate for an existing client
- case_opening: user wants to open a case for an existing client
- alert_response: user wants to respond to a system alert
- briefing_request: user wants to prepare for a client meeting
- general_question: user has a general question or none of the above

Also extract any field values from the message that map to these fields:
- Onboarding: name, email, phone, pan, age, risk_appetite (aggressive/moderate/conservative),
  time_horizon (under_3_years/3_to_5_years/over_5_years).
- Mandate creation: investor_name (the client the mandate is for), investor_pan
  (if mentioned).
- Case opening: investor_name, investor_pan (the client the case is for),
  case_mode (proposed_action / scenario / diagnostic / briefing), case_intent
  (rebalance_proposal / new_investment / exit_position / product_evaluation /
  asset_allocation_change / tax_loss_harvesting / liquidity_mobilisation /
  mandate_review_response / portfolio_health / meeting_prep / other),
  proposed_action (free-text description of the action under consideration).

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
- investor_name, investor_pan: investor disambiguation references
- equity_min_pct, equity_max_pct, debt_min_pct, debt_max_pct,
  alternatives_min_pct, alternatives_max_pct: integers 0-100, asset
  allocation band bounds. Cluster 2 mandate_creation intent.
- single_position_max_pct, liquidity_floor_pct, sector_max_pct:
  integers 0-100, percentage caps. Cluster 2 mandate_creation intent.
- prohibited_instruments: list of strings (specific instruments,
  categories, or themes the investor excludes). Cluster 2 mandate_creation
  intent. Treat user inputs like "none" / "nothing" / "no exclusions" as
  an empty list.
- use_defaults: boolean. Set to true when the user says "use defaults",
  "use I0 suggestions", "the suggested values are fine", or similar
  affordances during the mandate_creation flow.
- case_mode: exactly one of proposed_action, scenario, diagnostic, briefing.
  Cluster 5 case_opening intent. Map free-text affordances: "I'm thinking of
  buying X" → proposed_action; "what if X happens" → scenario; "how is the
  portfolio doing" → diagnostic; "I have a meeting next week" → briefing.
- case_intent: cluster 5 case_opening intent. Pick the closest match from
  rebalance_proposal, new_investment, exit_position, product_evaluation,
  asset_allocation_change, tax_loss_harvesting, liquidity_mobilisation,
  mandate_review_response, portfolio_health, meeting_prep. Use "other" only
  if no listed intent fits.
- proposed_action: cluster 5 case_opening intent. Free-text summary of the
  action the user is considering, e.g. "shift 10% from equity to debt",
  "exit RELIANCE", "evaluate adding a multicap PMS".

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
