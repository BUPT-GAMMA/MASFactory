import type { VibeEdgeSpec, VibeGraphDesign, VibeNodeSpec } from '../stores/vibe';
import { normalizeGraphDesign } from '../stores/vibeModel';

export type AmlGraphParseResult = {
  version: string;
  graph: VibeGraphDesign;
  warnings: string[];
};

export type AmlImplementationExpansion = {
  nodes?: string[];
  nodeTypes?: Record<string, string>;
  edges?: Array<{ from?: string; to?: string; keysDetails?: Record<string, string>; keys?: string[] }>;
  nodeLineNumbers?: Record<string, number>;
  nodeFilePaths?: Record<string, string>;
  nodePullKeys?: Record<string, unknown>;
  nodePushKeys?: Record<string, unknown>;
  nodeAttributes?: Record<string, unknown>;
  subgraphs?: Record<string, string[]>;
  subgraphParents?: Record<string, string>;
  graphAttributesSummary?: Record<string, unknown>;
};

export type AmlPreviewTarget = {
  filePath?: string;
  line?: number;
  column?: number;
};

export type AmlImportedDocument = {
  alias?: string;
  filePath?: string;
  text?: string;
};

export type AmlExternalGraphWrite = {
  filePath: string;
  graphId: string;
  text: string;
};

export type AmlGraphParseOptions = {
  implementationGraphs?: Record<string, unknown>;
  implementationTargets?: Record<string, unknown>;
  importedDocuments?: Record<string, unknown>;
  graphId?: string;
};

type SerializeScope = {
  parent?: string;
  loopScope?: boolean;
  depth: number;
};

type AmlAgentDefinition = { instructions?: string; promptTemplate?: string };

type AmlDocumentContext = {
  root: Element;
  agentDefs: Map<string, AmlAgentDefinition>;
  graphDefs: Map<string, Element>;
  graphLines: Map<string, number>;
  importedDocs: Map<string, AmlDocumentContext>;
  filePath?: string;
  alias?: string;
};

type ResolvedGraphRef = {
  ref: string;
  graph: Element;
  ctx: AmlDocumentContext;
  graphId: string;
  filePath?: string;
  line?: number;
  external: boolean;
};

export const AML_ROOT_ATTRIBUTES_XML_KEY = '__aml_rootAttributesXml';
export const AML_ACTIVE_GRAPH_ID_KEY = '__aml_activeGraphId';

function localName(element: Element): string {
  return element.localName || element.nodeName;
}

function directChildren(parent: Element, tagName?: string): Element[] {
  const children = Array.from(parent.children || []);
  if (!tagName) return children;
  return children.filter((child) => localName(child) === tagName);
}

function firstDirect(parent: Element, tagName: string): Element | null {
  return directChildren(parent, tagName)[0] || null;
}

function attr(element: Element, name: string): string {
  return String(element.getAttribute(name) || '').trim();
}

function refId(value: string): string {
  const ref = String(value || '').trim();
  return ref.startsWith('#') ? ref.slice(1) : ref;
}

function endpointToInternal(endpoint: string, parent?: string, loopScope = false): string {
  const value = String(endpoint || '').trim();
  const lower = value.toLowerCase();
  if (parent) {
    if (loopScope) {
      if (lower === 'controller') return `${parent}.controller`;
      if (lower === 'terminate') return `${parent}.terminate`;
    } else {
      if (lower === 'entry') return `${parent}.entry`;
      if (lower === 'exit') return `${parent}.exit`;
    }
    return value;
  }
  if (lower === 'entry') return 'entry';
  if (lower === 'exit') return 'exit';
  return value;
}

function fieldDict(container: Element | null): Record<string, string> | undefined {
  if (!container) return undefined;
  const mode = attr(container, 'mode').toLowerCase();
  if (mode === 'all') return undefined;
  const out: Record<string, string> = {};
  for (const field of directChildren(container, 'field')) {
    const name = attr(field, 'name');
    if (!name) continue;
    out[name] = attr(field, 'description') || attr(field, 'type');
  }
  return out;
}

