import type { GraphData, GraphEdge } from '../parser/types';

export type MergePrefixedStructureMode = 'replace' | 'add';

export type ComponentLikeStructure = {
  nodes: string[];
  nodeTypes?: Record<string, string>;
  nodeLineNumbers?: Record<string, number>;
  nodeFilePaths?: Record<string, string>;
  nodePullKeys?: Record<string, any>;
  nodePushKeys?: Record<string, any>;
  nodeAttributes?: Record<string, any>;
  edges?: GraphEdge[];
  subgraphs?: Record<string, string[]>;
  subgraphParents?: Record<string, string>;
  sourceFilePath?: string;
};

function pushUnique(list: string[], value: string): void {
  if (!value) return;
  if (list.includes(value)) return;
  list.push(value);
}

function inferInternalBoundaryNodes(graphData: GraphData, parentNode: string): string[] {
  const out: string[] = [];
  const candidates = [
    `${parentNode}_controller`,
    `${parentNode}_terminate`,
    `${parentNode}_entry`,
    `${parentNode}_exit`
  ];
  for (const id of candidates) {
    const t = graphData.nodeTypes?.[id];
    const exists = graphData.nodes.includes(id);
    if (!exists && !t) continue;
    pushUnique(out, id);
  }
  return out;
}

function inferStructureBoundaries(parentNode: string, structure: ComponentLikeStructure): string[] {
  const rawNodes = Array.isArray(structure.nodes) ? structure.nodes.filter((n) => typeof n === 'string') : [];
  const has = (name: string): boolean => rawNodes.includes(name);

  const out: string[] = [];
  if (has('controller')) pushUnique(out, `${parentNode}_controller`);
  if (has('terminate')) pushUnique(out, `${parentNode}_terminate`);
  if (has('entry')) pushUnique(out, `${parentNode}_entry`);
  if (has('exit')) pushUnique(out, `${parentNode}_exit`);
  return out;
}

function removeNodeFromGraphData(graphData: GraphData, nodeId: string): void {
  graphData.nodes = graphData.nodes.filter((n) => n !== nodeId);
  delete graphData.nodeTypes[nodeId];
  delete graphData.nodeLineNumbers[nodeId];
  delete graphData.nodePullKeys[nodeId];
  delete graphData.nodePushKeys[nodeId];
  delete graphData.nodeAttributes[nodeId];
  if (graphData.nodeAliases) delete graphData.nodeAliases[nodeId];
  if (graphData.nodeFilePaths) delete graphData.nodeFilePaths[nodeId];

  if (graphData.subgraphParents) delete graphData.subgraphParents[nodeId];

  for (const [parent, children] of Object.entries(graphData.subgraphs || {})) {
    if (!Array.isArray(children) || children.length === 0) continue;
    graphData.subgraphs[parent] = children.filter((c) => c !== nodeId);
  }

  graphData.edges = (graphData.edges || []).filter((e) => e?.from !== nodeId && e?.to !== nodeId);
}

