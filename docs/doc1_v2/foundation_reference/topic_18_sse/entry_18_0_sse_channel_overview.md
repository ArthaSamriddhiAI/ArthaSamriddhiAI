# Foundation Reference Entry 18.0: SSE Channel Overview

**Topic:** 18 Real-Time Layer (SSE)
**Entry:** 18.0
**Title:** SSE Channel Overview
**Status:** Locked (cluster 0; chunk 0.1 shipped May 2026); event payload schemas accumulate in subsequent clusters
**Date:** April 2026
**Author:** Shubham Sahamate, with consolidation support from Claude Opus 4.7 Adaptive

---

## Cross-references In

- FR Entry 17.0 (OIDC Authentication; SSE auth depends on auth completion)
- FR Entry 17.1 (JWT Session Management; SSE uses JWT for connection auth)
- FR Entry 17.2 (Role-Permission Vocabulary; SSE subscription scope depends on role)
- CP Chunk 0.1 (walking skeleton SSE connection establishment)
- All future event-emitting components (M0, agents, governance, PM1, T2, etc.) will reference this entry

## Cross-references Out

- Doc 2 Pass 4 (the original SSE multiplex schema specification; this entry implements it)
- Principles §1.3 (foundation reference + chunk plan structure)

---

## 1. Purpose

The SSE (Server-Sent Events) channel is the real-time push mechanism from the Samriddhi backend to authenticated clients. A single connection per session multiplexes all event types the user's role permits. SSE drives every UI surface that needs to update without polling: alert notifications, case progress, clarification questions, system status changes.

The channel was specified in Doc 2 Pass 4 §1 with eleven event types, the EventEnvelope structure, ordering and reconnect semantics, heartbeat sizing, and the access-token-refresh-during-connection mechanism. This foundation reference entry implements that specification. Cluster 0 ships the channel infrastructure plus two event types (`connection_established`, `connection_heartbeat`); subsequent clusters add event types as the components that emit them ship.

## 2. Functional Specification

### 2.1 Connection Establishment

The client (React app) opens an SSE connection to `GET /api/v2/events/stream` with the `Authorization: Bearer <jwt>` header. The backend validates the JWT, extracts user_id, firm_id, role from claims, and accepts the connection.

The backend immediately emits a `connection_established` event with the connection ID, the user's role, the subscribed event types (filtered by role per FR Entry 17.2), and operational parameters (heartbeat interval, max payload bytes). The client uses this event to confirm connection establishment and to know which event types to expect.

The connection's `Content-Type` is `text/event-stream; charset=utf-8`. The backend sets `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no` to defeat any intermediate proxy buffering.

### 2.2 SSE Frame Format

Every event sent on the stream conforms to the SSE specification (HTML Living Standard) with three fields plus a terminating blank line:

```
id: <event_id>
event: <event_type>
data: <JSON payload>

```

The `id` is a ULID, monotonically increasing within a connection. Clients reading the `Last-Event-ID` header on reconnect resume from this point.

The `event` field is the event type from the catalogue (Section 3 below).

The `data` field is a JSON document conforming to the EventEnvelope schema (Section 4 below) with the per-event-type payload nested in the `payload` field.

### 2.3 EventEnvelope Schema