function attributesForNode(element: Element): Record<string, unknown> | undefined {
  const attributes = firstDirect(element, 'attributes');
  if (!attributes) return undefined;
  const out: Record<string, unknown> = {};
  for (const item of directChildren(attributes, 'attribute')) {
    const name = attr(item, 'name');
    if (!name) continue;
    const value = attr(item, 'value');
    out[name] = value || item.textContent?.trim() || '';
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

function applyAttributes(node: VibeNodeSpec, element: Element): void {
  const attributes = firstDirect(element, 'attributes');
  if (!attributes) return;
  const pull = fieldDict(firstDirect(attributes, 'pull_keys'));
  const push = fieldDict(firstDirect(attributes, 'push_keys'));
  const metadata = attributesForNode(element);
  if (pull !== undefined) node.pull_keys = pull;
  if (push !== undefined) node.push_keys = push;
  if (metadata !== undefined) node.attributes = metadata;
}

function edgeKeys(edge: Element): Record<string, string> | undefined {
  const keys = fieldDict(firstDirect(edge, 'keys'));
  return keys && Object.keys(keys).length > 0 ? keys : undefined;
}

function directGraphContainers(graph: Element): { nodes: Element | null; edges: Element | null } {
  return {
    nodes: firstDirect(graph, 'nodes'),
    edges: firstDirect(graph, 'edges')
  };
}

function hasInlineGraphBody(graph: Element): boolean {
  const containers = directGraphContainers(graph);
  return !!containers.nodes || !!containers.edges;
}

function agentDefinitions(root: Element): Map<string, AmlAgentDefinition> {
  const out = new Map<string, AmlAgentDefinition>();
  for (const agents of Array.from(root.getElementsByTagName('agents'))) {
    for (const agent of directChildren(agents, 'agent')) {
      const id = attr(agent, 'id');
      if (!id) continue;
      out.set(id, {
        instructions: attr(agent, 'instructions') || firstDirect(agent, 'instructions')?.textContent?.trim() || undefined,
        promptTemplate:
          attr(agent, 'prompt_template') || firstDirect(agent, 'prompt_template')?.textContent?.trim() || undefined
      });
    }
  }
  return out;
}

function graphDefinitions(root: Element): Map<string, Element> {
  const out = new Map<string, Element>();
  for (const graph of Array.from(root.getElementsByTagName('graph'))) {
    const id = attr(graph, 'id') || attr(graph, 'name');
    if (!id) continue;
    out.set(id, graph);
  }
  return out;
}

function graphDefinitionLines(source: string): Map<string, number> {
  const out = new Map<string, number>();
  const pattern = /<graph\b([^>]*?)>/gi;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(source || ''))) {
    const full = match[0] || '';
    if (full.startsWith('</')) continue;
    const attrs = match[1] || '';
    const idMatch = /\b(?:id|name)\s*=\s*(["'])(.*?)\1/i.exec(attrs);
    const id = String(idMatch?.[2] || '').trim();
    if (!id || out.has(id)) continue;
    out.set(id, 1 + (source.slice(0, match.index).match(/\n/g) || []).length);
  }
  return out;
}

function findRootGraph(root: Element): Element {
  const graphs = Array.from(root.getElementsByTagName('graph'));
  const rootGraph = graphs.find((graph) => attr(graph, 'kind') === 'root');
  if (rootGraph) return rootGraph;
  if (graphs[0]) return graphs[0];
  throw new Error('AML document must contain a <graph> element.');
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function asAmlPreviewTarget(value: unknown): AmlPreviewTarget | null {
  const record = asRecord(value);
  if (!record) return null;
  const filePath = typeof record.filePath === 'string' && record.filePath.trim() ? record.filePath.trim() : undefined;
  const line = Number(record.line);
  const column = Number(record.column);
  if (!filePath) return null;
  return {
    filePath,
    line: Number.isFinite(line) && line > 0 ? Math.floor(line) : undefined,
    column: Number.isFinite(column) && column > 0 ? Math.floor(column) : undefined
  };
}

function implementationTargetFor(
  implementation: string,
  options?: AmlGraphParseOptions
): AmlPreviewTarget | null {
  return asAmlPreviewTarget(options?.implementationTargets?.[implementation]);
}

function parseAmlDocument(text: string): Document {
  const parser = new DOMParser();
  const doc = parser.parseFromString(text || '', 'application/xml');
  const parserError = doc.getElementsByTagName('parsererror')[0];
  if (parserError) {
    throw new Error(parserError.textContent?.trim() || 'Invalid AML XML.');
  }
  return doc;
}

function buildAmlDocumentContext(
  root: Element,
  source: string,
  importedDocs: Map<string, AmlDocumentContext>,
  filePath?: string,
  alias?: string
): AmlDocumentContext {
  return {
    root,
    agentDefs: agentDefinitions(root),
    graphDefs: graphDefinitions(root),
    graphLines: graphDefinitionLines(source),
    importedDocs,
    filePath,
    alias
  };
}

function buildImportedDocumentContexts(options: AmlGraphParseOptions): Map<string, AmlDocumentContext> {
  const importedDocs = new Map<string, AmlDocumentContext>();
  const rawDocs = asRecord(options.importedDocuments);
  if (!rawDocs) return importedDocs;

  for (const [alias, raw] of Object.entries(rawDocs)) {
    const record = asRecord(raw);
    const text = typeof record?.text === 'string' ? record.text : '';
    if (!text.trim()) continue;
    try {
      const doc = parseAmlDocument(text);
      const root = doc.documentElement;
      if (!root || localName(root) !== 'aml') continue;
      const filePath = typeof record?.filePath === 'string' && record.filePath.trim() ? record.filePath.trim() : undefined;
      importedDocs.set(alias, buildAmlDocumentContext(root, text, importedDocs, filePath, alias));
    } catch {
      // Keep the current document preview usable even if one import is invalid.
    }
  }

  return importedDocs;
}

function splitQualifiedRef(ref: string): { alias?: string; id: string } {
  const value = refId(ref);
  const marker = value.indexOf('::');
  if (marker === -1) return { id: value };
  return {
    alias: value.slice(0, marker),
    id: value.slice(marker + 2)
  };
}

function resolveGraphRef(ref: string, ctx: AmlDocumentContext): ResolvedGraphRef | null {
  const normalized = refId(ref);
  if (!normalized) return null;
  const parsed = splitQualifiedRef(normalized);
  const targetCtx = parsed.alias ? ctx.importedDocs.get(parsed.alias) || null : ctx;
  if (!targetCtx) return null;
  const graph = targetCtx.graphDefs.get(parsed.id) || null;
  if (!graph) return null;
  return {
    ref: normalized,
    graph,
    ctx: targetCtx,
    graphId: parsed.id,
    filePath: targetCtx.filePath,
    line: targetCtx.graphLines.get(parsed.id),
    external: targetCtx !== ctx || !!parsed.alias
  };
}

function markRefPreview(
  parsed: { nodes: VibeNodeSpec[]; edges: VibeEdgeSpec[] },
  refInfo: ResolvedGraphRef,
  parentId: string
): { nodes: VibeNodeSpec[]; edges: VibeEdgeSpec[] } {
  const scopedName = (name: string): string => `${parentId}__${String(name || '').replace(/[^A-Za-z0-9_-]/g, '_')}`;
  const idMap = new Map<string, string>();
  for (const node of parsed.nodes) {
    const name = String((node as any)?.name || '').trim();
    if (!name || name === parentId || isBoundaryNode(name)) continue;
    if (!idMap.has(name)) idMap.set(name, scopedName(name));
  }
  const mapEndpoint = (endpoint: unknown): string => {
    const value = String(endpoint || '').trim();
    if (!value) return '';
    if (value === 'entry' || value === 'exit' || value === 'controller' || value === 'terminate') return value;
    if (value.startsWith(`${parentId}.`)) return value;
    const idx = value.indexOf('.');
    if (idx !== -1) {
      const base = value.slice(0, idx);
      const suffix = value.slice(idx + 1);
      const mapped = idMap.get(base);
      return mapped ? `${mapped}.${suffix}` : value;
    }
    return idMap.get(value) || value;
  };
  const childParentId = (value: unknown): string => {
    const existing = String((value as any)?.__aml_external_parent || '').trim();
    return existing ? mapEndpoint(existing) || existing : parentId;
  };
  const childFilePath = (value: unknown): string | undefined => {
    const existing = String((value as any)?.__aml_ref_filePath || '').trim();
    return existing || refInfo.filePath;
  };
  const childGraphId = (value: unknown): string => {
    const existing = String((value as any)?.__aml_ref_graphId || '').trim();
    return existing || refInfo.graphId;
  };

  return {
    nodes: parsed.nodes.map((node) => {
      const local = String((node as any).name || '');
      return {
        ...node,
        name: idMap.get(local) || node.name,
        parent:
          typeof node.parent === 'string' && node.parent
            ? node.parent === parentId
              ? parentId
              : idMap.get(node.parent) || node.parent
            : node.parent,
        __aml_from_ref: true,
        __aml_ref: (node as any).__aml_ref || refInfo.ref,
        __aml_ref_graphId: childGraphId(node),
        __aml_ref_filePath: childFilePath(node),
        __aml_ref_line: (node as any).__aml_ref_line || refInfo.line,
        __aml_external_parent: childParentId(node),
        __aml_external_local_name: local
      };
    }),
    edges: parsed.edges.map((edge) => ({
      ...edge,
      from: mapEndpoint(edge.from),
      to: mapEndpoint(edge.to),
      __aml_from_ref: true,
      __aml_ref: (edge as any).__aml_ref || refInfo.ref,
      __aml_ref_graphId: childGraphId(edge),
      __aml_ref_filePath: childFilePath(edge),
      __aml_ref_line: (edge as any).__aml_ref_line || refInfo.line,
      __aml_external_parent: childParentId(edge)
    }))
  };
}

function normalizePreviewType(type: unknown): VibeNodeSpec['type'] {
  const raw = typeof type === 'string' && type.trim() ? type.trim() : 'Node';
  const last = raw.includes('.') ? raw.split('.').pop() || raw : raw;
  if (last === 'Action' || last === 'SingleAgent') return 'Agent';
  if (last === 'Node') return 'CustomNode';
  if (last === 'Switch') return 'LogicSwitch';
  if (
    last === 'Loop' ||
    last === 'HubGraph' ||
    last === 'MeshGraph' ||
    last === 'InstructorAssistantGraph' ||
    last === 'PingPongGraph' ||
    last === 'VerticalDecisionGraph' ||
    last.endsWith('Loop')
  ) {
    return 'Loop';
  }
  if (last === 'RootGraph' || last.endsWith('Graph')) return 'Graph';
  return last;
}

function isBoundaryNode(id: string): boolean {
  const lower = String(id || '').toLowerCase();
  return lower === 'entry' || lower === 'exit' || lower === 'controller' || lower === 'terminate';
}

function splitLegacyBoundary(endpoint: string, idMap: Map<string, string>): { base: string; suffix: string } | null {
  const suffixes = ['_controller', '_terminate', '_entry', '_exit'];
  for (const suffix of suffixes) {
    if (!endpoint.endsWith(suffix)) continue;
    const base = endpoint.slice(0, -suffix.length);
    if (!base || !idMap.has(base)) continue;
    return { base, suffix: suffix.slice(1) };
  }
  return null;
}

function mapGraphEndpoint(endpoint: string, parentId: string, idMap: Map<string, string>): string {
  const value = String(endpoint || '').trim();
  const lower = value.toLowerCase();
  if (lower === 'entry') return `${parentId}.entry`;
  if (lower === 'exit') return `${parentId}.exit`;
  if (lower === 'controller') return `${parentId}.controller`;
  if (lower === 'terminate') return `${parentId}.terminate`;

  const legacyBoundary = splitLegacyBoundary(value, idMap);
  if (legacyBoundary) {
    return `${idMap.get(legacyBoundary.base)}.${legacyBoundary.suffix}`;
  }

  return idMap.get(value) || `${parentId}__${value.replace(/[^A-Za-z0-9_-]/g, '_')}`;
}

function objectKeysToDescriptions(value: unknown): Record<string, string> | undefined {
  if (value === null || value === undefined || value === 'empty') return {};
  if (typeof value !== 'object' || Array.isArray(value)) return undefined;
  const out: Record<string, string> = {};
  for (const [key, desc] of Object.entries(value as Record<string, unknown>)) {
    out[key] = desc === undefined || desc === null ? '' : String(desc);
  }
  return out;
}

function hasConcreteSubgraphBody(expansion: AmlImplementationExpansion, nodeName: string): boolean {
  const subgraphs = asRecord(expansion.subgraphs);
  const children = Array.isArray(subgraphs?.[nodeName]) ? (subgraphs[nodeName] as unknown[]) : [];
  return children.some((child) => {
    const value = typeof child === 'string' ? child : '';
    if (!value) return false;
    if (isBoundaryNode(value)) return false;
    if (value.endsWith('_entry') || value.endsWith('_exit')) return false;
    if (value.endsWith('_controller') || value.endsWith('_terminate')) return false;
    return true;
  });
}

function implementationExpansionFor(
  implementation: string,
  options?: AmlGraphParseOptions
): AmlImplementationExpansion | null {
  const raw = options?.implementationGraphs?.[implementation];
  const record = asRecord(raw);
  if (!record || !Array.isArray(record.nodes)) return null;
  return record as AmlImplementationExpansion;
}

function expansionHasUsableTopology(
  parentId: string,
  nodeNames: Set<string>,
  edges: VibeEdgeSpec[],
  loopScope: boolean
): boolean {
  if (nodeNames.size === 0 || edges.length === 0) return false;

  if (loopScope) {
    const controller = `${parentId}.controller`;
    const hasControllerToNode = edges.some((edge) => edge.from === controller && nodeNames.has(String(edge.to || '')));
    const hasNodeToControllerOrTerminate = edges.some((edge) => {
      const from = String(edge.from || '');
      const to = String(edge.to || '');
      return nodeNames.has(from) && (to === controller || to === `${parentId}.terminate`);
    });
    return hasControllerToNode && hasNodeToControllerOrTerminate;
  }

  const entry = `${parentId}.entry`;
  const exit = `${parentId}.exit`;
  const hasEntryToNode = edges.some((edge) => edge.from === entry && nodeNames.has(String(edge.to || '')));
  const hasNodeToExit = edges.some((edge) => nodeNames.has(String(edge.from || '')) && edge.to === exit);
  return hasEntryToNode && hasNodeToExit;
}

function expansionToScopedGraph(
  expansion: AmlImplementationExpansion,
  parentId: string,
  loopScope: boolean,
  target?: AmlPreviewTarget | null
): { nodes: VibeNodeSpec[]; edges: VibeEdgeSpec[] } | null {
  const rawNodes = Array.isArray(expansion.nodes)
    ? expansion.nodes.filter((node): node is string => typeof node === 'string' && !!node.trim())
    : [];
  const nodeTypes = asRecord(expansion.nodeTypes) || {};
  const subgraphParents = asRecord(expansion.subgraphParents) || {};
  const idMap = new Map<string, string>();
  const nodeNames = new Set<string>();
  const nodes: VibeNodeSpec[] = [];

  for (const rawName of rawNodes) {
    if (isBoundaryNode(rawName) || rawName.endsWith('_entry') || rawName.endsWith('_exit')) continue;
    if (rawName.endsWith('_controller') || rawName.endsWith('_terminate')) continue;
    const mapped = `${parentId}__${rawName.replace(/[^A-Za-z0-9_-]/g, '_')}`;
    idMap.set(rawName, mapped);
    nodeNames.add(mapped);
  }

  for (const rawName of rawNodes) {
    const mapped = idMap.get(rawName);
    if (!mapped) continue;
    const localParent = typeof subgraphParents[rawName] === 'string' ? String(subgraphParents[rawName]) : '';
    const mappedParent = localParent && idMap.has(localParent) ? idMap.get(localParent) : parentId;

    const node: VibeNodeSpec = {
      name: mapped,
      type: normalizePreviewType(nodeTypes[rawName]),
      label: rawName,
      parent: mappedParent || parentId,
      __aml_from_implementation: true
    };
    if (target?.filePath) {
      node.__aml_implementation_filePath = target.filePath;
      node.__aml_implementation_line =
        Number(expansion.nodeLineNumbers?.[rawName]) > 0 ? expansion.nodeLineNumbers?.[rawName] : target.line;
      node.__aml_implementation_column = target.column;
    }

    if ((node.type === 'Graph' || node.type === 'Loop') && !hasConcreteSubgraphBody(expansion, rawName)) {
      node.__aml_opaque = true;
    }

    const pull = objectKeysToDescriptions(expansion.nodePullKeys?.[rawName]);
    const push = objectKeysToDescriptions(expansion.nodePushKeys?.[rawName]);
    const attrs = asRecord(expansion.nodeAttributes?.[rawName]);
    if (pull !== undefined) node.pull_keys = pull;
    if (push !== undefined) node.push_keys = push;
    if (attrs) node.attributes = attrs;
    nodes.push(node);
  }

  const edges: VibeEdgeSpec[] = [];
  const rawEdges = Array.isArray(expansion.edges) ? expansion.edges : [];
  for (const edge of rawEdges) {
    if (!edge || typeof edge !== 'object') continue;
    const from = mapGraphEndpoint(String(edge.from || ''), parentId, idMap);
    const to = mapGraphEndpoint(String(edge.to || ''), parentId, idMap);
    if (!from || !to || from === to) continue;

    const spec: VibeEdgeSpec = { from, to };
    spec.__aml_from_implementation = true;
    if (target?.filePath) {
      spec.__aml_implementation_filePath = target.filePath;
      spec.__aml_implementation_line = target.line;
      spec.__aml_implementation_column = target.column;
    }
    if (edge.keysDetails && typeof edge.keysDetails === 'object') {
      spec.keys = edge.keysDetails;
    } else if (Array.isArray(edge.keys) && edge.keys.length > 0) {
      spec.keys = Object.fromEntries(edge.keys.map((key) => [String(key), '']));
    }
    edges.push(spec);
  }

  if (!expansionHasUsableTopology(parentId, nodeNames, edges, loopScope)) {
    return null;
  }

  return { nodes, edges };
}

function parseNode(
  element: Element,
  ctx: AmlDocumentContext,
  options: AmlGraphParseOptions,
  parent?: string
): { node: VibeNodeSpec | null; children: VibeNodeSpec[]; edges: VibeEdgeSpec[] } {
  const tag = localName(element);
  const id = attr(element, 'id') || attr(element, 'name');
  if (!id) return { node: null, children: [], edges: [] };

  const node: VibeNodeSpec = {
    name: id,
    type: 'Agent',
    label: attr(element, 'label') || id,
    parent
  };
  const children: VibeNodeSpec[] = [];
  const edges: VibeEdgeSpec[] = [];

  if (tag === 'agent') {
    const ref = refId(attr(element, 'ref')) || id;
    const def = ctx.agentDefs.get(ref) || {};
    node.type = 'Agent';
    node.agent = ref;
    node.instructions =
      attr(element, 'instructions') ||
      firstDirect(element, 'instructions')?.textContent?.trim() ||
      def.instructions ||
      undefined;
    node.prompt_template =
      attr(element, 'prompt_template') ||
      firstDirect(element, 'prompt_template')?.textContent?.trim() ||
      def.promptTemplate ||
      undefined;
  } else if (tag === 'custom_node') {
    node.type = 'CustomNode';
    const forward = attr(element, 'forward');
    if (forward) node.forward_body = forward;
  } else if (tag === 'logic_switch' || tag === 'switch') {
    node.type = 'LogicSwitch';
  } else if (tag === 'agent_switch') {
    node.type = 'AgentSwitch';
  } else if (tag === 'graph') {
    node.type = 'Graph';
    const ref = refId(attr(element, 'ref'));
    const refInfo = ref ? resolveGraphRef(ref, ctx) : null;
    const refGraph = refInfo?.graph || null;
    const implementation = attr(element, 'implementation') || (refGraph ? attr(refGraph, 'implementation') : '');
    if (ref) node.ref = ref;
    if (refInfo) {
      node.__aml_ref_expanded = true;
      node.__aml_ref_graphId = refInfo.graphId;
      node.__aml_ref_filePath = refInfo.filePath;
      node.__aml_ref_line = refInfo.line;
    }
    if (implementation) {
      node.implementation = implementation;
      if (refGraph && !attr(element, 'implementation')) node.__aml_inherited_implementation = true;
      const target = implementationTargetFor(implementation, options);
      if (target?.filePath) {
        node.__aml_implementation_filePath = target.filePath;
        node.__aml_implementation_line = target.line;
        node.__aml_implementation_column = target.column;
      }
    }
    const expansion = implementation ? implementationExpansionFor(implementation, options) : null;
    const target = implementation ? implementationTargetFor(implementation, options) : null;
    const expanded = expansion ? expansionToScopedGraph(expansion, id, false, target) : null;
    if (expanded) {
      node.__aml_implementation_expanded = true;
      children.push(...expanded.nodes);
      edges.push(...expanded.edges);
    } else if (hasInlineGraphBody(element)) {
      const nested = parseGraphScope(element, ctx, options, id, false);
      children.push(...nested.nodes);
      edges.push(...nested.edges);
    } else if (refInfo && hasInlineGraphBody(refInfo.graph)) {
      const nested = markRefPreview(parseGraphScope(refInfo.graph, refInfo.ctx, options, id, false), refInfo, id);
      children.push(...nested.nodes);
      edges.push(...nested.edges);
    } else {
      node.__aml_opaque = true;
    }
  } else if (tag === 'loop') {
    node.type = 'Loop';
    const maxIterations = Number(attr(element, 'max_iterations') || '0');
    if (Number.isFinite(maxIterations) && maxIterations > 0) node.max_iterations = maxIterations;
    const terminate = firstDirect(element, 'terminate');
    if (terminate) {
      const match = attr(terminate, 'match');
      const expr = attr(terminate, 'if');
      if (match) node.terminate_condition_prompt = match;
      else if (expr) node.terminate_condition_expr = expr;
      else if (terminate.textContent?.trim()) node.terminate_condition_prompt = terminate.textContent.trim();
    }
    const implementation = attr(element, 'implementation');
    if (implementation) {
      node.implementation = implementation;
      const target = implementationTargetFor(implementation, options);
      if (target?.filePath) {
        node.__aml_implementation_filePath = target.filePath;
        node.__aml_implementation_line = target.line;
        node.__aml_implementation_column = target.column;
      }
    }
    const expansion = implementation ? implementationExpansionFor(implementation, options) : null;
    const target = implementation ? implementationTargetFor(implementation, options) : null;
    const expanded = expansion ? expansionToScopedGraph(expansion, id, true, target) : null;
    if (expanded) {
      node.__aml_implementation_expanded = true;
      children.push(...expanded.nodes);
      edges.push(...expanded.edges);
    } else if (hasInlineGraphBody(element)) {
      const nested = parseGraphScope(element, ctx, options, id, true);
      children.push(...nested.nodes);
      edges.push(...nested.edges);
    } else {
      node.__aml_opaque = true;
    }
  } else {
    return { node: null, children: [], edges: [] };
  }

  applyAttributes(node, element);
  return { node, children, edges };
}

function parseGraphScope(
  graph: Element,
  ctx: AmlDocumentContext,
  options: AmlGraphParseOptions,
  parent?: string,
  loopScope = false
): { nodes: VibeNodeSpec[]; edges: VibeEdgeSpec[] } {
  const nodes: VibeNodeSpec[] = [];
  const edges: VibeEdgeSpec[] = [];
  const { nodes: nodesContainer, edges: edgesContainer } = directGraphContainers(graph);

  if (nodesContainer) {
    for (const child of directChildren(nodesContainer)) {
      const parsed = parseNode(child, ctx, options, parent);
      if (parsed.node) nodes.push(parsed.node);
      nodes.push(...parsed.children);
      edges.push(...parsed.edges);
    }
  }

  if (edgesContainer) {
    for (const edge of directChildren(edgesContainer, 'edge')) {
      const from = endpointToInternal(attr(edge, 'from'), parent, loopScope);
      const to = endpointToInternal(attr(edge, 'to'), parent, loopScope);
      if (!from || !to) continue;
      const spec: VibeEdgeSpec = { from, to };
      const expr = attr(edge, 'if');
      const match = attr(edge, 'match');
      if (expr) {
        spec.condition = expr;
        spec.condition_kind = 'if';
      } else if (match) {
        spec.condition = match;
        spec.condition_kind = 'match';
      }
      const keys = edgeKeys(edge);
      if (keys) spec.keys = keys;
      edges.push(spec);
    }
  }

  return { nodes, edges };
}

export function parseAmlGraphDesign(source: string, options: AmlGraphParseOptions = {}): AmlGraphParseResult {
  const doc = parseAmlDocument(source);
  const root = doc.documentElement;
  if (!root || localName(root) !== 'aml') {
    throw new Error('AML document root must be <aml>.');
  }

  const version = attr(root, 'version') || '0.2';
  if (version !== '0.2') {
    throw new Error(`Unsupported AML version "${version}". Supported versions: 0.2.`);
  }

  const importedDocs = buildImportedDocumentContexts(options);
  const ctx = buildAmlDocumentContext(root, source, importedDocs);
  const graph =
    typeof options.graphId === 'string' && options.graphId.trim()
      ? ctx.graphDefs.get(options.graphId.trim()) || findRootGraph(root)
      : findRootGraph(root);
  const parsed = parseGraphScope(graph, ctx, options);
  const rawGraph: VibeGraphDesign = { Nodes: parsed.nodes, Edges: parsed.edges };
  const activeGraphId = attr(graph, 'id') || attr(graph, 'name');
  if (activeGraphId) {
    (rawGraph as any)[AML_ACTIVE_GRAPH_ID_KEY] = activeGraphId;
  }
  const rootAttributesXml = rootGraphContainerSource(source, 'attributes', activeGraphId);
  if (rootAttributesXml !== undefined) {
    (rawGraph as any)[AML_ROOT_ATTRIBUTES_XML_KEY] = rootAttributesXml;
  }
  const warnings: string[] = [];
  if (parsed.nodes.length === 0) warnings.push('The root graph has no visible AML nodes.');
  return {
    version,
    graph: normalizeGraphDesign(rawGraph),
    warnings
  };
}

function escapeXml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function indent(depth: number): string {
  return '  '.repeat(Math.max(0, depth));
}

function isDerivedNode(node: VibeNodeSpec): boolean {
  return !!(node.__aml_from_implementation || node.__aml_from_ref);
}

function isDerivedEdge(edge: VibeEdgeSpec): boolean {
  return !!(edge.__aml_from_implementation || edge.__aml_from_ref);
}

function isRecordLike(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function externalRefFilePath(value: unknown): string {
  return String((value as any)?.__aml_ref_filePath || '').trim();
}

function externalRefGraphId(value: unknown): string {
  return String((value as any)?.__aml_ref_graphId || '').trim();
}

function externalRefParent(value: unknown): string {
  return String((value as any)?.__aml_external_parent || '').trim();
}

function isExternalRefNode(node: VibeNodeSpec | null | undefined): boolean {
  return !!node && !!(node as any).__aml_from_ref;
}

function isExternalRefEdge(edge: VibeEdgeSpec | null | undefined): boolean {
  return !!edge && !!(edge as any).__aml_from_ref;
}

function importedDocumentsByFilePath(importedDocuments?: Record<string, unknown>): Map<string, AmlImportedDocument> {
  const out = new Map<string, AmlImportedDocument>();
  const docs = asRecord(importedDocuments);
  if (!docs) return out;
  for (const [alias, raw] of Object.entries(docs)) {
    const record = asRecord(raw);
    if (!record) continue;
    const filePath = typeof record.filePath === 'string' && record.filePath.trim() ? record.filePath.trim() : '';
    const text = typeof record.text === 'string' ? record.text : '';
    if (!filePath || !text) continue;
    out.set(filePath, {
      alias: typeof record.alias === 'string' && record.alias.trim() ? record.alias.trim() : alias,
      filePath,
      text
    });
  }
  return out;
}

function stripAmlPrivateFields<T extends Record<string, unknown>>(value: T): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (key.startsWith('__aml_')) continue;
    out[key] = item;
  }
  return out;
}

function localizeExternalEndpoint(endpoint: unknown, parentId: string): string {
  const value = String(endpoint || '').trim();
  if (!value) return '';
  if (value === parentId) return '';
  const boundaryPrefix = `${parentId}.`;
  if (value.startsWith(boundaryPrefix)) return value.slice(boundaryPrefix.length);
  const nodePrefix = `${parentId}__`;
  if (value.startsWith(nodePrefix)) return value.slice(nodePrefix.length);
  const idx = value.indexOf('.');
  if (idx !== -1) {
    const base = value.slice(0, idx);
    const suffix = value.slice(idx + 1);
    if (base === parentId) return suffix;
    if (base.startsWith(nodePrefix)) return `${base.slice(nodePrefix.length)}.${suffix}`;
  }
  return value;
}

function localizeExternalNode(node: VibeNodeSpec, parentId: string): VibeNodeSpec | null {
  const rawName = String((node as any).name || '').trim();
  const name = localizeExternalEndpoint(rawName, parentId) || String((node as any).__aml_external_local_name || '').trim();
  if (!name || isBoundaryNode(name)) return null;

  const out = stripAmlPrivateFields(node as any) as VibeNodeSpec;
  out.name = name;
  const parent = localizeExternalEndpoint((node as any).parent, parentId);
  if (parent) out.parent = parent;
  else delete (out as any).parent;
  if (typeof out.label === 'string' && out.label === rawName) {
    out.label = name;
  }
  return out;
}

function localizeExternalEdge(edge: VibeEdgeSpec, parentId: string): VibeEdgeSpec | null {
  const from = localizeExternalEndpoint((edge as any).from, parentId);
  const to = localizeExternalEndpoint((edge as any).to, parentId);
  if (!from || !to) return null;
  return {
    ...(stripAmlPrivateFields(edge as any) as VibeEdgeSpec),
    from,
    to
  };
}

function externalEdgeSignature(edge: VibeEdgeSpec): string {
  return JSON.stringify(edge);
}

function parentOfEndpointForSave(endpoint: string, parentByName: Record<string, string | undefined>): string | undefined {
  const ep = String(endpoint || '');
  if (ep === 'entry' || ep === 'exit') return undefined;
  const idx = ep.indexOf('.');
  if (idx !== -1) {
    const base = ep.slice(0, idx);
    const suffix = ep.slice(idx + 1);
    if (suffix === 'entry' || suffix === 'exit' || suffix === 'controller' || suffix === 'terminate') return base;
    return parentByName[base];
  }
  return parentByName[ep];
}

function endpointToAml(endpoint: string, scope: SerializeScope): string {
  const ep = String(endpoint || '');
  if (!scope.parent) return ep;
  const prefix = `${scope.parent}.`;
  if (!ep.startsWith(prefix)) return ep;
  const suffix = ep.slice(prefix.length);
  if (suffix === 'entry' || suffix === 'exit' || suffix === 'controller' || suffix === 'terminate') return suffix;
  return ep;
}

function serializeFieldMap(tag: string, value: unknown, depth: number): string[] {
  if (value === undefined) return [];
  if (value === null) return [`${indent(depth)}<${tag} mode="all" />`];
  if (!isRecordLike(value) || Object.keys(value).length === 0) return [`${indent(depth)}<${tag} mode="keys" />`];
  const lines = [`${indent(depth)}<${tag} mode="keys">`];
  for (const [name, desc] of Object.entries(value)) {
    const attrs = [`name="${escapeXml(name)}"`];
    if (desc !== undefined && desc !== null && String(desc)) attrs.push(`description="${escapeXml(desc)}"`);
    lines.push(`${indent(depth + 1)}<field ${attrs.join(' ')} />`);
  }
  lines.push(`${indent(depth)}</${tag}>`);
  return lines;
}

function serializeAttributes(node: VibeNodeSpec, depth: number): string[] {
  const lines: string[] = [];
  const pull = node.pull_keys;
  const push = node.push_keys;
  const attrs = isRecordLike(node.attributes) ? node.attributes : null;
  if (pull === undefined && push === undefined && (!attrs || Object.keys(attrs).length === 0)) return lines;

  lines.push(`${indent(depth)}<attributes>`);
  lines.push(...serializeFieldMap('pull_keys', pull, depth + 1));
  lines.push(...serializeFieldMap('push_keys', push, depth + 1));
  if (attrs) {
    for (const [name, value] of Object.entries(attrs)) {
      if (isRecordLike(value) || Array.isArray(value)) {
        lines.push(`${indent(depth + 1)}<attribute name="${escapeXml(name)}">${escapeXml(JSON.stringify(value))}</attribute>`);
      } else {
        lines.push(`${indent(depth + 1)}<attribute name="${escapeXml(name)}" value="${escapeXml(value)}" />`);
      }
    }
  }
  lines.push(`${indent(depth)}</attributes>`);
  return lines;
}

function serializeEdgeKeys(edge: VibeEdgeSpec, depth: number): string[] {
  const keys = edge.keys;
  if (!isRecordLike(keys) || Object.keys(keys).length === 0) return [];
  const lines = [`${indent(depth)}<keys>`];
  for (const [name, desc] of Object.entries(keys)) {
    const attrs = [`name="${escapeXml(name)}"`];
    if (desc !== undefined && desc !== null && String(desc)) attrs.push(`description="${escapeXml(desc)}"`);
    lines.push(`${indent(depth + 1)}<field ${attrs.join(' ')} />`);
  }
  lines.push(`${indent(depth)}</keys>`);
  return lines;
}

function serializeNode(
  node: VibeNodeSpec,
  graph: VibeGraphDesign,
  childrenByParent: Map<string | undefined, VibeNodeSpec[]>,
  edgesByScope: Map<string | undefined, VibeEdgeSpec[]>,
  scope: SerializeScope
): string[] {
  const type = String(node.type || 'Agent');
  const id = String(node.name || '').trim();
  if (!id || isDerivedNode(node)) return [];

  const tag =
    type === 'CustomNode'
      ? 'custom_node'
      : type === 'Loop'
        ? 'loop'
        : type === 'Graph' || type === 'Subgraph'
          ? 'graph'
          : type === 'LogicSwitch'
            ? 'logic_switch'
            : type === 'AgentSwitch'
              ? 'agent_switch'
              : 'agent';

  const attrs = [`id="${escapeXml(id)}"`];
  if (typeof node.label === 'string' && node.label && node.label !== id) attrs.push(`label="${escapeXml(node.label)}"`);
  if (tag === 'agent' && typeof node.agent === 'string' && node.agent) attrs.push(`ref="#${escapeXml(node.agent)}"`);
  if (tag === 'custom_node' && typeof node.forward_body === 'string' && node.forward_body) {
    attrs.push(`forward="${escapeXml(node.forward_body)}"`);
  }
  if ((tag === 'graph' || tag === 'loop') && typeof node.ref === 'string' && node.ref) {
    attrs.push(`ref="#${escapeXml(node.ref)}"`);
  }
  if (
    (tag === 'graph' || tag === 'loop') &&
    typeof node.implementation === 'string' &&
    node.implementation &&
    !node.__aml_inherited_implementation
  ) {
    attrs.push(`implementation="${escapeXml(node.implementation)}"`);
  }
  if (tag === 'loop' && Number.isFinite(Number(node.max_iterations))) {
    attrs.push(`max_iterations="${escapeXml(Number(node.max_iterations))}"`);
  }

  const childNodes = childrenByParent.get(id) || [];
  const scopedEdges = edgesByScope.get(id) || [];
  const body: string[] = [];
  if (tag === 'loop') {
    const terminateMatch = String(node.terminate_condition_prompt || '').trim();
    const terminateIf = String(node.terminate_condition_expr || node.terminate_condition_code || '').trim();
    if (terminateMatch) body.push(`${indent(scope.depth + 1)}<terminate match="${escapeXml(terminateMatch)}" />`);
    else if (terminateIf) body.push(`${indent(scope.depth + 1)}<terminate if="${escapeXml(terminateIf)}" />`);
  }
  body.push(...serializeAttributes(node, scope.depth + 1));
  if (childNodes.length > 0) {
    body.push(`${indent(scope.depth + 1)}<nodes>`);
    for (const child of childNodes) {
      body.push(
        ...serializeNode(child, graph, childrenByParent, edgesByScope, {
          parent: id,
          loopScope: tag === 'loop',
          depth: scope.depth + 2
        })
      );
    }
    body.push(`${indent(scope.depth + 1)}</nodes>`);
  }
  if (scopedEdges.length > 0) {
    body.push(`${indent(scope.depth + 1)}<edges>`);
    for (const edge of scopedEdges) {
      body.push(...serializeEdge(edge, { parent: id, loopScope: tag === 'loop', depth: scope.depth + 2 }));
    }
    body.push(`${indent(scope.depth + 1)}</edges>`);
  }

  if (body.length === 0) return [`${indent(scope.depth)}<${tag} ${attrs.join(' ')} />`];
  return [`${indent(scope.depth)}<${tag} ${attrs.join(' ')}>`, ...body, `${indent(scope.depth)}</${tag}>`];
}

function serializeEdge(edge: VibeEdgeSpec, scope: SerializeScope): string[] {
  if (isDerivedEdge(edge)) return [];
  const from = endpointToAml(String(edge.from || ''), scope);
  const to = endpointToAml(String(edge.to || ''), scope);
  if (!from || !to) return [];
  const attrs = [`from="${escapeXml(from)}"`, `to="${escapeXml(to)}"`];
  const condition = typeof edge.condition === 'string' ? edge.condition.trim() : '';
  const conditionKind = typeof edge.condition_kind === 'string' ? edge.condition_kind : '';
  if (condition) attrs.push(`${conditionKind === 'match' ? 'match' : 'if'}="${escapeXml(condition)}"`);
  const keys = serializeEdgeKeys(edge, scope.depth + 1);
  if (keys.length === 0) return [`${indent(scope.depth)}<edge ${attrs.join(' ')} />`];
  return [`${indent(scope.depth)}<edge ${attrs.join(' ')}>`, ...keys, `${indent(scope.depth)}</edge>`];
}

function buildSerializableGraph(graph: VibeGraphDesign): {
  childrenByParent: Map<string | undefined, VibeNodeSpec[]>;
  edgesByScope: Map<string | undefined, VibeEdgeSpec[]>;
} {
  const nodes = Array.isArray(graph.Nodes) ? graph.Nodes.filter((node) => node && !isDerivedNode(node)) : [];
  const parentByName: Record<string, string | undefined> = {};
  const childrenByParent = new Map<string | undefined, VibeNodeSpec[]>();
  for (const node of nodes) {
    const id = String(node.name || '').trim();
    if (!id) continue;
    const parent = typeof node.parent === 'string' && node.parent.trim() ? node.parent.trim() : undefined;
    parentByName[id] = parent;
    const list = childrenByParent.get(parent) || [];
    list.push(node);
    childrenByParent.set(parent, list);
  }

  const edgesByScope = new Map<string | undefined, VibeEdgeSpec[]>();
  const edges = Array.isArray(graph.Edges) ? graph.Edges.filter((edge) => edge && !isDerivedEdge(edge)) : [];
  for (const edge of edges) {
    const fromParent = parentOfEndpointForSave(String(edge.from || ''), parentByName);
    const toParent = parentOfEndpointForSave(String(edge.to || ''), parentByName);
    if (fromParent !== toParent) continue;
    const list = edgesByScope.get(fromParent) || [];
    list.push(edge);
    edgesByScope.set(fromParent, list);
  }
  return { childrenByParent, edgesByScope };
}

function serializeNodesContainer(graph: VibeGraphDesign, depth: number): string {
  const { childrenByParent, edgesByScope } = buildSerializableGraph(graph);
  const lines = [`${indent(depth)}<nodes>`];
  for (const node of childrenByParent.get(undefined) || []) {
    lines.push(...serializeNode(node, graph, childrenByParent, edgesByScope, { depth: depth + 1 }));
  }
  lines.push(`${indent(depth)}</nodes>`);
  return lines.join('\n');
}

function serializeEdgesContainer(graph: VibeGraphDesign, depth: number): string {
  const { edgesByScope } = buildSerializableGraph(graph);
  const lines = [`${indent(depth)}<edges>`];
  for (const edge of edgesByScope.get(undefined) || []) {
    lines.push(...serializeEdge(edge, { depth: depth + 1 }));
  }
  lines.push(`${indent(depth)}</edges>`);
  return lines.join('\n');
}

function rootGraphRange(source: string, graphId?: string): { start: number; end: number; openEnd: number } {
  const findGraphEnd = (openEnd: number): number | null => {
    const closePattern = /<(\/?)graph\b([^>]*?)(\/?)>/gi;
    closePattern.lastIndex = openEnd;
    let depth = 1;
    let inner: RegExpExecArray | null;
    while ((inner = closePattern.exec(source))) {
      const innerFull = inner[0];
      const innerClosing = !!inner[1];
      const innerSelfClosing = !!inner[3] || innerFull.endsWith('/>');
      if (innerClosing) {
        depth--;
        if (depth === 0) return inner.index + innerFull.length;
      } else if (!innerSelfClosing) {
        depth++;
      }
    }
    return null;
  };

  const tagPattern = /<(\/?)graph\b([^>]*?)(\/?)>/gi;
  let firstGraph: { start: number; openEnd: number } | null = null;
  let match: RegExpExecArray | null;
  while ((match = tagPattern.exec(source))) {
    const full = match[0];
    const closing = !!match[1];
    const body = match[2] || '';
    const selfClosing = !!match[3] || full.endsWith('/>');
    if (closing || selfClosing) continue;

    const start = match.index;
    const openEnd = start + full.length;
    if (!firstGraph) firstGraph = { start, openEnd };
    if (graphId) {
      const idMatch = /\b(?:id|name)\s*=\s*(["'])(.*?)\1/i.exec(body);
      if (String(idMatch?.[2] || '').trim() === graphId) {
        const end = findGraphEnd(openEnd);
        if (end !== null) return { start, end, openEnd };
      }
    }
    if (!graphId && /\bkind\s*=\s*(["'])root\1/i.test(body)) {
      const end = findGraphEnd(openEnd);
      if (end !== null) return { start, end, openEnd };
    }
  }
  if (firstGraph) {
    const end = findGraphEnd(firstGraph.openEnd);
    if (end !== null) return { start: firstGraph.start, end, openEnd: firstGraph.openEnd };
  }
  throw new Error('Cannot locate a writable root <graph> in AML source.');
}

function xmlLocalName(name: string): string {
  const value = String(name || '').toLowerCase();
  const idx = value.indexOf(':');
  return idx === -1 ? value : value.slice(idx + 1);
}

function matchingElementEnd(text: string, tag: string, openEnd: number): number | null {
  const tokenPattern = /<(\/?)([A-Za-z_][\w:.-]*)(?:\s[^<>]*?)?(\/?)>/g;
  tokenPattern.lastIndex = openEnd;
  let depth = 1;
  let match: RegExpExecArray | null;
  while ((match = tokenPattern.exec(text))) {
    const full = match[0];
    const closing = !!match[1];
    const name = xmlLocalName(match[2] || '');
    const selfClosing = !!match[3] || full.endsWith('/>');
    if (name !== tag) continue;
    if (closing) {
      depth--;
      if (depth === 0) return match.index + full.length;
    } else if (!selfClosing) {
      depth++;
    }
  }
  return null;
}

function directContainerRange(rootText: string, tag: 'nodes' | 'edges' | 'attributes'): { start: number; end: number } | null {
  const rootOpen = rootText.match(/^<graph\b[^>]*>/i);
  if (!rootOpen) return null;
  const tokenPattern = /<(\/?)([A-Za-z_][\w:.-]*)(?:\s[^<>]*?)?(\/?)>/g;
  tokenPattern.lastIndex = rootOpen[0].length;
  let depth = 1;
  let match: RegExpExecArray | null;
  while ((match = tokenPattern.exec(rootText))) {
    const full = match[0];
    const closing = !!match[1];
    const name = xmlLocalName(match[2] || '');
    const selfClosing = !!match[3] || full.endsWith('/>');
    if (!closing && depth === 1 && name === tag) {
      if (selfClosing) return { start: match.index, end: match.index + full.length };
      const end = matchingElementEnd(rootText, tag, match.index + full.length);
      return end === null ? null : { start: match.index, end };
    }
    if (closing) depth--;
    else if (!selfClosing) depth++;
  }
  return null;
}

function rootGraphContainerSource(source: string, tag: 'nodes' | 'edges' | 'attributes', graphId?: string): string | undefined {
  try {
    const range = rootGraphRange(source, graphId);
    const rootText = source.slice(range.start, range.end);
    const childRange = directContainerRange(rootText, tag);
    if (!childRange) return undefined;
    return rootText.slice(childRange.start, childRange.end);
  } catch {
    return undefined;
  }
}

function replaceOrInsertContainer(rootText: string, tag: 'nodes' | 'edges' | 'attributes', xml: string): string {
  const range = directContainerRange(rootText, tag);
  if (!xml.trim()) {
    if (!range) return rootText;
    return rootText.slice(0, range.start) + rootText.slice(range.end);
  }
  if (range) {
    return rootText.slice(0, range.start) + xml + rootText.slice(range.end);
  }
  if (tag === 'attributes') {
    const nodesRange = directContainerRange(rootText, 'nodes');
    if (nodesRange) {
      return rootText.slice(0, nodesRange.start) + xml + '\n' + rootText.slice(nodesRange.start);
    }
  }
  const open = rootText.match(/^<graph\b[^>]*>/i);
  if (!open) return rootText;
  return rootText.slice(0, open[0].length) + '\n' + xml + rootText.slice(open[0].length);
}

export function serializeAmlGraphDesign(source: string, graph: VibeGraphDesign): string {
  const graphId =
    typeof (graph as any)[AML_ACTIVE_GRAPH_ID_KEY] === 'string' ? String((graph as any)[AML_ACTIVE_GRAPH_ID_KEY]) : '';
  const range = rootGraphRange(source, graphId || undefined);
  let rootText = source.slice(range.start, range.end);
  if (Object.prototype.hasOwnProperty.call(graph as any, AML_ROOT_ATTRIBUTES_XML_KEY)) {
    rootText = replaceOrInsertContainer(rootText, 'attributes', String((graph as any)[AML_ROOT_ATTRIBUTES_XML_KEY] || ''));
  }
  rootText = replaceOrInsertContainer(rootText, 'nodes', serializeNodesContainer(graph, 2));
  rootText = replaceOrInsertContainer(rootText, 'edges', serializeEdgesContainer(graph, 2));
  return source.slice(0, range.start) + rootText + source.slice(range.end);
}

export function serializeAmlExternalGraphEdits(
  graph: VibeGraphDesign,
  importedDocuments?: Record<string, unknown>
): AmlExternalGraphWrite[] {
  const docsByFilePath = importedDocumentsByFilePath(importedDocuments);
  if (docsByFilePath.size === 0) return [];

  type ExternalGroup = {
    filePath: string;
    graphId: string;
    parentId: string;
    nodes: VibeNodeSpec[];
    edges: VibeEdgeSpec[];
    edgeSigs: Set<string>;
  };

  const groups = new Map<string, ExternalGroup>();
  const keyFor = (filePath: string, graphId: string, parentId: string): string => `${filePath}\n${graphId}\n${parentId}`;
  const ensureGroup = (filePath: string, graphId: string, parentId: string): ExternalGroup => {
    const key = keyFor(filePath, graphId, parentId);
    const existing = groups.get(key);
    if (existing) return existing;
    const group: ExternalGroup = { filePath, graphId, parentId, nodes: [], edges: [], edgeSigs: new Set<string>() };
    groups.set(key, group);
    return group;
  };

  for (const node of Array.isArray(graph.Nodes) ? graph.Nodes : []) {
    if (!node || isExternalRefNode(node)) continue;
    const filePath = externalRefFilePath(node);
    const graphId = externalRefGraphId(node);
    const parentId = String((node as any).name || '').trim();
    if (!filePath || !graphId || !parentId || !docsByFilePath.has(filePath)) continue;
    ensureGroup(filePath, graphId, parentId);
  }

  for (const node of Array.isArray(graph.Nodes) ? graph.Nodes : []) {
    if (!isExternalRefNode(node)) continue;
    const filePath = externalRefFilePath(node);
    const graphId = externalRefGraphId(node);
    const parentId = externalRefParent(node);
    if (!filePath || !graphId || !parentId || !docsByFilePath.has(filePath)) continue;
    const localized = localizeExternalNode(node, parentId);
    if (!localized) continue;
    ensureGroup(filePath, graphId, parentId).nodes.push(localized);
  }

  for (const edge of Array.isArray(graph.Edges) ? graph.Edges : []) {
    if (!isExternalRefEdge(edge)) continue;
    const filePath = externalRefFilePath(edge);
    const graphId = externalRefGraphId(edge);
    const parentId = externalRefParent(edge);
    if (!filePath || !graphId || !parentId || !docsByFilePath.has(filePath)) continue;
    const localized = localizeExternalEdge(edge, parentId);
    if (!localized) continue;
    const group = ensureGroup(filePath, graphId, parentId);
    const sig = externalEdgeSignature(localized);
    if (group.edgeSigs.has(sig)) continue;
    group.edgeSigs.add(sig);
    group.edges.push(localized);
  }

  const writesByFile = new Map<string, { filePath: string; text: string; graphIds: Set<string> }>();
  for (const group of groups.values()) {
    const imported = docsByFilePath.get(group.filePath);
    if (!imported?.text) continue;
    const existing = writesByFile.get(group.filePath);
    const source = existing?.text || imported.text;
    const localGraph: VibeGraphDesign = {
      Nodes: group.nodes,
      Edges: group.edges,
      [AML_ACTIVE_GRAPH_ID_KEY]: group.graphId
    };
    const text = serializeAmlGraphDesign(source, localGraph);
    if (existing) {
      existing.text = text;
      existing.graphIds.add(group.graphId);
    } else {
      writesByFile.set(group.filePath, { filePath: group.filePath, text, graphIds: new Set([group.graphId]) });
    }
  }

  return Array.from(writesByFile.values()).map((write) => ({
    filePath: write.filePath,
    graphId: Array.from(write.graphIds).join(','),
    text: write.text
  }));
}
