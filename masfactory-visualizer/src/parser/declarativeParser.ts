/**
 * Declarative Graph Parser
 *
 * Supports MASFactory "declarative" construction patterns:
 *   g = RootGraph(name="...", nodes=[(...), ...], edges=[(...), ...])
 *
 * MASFactory runtime behavior (repo mainline):
 * - Graph.build() consumes nodes/edges lists (nodes tuples, edges tuples)
 * - Loop.build() consumes nodes/edges lists and uses controller/terminate semantics
 * - Edge(keys=None) defaults to {"message": ""}
 *
 * This module extracts a best-effort topology (nodes/edges) from those literals.
 * It intentionally only supports simple literals: list/tuple/dict/None/string/int.
 */
import type { Node as TSNode } from 'web-tree-sitter';

import { getNodeText, parseDictArgument } from './astUtils';
import { EdgeParseContext } from './edgeParser';
import { NodeParseContext } from './nodeParser';
import { ParsedNodeTemplate, tryParseNodeTemplateAssignment } from './templateParser';

type LiteralValues = { [name: string]: TSNode };

function stripStringQuotes(raw: string): string {
    return raw.replace(/^f?["']|["']$/g, '');
}

function parseStringLiteral(node: TSNode, code: string): string | null {
    if (node.type !== 'string') return null;
    return stripStringQuotes(getNodeText(node, code).trim());
}

function normalizeTypeName(raw: string): string {
    const text = String(raw || '').trim();
    if (!text) return 'Node';
    return text.includes('.') ? text.split('.').pop()! : text;
}

function parseNodeTypeExpression(
    node: TSNode,
    code: string
): { typeText: string; typeIsCall: boolean } {
    if (node.type === 'call') {
        const funcNode = node.childForFieldName('function');
        const funcText = funcNode ? getNodeText(funcNode, code).trim() : '';
        const callee = normalizeTypeName(funcText);
        // NodeTemplate(Agent/Loop/Graph, ...) should display as the base class name.
        if (callee === 'NodeTemplate') {
            const args = getCallArgs(node);
            const positional = getPositionalArgs(args);
            if (positional.length > 0) {
                return { typeText: getNodeText(positional[0], code).trim() || 'Node', typeIsCall: true };
            }
            return { typeText: 'Node', typeIsCall: true };
        }
        // Template instantiation: BaseAgent(...) => display "BaseAgent" (without args).
        return { typeText: funcText || 'Node', typeIsCall: true };
    }

    return { typeText: getNodeText(node, code).trim() || 'Node', typeIsCall: false };
}

function resolveLiteralNode(
    node: TSNode,
    code: string,
    literalValues?: LiteralValues
): TSNode {
    if (!literalValues) return node;
    if (node.type !== 'identifier' && node.type !== 'attribute') return node;
    const raw = getNodeText(node, code).trim();
    if (literalValues[raw]) return literalValues[raw];
    if (raw.startsWith('self._') && literalValues[raw.replace('self._', '')]) return literalValues[raw.replace('self._', '')];
    if (raw.startsWith('self.') && literalValues[raw.replace('self.', '')]) return literalValues[raw.replace('self.', '')];
    const last = raw.split('.').pop();
    if (last && literalValues[last]) return literalValues[last];
    if (last && last.startsWith('_') && literalValues[last.slice(1)]) return literalValues[last.slice(1)];
    return node;
}

function getCallArgs(callNode: TSNode): TSNode[] {
    const argsNode = callNode.childForFieldName('arguments');
    if (!argsNode) return [];
    return argsNode.namedChildren.filter((n): n is TSNode => !!n && n.type !== 'comment');
}

function getKeywordArgMap(args: TSNode[], code: string): Map<string, TSNode> {
    const map = new Map<string, TSNode>();
    for (const arg of args) {
        if (arg.type !== 'keyword_argument') continue;
        const nameNode = arg.childForFieldName('name');
        const valueNode = arg.childForFieldName('value');
        if (!nameNode || !valueNode) continue;
        map.set(getNodeText(nameNode, code).trim(), valueNode);
    }
    return map;
}

function getPositionalArgs(args: TSNode[]): TSNode[] {
    return args.filter(arg => arg.type !== 'keyword_argument' && arg.type !== 'comment');
}

function resolveTemplateBaseKind(
    rawTypeText: string,
    templates?: { [name: string]: ParsedNodeTemplate }
): 'Graph' | 'Loop' | 'Node' | null {
    if (!templates) return null;
    const direct = templates[rawTypeText];
    if (direct) return direct.baseKind;
    const normalized = rawTypeText.includes('.') ? rawTypeText.split('.').pop()! : rawTypeText;
    const byLast = templates[normalized];
    return byLast ? byLast.baseKind : null;
}

function inferContainerKind(
    rawTypeText: string,
    templates?: { [name: string]: ParsedNodeTemplate }
): 'Graph' | 'Loop' | null {
    const templateKind = resolveTemplateBaseKind(rawTypeText, templates);
    if (templateKind === 'Graph' || templateKind === 'Loop') return templateKind;

    const normalized = rawTypeText.includes('.') ? rawTypeText.split('.').pop()! : rawTypeText;
    if (normalized === 'Loop' || normalized.endsWith('Loop')) return 'Loop';
    if (normalized === 'Graph' || normalized === 'RootGraph') return 'Graph';
    if (normalized.endsWith('Graph') || normalized.endsWith('Workflow')) return 'Graph';
    return null;
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

function addNodeIfMissing(nodeName: string, nodeType: string, lineNumber: number, nodeCtx: NodeParseContext): void {
    if (!nodeCtx.nodes.includes(nodeName)) {
        nodeCtx.nodes.push(nodeName);
    }
    if (!nodeCtx.nodeTypes[nodeName]) {
        nodeCtx.nodeTypes[nodeName] = nodeType || 'Node';
    }
    if (!nodeCtx.nodeLineNumbers[nodeName]) {
        nodeCtx.nodeLineNumbers[nodeName] = lineNumber;
    }
}

function parseEdgeKeysArgument(
    node: TSNode | undefined,
    code: string
): { keys: string[]; keysDetails?: { [key: string]: string } } {
    // keys omitted or None => default "message"
    if (!node || node.type === 'none') {
        return { keys: ['message'], keysDetails: { message: '' } };
    }
    if (node.type === 'dictionary') {
        const parsed = parseDictArgument(node, code);
        if (parsed) {
            return { keys: Object.keys(parsed), keysDetails: parsed };
        }
        // Empty dict literal => no keys
        return { keys: [], keysDetails: {} };
    }
    // Unsupported dynamic value => treat as default
    return { keys: ['message'], keysDetails: { message: '' } };
}

function parseNodesListLiteral(
    node: TSNode,
    code: string,
    literalValues?: LiteralValues
): Array<{ name: string; typeText: string; typeIsCall: boolean; args: TSNode[]; lineNumber: number }> {
    node = resolveLiteralNode(node, code, literalValues);
    if (node.type !== 'list') return [];
    const out: Array<{ name: string; typeText: string; typeIsCall: boolean; args: TSNode[]; lineNumber: number }> = [];
    for (const item of node.namedChildren) {
        if (!item) continue;
        if (item.type !== 'tuple') continue;
        const elems = item.namedChildren.filter((c): c is TSNode => !!c && c.type !== 'comment');
        if (elems.length < 2) continue;
        const name = parseStringLiteral(elems[0], code);
        if (!name) continue;
        const typeSpec = parseNodeTypeExpression(elems[1], code);
        const args = elems.slice(2);
        out.push({ name, typeText: typeSpec.typeText, typeIsCall: typeSpec.typeIsCall, args, lineNumber: item.startPosition.row + 1 });
    }
    return out;
}

function parseEdgesListLiteral(
    node: TSNode,
    code: string,
    literalValues?: LiteralValues
): Array<{ from: string; to: string; keysNode?: TSNode; lineNumber: number }> {
    node = resolveLiteralNode(node, code, literalValues);
    if (node.type !== 'list') return [];
    const out: Array<{ from: string; to: string; keysNode?: TSNode; lineNumber: number }> = [];
    for (const item of node.namedChildren) {
        if (!item) continue;
        if (item.type !== 'tuple') continue;
        const elems = item.namedChildren.filter((c): c is TSNode => !!c && c.type !== 'comment');
        if (elems.length < 2) continue;
        const from = parseStringLiteral(elems[0], code);
        const to = parseStringLiteral(elems[1], code);
        if (!from || !to) continue;
        const keysNode = elems.length >= 3 ? elems[2] : undefined;
        out.push({ from, to, keysNode, lineNumber: item.startPosition.row + 1 });
    }
    return out;
}

function normalizeContainerEndpoint(name: string, kind: 'Graph' | 'Loop'): string {
    if (!name) return name;
    const lowered = name.trim().toLowerCase();
    if (kind === 'Loop') {
        if (lowered === 'controller') return 'controller';
        if (lowered === 'terminate' || lowered === 'terminate_node') return 'terminate';
        return name;
    }
    if (lowered === 'entry') return 'entry';
    if (lowered === 'exit') return 'exit';
    return name;
}

export function isDeclarativeGraphCall(functionText: string): boolean {
    const normalized = functionText.includes('.') ? functionText.split('.').pop()! : functionText;
    return normalized === 'RootGraph' || normalized === 'Graph' || normalized === 'Loop';
}

function looksLikeEdgeTupleList(node: TSNode, code: string, literalValues?: LiteralValues): boolean {
    const resolved = resolveLiteralNode(node, code, literalValues);
    if (resolved.type !== 'list') return false;
    const firstTuple = resolved.namedChildren.find((c): c is TSNode => !!c && c.type === 'tuple');
    if (!firstTuple) return false;
    const elems = firstTuple.namedChildren.filter((c): c is TSNode => !!c && c.type !== 'comment');
    if (elems.length < 2) return false;
    return elems[0].type === 'string' && elems[1].type === 'string';
}

function looksLikeNodeTupleList(node: TSNode, code: string, literalValues?: LiteralValues): boolean {
    const resolved = resolveLiteralNode(node, code, literalValues);
    if (resolved.type !== 'list') return false;
    const firstTuple = resolved.namedChildren.find((c): c is TSNode => !!c && c.type === 'tuple');
    if (!firstTuple) return false;
    const elems = firstTuple.namedChildren.filter((c): c is TSNode => !!c && c.type !== 'comment');
    if (elems.length < 2) return false;
    // Nodes list: (name:str, type:identifier/template, ...)
    return elems[0].type === 'string' && elems[1].type !== 'string';
}

function extractContainerListsFromArgs(
    args: TSNode[],
    code: string,
    literalValues?: LiteralValues
): { nodesNode?: TSNode; edgesNode?: TSNode } {
    const listCandidates: TSNode[] = [];
    for (const arg of args) {
        const resolved = resolveLiteralNode(arg, code, literalValues);
        if (resolved.type === 'list') listCandidates.push(arg);
    }
    let nodesNode: TSNode | undefined;
    let edgesNode: TSNode | undefined;
    for (const candidate of listCandidates) {
        if (!edgesNode && looksLikeEdgeTupleList(candidate, code, literalValues)) {
            edgesNode = candidate;
            continue;
        }
        if (!nodesNode && looksLikeNodeTupleList(candidate, code, literalValues)) {
            nodesNode = candidate;
            continue;
        }
    }
    // Fallback: try last two list-like args, interpret by shape
    if (!nodesNode || !edgesNode) {
        const reversed = [...listCandidates].reverse();
        for (const candidate of reversed) {
            if (!edgesNode && looksLikeEdgeTupleList(candidate, code, literalValues)) edgesNode = candidate;
            if (!nodesNode && looksLikeNodeTupleList(candidate, code, literalValues)) nodesNode = candidate;
        }
    }
    return { nodesNode, edgesNode };
}

function ensureNodeDefaults(
    nodeName: string,
    typeText: string,
    nodeCtx: NodeParseContext,
    templates?: { [name: string]: ParsedNodeTemplate }
): ParsedNodeTemplate | undefined {
    const normalized = typeText.includes('.') ? typeText.split('.').pop()! : typeText;

    if (nodeCtx.nodePullKeys[nodeName] === undefined) {
        nodeCtx.nodePullKeys[nodeName] = normalized === 'Agent' ? 'empty' : null;
    }
    if (nodeCtx.nodePushKeys[nodeName] === undefined) {
        if (normalized === 'Agent') {
            nodeCtx.nodePushKeys[nodeName] = 'empty';
        } else if (normalized === 'Loop' || normalized.endsWith('Loop')) {
            // Loop has special default push_keys in MASFactory (iteration counters).
            nodeCtx.nodePushKeys[nodeName] = {
                current_iteration: 'Current iteration of the loop.',
                max_iterations: 'Maximum iterations of the loop.'
            };
        } else {
            nodeCtx.nodePushKeys[nodeName] = null;
        }
    }
    if (nodeCtx.nodeAttributes[nodeName] === undefined) {
        nodeCtx.nodeAttributes[nodeName] = null;
    }

    const templateInfo =
        templates?.[typeText] ||
        templates?.[normalized];
    if (templateInfo) {
        if (templateInfo.pullKeys !== undefined) nodeCtx.nodePullKeys[nodeName] = templateInfo.pullKeys;
        if (templateInfo.pushKeys !== undefined) nodeCtx.nodePushKeys[nodeName] = templateInfo.pushKeys;
        if (templateInfo.attributes !== undefined) nodeCtx.nodeAttributes[nodeName] = templateInfo.attributes;
    }
    return templateInfo;
}

function setNodeTypeLabel(
    nodeName: string,
    typeText: string,
    typeIsCall: boolean,
    templateInfo: ParsedNodeTemplate | undefined,
    nodeCtx: NodeParseContext
): void {
    // Declarative rule:
    // - ("x", NodeTemplate(Agent, ...)) => x(Agent)
    // - ("x", TemplateName(...))        => x(TemplateName)
    // - ("x", TemplateName)             => x(<base class of TemplateName>)
    const labelType =
        !typeIsCall && templateInfo?.nodeClass ? normalizeTypeName(templateInfo.nodeClass) : normalizeTypeName(typeText);
    nodeCtx.nodeTypes[nodeName] = labelType || 'Node';
}

function addContainerInternalNodes(
    containerName: string,
    kind: 'Graph' | 'Loop',
    lineNumber: number,
    nodeCtx: NodeParseContext,
    subgraphs: { [parent: string]: string[] }
): void {
    if (kind === 'Loop') {
        const controllerName = `${containerName}_controller`;
        const terminateName = `${containerName}_terminate`;
        addNodeIfMissing(controllerName, 'Controller', lineNumber, nodeCtx);
        addNodeIfMissing(terminateName, 'TerminateNode', lineNumber, nodeCtx);
        ensureSubgraphMembership(containerName, controllerName, subgraphs, nodeCtx.subgraphParents || (nodeCtx.subgraphParents = {}));
        ensureSubgraphMembership(containerName, terminateName, subgraphs, nodeCtx.subgraphParents || (nodeCtx.subgraphParents = {}));
    } else {
        const entryName = `${containerName}_entry`;
        const exitName = `${containerName}_exit`;
        addNodeIfMissing(entryName, 'entry', lineNumber, nodeCtx);
        addNodeIfMissing(exitName, 'exit', lineNumber, nodeCtx);
        ensureSubgraphMembership(containerName, entryName, subgraphs, nodeCtx.subgraphParents || (nodeCtx.subgraphParents = {}));
        ensureSubgraphMembership(containerName, exitName, subgraphs, nodeCtx.subgraphParents || (nodeCtx.subgraphParents = {}));
    }
}

function expandContainerFromDeclarativeLists(
    containerName: string,
    kind: 'Graph' | 'Loop',
    nodesNode: TSNode | undefined,
    edgesNode: TSNode | undefined,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    templates?: { [name: string]: ParsedNodeTemplate },
    literalValues?: LiteralValues,
    visited?: Set<string>
): void {
    if (!nodesNode && !edgesNode) return;
    if (!visited) visited = new Set<string>();
    if (visited.has(containerName)) return;
    visited.add(containerName);

    // Ensure container has its internal nodes recorded.
    addContainerInternalNodes(containerName, kind, 0, nodeCtx, subgraphs);

    const prefix = `${containerName}_`;

    if (nodesNode) {
        const specs = parseNodesListLiteral(nodesNode, code, literalValues);
        for (const spec of specs) {
            const fullName = `${prefix}${spec.name}`;
            addNodeIfMissing(fullName, spec.typeText || 'Node', spec.lineNumber, nodeCtx);
            ensureSubgraphMembership(containerName, fullName, subgraphs, nodeCtx.subgraphParents || (nodeCtx.subgraphParents = {}));

            const templateInfo = ensureNodeDefaults(fullName, spec.typeText || 'Node', nodeCtx, templates);
            setNodeTypeLabel(fullName, spec.typeText || 'Node', spec.typeIsCall, templateInfo, nodeCtx);

            const childKind = inferContainerKind(spec.typeText, templates);
            if (childKind) {
                addContainerInternalNodes(fullName, childKind, spec.lineNumber, nodeCtx, subgraphs);

                // Try to expand from template literals first, else from positional args (class-direct).
                if (templateInfo?.nodesArg || templateInfo?.edgesArg) {
                    expandContainerFromDeclarativeLists(
                        fullName,
                        childKind,
                        templateInfo.nodesArg,
                        templateInfo.edgesArg,
                        code,
                        nodeCtx,
                        edgeCtx,
                        subgraphs,
                        templates,
                        literalValues,
                        visited
                    );
                } else if (spec.args && spec.args.length > 0) {
                    const extracted = extractContainerListsFromArgs(spec.args, code, literalValues);
                    if (extracted.nodesNode || extracted.edgesNode) {
                        expandContainerFromDeclarativeLists(
                            fullName,
                            childKind,
                            extracted.nodesNode,
                            extracted.edgesNode,
                            code,
                            nodeCtx,
                            edgeCtx,
                            subgraphs,
                            templates,
                            literalValues,
                            visited
                        );
                    }
                }
            }

            // If this node comes from a template that defines build_func, record it (best-effort).
            if (templateInfo?.buildFunc) {
                if (!nodeCtx.nodeBuildFuncs) nodeCtx.nodeBuildFuncs = {};
                nodeCtx.nodeBuildFuncs[fullName] = templateInfo.buildFunc as any;
            }
        }
    }

    if (edgesNode) {
        const specs = parseEdgesListLiteral(edgesNode, code, literalValues);
        for (const spec of specs) {
            const from = `${prefix}${normalizeContainerEndpoint(spec.from, kind)}`;
            const to = `${prefix}${normalizeContainerEndpoint(spec.to, kind)}`;

            // Ensure endpoints exist (best-effort for dynamic/incomplete lists).
            addNodeIfMissing(from, nodeCtx.nodeTypes[from] || 'Node', spec.lineNumber, nodeCtx);
            addNodeIfMissing(to, nodeCtx.nodeTypes[to] || 'Node', spec.lineNumber, nodeCtx);

            const { keys, keysDetails } = parseEdgeKeysArgument(spec.keysNode, code);
            edgeCtx.edges.push({
                from,
                to,
                keys,
                keysDetails,
                lineNumber: spec.lineNumber
            });
        }
    }
}

/**
 * Parse RootGraph/Graph/Loop constructor call and populate NodeParseContext/EdgeParseContext.
 * This only handles the *top-level* graph declared by the call (not nested templates).
 */
export function parseDeclarativeGraphCallIntoContexts(
    callNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    templates?: { [name: string]: ParsedNodeTemplate },
    opts?: { isRootGraph?: boolean }
): void {
    const args = getCallArgs(callNode);
    const kw = getKeywordArgMap(args, code);

    const nodesArg = kw.get('nodes');
    const edgesArg = kw.get('edges');

    if (nodesArg) {
        const nodeSpecs = parseNodesListLiteral(nodesArg, code, nodeCtx.literalValues);
        const visited = new Set<string>();
        for (const spec of nodeSpecs) {
            addNodeIfMissing(spec.name, spec.typeText || 'Node', spec.lineNumber, nodeCtx);

            const templateInfo = ensureNodeDefaults(spec.name, spec.typeText || 'Node', nodeCtx, templates);
            setNodeTypeLabel(spec.name, spec.typeText || 'Node', spec.typeIsCall, templateInfo, nodeCtx);

            // Internal structure markers (entry/exit/controller/terminate)
            const kind = inferContainerKind(spec.typeText, templates);
            if (kind) {
                addContainerInternalNodes(spec.name, kind, spec.lineNumber, nodeCtx, subgraphs);

                // Expand declarative Graph/Loop internals when available:
                // - NodeTemplate(Graph/Loop, nodes=[...], edges=[...])
                // - Direct class usage: (name, Graph/Loop, ..., edges_list, nodes_list)
                const extractedFromArgs =
                    !templateInfo?.nodesArg && !templateInfo?.edgesArg && spec.args?.length
                        ? extractContainerListsFromArgs(spec.args, code, nodeCtx.literalValues)
                        : {};

                const innerNodes = templateInfo?.nodesArg ?? (extractedFromArgs as any).nodesNode;
                const innerEdges = templateInfo?.edgesArg ?? (extractedFromArgs as any).edgesNode;

                if (innerNodes || innerEdges) {
                    expandContainerFromDeclarativeLists(
                        spec.name,
                        kind,
                        innerNodes,
                        innerEdges,
                        code,
                        nodeCtx,
                        edgeCtx,
                        subgraphs,
                        templates,
                        nodeCtx.literalValues,
                        visited
                    );
                }
            }

            // If this node comes from a template that defines build_func, record it for async expansion (best-effort).
            if (templateInfo?.buildFunc) {
                if (!nodeCtx.nodeBuildFuncs) nodeCtx.nodeBuildFuncs = {};
                nodeCtx.nodeBuildFuncs[spec.name] = templateInfo.buildFunc;
            }

            // NOTE: positional args in declarative node tuples are not interpreted here.
            // For MASFactory, these can be risky for complex nodes; users should prefer NodeTemplate.
        }
    }

    if (edgesArg) {
        const edgeSpecs = parseEdgesListLiteral(edgesArg, code, nodeCtx.literalValues);
        for (const spec of edgeSpecs) {
            const from = opts?.isRootGraph ? normalizeContainerEndpoint(spec.from, 'Graph') : spec.from;
            const to = opts?.isRootGraph ? normalizeContainerEndpoint(spec.to, 'Graph') : spec.to;

            // RootGraph uses global 'entry'/'exit' display nodes; Graph/Loop templates will be handled in expansion.
            const resolvedFrom = opts?.isRootGraph && from === 'entry' ? 'entry' : from;
            const resolvedTo = opts?.isRootGraph && to === 'exit' ? 'exit' : to;

            const { keys, keysDetails } = parseEdgeKeysArgument(spec.keysNode, code);

            edgeCtx.edges.push({
                from: resolvedFrom,
                to: resolvedTo,
                keys,
                keysDetails,
                lineNumber: spec.lineNumber
            });
        }
    }

    // Graph-level pull_keys/push_keys/attributes are not represented as a node in preview (no root node).
    // Subgraph-level summaries are computed later from nodeCtx.* mappings.
}

/**
 * Collect NodeTemplate definitions from a block (best-effort, shallow scan).
 * This is used so declarative parsing can resolve template base kinds.
 */
export function collectLocalTemplates(
    blockNode: TSNode,
    code: string,
    templates: { [name: string]: ParsedNodeTemplate }
): void {
    for (const child of blockNode.children) {
        if (!child) continue;
        if (child.type === 'function_definition' || child.type === 'class_definition') continue;
        if (child.type !== 'expression_statement') continue;
        const first = child.namedChildren[0];
        if (!first || (first.type !== 'assignment' && first.type !== 'typed_assignment')) continue;
        const left = first.childForFieldName('left');
        const right = first.childForFieldName('right');
        if (!left || !right || right.type !== 'call') continue;
        const funcNode = right.childForFieldName('function');
        if (!funcNode) continue;
        const funcText = getNodeText(funcNode, code).trim();
        if (funcText !== 'NodeTemplate' && !funcText.endsWith('.NodeTemplate')) continue;
        const leftText = getNodeText(left, code).trim();
        const parsed = tryParseNodeTemplateAssignment(leftText, right, code);
        if (parsed) {
            templates[parsed.templateName] = parsed;
        }
    }
}
