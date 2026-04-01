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
      execution_submitted: '#15803d', error: '#b91c1c'
    };
    return map[type] || '#94a3b8';
  },

  traceNodeLabel: (type) => {
    const map = {
      intent_received: 'Intent Received', evidence_frozen: 'Evidence Frozen',
      agent_invoked: 'Agent Invoked', agent_output: 'Agent Output',
      rule_evaluated: 'Rule Evaluated', permission_granted: 'Permission Granted',
      permission_denied: 'Permission Denied', escalation_required: 'Escalation Required',
      human_approval: 'Human Approval', execution_submitted: 'Execution Submitted', error: 'Error'
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
};
