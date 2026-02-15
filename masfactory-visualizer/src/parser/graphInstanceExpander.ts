/**
 * Instance expanders for composed graphs (best-effort, static-literal only).
 *
 * Goal: when users write `graph.create_node(AdjacencyListGraph, ..., node_args_list=[...], adjacency_list=[...])`,
 * expand the subgraph's internal nodes/edges from literals so the preview isn't empty.
 *
 * This module intentionally only handles simple literals (list/tuple/dict/None/int/string, and np.array([...])).
 * Dynamic structures will be skipped safely.
 */
import type { Node as TSNode } from 'web-tree-sitter';

import { getNodeText, queryNodes } from './astUtils';
import { NodeParseContext } from './nodeParser';
import { EdgeParseContext } from './edgeParser';

type DictLiteral = { [key: string]: string };

function stripStringQuotes(raw: string): string {
    return raw.replace(/^f?["']|["']$/g, '');
}

function normalizeScalar(node: TSNode, code: string): string {
    const raw = getNodeText(node, code).trim();
    if (node.type === 'string') return stripStringQuotes(raw);
    return raw;
}

function parseIntLiteral(node: TSNode, code: string): number | null {
    if (node.type !== 'integer') return null;
    const raw = getNodeText(node, code).trim().replace(/_/g, '');
    const n = Number.parseInt(raw, 10);
    return Number.isFinite(n) ? n : null;
}

function parseDictLiteral(node: TSNode, code: string): DictLiteral | null {
    if (node.type !== 'dictionary') return null;
    const out: DictLiteral = {};
    for (const child of node.namedChildren) {
        if (!child) continue;
        if (child.type !== 'pair') continue;
        const keyNode = child.childForFieldName('key');
        const valueNode = child.childForFieldName('value');
        if (!keyNode || !valueNode) continue;
        const key = stripStringQuotes(getNodeText(keyNode, code).trim());
        out[key] = normalizeScalar(valueNode, code);
    }
    return out;
}

function getDictValueNodes(node: TSNode, code: string): Map<string, TSNode> {
    const map = new Map<string, TSNode>();
    if (node.type !== 'dictionary') return map;

    for (const child of node.namedChildren) {
        if (!child) continue;
        if (child.type !== 'pair') continue;
        const keyNode = child.childForFieldName('key');
        const valueNode = child.childForFieldName('value');
        if (!keyNode || !valueNode) continue;
        let keyText = getNodeText(keyNode, code).trim();
        if (keyNode.type === 'string') keyText = stripStringQuotes(keyText);
        map.set(keyText, valueNode);
    }
    return map;
}

function parseListElements(node: TSNode): TSNode[] | null {
    if (node.type !== 'list') return null;
    return node.namedChildren.filter((c): c is TSNode => !!c && c.type !== 'comment');
}

function parseTupleElements(node: TSNode): TSNode[] | null {
    if (node.type !== 'tuple') return null;
    return node.namedChildren.filter((c): c is TSNode => !!c && c.type !== 'comment');
}

function parseListOrTupleElements(node: TSNode): TSNode[] | null {
    if (node.type === 'list') return parseListElements(node);
    if (node.type === 'tuple') return parseTupleElements(node);
    return null;
}

function sanitizeIdPart(value: string): string {
    const cleaned = value
        .trim()
        .replace(/\s+/g, '_')
        .replace(/[^a-zA-Z0-9_]+/g, '_')
        .replace(/_+/g, '_')
        .replace(/^_+|_+$/g, '');
    return cleaned || 'node';
}

function getKeywordArgs(argsNode: TSNode, code: string): Map<string, TSNode> {
    const map = new Map<string, TSNode>();
    for (const arg of argsNode.namedChildren) {
        if (!arg) continue;
        if (arg.type !== 'keyword_argument') continue;
        const nameNode = arg.childForFieldName('name');
        const valueNode = arg.childForFieldName('value');
        if (!nameNode || !valueNode) continue;
        const name = getNodeText(nameNode, code).trim();
        map.set(name, valueNode);
    }
    return map;
}

function ensureSubgraphMembership(
    parent: string,
    child: string,
    subgraphs: { [parent: string]: string[] },
    subgraphParents: { [child: string]: string }
): void {
    if (!subgraphs[parent]) subgraphs[parent] = [];
    if (!subgraphs[parent].includes(child)) subgraphs[parent].push(child);
    subgraphParents[child] = parent;
}

function addNodeIfMissing(
    nodeName: string,
    nodeType: string,
    lineNumber: number,
    nodeCtx: NodeParseContext
): void {
    if (!nodeCtx.nodes.includes(nodeName)) {
        nodeCtx.nodes.push(nodeName);
    }
    nodeCtx.nodeTypes[nodeName] = nodeType || 'Node';
    if (!nodeCtx.nodeLineNumbers[nodeName]) {
        nodeCtx.nodeLineNumbers[nodeName] = lineNumber;
    }
    // Default metadata for expanded nodes
    if (nodeCtx.nodePullKeys[nodeName] === undefined) nodeCtx.nodePullKeys[nodeName] = 'empty';
    if (nodeCtx.nodePushKeys[nodeName] === undefined) nodeCtx.nodePushKeys[nodeName] = 'empty';
    if (nodeCtx.nodeAttributes[nodeName] === undefined) nodeCtx.nodeAttributes[nodeName] = null;
}

function addEdgeIfMissing(
    from: string,
    to: string,
    keysDetails: DictLiteral | undefined,
    lineNumber: number,
    edgeCtx: EdgeParseContext
): void {
    const exists = edgeCtx.edges.some(e => e.from === from && e.to === to);
    if (exists) return;
    edgeCtx.edges.push({
        from,
        to,
        keys: keysDetails ? Object.keys(keysDetails) : [],
        keysDetails,
        lineNumber
    });
}

/**
 * Expand composed-graph instances from literals.
 *
 * This mutates the passed contexts (nodes/edges/subgraphs) in-place.
 */
export function expandComposedGraphInstances(
    rootNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] }
): void {
    const subgraphParents = nodeCtx.subgraphParents || {};

    const normalizeType = (t: string | undefined): string => {
        if (!t) return '';
        return t.includes('.') ? t.split('.').pop()! : t;
    };

    const assignments = [
        ...queryNodes(rootNode, 'assignment'),
        ...queryNodes(rootNode, 'typed_assignment')
    ];

    for (const assign of assignments) {
        const leftSide = assign.childForFieldName('left');
        const rightSide = assign.childForFieldName('right');
        if (!leftSide || !rightSide || rightSide.type !== 'call') continue;

        const funcNode = rightSide.childForFieldName('function');
        if (!funcNode) continue;
        const funcText = getNodeText(funcNode, code).trim();
        if (!funcText.endsWith('.create_node') && funcText !== 'create_node' && funcText !== 'self.create_node') {
            continue;
        }

        const variableName = getNodeText(leftSide, code);
        const lineNumber = rightSide.startPosition.row + 1;
        const createdNodeName = nodeCtx.variableToNodeName[variableName];
        if (!createdNodeName) continue;

        const createdNodeTypeRaw = nodeCtx.nodeTypes[createdNodeName];
        const createdNodeType = normalizeType(createdNodeTypeRaw);

        const argsNode = rightSide.childForFieldName('arguments');
        if (!argsNode) continue;
        const kw = getKeywordArgs(argsNode, code);

        // Common internal entry/exit nodes for Graph-based composed graphs.
        const entryId = `${createdNodeName}_entry`;
        const exitId = `${createdNodeName}_exit`;

        if (createdNodeType === 'VerticalGraph') {
            const nodeConfigsNode = kw.get('node_configs');
            if (!nodeConfigsNode) continue;
            const nodeConfigs = parseListElements(nodeConfigsNode);
            if (!nodeConfigs) continue;

            // Ensure internal entry/exit exist.
            addNodeIfMissing(entryId, 'entry', lineNumber, nodeCtx);
            addNodeIfMissing(exitId, 'exit', lineNumber, nodeCtx);
            ensureSubgraphMembership(createdNodeName, entryId, subgraphs, subgraphParents);
            ensureSubgraphMembership(createdNodeName, exitId, subgraphs, subgraphParents);

            // Optional aggregator.
            let aggregatorId: string | null = null;
            const aggregatorArgsNode = kw.get('aggregator_args');
            if (aggregatorArgsNode && aggregatorArgsNode.type === 'dictionary') {
                const aggDict = parseDictLiteral(aggregatorArgsNode, code) || {};
                const rawAggName = aggDict['name'] || 'aggregator';
                const aggType = aggDict['cls'] || aggDict['node_type'] || 'Node';
                aggregatorId = `${createdNodeName}_aggregator_${sanitizeIdPart(rawAggName)}`;
                addNodeIfMissing(aggregatorId, aggType, lineNumber, nodeCtx);
                ensureSubgraphMembership(createdNodeName, aggregatorId, subgraphs, subgraphParents);
                addEdgeIfMissing(aggregatorId, exitId, undefined, lineNumber, edgeCtx);
            }

            for (let i = 0; i < nodeConfigs.length; i++) {
                const cfgNode = nodeConfigs[i];
                if (cfgNode.type !== 'dictionary') continue;
                const entries = getDictValueNodes(cfgNode, code);
                const nodeArgsNode = entries.get('node');
                if (!nodeArgsNode || nodeArgsNode.type !== 'dictionary') continue;

                const nodeArgs = parseDictLiteral(nodeArgsNode, code) || {};
                const rawName = nodeArgs['name'] || nodeArgs['role_name'] || `node${i + 1}`;
                const nodeType = nodeArgs['cls'] || nodeArgs['node_type'] || 'Node';
                const internalId = `${createdNodeName}_${i + 1}_${sanitizeIdPart(rawName)}`;

                addNodeIfMissing(internalId, nodeType, lineNumber, nodeCtx);
                ensureSubgraphMembership(createdNodeName, internalId, subgraphs, subgraphParents);

                const inputKeysNode = entries.get('input_keys');
                const outputKeysNode = entries.get('output_keys');
                const inputKeys = inputKeysNode && inputKeysNode.type === 'dictionary'
                    ? (parseDictLiteral(inputKeysNode, code) || undefined)
                    : undefined;
                const outputKeys = outputKeysNode && outputKeysNode.type === 'dictionary'
                    ? (parseDictLiteral(outputKeysNode, code) || undefined)
                    : undefined;

                addEdgeIfMissing(entryId, internalId, inputKeys, lineNumber, edgeCtx);
                if (aggregatorId) {
                    addEdgeIfMissing(internalId, aggregatorId, outputKeys, lineNumber, edgeCtx);
                } else {
                    addEdgeIfMissing(internalId, exitId, outputKeys, lineNumber, edgeCtx);
                }
            }

            continue;
        }

        if (createdNodeType === 'HorizontalGraph') {
            const nodeArgsListNode = kw.get('node_args_list');
            if (!nodeArgsListNode) continue;
            const nodeArgsList = parseListElements(nodeArgsListNode);
            if (!nodeArgsList) continue;

            // Ensure internal entry/exit exist.
            addNodeIfMissing(entryId, 'entry', lineNumber, nodeCtx);
            addNodeIfMissing(exitId, 'exit', lineNumber, nodeCtx);
            ensureSubgraphMembership(createdNodeName, entryId, subgraphs, subgraphParents);
            ensureSubgraphMembership(createdNodeName, exitId, subgraphs, subgraphParents);

            const edgeKeysListNode = kw.get('edge_keys_list');
            const edgeKeysList = edgeKeysListNode ? parseListElements(edgeKeysListNode) : null;

            const internalIds: string[] = [];
            for (let i = 0; i < nodeArgsList.length; i++) {
                const nodeArgsNode = nodeArgsList[i];
                const dict = nodeArgsNode.type === 'dictionary' ? (parseDictLiteral(nodeArgsNode, code) || {}) : {};
                const rawName = dict['name'] || dict['role_name'] || `node${i + 1}`;
                const nodeType = dict['cls'] || dict['node_type'] || 'Node';
                const internalId = `${createdNodeName}_${i + 1}_${sanitizeIdPart(rawName)}`;
                addNodeIfMissing(internalId, nodeType, lineNumber, nodeCtx);
                ensureSubgraphMembership(createdNodeName, internalId, subgraphs, subgraphParents);
                internalIds.push(internalId);
            }

            if (internalIds.length > 0) {
                addEdgeIfMissing(entryId, internalIds[0], undefined, lineNumber, edgeCtx);
                for (let i = 0; i < internalIds.length - 1; i++) {
                    let keysDetails: DictLiteral | undefined;
                    const keysNode = edgeKeysList && edgeKeysList[i] ? edgeKeysList[i] : null;
                    if (keysNode && keysNode.type === 'dictionary') {
                        keysDetails = parseDictLiteral(keysNode, code) || undefined;
                    } else if (keysNode && keysNode.type === 'none') {
                        keysDetails = undefined;
                    }
                    addEdgeIfMissing(internalIds[i], internalIds[i + 1], keysDetails, lineNumber, edgeCtx);
                }
                addEdgeIfMissing(internalIds[internalIds.length - 1], exitId, undefined, lineNumber, edgeCtx);
            }

            continue;
        }

        if (createdNodeType !== 'AdjacencyListGraph' && createdNodeType !== 'AdjacencyMatrixGraph') {
            continue;
        }

        const nodeArgsListNode = kw.get('node_args_list');
        if (!nodeArgsListNode) continue;

        const nodeArgsList = parseListElements(nodeArgsListNode);
        if (!nodeArgsList) continue;

        // Build index -> internal nodeId mapping.
        const indexToNodeId = new Map<number, string>();
        const n = nodeArgsList.length;
        if (n < 2) continue;

        // Use existing internal entry/exit names if present, otherwise add them.
        addNodeIfMissing(entryId, 'entry', lineNumber, nodeCtx);
        addNodeIfMissing(exitId, 'exit', lineNumber, nodeCtx);
        ensureSubgraphMembership(createdNodeName, entryId, subgraphs, subgraphParents);
        ensureSubgraphMembership(createdNodeName, exitId, subgraphs, subgraphParents);

        indexToNodeId.set(0, entryId);
        indexToNodeId.set(n - 1, exitId);

        for (let i = 1; i < n - 1; i++) {
            const dict = parseDictLiteral(nodeArgsList[i], code) || {};
            const rawName = dict['name'] || dict['role_name'] || `node${i}`;
            const internalId = `${createdNodeName}_${i}_${sanitizeIdPart(rawName)}`;

            const nodeType = dict['cls'] || dict['node_type'] || 'Node';

            addNodeIfMissing(internalId, nodeType, lineNumber, nodeCtx);
            ensureSubgraphMembership(createdNodeName, internalId, subgraphs, subgraphParents);
            indexToNodeId.set(i, internalId);
        }

        if (createdNodeType === 'AdjacencyListGraph') {
            const adjacencyListNode = kw.get('adjacency_list');
            if (!adjacencyListNode) continue;
            const rows = parseListElements(adjacencyListNode);
            if (!rows) continue;

            // Two formats supported:
            // 1) Preferred (matches composed_graph): adjacency_list is list[list[edgeSpec]]
            // 2) Legacy fallback: adjacency_list is list[(from_idx, to_idx, keys?)]
            if (rows.length === n) {
                for (let fromIdx = 0; fromIdx < rows.length; fromIdx++) {
                    const row = rows[fromIdx];
                    const edgeSpecs = parseListOrTupleElements(row);
                    if (!edgeSpecs) continue;
                    const fromId = indexToNodeId.get(fromIdx);
                    if (!fromId) continue;

                    for (const edgeSpec of edgeSpecs) {
                        let toIdx: number | null = null;
                        let keysDetails: DictLiteral | undefined;

                        if (edgeSpec.type === 'integer') {
                            toIdx = parseIntLiteral(edgeSpec, code);
                        } else if (edgeSpec.type === 'tuple' || edgeSpec.type === 'list') {
                            const parts = parseListOrTupleElements(edgeSpec);
                            if (!parts || parts.length === 0) continue;
                            toIdx = parseIntLiteral(parts[0], code);
                            if (parts.length >= 2) {
                                const keysNode = parts[1];
                                if (keysNode.type === 'dictionary') {
                                    keysDetails = parseDictLiteral(keysNode, code) || undefined;
                                } else if (keysNode.type === 'none') {
                                    keysDetails = undefined;
                                }
                            }
                        } else {
                            continue;
                        }

                        if (toIdx === null) continue;
                        const toId = indexToNodeId.get(toIdx);
                        if (!toId) continue;
                        addEdgeIfMissing(fromId, toId, keysDetails, lineNumber, edgeCtx);
                    }
                }
            } else {
                for (const tup of rows) {
                    const parts = parseListOrTupleElements(tup);
                    if (!parts || parts.length < 2) continue;
                    const fromIdx = parseIntLiteral(parts[0], code);
                    const toIdx = parseIntLiteral(parts[1], code);
                    if (fromIdx === null || toIdx === null) continue;

                    const fromId = indexToNodeId.get(fromIdx);
                    const toId = indexToNodeId.get(toIdx);
                    if (!fromId || !toId) continue;

                    let keysDetails: DictLiteral | undefined;
                    if (parts.length >= 3) {
                        const keysNode = parts[2];
                        if (keysNode.type === 'dictionary') {
                            keysDetails = parseDictLiteral(keysNode, code) || undefined;
                        } else if (keysNode.type === 'none') {
                            keysDetails = undefined;
                        }
                    }

                    addEdgeIfMissing(fromId, toId, keysDetails, lineNumber, edgeCtx);
                }
            }
        } else if (createdNodeType === 'AdjacencyMatrixGraph') {
            const adjacencyMatrixNode = kw.get('adjacency_matrix');
            if (!adjacencyMatrixNode) continue;

            // Support adjacency_matrix=[...] or adjacency_matrix=np.array([...])
            let matrixListNode: TSNode | null = null;
            if (adjacencyMatrixNode.type === 'list') {
                matrixListNode = adjacencyMatrixNode;
            } else if (adjacencyMatrixNode.type === 'call') {
                const fn = adjacencyMatrixNode.childForFieldName('function');
                const fnText = fn ? getNodeText(fn, code).trim() : '';
                if (fnText.endsWith('.array') || fnText === 'array') {
                    const args = adjacencyMatrixNode.childForFieldName('arguments');
                    const firstPos = args?.namedChildren.find(
                        (a): a is TSNode => !!a && a.type !== 'keyword_argument' && a.type !== 'comment'
                    );
                    if (firstPos && firstPos.type === 'list') {
                        matrixListNode = firstPos;
                    }
                }
            }

            if (!matrixListNode) continue;
            const rows = parseListElements(matrixListNode);
            if (!rows) continue;

            for (let i = 0; i < rows.length; i++) {
                const row = rows[i];
                const cells = parseListElements(row);
                if (!cells) continue;
                for (let j = 0; j < cells.length; j++) {
                    const cell = cells[j];

                    // Determine whether there is an edge.
                    let hasEdge = false;
                    let keysDetails: DictLiteral | undefined;

                    if (cell.type === 'dictionary') {
                        hasEdge = true;
                        keysDetails = parseDictLiteral(cell, code) || undefined;
                    } else if (cell.type === 'none') {
                        hasEdge = true;
                    } else if (cell.type === 'integer') {
                        const v = parseIntLiteral(cell, code);
                        if (v !== null && v !== 0) hasEdge = true;
                    }

                    if (!hasEdge) continue;

                    const fromId = indexToNodeId.get(i);
                    const toId = indexToNodeId.get(j);
                    if (!fromId || !toId) continue;
                    addEdgeIfMissing(fromId, toId, keysDetails, lineNumber, edgeCtx);
                }
            }
        }
    }

    // Persist mutated subgraphParents back to context if it was missing.
    nodeCtx.subgraphParents = subgraphParents;
}
