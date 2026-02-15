/**
 * Build Cytoscape elements from MASFactory GraphData (Preview + Runtime).
 *
 * This is extracted from the legacy preview element builder so that all tabs can
 * share the same graph-to-elements mapping.
 */

const INTERNAL_NODE_TYPES = ['Controller', 'TerminateNode'];

/**
 * @param {unknown} value
 * @returns {Record<string, any>}
 */
function asRecord(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

/**
 * @param {unknown} data
 * @returns {{
 *   nodes: string[],
 *   nodeTypes: Record<string, string>,
 *   edges: Array<any>,
 *   subgraphs: Record<string, string[]>,
 *   subgraphTypes: Record<string, string>,
 *   subgraphParents: Record<string, string>,
 *   nodeLineNumbers: Record<string, number>,
 *   nodeFilePaths: Record<string, string>,
 *   nodePullKeys: Record<string, any>,
 *   nodePushKeys: Record<string, any>,
 *   nodeAttributes: Record<string, any>,
 *   nodeAliases: Record<string, string[]>,
 *   graphAttributesSummary: Record<string, any>
 * }}
 */
function normalizeGraphData(data) {
  const r = asRecord(data);
  return {
    nodes: Array.isArray(r.nodes) ? r.nodes.filter((x) => typeof x === 'string' && x) : [],
    nodeTypes: asRecord(r.nodeTypes),
    edges: Array.isArray(r.edges) ? r.edges.filter((e) => e && typeof e === 'object') : [],
    subgraphs: asRecord(r.subgraphs),
    subgraphTypes: asRecord(r.subgraphTypes),
    subgraphParents: asRecord(r.subgraphParents),
    nodeLineNumbers: asRecord(r.nodeLineNumbers),
    nodeFilePaths: asRecord(r.nodeFilePaths),
    nodePullKeys: asRecord(r.nodePullKeys),
    nodePushKeys: asRecord(r.nodePushKeys),
    nodeAttributes: asRecord(r.nodeAttributes),
    nodeAliases: asRecord(r.nodeAliases),
    graphAttributesSummary: asRecord(r.graphAttributesSummary)
  };
}

/**
 * @param {string} nodeType
 * @param {string} nodeId
 * @returns {string}
 */
function buildNodeLabel(nodeType, nodeId) {
  const isInternal = INTERNAL_NODE_TYPES.includes(nodeType);
  if (nodeType === 'entry' || nodeType === 'exit') return nodeType;
  if (isInternal) {
    if (nodeId.endsWith('_controller')) return 'controller';
    if (nodeId.endsWith('_terminate')) return 'terminate';
    return nodeId;
  }
  if (nodeType === 'Node' || nodeType === 'entry' || nodeType === 'exit') return nodeId;
  return `${nodeId}(${nodeType})`;
}

/**
 * @param {any} edge
 * @returns {string}
 */
function buildEdgeDisplayLabel(edge) {
  if (edge?.keysDetails && typeof edge.keysDetails === 'object' && !Array.isArray(edge.keysDetails)) {
    const keys = Object.keys(edge.keysDetails);
    if (keys.length > 0) return keys.join('\n');
  }
  if (Array.isArray(edge?.keys) && edge.keys.length > 0) {
    const keys = edge.keys.filter((x) => typeof x === 'string' && x);
    if (keys.length > 0) return keys.join('\n');
  }
  return typeof edge?.label === 'string' ? edge.label : '';
}

/**
 * @param {unknown} graph
 * @param {{ collapsedSubgraphs?: Record<string, boolean> }} [opts]
 * @returns {Array<any>}
 */
export function buildGraphElements(graph, opts) {
  const data = normalizeGraphData(graph);
  const collapsed = asRecord(opts && opts.collapsedSubgraphs);

  /** @type {Array<any>} */
  const elements = [];
  const nodesInSubgraphs = new Set();

  for (const children of Object.values(data.subgraphs)) {
    if (!Array.isArray(children)) continue;
    for (const child of children) {
      if (typeof child === 'string' && child) nodesInSubgraphs.add(child);
    }
  }

  /**
   * @param {string} nodeName
   * @returns {boolean}
   */
  function isSubgraph(nodeName) {
    const children = data.subgraphs[nodeName];
    if (!Array.isArray(children) || children.length === 0) return false;
    const nodeType = typeof data.nodeTypes[nodeName] === 'string' ? String(data.nodeTypes[nodeName]) : '';
    if (nodeType === 'Controller') return false;
    return true;
  }

  /**
   * @param {string} parentName
   * @param {string|null} [parentId]
   */
  function addSubgraphNodes(parentName, parentId = null) {
    const children = data.subgraphs[parentName];
    if (!Array.isArray(children) || children.length === 0) return;

    const parentType = typeof data.subgraphTypes[parentName] === 'string' ? data.subgraphTypes[parentName] : 'Subgraph';
    const parentNodeType = typeof data.nodeTypes[parentName] === 'string' ? data.nodeTypes[parentName] : parentType;

    const classList = ['subgraph'];
    if (collapsed[parentName]) classList.push('collapsed');

    elements.push({
      group: 'nodes',
      data: {
        id: parentName,
        label: `${parentName}(${parentNodeType})`,
        type: parentNodeType,
        parent: parentId || undefined,
        pullKeys: data.nodePullKeys[parentName],
        pushKeys: data.nodePushKeys[parentName],
        attributes: data.nodeAttributes[parentName],
        aliases: data.nodeAliases[parentName],
        graphAttributesSummary: data.graphAttributesSummary[parentName]
      },
      classes: classList.join(' ')
    });

    for (const child of children) {
      if (typeof child !== 'string' || !child) continue;
      if (isSubgraph(child)) {
        addSubgraphNodes(child, parentName);
        continue;
      }

      const nodeType = typeof data.nodeTypes[child] === 'string' ? data.nodeTypes[child] : 'Node';
      const label = buildNodeLabel(nodeType, child);

      elements.push({
        group: 'nodes',
        data: {
          id: child,
          label,
          type: nodeType,
          parent: parentName,
          pullKeys: data.nodePullKeys[child],
          pushKeys: data.nodePushKeys[child],
          aliases: data.nodeAliases[child],
          attributes: data.nodeAttributes[child]
        }
      });
    }
  }

  const topLevelSubgraphs = Object.keys(data.subgraphs).filter((sgName) => {
    if (!isSubgraph(sgName)) return false;
    const sgType = typeof data.nodeTypes[sgName] === 'string' ? data.nodeTypes[sgName] : '';
    if (sgType === 'Controller') return false;
    const parent = data.subgraphParents ? data.subgraphParents[sgName] : undefined;
    return !parent || parent === 'graph' || parent === 'root';
  });

  for (const sgName of topLevelSubgraphs) addSubgraphNodes(sgName, null);

  const topLevelNodes = data.nodes.filter((n) => typeof n === 'string' && n && !nodesInSubgraphs.has(n));
  for (const node of topLevelNodes) {
    // Graph/Loop containers are already added as compound nodes via addSubgraphNodes().
    if (isSubgraph(node)) continue;
    const nodeType = typeof data.nodeTypes[node] === 'string' ? data.nodeTypes[node] : 'Node';
    const label = buildNodeLabel(nodeType, node);

    /** @type {any} */
    const nodeData = {
      id: node,
      label,
      type: nodeType,
      pullKeys: data.nodePullKeys[node],
      pushKeys: data.nodePushKeys[node],
      attributes: data.nodeAttributes[node],
      aliases: data.nodeAliases[node]
    };

    if (node === 'entry') nodeData.rank = 'min';
    if (node === 'exit') nodeData.rank = 'max';

    elements.push({ group: 'nodes', data: nodeData });
  }

  const nodeIdSet = new Set(data.nodes);
  const edgeIdSeen = new Set();
  for (const edge of data.edges) {
    const from = typeof edge.from === 'string' ? edge.from : '';
    const to = typeof edge.to === 'string' ? edge.to : '';
    if (!from || !to) continue;
    if (!nodeIdSet.has(from) || !nodeIdSet.has(to)) continue;

    const displayLabel = buildEdgeDisplayLabel(edge);
    const baseId = `${from}-${to}`;
    let id = baseId;
    let i = 1;
    while (edgeIdSeen.has(id)) {
      id = `${baseId}#${i++}`;
    }
    edgeIdSeen.add(id);

    elements.push({
      group: 'edges',
      data: {
        id,
        source: from,
        target: to,
        keysDetails: edge.keysDetails,
        keysList: edge.label,
        variableName: edge.variableName,
        displayLabel,
        originalDisplayLabel: displayLabel
      }
    });
  }

  return elements;
}