Every event payload (the `data` field's JSON body) shares a common envelope structure:

```json
{
  "event_id": "01J0...",
  "event_type": "n0_alert_created",
  "emitted_at": "2026-04-30T12:34:56.789Z",
  "firm_id": "...",
  "schema_version": "1",
  "payload": { ... event-type-specific structure ... },
  "request_id": "..."
}
```

The `event_id` matches the SSE frame's `id`. The `emitted_at` is the server timestamp at emission. The `firm_id` is the deployment's firm identifier. The `schema_version` allows the multiplex schema to evolve without breaking older clients; clients ignore events whose `schema_version` they do not recognise rather than failing.

The `request_id` is the foreign key into T1 if the event was triggered by a specific HTTP request. For events emitted outside an HTTP request context (heartbeats, scheduled events), `request_id` is null.

The `payload` field is the per-event-type substructure. Schemas for each event type are in their respective foundation reference entries: `connection_established` and `connection_heartbeat` are below; future event types are introduced by their originating clusters.

### 2.4 Heartbeats

Every 30 seconds (default; configurable per deployment via `SAMRIDDHI_SSE_HEARTBEAT_SECONDS`), the backend emits a `connection_heartbeat` event to every active connection. The heartbeat keeps the connection alive through corporate proxies that timeout silent connections.

If the client does not see a heartbeat within twice the heartbeat interval (default 60 seconds), it should assume the connection is dead and reconnect with `Last-Event-ID`.

### 2.5 Reconnect Semantics

When the client reconnects after a disconnect (network blip, deployment, idle proxy timeout), it includes the `Last-Event-ID` header carrying the last event_id it successfully processed. The backend returns events with `event_id > Last-Event-ID` from a per-connection buffer.

The buffer holds the last 5 minutes of events per active connection identity. Events older than 5 minutes are not replayable; the client must do a full state refresh by fetching current data through REST endpoints.

If `Last-Event-ID` is older than the buffer's earliest event, the backend emits a `connection_established` event (signalling the client should treat the connection as fresh) and then begins normal event delivery.

### 2.6 Per-Connection Subscription Filtering

Each event is checked against the connection's subscription filter before delivery. The filter is determined at connection establishment by the user's role and the events_subscribe permissions:

`events:subscribe:own_scope`: receives only events scoped to the user's own data (own-book investors, own-book cases, own-book alerts). Advisors get this scope.

`events:subscribe:firm_scope`: receives all events in the firm. CIO, compliance, audit get this scope.

The filter is applied at emission time on the backend, not at receive time on the client. This protects scope confidentiality (an advisor cannot see another advisor's events even by inspecting network traffic).

### 2.7 Token Refresh During Connection

The connection is authenticated at establishment. Once established, the connection remains alive regardless of subsequent token expiry. The backend tracks the connection's identity by connection_session_token (set at establishment, persists across reconnects within the same session).

When the user's access token approaches expiry (60 seconds remaining), the backend emits `token_refresh_required`. The client calls the refresh endpoint (separate from the SSE connection), receives a new access token, and continues using the existing SSE connection without re-establishing.

If the refresh token is also exhausted (8-hour session expired), `token_refresh_required` will fail. The backend then emits `connection_terminating` with `session_will_expire: true`, signalling the client to redirect to login.

## 3. Event Type Catalogue

Eleven event types are defined in v1 of the multiplex schema. Cluster 0 implements the first two; later clusters add the rest as their components ship.

### 3.1 Implemented in Cluster 0

`connection_established`: emitted once per connection open. Payload includes connection_id, user_id, role, subscribed event types, subscription scope, server time, heartbeat interval, max payload bytes.

`connection_heartbeat`: periodic keepalive every 30 seconds. Payload contains only server_time.

### 3.2 Implemented in Subsequent Clusters

`n0_alert_created`: cluster 11 (watch tier) and onwards. Triggered when a new N0 alert is assigned to a user.

`n0_alert_updated`: cluster 11 onwards. Triggered when an existing alert changes status.

`case_progress_update`: cluster 5 onwards. Triggered when a case status transitions or a component within a case completes.

`clarification_question_posed`: cluster 5 onwards. Triggered when M0 pauses a case for an advisor clarification.

`system_status_change`: clusters 4 (model portfolio), 7 (synthesis), 16 (T2) onwards. Triggered for system-level events.

`model_portfolio_version_activated`: cluster 4 onwards. High-frequency variant of `system_status_change`.

`rule_corpus_version_updated`: cluster 8 onwards. Variant of `system_status_change`.

`token_refresh_required`: cluster 0 (mechanism in place); fires per JWT expiry timing in actual operation.

`connection_terminating`: cluster 0 (mechanism in place); fires for graceful close events.

Per-event-type payload schemas are in the foundation reference entry of the cluster that introduces the event. For example, the `n0_alert_created` payload schema is in FR Entry 14.1 (N0 Alert Tiers and Inbox), authored when cluster 11 ships.

## 4. Cluster 0 Event Payloads

### 4.1 connection_established Payload

```json
{
  "connection_id": "conn_01J0...",
  "user_id": "...",
  "role": "advisor|cio|compliance|audit",
  "subscribed_event_types": ["connection_established", "connection_heartbeat", "token_refresh_required", "connection_terminating"],
  "subscription_scope": {
    "alerts": "own_scope|firm_scope",
    "cases": "own_scope|firm_scope",
    "monitoring": "own_scope|firm_scope"
  },
  "server_time": "2026-04-30T12:34:56.789Z",
  "heartbeat_interval_seconds": 30,
  "max_payload_bytes": 65536
}
```

In cluster 0, the `subscribed_event_types` only includes the four event types implemented (connection_established, connection_heartbeat, token_refresh_required, connection_terminating). As later clusters add event types, this list grows accordingly per the user's role.

### 4.2 connection_heartbeat Payload

```json
{
  "server_time": "2026-04-30T12:35:26.789Z"
}
```

Minimal payload. Heartbeats are frequent and high-volume; keeping the payload tiny minimises bandwidth.

## 5. Integration Points

### 5.1 Reads From

The application JWT from the connection's `Authorization` header (validation per FR Entry 17.1).

The deployment's connection registry (in-memory or Redis) for tracking active connections.

The per-connection buffer (in-memory, 5-minute window) for reconnect replay.

Future: events emitted by other components (M0 case progress, N0 alerts, governance events, PM1 events) flow into the SSE channel via an internal publish mechanism.

### 5.2 Writes To

The HTTP response body (the SSE stream itself).

T1 telemetry: `sse_connection_opened`, `sse_connection_closed`, `sse_event_emitted`. Per FR Entry 9.0.

The connection registry (insert on open, remove on close).

The per-connection buffer (append on every event emission).

### 5.3 Read By

The React app's `useSSEConnection` hook (per Doc 3 Pass 1 Decision 9) reads the stream and demultiplexes to TanStack Query cache invalidations, Zustand state updates, and toast notifications.

## 6. Telemetry and Observability

T1 captures three event types:

`sse_connection_opened`: emitted on connection establishment. Includes connection_id, user_id, firm_id, role, user_agent.

`sse_connection_closed`: emitted on connection close (client-initiated, server-initiated, or network failure). Includes connection_id, close_reason, total_events_emitted, connection_duration_seconds.

`sse_event_emitted`: emitted for high-priority events (must_respond N0 alerts, case progress updates with critical status). Not emitted for every event (which would be noisy); selective by event type.

Operational metrics: active connection count per deployment, event emission rate, per-connection event delivery latency (proxied by client-side acknowledgment of connection_heartbeat). These are operational; they live in Doc 4.

## 7. Failure Modes and EX1 Contract

### 7.1 SSE Infrastructure Unavailable

The SSE infrastructure cannot accept new connections (resource exhaustion, deployment issue). New connection attempts return HTTP 503. Existing connections continue if possible.

EX1 routing: critical infrastructure failure. Operations response is degraded-mode: REST endpoints continue working; advisors poll for updates instead of receiving real-time events; the user experience is degraded but the system remains functional.

### 7.2 Per-Connection Buffer Overflow

If a connection is sluggish in consuming events (slow client, network congestion), the per-connection buffer can overflow. The backend drops the oldest events from the buffer to make room for new events. The dropped events are lost from the reconnect buffer; if the client reconnects with a Last-Event-ID older than the new buffer floor, it will receive a fresh connection_established and must do a full state refresh.

EX1 routing: routine degradation. Logged to operational metrics; not a customer-facing alert unless persistent.

### 7.3 Event Emission Rate Limit

Per Doc 2 Pass 1 Decision 8, the SSE event-emission rate per connection is capped (default 600 events per minute). If a component emits faster than this, the rate limiter buffers and slows emission. Sustained over-emission triggers an EX1 alert because it indicates a downstream component is misbehaving.

### 7.4 Event Ordering Within a Connection

Events within a single connection are strictly ordered by event_id. If a downstream component emits events out of order (e.g., case_progress_update at time T, then case_progress_update at time T-1 because of a clock skew or delayed processing), the SSE channel emits them in the order received, not in the order of their timestamps. The client must tolerate slight ordering anomalies.

This is not strictly a failure; it is an architectural acknowledgment that "order received" and "order generated" can differ. T1 records both timestamps (the event's logical timestamp from its origin, the SSE emission timestamp).

## 8. Acceptance Criteria

**Test 1.** A client with a valid JWT can establish an SSE connection at `/api/v2/events/stream` and receives a `connection_established` event immediately.

**Test 2.** A client without a JWT cannot establish a connection; the response is HTTP 401.

**Test 3.** A client with insufficient permissions (e.g., trying to subscribe to firm_scope as an advisor) cannot establish a connection at firm_scope; the connection establishes at the user's actual scope.

**Test 4.** Heartbeats arrive every 30 seconds (within 1 second tolerance).

**Test 5.** A client that disconnects and reconnects with `Last-Event-ID` receives the events emitted between disconnect and reconnect, if within the 5-minute buffer window.

**Test 6.** A client whose `Last-Event-ID` is older than the buffer receives a `connection_established` event and must refresh state via REST.

**Test 7.** When the access token approaches expiry, `token_refresh_required` is emitted; the SSE connection itself remains alive after the token refresh completes.

**Test 8.** When the refresh token is exhausted, `connection_terminating` is emitted with `session_will_expire: true`.

**Test 9.** Event payloads conform to the EventEnvelope schema; `connection_established` and `connection_heartbeat` have the payloads specified in Section 4.

**Test 10.** T1 events for `sse_connection_opened`, `sse_connection_closed`, `sse_event_emitted` are emitted with correct payloads.

## 9. Open Questions

The connection_session_token mechanism (used to bind reconnect identity to a session) is in this entry's specification at high level. The full operational specification (token lifecycle, storage, refresh) is a Doc 4 Operations concern but the contract here defines what the application-layer behaviour must be.

The 5-minute per-connection buffer size is a working default. Some firms with higher-latency connections may need longer buffers; some with strict memory budgets may want shorter. Configurable per deployment; the default is reasonable for typical 2026 advisor environments.

The 600-events-per-minute rate limit is a working default. Adjustable per deployment if specific use patterns warrant; in practice, no v1.0 component should produce events anywhere near this rate.

## 10. Revision History

April 2026 (cluster 0 drafting pass): Initial entry authored. Cluster 0 ships connection_established, connection_heartbeat, token_refresh_required, connection_terminating event types and the full multiplex infrastructure. Subsequent clusters add event types per their introducing components.

May 2026 (cluster 0 chunk 0.1 shipped): Implementation completed across `src/artha/api_v2/events/` (envelope, event_types, buffer, subscription, registry, stream, router). All 10 acceptance tests in §8 verified via `tests/test_unit/test_api_v2_events.py` (34 tests). Per-session shared `BufferRegistry` keyed by `session_id` so Last-Event-ID replay survives reconnects within a session (FR §2.7's "connection_session_token persists across reconnects within the same session"). Connection auth via `Authorization: Bearer <jwt>` header from §2.1 — NOTE the frontend uses `@microsoft/fetch-event-source` rather than the native EventSource API because the latter cannot send custom headers; the Bearer-header contract from §2.1 is honoured but the implementation deviates from any "use native EventSource" reading. Heartbeat watchdog deferred to a future cluster (the library's auto-reconnect handles transport errors; pure server-stop-sending edge cases would need explicit watchdog).

---

**End of FR Entry 18.0.**
