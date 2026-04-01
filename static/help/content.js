// Contextual help content keyed by section
window.helpContent = {
  'agents': 'Agents are specialized AI reasoning modules. Each agent analyzes a different aspect: Allocation evaluates portfolio weights, Risk Interpretation assesses risk scores, and Review synthesizes findings. Agents surface risk — they do NOT decide.',
  'rules': 'Rules are deterministic, versioned governance constraints. HARD rules block actions entirely. SOFT rules trigger escalation for human review. Each rule condition is evaluated in a sandboxed environment.',
  'permissions': 'The permission filter transforms rule evaluations into action permissions. Any hard violation means rejection. Any soft violation means escalation required. All pass means approved.',
  'trace': 'The decision trace is a causal directed acyclic graph (DAG). Each node represents a step in the decision process. Traverse backwards from any outcome to understand why a decision was made.',
  'evidence': 'Evidence artifacts are append-only and immutable. At decision time, they are frozen into a snapshot. This ensures decisions can always be reconstructed with the evidence that was available at the time.',
};