export function mergePrefixedStructure(
  graphData: GraphData,
  parentNode: string,
  structure: ComponentLikeStructure | null | undefined,
  opts: { mode: MergePrefixedStructureMode }
): void {
  if (!structure || !Array.isArray(structure.nodes)) return;

  const prefix = `${parentNode}_`;
  const prefixed = (name: string) => `${prefix}${name}`;

  const localSubgraphs: Record<string, string[]> = structure.subgraphs || {};
  const localTypes: Record<string, string> = structure.nodeTypes || {};
  const localParent: Record<string, string> = structure.subgraphParents || {};

  const addedNodeNames: string[] = [];

  for (const node of structure.nodes) {
    if (typeof node !== 'string') continue;
    const newName = prefixed(node);
    if (!graphData.nodes.includes(newName)) {
      graphData.nodes.push(newName);
      addedNodeNames.push(newName);
    }
    graphData.nodeTypes[newName] = localTypes[node] || structure.nodeTypes?.[node] || 'Node';
    graphData.nodeLineNumbers[newName] = structure.nodeLineNumbers?.[node] || 0;

    if (structure.nodeFilePaths?.[node]) {
      if (!graphData.nodeFilePaths) graphData.nodeFilePaths = {};
      graphData.nodeFilePaths[newName] = structure.nodeFilePaths[node];
    }

    if (structure.nodePullKeys?.[node] !== undefined) {
      graphData.nodePullKeys[newName] = structure.nodePullKeys[node];
    } else {
      graphData.nodePullKeys[newName] = 'empty';
    }
    if (structure.nodePushKeys?.[node] !== undefined) {
      graphData.nodePushKeys[newName] = structure.nodePushKeys[node];
    } else {
      graphData.nodePushKeys[newName] = 'empty';
    }
    if (structure.nodeAttributes?.[node] !== undefined) {
      graphData.nodeAttributes[newName] = structure.nodeAttributes[node];
    } else {
      graphData.nodeAttributes[newName] = null;
    }
  }

  const containerChildren = structure.subgraphs?.graph || structure.subgraphs?.root || [];
  const controllerName = containerChildren.find((c) => c.endsWith('_controller') || c === 'controller');
  const terminateName = containerChildren.find((c) => c.endsWith('_terminate') || c === 'terminate');
  const entryName = containerChildren.find((c) => c.endsWith('_entry') || c === 'entry');
  const exitName = containerChildren.find((c) => c.endsWith('_exit') || c === 'exit');

  const boundaryFromStructure = inferStructureBoundaries(parentNode, structure);

  const defaultInternal: string[] = [];
  if (controllerName) pushUnique(defaultInternal, prefixed(controllerName));
  if (terminateName) pushUnique(defaultInternal, prefixed(terminateName));
  if (entryName) pushUnique(defaultInternal, prefixed(entryName));
  if (exitName) pushUnique(defaultInternal, prefixed(exitName));
  for (const id of boundaryFromStructure) pushUnique(defaultInternal, id);

  // Some component structures omit a synthetic root container subgraph (common in build() parsing).
  // Preserve previously-created boundary nodes only when we can't infer boundaries from the structure.
  if (defaultInternal.length === 0) {
    for (const id of inferInternalBoundaryNodes(graphData, parentNode)) pushUnique(defaultInternal, id);
  } else if (boundaryFromStructure.length > 0) {
    // If the parser previously guessed the wrong container kind (e.g., a Loop named "*Graph"),
    // it may have created mismatched boundary nodes. Prune those to avoid showing both sets.
    const keep = new Set(defaultInternal);
    const candidates = [
      `${parentNode}_controller`,
      `${parentNode}_terminate`,
      `${parentNode}_entry`,
      `${parentNode}_exit`
    ];
    for (const id of candidates) {
      if (keep.has(id)) continue;
      if (!graphData.nodes.includes(id) && !graphData.nodeTypes?.[id]) continue;
      removeNodeFromGraphData(graphData, id);
    }
  }

  if (!graphData.subgraphs[parentNode]) {
    graphData.subgraphs[parentNode] = [];
    graphData.subgraphTypes[parentNode] =
      localTypes.graph || localTypes.root || graphData.nodeTypes[parentNode] || 'Graph';
  }

  if (opts.mode === 'replace') {
    graphData.subgraphs[parentNode] = [];
    for (const id of defaultInternal) {
      pushUnique(graphData.subgraphs[parentNode], id);
      graphData.subgraphParents[id] = parentNode;
    }

    for (const node of structure.nodes) {
      if (typeof node !== 'string') continue;
      const id = prefixed(node);
      if (!defaultInternal.includes(id)) {
        pushUnique(graphData.subgraphs[parentNode], id);
        graphData.subgraphParents[id] = parentNode;
      }
    }
  }

  if (opts.mode === 'add') {
    for (const nodeName of addedNodeNames) {
      if (!defaultInternal.includes(nodeName)) {
        if (!graphData.subgraphs[parentNode].includes(nodeName)) {
          graphData.subgraphs[parentNode].push(nodeName);
        }
        graphData.subgraphParents[nodeName] = parentNode;
      }
    }
  }

  for (const [sg, children] of Object.entries(localSubgraphs)) {
    if (!Array.isArray(children)) continue;
    const sgPrefixed = prefixed(sg);
    const childrenPrefixed = children.filter((c: any) => typeof c === 'string').map(prefixed);
    graphData.subgraphs[sgPrefixed] = childrenPrefixed;

    const sgLocalParent = localParent[sg];
    graphData.subgraphParents[sgPrefixed] = sgLocalParent ? prefixed(sgLocalParent) : parentNode;

    for (const child of childrenPrefixed) {
      graphData.subgraphParents[child] = sgPrefixed;
    }
  }

  if (Array.isArray(structure.edges)) {
    for (const edge of structure.edges) {
      if (!edge || typeof edge.from !== 'string' || typeof edge.to !== 'string') continue;
      const prefixedEdge: GraphEdge = {
        ...edge,
        from: prefixed(edge.from),
        to: prefixed(edge.to),
        filePath: structure.sourceFilePath ? 'file://' + structure.sourceFilePath : edge.filePath
      };
      const exists = graphData.edges.some((e) => e.from === prefixedEdge.from && e.to === prefixedEdge.to);
      if (!exists) {
        graphData.edges.push(prefixedEdge);
      }
    }
  }
}
