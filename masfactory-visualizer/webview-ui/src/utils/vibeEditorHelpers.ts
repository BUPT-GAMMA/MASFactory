import type { VibeGraphDesign, VibeNodeSpec, VibeNodeType } from '../stores/vibe';

export function parseEndpoint(name: string): { base: string; suffix: string | null } {
  const s = String(name || '');
  const idx = s.indexOf('.');
  if (idx === -1) return { base: s, suffix: null };
  return { base: s.slice(0, idx), suffix: s.slice(idx + 1) || null };
}

export function isInternalNodeId(id: string): boolean {
  return (
    id === 'entry' ||
    id === 'exit' ||
    id.endsWith('.entry') ||
    id.endsWith('.exit') ||
    id.endsWith('.controller') ||
    id.endsWith('.terminate')
  );
}

export function findNodeSpec(g: VibeGraphDesign, nodeId: string): VibeNodeSpec | null {
  if (isInternalNodeId(nodeId)) return null;
  const nodes = Array.isArray(g.Nodes) ? g.Nodes : [];
  return nodes.find((n) => n && n.name === nodeId) || null;
}

export function generateUniqueName(g: VibeGraphDesign, base: string): string {
  const used = new Set((g.Nodes || []).map((n) => String((n as any)?.name || '')).filter(Boolean));
  if (!used.has(base)) return base;
  let i = 1;
  while (used.has(`${base}_${i}`)) i++;
  return `${base}_${i}`;
}

export function defaultSpec(
  type: VibeNodeType,
  name: string,
  parent: string | undefined,
  graphFormat: 'v3' | 'legacy'
): VibeNodeSpec {
  const common: VibeNodeSpec = {
    name,
    type,
    parent: parent || undefined,
    // `graph_design.json` v4 requires label; default to name for newly added nodes.
    label: name
  };
  if (type === 'Loop') return { ...common, max_iterations: 3 };
  if (type === 'Agent') return { ...common, agent: '', instructions: '', prompt_template: '' };
  if (type === 'CustomNode') {
    return graphFormat === 'v3' ? { ...common, code: '' } : { ...common, forward_body: '' };
  }
  if (type === 'LogicSwitch' || type === 'AgentSwitch') {
    return graphFormat === 'v3' ? { ...common, branches: [] } : { ...common, condition_bindings: [] };
  }
  return common;
}

export function baseNameForType(type: VibeNodeType): string {
  switch (type) {
    case 'Agent':
      return 'agent';
    case 'CustomNode':
      return 'custom_node';
    case 'Graph':
      return 'graph';
    case 'Loop':
      return 'loop';
    case 'LogicSwitch':
      return 'logic_switch';
    case 'AgentSwitch':
      return 'agent_switch';
    default:
      return 'node';
  }
}
