// ArthaSamriddhiAI API Client
const BASE = '/api/v1';

async function request(method, path, body = null) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  try {
    const res = await fetch(`${BASE}${path}`, opts);
    const data = await res.json();
    if (!res.ok) return { error: data.detail || `HTTP ${res.status}`, status: res.status };
    return data;
  } catch (e) {
    return { error: e.message };
  }
}

window.api = {
  health: () => request('GET', '/health'),

  // Governance
  submitIntent: (data) => request('POST', '/governance/intents', data),

  // Accountability
  listDecisions: (limit = 50) => request('GET', `/accountability/decisions?limit=${limit}`),
  listDecisionsSummary: (limit = 50) => request('GET', `/accountability/decisions/summary?limit=${limit}`),
  getTrace: (id) => request('GET', `/accountability/decisions/${id}/trace`),
  getAudit: (id) => request('GET', `/accountability/decisions/${id}/audit`),
  getApprovals: (id) => request('GET', `/accountability/decisions/${id}/approvals`),
  submitApproval: (data) => request('POST', '/accountability/approvals', data),

  // Evidence
  ingestMarketData: (data) => request('POST', '/evidence/ingest', data),
  computeEvidence: (symbols, holdings) => request('POST', `/evidence/compute?${new URLSearchParams({ symbols: JSON.stringify(symbols) })}`, holdings),
  getArtifact: (id) => request('GET', `/evidence/artifacts/${id}`),
  getLatestEvidence: (type) => request('GET', `/evidence/latest/${type}`),

  // Execution
  getKillSwitch: () => request('GET', '/execution/killswitch'),
  activateKillSwitch: (by = 'ui') => request('POST', `/execution/killswitch/activate?by=${by}`),
  deactivateKillSwitch: (by = 'ui') => request('POST', `/execution/killswitch/deactivate?by=${by}`),
};
