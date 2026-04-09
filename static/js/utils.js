// Shared utilities
window.utils = {
  truncateId: (id) => id ? id.substring(0, 8) : '',

  statusBadge: (status) => {
    const map = { approved: 'badge-approved', rejected: 'badge-rejected', escalation_required: 'badge-escalation', error: 'badge-error' };
    return map[status] || 'badge-info';
  },
  statusLabel: (status) => {
    const map = { approved: 'Approved', rejected: 'Rejected', escalation_required: 'Escalation Required', error: 'Error' };
    return map[status] || status;
  },
  riskBadge: (level) => {
    const map = { low: 'badge-low', medium: 'badge-medium', high: 'badge-high', critical: 'badge-critical' };
    return map[level] || 'badge-info';
  },
  severityBadge: (sev) => {
    const map = { hard: 'badge-hard', soft: 'badge-soft', info: 'badge-info' };
    return map[sev] || 'badge-info';
  },

  riskColor: (level) => {
    const map = { low: '#22c55e', medium: '#eab308', high: '#f97316', critical: '#ef4444' };
    return map[level] || '#94a3b8';
  },

  traceNodeColor: (type) => {
    const map = {
      intent_received: '#60a5fa', evidence_frozen: '#818cf8', agent_invoked: '#a78bfa',
      agent_output: '#7c3aed', rule_evaluated: '#eab308', permission_granted: '#22c55e',
      permission_denied: '#ef4444', escalation_required: '#f59e0b', human_approval: '#14b8a6',
      execution_submitted: '#15803d', analysis_started: '#0d9488', analysis_synthesized: '#0f766e',
      portfolio_review_started: '#0891b2', portfolio_review_complete: '#0e7490',
      suggestion_set_generated: '#7c3aed', suggestion_ega_result: '#6d28d9',
      error: '#b91c1c'
    };
    return map[type] || '#94a3b8';
  },

  traceNodeLabel: (type) => {
    const map = {
      intent_received: 'Intent Received', evidence_frozen: 'Evidence Frozen',
      agent_invoked: 'Agent Invoked', agent_output: 'Agent Output',
      rule_evaluated: 'Rule Evaluated', permission_granted: 'Permission Granted',
      permission_denied: 'Permission Denied', escalation_required: 'Escalation Required',
      human_approval: 'Human Approval', execution_submitted: 'Execution Submitted',
      analysis_started: 'Analysis Started', analysis_synthesized: 'Analysis Synthesized',
      portfolio_review_started: 'Portfolio Review Started', portfolio_review_complete: 'Portfolio Review Complete',
      suggestion_set_generated: 'Suggestions Generated', suggestion_ega_result: 'Suggestion EGA Result',
      error: 'Error'
    };
    return map[type] || type;
  },

  relativeTime: (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const diff = (now - d) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
    return d.toLocaleDateString();
  },

  formatTime: (iso) => {
    if (!iso) return '';
    return new Date(iso).toLocaleString();
  },

  copyToClipboard: async (text) => {
    try { await navigator.clipboard.writeText(text); } catch {}
  },

  formatPercent: (v) => v != null ? (v * 100).toFixed(1) + '%' : '-',

  // T-6: Indian number formatting (1,00,000 not 100,000)
  formatINR: (v) => {
    if (v == null || isNaN(v)) return '0';
    const abs = Math.abs(v);
    const sign = v < 0 ? '-' : '';
    if (abs >= 10000000) return sign + 'Rs ' + (abs / 10000000).toFixed(2) + ' Cr';
    if (abs >= 100000) return sign + 'Rs ' + (abs / 100000).toFixed(2) + ' L';
    // Indian grouping: last 3, then groups of 2
    const str = Math.round(abs).toString();
    if (str.length <= 3) return sign + 'Rs ' + str;
    const last3 = str.slice(-3);
    const rest = str.slice(0, -3);
    const grouped = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',');
    return sign + 'Rs ' + grouped + ',' + last3;
  },

  // T-6: Capitalise known abbreviations
  capitalize: (s) => {
    if (!s) return '';
    const abbrs = { 'hni': 'HNI', 'aum': 'AUM', 'aif': 'AIF', 'pms': 'PMS', 'nps': 'NPS', 'ppf': 'PPF', 'fd': 'FD', 'emi': 'EMI', 'sip': 'SIP', 'nav': 'NAV', 'sebi': 'SEBI', 'nse': 'NSE', 'bse': 'BSE' };
    return s.replace(/\b\w+\b/g, w => abbrs[w.toLowerCase()] || w);
  },

  // T-6: Strip em dashes from LLM text
  cleanText: (s) => {
    if (!s) return '';
    return s.replace(/\s*—\s*/g, ', ').replace(/\s*–\s*/g, ', ');
  },
};
