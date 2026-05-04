# Foundation Reference Entry 14.0 Cluster 2 Revision Note

**Revising:** FR Entry 14.0 (C0 Conversational Orchestrator)
**Cluster Triggering Revision:** 2 (Mandate Management)
**Status:** Revision note; original entry remains; this note captures cluster 2 additions
**Date:** April 2026
**Author:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## 1. Purpose of This Note

This is a revision note attached to FR Entry 14.0 (C0 Conversational Orchestrator). The original entry was authored in cluster 1 and locked the architecture for C0 with the `investor_onboarding` intent fully specified. Cluster 2 adds a new intent (`mandate_creation`) to C0's intent vocabulary.

Rather than rewriting the entire FR Entry 14.0, this note captures the cluster 2 additions. Both documents (the original entry and this note) together describe C0's current state. Future clusters that add more intents will produce similar revision notes.

When cluster 2 ships, the original FR Entry 14.0 should be read alongside this note. When cluster 7 (briefings) or cluster 11 (alerts) adds further intents, those clusters' revision notes are also appended.

---

## 2. New Intent: mandate_creation

### 2.1 Intent Definition

The `mandate_creation` intent is added to C0's intent vocabulary. The intent vocabulary now contains:

- investor_onboarding (cluster 1, fully implemented)
- **mandate_creation (cluster 2, fully implemented)**
- case_opening (reserved; future cluster)
- alert_response (reserved; future cluster)
- briefing_request (reserved; future cluster)
- general_question (reserved; future cluster)

### 2.2 Intent Detection Prompt Update

The intent detection prompt in C0's skill.md is updated to include `mandate_creation` in the candidate intents list. The prompt now reads:

```
You are an intent classifier for a wealth advisory system.
Classify the following user message as one of these intents:
- investor_onboarding: user wants to add a new client to the system
- mandate_creation: user wants to set up an investment policy mandate for an existing client
- case_opening: user wants to open a case for an existing client
- alert_response: user wants to respond to a system alert
- briefing_request: user wants to prepare for a client meeting
- general_question: user has a general question or none of the above

Return JSON: {"intent": "<intent>", "extracted_fields": {<field>: <value>, ...}}

User message: <user_message>
```

The `extracted_fields` for `mandate_creation` intent can include investor name references (e.g., "set up mandate for Rajesh" extracts name="Rajesh"). The mandate-specific constraint values are not extracted at the initial intent step; they are collected via the state machine.

### 2.3 Mandate Creation State Machine

Per Cluster 2 Ideation §4.3, the state machine for mandate_creation has eight states:

- **STATE_INVESTOR_DISAMBIGUATION:** Identify which investor the advisor refers to. Per cluster 2 ideation §4.2, uses structured disambiguation (not LLM fuzzy matching). C0 queries the advisor's investor book for matches, presents options if multiple, asks for clarification if none.
- **STATE_COLLECTING_ASSET_ALLOCATION:** Collect equity/debt/alternatives min-max bands. Presents I0-suggested defaults (per FR Entry 12.1 §2.4) and asks if the advisor wants to use defaults or customise.
- **STATE_COLLECTING_CONCENTRATION:** Collect single_position_max_pct.
- **STATE_COLLECTING_LIQUIDITY:** Collect liquidity_floor_pct with I0 suggestion (per FR Entry 12.1 §4.4).
- **STATE_COLLECTING_SECTOR:** Collect sector_max_pct.
- **STATE_COLLECTING_PROHIBITED:** Collect prohibited instruments list. Advisor can say "none" or list specific items.
- **STATE_AWAITING_CONFIRMATION:** Present summary card with all collected constraints, plus Confirm/Edit buttons.
- **STATE_EXECUTING:** Call M1 to create the mandate. Receive the created mandate response.
- **STATE_COMPLETED:** Display success card with the activated mandate.

The state machine reuses C0's existing patterns (templated prompts, slot extraction via LLM, validation, error fallback).

### 2.4 Skip-To-Defaults Affordance

Per Cluster 2 Ideation §4.4: at any state during the mandate_creation conversation, the advisor can say "use defaults" or similar phrasing. C0's slot extractor recognises this affordance (via a templated prompt asking the LLM to detect "fill remaining with defaults" intent). When detected, C0 fills the remaining slots with I0-suggested defaults and skips to STATE_AWAITING_CONFIRMATION.

This affordance is for the common case where the advisor wants the suggested defaults and doesn't need to customise everything.

