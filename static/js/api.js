// Samriddhi AI API Client
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
  getDecisionDetail: (id) => request('GET', `/accountability/decisions/${id}/detail`),
  getTrace: (id) => request('GET', `/accountability/decisions/${id}/trace`),
  getAudit: (id) => request('GET', `/accountability/decisions/${id}/audit`),
  getApprovals: (id) => request('GET', `/accountability/decisions/${id}/approvals`),
  submitApproval: (data) => request('POST', '/accountability/approvals', data),
  telemetryAnalytics: () => request('GET', '/accountability/telemetry'),

  // Evidence
  ingestMarketData: (data) => request('POST', '/evidence/ingest', data),
  computeEvidence: (symbols, holdings) => request('POST', `/evidence/compute?${new URLSearchParams({ symbols: JSON.stringify(symbols) })}`, holdings),
  getArtifact: (id) => request('GET', `/evidence/artifacts/${id}`),
  getLatestEvidence: (type) => request('GET', `/evidence/latest/${type}`),

  // Investor
  listInvestors: (limit = 50) => request('GET', `/investor/investors?limit=${limit}`),
  getInvestor: (id) => request('GET', `/investor/investors/${id}`),
  createInvestor: (data) => request('POST', '/investor/investors', data),
  getQuestionnaireTemplate: () => request('GET', '/investor/questionnaire/template'),
  submitQuestionnaire: (investorId, data) => request('POST', `/investor/investors/${investorId}/questionnaire`, data),
  getInvestorProfile: (id) => request('GET', `/investor/investors/${id}/profile`),
  getAssessmentHistory: (investorId) => request('GET', `/investor/investors/${investorId}/assessments`),
  getAssessmentDetail: (id) => request('GET', `/investor/assessments/${id}`),
  createFamilyOffice: (data) => request('POST', '/investor/family-offices', data),
  getMandateTypes: () => request('GET', '/investor/mandate-types'),
  getMandates: (investorId) => request('GET', `/investor/investors/${investorId}/mandates`),
  setMandate: (investorId, data) => request('POST', `/investor/investors/${investorId}/mandates`, data),
  deleteMandate: (id) => request('DELETE', `/investor/mandates/${id}`),

  // Portfolio
  portfolioSummary: (investorId) => request('GET', `/portfolio/${investorId}/summary`),
  portfolioHoldings: (investorId) => request('GET', `/portfolio/${investorId}/holdings`),
  addHolding: (investorId, data) => request('POST', `/portfolio/${investorId}/holdings`, data),
  deleteHolding: (id) => request('DELETE', `/portfolio/holdings/${id}`),
  portfolioPerformance: (id) => request('GET', `/portfolio/${id}/performance`),
  portfolioRebalance: (id) => request('GET', `/portfolio/${id}/rebalance-check`),
  portfolioScenario: (id, type) => request('GET', `/portfolio/${id}/scenario?type=${type}`),
  portfolioTax: (id) => request('GET', `/portfolio/${id}/tax-summary`),
  portfolioGoals: (id) => request('GET', `/portfolio/${id}/goals`),
  addGoal: (id, data) => request('POST', `/portfolio/${id}/goals`, data),
  advisorDashboard: () => request('GET', '/portfolio/advisor/dashboard'),
  scenariosList: () => request('GET', '/portfolio/scenarios/list'),
  marketBrief: () => request('GET', '/data/market-brief'),

  // Data Explorer
  dataSummary: () => request('GET', '/data/summary'),
  stocksLatest: (limit = 50) => request('GET', `/data/stocks/latest?limit=${limit}`),
  stockSearch: (q) => request('GET', `/data/stocks/search?q=${q}`),
  stockPrices: (sym, days = 30) => request('GET', `/data/stocks?symbol=${sym}&days=${days}`),
  mfLatest: (limit = 50) => request('GET', `/data/mf/latest?limit=${limit}`),
  mfSearch: (q) => request('GET', `/data/mf/search?q=${q}`),
  mfHistory: (code, days = 365) => request('GET', `/data/mf/${code}?days=${days}`),
  commodities: () => request('GET', '/data/commodities'),
  forex: () => request('GET', '/data/forex'),
  macro: () => request('GET', '/data/macro'),
  crypto: () => request('GET', '/data/crypto'),

  // Execution
  getKillSwitch: () => request('GET', '/execution/killswitch'),
  activateKillSwitch: (by = 'ui') => request('POST', `/execution/killswitch/activate?by=${by}`),
  deactivateKillSwitch: (by = 'ui') => request('POST', `/execution/killswitch/deactivate?by=${by}`),
};