### 2.5 Investor Disambiguation Flow

Per Cluster 2 Ideation §4.2, the structured disambiguation flow:

1. C0 extracts any name-like reference from the advisor's first message via slot extraction.
2. C0 queries the advisor's investor book for matches (exact name match, fuzzy substring match, or PAN partial match).
3. If exactly one match, C0 confirms with the advisor: "I found Rajesh Kumar (PAN ABCDE1234F). Is this the right investor?" Confirmation proceeds; rejection asks for more clarification.
4. If multiple matches, C0 presents the options as a structured list with name, PAN, age, last activity. Advisor selects.
5. If no matches, C0 asks for clarification: "I couldn't find an investor matching that name. Can you provide the PAN or full name?" Advisor responds; lookup retries.
6. If still no match after retry, C0 offers to onboard a new investor first: "It looks like this investor isn't in your book yet. Should I onboard them first?" If yes, transitions to investor_onboarding intent flow, then returns to mandate_creation after onboarding completes.

The query logic for matching is implemented in C0's backend service. The disambiguation UI in the chat surface presents matches as an interactive list; the advisor clicks to select.

---

## 3. Updated Acceptance Criteria

The original FR Entry 14.0 §7 acceptance criteria for cluster 1 (investor_onboarding intent) all remain valid. Cluster 2 adds:

12. The advisor can type "I want to set up the mandate for [investor name]" and C0 correctly classifies the intent as `mandate_creation`.

13. C0 successfully disambiguates the investor reference per §2.5; if exactly one match, proceeds; if multiple, presents structured options; if none, asks for clarification or offers to onboard.

14. The mandate_creation state machine collects all five constraint families through templated prompts and LLM-extracted user responses.

15. I0 defaults are correctly pre-populated and surface in the conversation (e.g., C0 says "Based on Rajesh's I0 deep liquidity tier, I'm suggesting a liquidity floor of 30%. Use this default or customise?").

16. The skip-to-defaults affordance correctly skips to STATE_AWAITING_CONFIRMATION when the advisor says "use defaults" or similar.

17. The confirmation summary card displays all five constraint families' values with correct visual treatment.

18. On confirmation, the mandate is created via M1 with `created_via=conversational`. The success card displays the active mandate's constraints.

19. T1 telemetry emits the same C0 events as cluster 1 (`c0_conversation_started`, `c0_intent_detected`, `c0_slot_extracted`, etc.) plus the mandate creation events from M1 (`mandate_created`, `mandate_version_activated`).

---

## 4. Cross-References Updated

Cluster 2's revision adds these cross-references in to FR Entry 14.0:

- FR Entry 12.0 (M1 Overview; consumed by mandate_creation intent's STATE_EXECUTING).
- FR Entry 12.1 (Mandate Schema and Constraints; the constraint values collected by the state machine).
- CP Chunk 2.2 (conversational mandate creation chunk).

Cross-references out from FR Entry 14.0 now include:

- FR Entry 12.0 (M1 service called by STATE_EXECUTING).
- FR Entry 11.1 (I0 active layer; consulted for default values during state machine collection).

These cross-references should be reflected in any updated copy of FR Entry 14.0 produced after cluster 2 ships.

---

## 5. Open Questions (Cluster 2 Specific)

The exact wording of the disambiguation prompts when C0 asks the advisor to clarify which investor is design discretion. Working answer: clear, concise, friendly tone matching the cluster 1 conversational pattern.

Whether the mandate_creation intent should support a "minimal mandate" mode that uses all I0 defaults automatically without asking each constraint family is open. Working answer: the skip-to-defaults affordance handles this; explicit minimal mode adds complexity without clear benefit.

Whether C0 should support expressing the entire mandate in a single utterance (e.g., "Set up a moderate mandate for Rajesh with no tobacco exclusions") is open. Working answer: the state machine asks for each constraint family separately. Single-utterance mandate creation is a more advanced feature that can be added later.

---

## 6. Revision History

April 2026 (cluster 2 drafting pass): Initial revision note created. Added mandate_creation intent specification, state machine, skip-to-defaults affordance, structured investor disambiguation flow, updated acceptance criteria.

When future clusters add intents (case_opening in cluster 5, alert_response in cluster 11, briefing_request in cluster 14, etc.), they author similar revision notes appended to FR Entry 14.0.

---

**End of FR Entry 14.0 Cluster 2 Revision Note.**
