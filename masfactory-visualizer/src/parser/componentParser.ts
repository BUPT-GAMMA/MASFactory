/**
 * Component Parser - Parses composite component definitions from external files
 */
import type { Node as TSNode } from 'web-tree-sitter';
import { createPythonParser } from './treeSitter';

import { GraphEdge } from './types';
import { queryNodes, getNodeText, getBaseClasses } from './astUtils';
import { findBuildMethodAndBaseType, parseBuildMethod } from './buildMethodParser';
import { NodeParseContext } from './nodeParser';
import { EdgeParseContext } from './edgeParser';
import { tryParseNodeTemplateAssignment, ParsedNodeTemplate } from './templateParser';
import { parseDictArgument } from './astUtils';

export interface ComponentStructure {
    nodes: string[];
    nodeTypes: { [key: string]: string };
    nodeLineNumbers: { [key: string]: number };
    nodePullKeys: { [key: string]: { [key: string]: any } | null | 'empty' };
    nodePushKeys: { [key: string]: { [key: string]: any } | null | 'empty' };
    nodeAttributes: { [key: string]: { [key: string]: any } | null };
    edges: GraphEdge[];
    subgraphs: { [parent: string]: string[] };
    hasComplexStructure: boolean;  // true if contains if/for (structure may be dynamic)
    /** Source file path where this component is defined (filled by GraphParser). */
    sourceFilePath?: string;
    /** Base classes (raw AST text) for optional inheritance fallback. */
    baseClasses?: string[];
    /** Which method was parsed to build this structure. */
    parsedMethodName?: 'build' | '__init__';
}

/**
 * Parse a composite component's internal structure from its source code
 */
export function parseComponentStructure(
    componentCode: string,
    componentClassName: string
): ComponentStructure | null {
    const parser = createPythonParser();
    if (!parser) return null;
    
    try {
        const tree = parser.parse(componentCode);
        if (!tree) return null;
        const rootNode = tree.rootNode;
        
        // Find the specific class definition
        const classNodes = queryNodes(rootNode, 'class_definition');
        let targetClass: TSNode | null = null;
        
        for (const classNode of classNodes) {
            const nameNode = classNode.childForFieldName('name');
            if (nameNode && getNodeText(nameNode, componentCode) === componentClassName) {
                targetClass = classNode;
                break;
            }
        }
        
        if (!targetClass) {
            console.log(`[ComponentParser] Class ${componentClassName} not found in code`);
            return null;
        }
        
        // Get base type
        const baseClasses = getBaseClasses(targetClass);
        const baseType = determineBaseType(baseClasses);
        
        // Find build method; fall back to __init__ for components that construct graphs there.
        const parsedMethodName: ComponentStructure['parsedMethodName'] =
            findMethodInClass(targetClass, componentCode, 'build') ? 'build' : '__init__';
        const buildMethod = findMethodInClass(targetClass, componentCode, parsedMethodName);
        if (!buildMethod) {
            console.log(`[ComponentParser] No build/__init__ method found in ${componentClassName}`);
            return null;
        }
        
        // Mark complex structure (if/for statements), but still parse best-effort.
        const hasComplexStructure = checkForComplexStructure(buildMethod);
        
        // Parse the build method
        const result = parseBuildMethodForComponent(buildMethod, componentCode, baseType);
        
        console.log(`[ComponentParser] Parsed ${componentClassName}: ${result.nodes.length} nodes, ${result.edges.length} edges`);
        
        return { ...result, hasComplexStructure, baseClasses, parsedMethodName };
    } catch (error) {
        console.error(`[ComponentParser] Error parsing ${componentClassName}:`, error);
        return null;
    }
}

function stripStringQuotes(raw: string): string {
    return raw.replace(/^f?["']|["']$/g, '');
}

function parseStringLiteral(node: TSNode, code: string): string | null {
    if (node.type !== 'string') return null;
    return stripStringQuotes(getNodeText(node, code).trim());
}

function resolveLiteralNode(
    node: TSNode,
    code: string,
    literalValues: { [name: string]: TSNode }
): TSNode {
    if (node.type !== 'identifier' && node.type !== 'attribute') return node;
    const raw = getNodeText(node, code).trim();
    return literalValues[raw] ?? (raw.includes('.') ? literalValues[raw.split('.').pop()!] ?? node : node);
}

function inferContainerKind(
    rawTypeText: string,
    templates: { [name: string]: ParsedNodeTemplate }
): 'Graph' | 'Loop' | null {
    const direct = templates[rawTypeText];
    if (direct?.baseKind === 'Graph' || direct?.baseKind === 'Loop') return direct.baseKind;
    const normalized = rawTypeText.includes('.') ? rawTypeText.split('.').pop()! : rawTypeText;
    const byLast = templates[normalized];
    if (byLast?.baseKind === 'Graph' || byLast?.baseKind === 'Loop') return byLast.baseKind;
    if (normalized === 'Loop' || normalized.endsWith('Loop')) return 'Loop';
    if (normalized === 'Graph' || normalized === 'RootGraph') return 'Graph';
    if (normalized.endsWith('Graph') || normalized.endsWith('Workflow')) return 'Graph';
    return null;
}

function parseNodesListLiteral(
    node: TSNode,
    code: string,
    literalValues: { [name: string]: TSNode }
): Array<{ name: string; typeText: string; args: TSNode[]; lineNumber: number }> {
    node = resolveLiteralNode(node, code, literalValues);
    if (node.type !== 'list') return [];
    const out: Array<{ name: string; typeText: string; args: TSNode[]; lineNumber: number }> = [];
    for (const item of node.namedChildren) {
        if (!item) continue;
        if (item.type !== 'tuple') continue;
        const elems = item.namedChildren.filter((c): c is TSNode => !!c && c.type !== 'comment');
        if (elems.length < 2) continue;
        const name = parseStringLiteral(elems[0], code);
        if (!name) continue;
        const typeText = getNodeText(elems[1], code).trim();
        const args = elems.slice(2);
        out.push({ name, typeText, args, lineNumber: item.startPosition.row + 1 });
    }
    return out;
}

function parseEdgesListLiteral(
    node: TSNode,
    code: string,
    literalValues: { [name: string]: TSNode }
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

function parseEdgeKeysArgument(
    node: TSNode | undefined,
    code: string
): { keys: string[]; keysDetails?: { [key: string]: string } } {
    if (!node || node.type === 'none') {
        return { keys: ['message'], keysDetails: { message: '' } };
    }
    if (node.type === 'dictionary') {
        const parsed = parseDictArgument(node, code);
        if (parsed) {
            return { keys: Object.keys(parsed), keysDetails: parsed };
        }
        return { keys: [], keysDetails: {} };
    }
    return { keys: ['message'], keysDetails: { message: '' } };
}

function looksLikeEdgeTupleList(
    node: TSNode,
    code: string,
    literalValues: { [name: string]: TSNode }
): boolean {
    const resolved = resolveLiteralNode(node, code, literalValues);
    if (resolved.type !== 'list') return false;
    const firstTuple = resolved.namedChildren.find((c): c is TSNode => !!c && c.type === 'tuple');
    if (!firstTuple) return false;
    const elems = firstTuple.namedChildren.filter((c): c is TSNode => !!c && c.type !== 'comment');
    if (elems.length < 2) return false;
    return elems[0].type === 'string' && elems[1].type === 'string';
}

function looksLikeNodeTupleList(
    node: TSNode,
    code: string,
    literalValues: { [name: string]: TSNode }
): boolean {
    const resolved = resolveLiteralNode(node, code, literalValues);
    if (resolved.type !== 'list') return false;
    const firstTuple = resolved.namedChildren.find((c): c is TSNode => !!c && c.type === 'tuple');
    if (!firstTuple) return false;
    const elems = firstTuple.namedChildren.filter((c): c is TSNode => !!c && c.type !== 'comment');
    if (elems.length < 2) return false;
    return elems[0].type === 'string' && elems[1].type !== 'string';
}

function extractContainerListsFromArgs(
    args: TSNode[],
    code: string,
    literalValues: { [name: string]: TSNode }
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
    return { nodesNode, edgesNode };
}

/**
 * Parse a NodeTemplate definition (module-level assignment) and return its internal graph structure.
 *
 * Supports patterns like:
 *   ProfileGenerationGraph = NodeTemplate(Graph, nodes=[...], edges=[...])
 */
export function parseTemplateStructure(
    componentCode: string,
    templateName: string
): ComponentStructure | null {
    const parser = createPythonParser();
    if (!parser) return null;

    try {
        const tree = parser.parse(componentCode);
        if (!tree) return null;
        const rootNode = tree.rootNode;

        // Collect simple literal bindings (edges/nodes variables) and NodeTemplate definitions.
        const literalValues: { [name: string]: TSNode } = {};
        const templates: { [name: string]: ParsedNodeTemplate } = {};

        for (const child of rootNode.children) {
            if (!child) continue;
            if (child.type !== 'expression_statement') continue;
            const first = child.namedChildren[0];
            if (!first || (first.type !== 'assignment' && first.type !== 'typed_assignment')) continue;
            const left = first.childForFieldName('left');
            const right = first.childForFieldName('right');
            if (!left || !right) continue;

            const leftText = getNodeText(left, componentCode).trim();

            if (right.type === 'list' || right.type === 'tuple' || right.type === 'dictionary') {
                if (leftText) literalValues[leftText] = right;
                continue;
            }

            if (right.type !== 'call') continue;
            const fn = right.childForFieldName('function');
            if (!fn) continue;
            const fnText = getNodeText(fn, componentCode).trim();
            if (fnText !== 'NodeTemplate' && !fnText.endsWith('.NodeTemplate')) continue;

            const parsed = tryParseNodeTemplateAssignment(leftText, right, componentCode);
            if (parsed) {
                templates[parsed.templateName] = parsed;
            }
        }

        const target =
            templates[templateName] ||
            templates[templateName.includes('.') ? templateName.split('.').pop()! : templateName];
        if (!target) {
            return null;
        }
        if (target.baseKind !== 'Graph' && target.baseKind !== 'Loop') {
            return null;
        }

        const baseType = target.baseKind;

        // Initialize internal nodes
        const nodes: string[] = [];
        const nodeTypes: { [key: string]: string } = {};
        const nodeLineNumbers: { [key: string]: number } = {};
        if (baseType === 'Loop') {
            nodes.push('controller', 'terminate');
            nodeTypes['controller'] = 'Controller';
            nodeTypes['terminate'] = 'TerminateNode';
        } else {
            nodes.push('entry', 'exit');
            nodeTypes['entry'] = 'entry';
            nodeTypes['exit'] = 'exit';
        }

        const nodePullKeys: { [key: string]: { [key: string]: any } | null | 'empty' } = {};
        const nodePushKeys: { [key: string]: { [key: string]: any } | null | 'empty' } = {};
        const nodeAttributes: { [key: string]: { [key: string]: any } | null } = {};
        const edges: GraphEdge[] = [];
        const subgraphs: { [parent: string]: string[] } = {};

        // Expand root container (no prefix) and recursively expand nested containers with prefixing.
        const expandContainer = (
            containerKey: string,
            kind: 'Graph' | 'Loop',
            nodesNode: TSNode | undefined,
            edgesNode: TSNode | undefined
        ) => {
            const prefix = containerKey ? `${containerKey}_` : '';

            if (nodesNode) {
                const specs = parseNodesListLiteral(nodesNode, componentCode, literalValues);
                for (const spec of specs) {
                    const fullName = `${prefix}${spec.name}`;
                    if (!nodes.includes(fullName)) nodes.push(fullName);
                    if (!nodeTypes[fullName]) nodeTypes[fullName] = spec.typeText || 'Node';
                    if (!nodeLineNumbers[fullName]) nodeLineNumbers[fullName] = spec.lineNumber;

                    if (containerKey) {
                        if (!subgraphs[containerKey]) subgraphs[containerKey] = [];
                        if (!subgraphs[containerKey].includes(fullName)) subgraphs[containerKey].push(fullName);
                    }

                    const templateInfo =
                        templates[spec.typeText] ||
                        templates[spec.typeText.includes('.') ? spec.typeText.split('.').pop()! : spec.typeText];

                    const childKind = inferContainerKind(spec.typeText, templates);
                    if (childKind) {
                        // Internal nodes for the child container
                        const internalA = childKind === 'Loop' ? `${fullName}_controller` : `${fullName}_entry`;
                        const internalB = childKind === 'Loop' ? `${fullName}_terminate` : `${fullName}_exit`;
                        if (!nodes.includes(internalA)) nodes.push(internalA);
                        if (!nodes.includes(internalB)) nodes.push(internalB);
                        nodeTypes[internalA] = childKind === 'Loop' ? 'Controller' : 'entry';
                        nodeTypes[internalB] = childKind === 'Loop' ? 'TerminateNode' : 'exit';
                        subgraphs[fullName] = [internalA, internalB];

                        // Determine nested declarative lists from template or positional args.
                        const extracted =
                            !templateInfo?.nodesArg && !templateInfo?.edgesArg && spec.args?.length
                                ? extractContainerListsFromArgs(spec.args, componentCode, literalValues)
                                : {};
                        const childNodesNode = templateInfo?.nodesArg ?? (extracted as any).nodesNode;
                        const childEdgesNode = templateInfo?.edgesArg ?? (extracted as any).edgesNode;
                        if (childNodesNode || childEdgesNode) {
                            expandContainer(fullName, childKind, childNodesNode, childEdgesNode);
                        }
                    }
                }
            }

            if (edgesNode) {
                const specs = parseEdgesListLiteral(edgesNode, componentCode, literalValues);
                for (const spec of specs) {
                    const from = `${prefix}${normalizeContainerEndpoint(spec.from, kind)}`;
                    const to = `${prefix}${normalizeContainerEndpoint(spec.to, kind)}`;

                    if (!nodes.includes(from)) {
                        nodes.push(from);
                        nodeTypes[from] = nodeTypes[from] || 'Node';
                    }
                    if (!nodes.includes(to)) {
                        nodes.push(to);
                        nodeTypes[to] = nodeTypes[to] || 'Node';
                    }

                    const { keys, keysDetails } = parseEdgeKeysArgument(spec.keysNode, componentCode);
                    edges.push({
                        from,
                        to,
                        keys,
                        keysDetails,
                        lineNumber: spec.lineNumber
                    });
                }
            }
        };

        expandContainer('', baseType, target.nodesArg, target.edgesArg);

        return {
            nodes,
            nodeTypes,
            nodeLineNumbers,
            nodePullKeys,
            nodePushKeys,
            nodeAttributes,
            edges,
            subgraphs,
            hasComplexStructure: false
        };
    } catch (error) {
        console.error(`[ComponentParser] Error parsing NodeTemplate ${templateName}:`, error);
        return null;
    }
}

/**
 * Find a method within a class definition (supports decorated defs)
 */
function findMethodInClass(classNode: TSNode, code: string, methodName: 'build' | '__init__'): TSNode | null {
    const body = classNode.childForFieldName('body');
    if (!body) return null;
    
    for (const child of body.namedChildren) {
        if (!child) continue;
        const funcDef = child.type === 'decorated_definition'
            ? child.namedChildren.find((c): c is TSNode => !!c && c.type === 'function_definition')
            : child.type === 'function_definition'
                ? child
                : null;
        if (!funcDef) continue;
        const nameNode = funcDef.childForFieldName('name');
        if (nameNode && getNodeText(nameNode, code) === methodName) {
            return funcDef;
        }
    }
    return null;
}

/**
 * Check if build method contains complex control flow (if/for)
 */
function checkForComplexStructure(buildMethod: TSNode): boolean {
    const body = buildMethod.childForFieldName('body');
    if (!body) return false;
    
    // Check for if_statement or for_statement at any level
    const ifNodes = queryNodes(body, 'if_statement');
    const forNodes = queryNodes(body, 'for_statement');
    const whileNodes = queryNodes(body, 'while_statement');
    const tryNodes = queryNodes(body, 'try_statement');
    
    return ifNodes.length > 0 || forNodes.length > 0 || whileNodes.length > 0 || tryNodes.length > 0;
}

/**
 * Determine base type from base classes
 */
function determineBaseType(baseClasses: string[]): string {
    const loopTypes = ['Loop', 'HubGraph', 'MeshGraph', 'InstructorAssistantGraph'];
    const graphTypes = ['Graph', 'RootGraph', 'VerticalGraph', 'HorizontalGraph', 
                        'AdjacencyListGraph', 'AdjacencyMatrixGraph', 'BrainstormingGraph', 'AutoGraph',
                        'VerticalDecisionGraph', 'VerticalSolverFirstDecisionGraph'];
    
    for (const base of baseClasses) {
        if (loopTypes.some(t => base.includes(t))) {
            return 'Loop';
        }
        if (graphTypes.some(t => base.includes(t))) {
            return 'Graph';
        }
    }
    return 'Graph';
}

/**
 * Parse build method and extract structure
 */
function parseBuildMethodForComponent(
    buildMethod: TSNode,
    code: string,
    baseType: string
): {
    nodes: string[];
    nodeTypes: { [key: string]: string };
    nodeLineNumbers: { [key: string]: number };
    nodePullKeys: { [key: string]: { [key: string]: any } | null | 'empty' };
    nodePushKeys: { [key: string]: { [key: string]: any } | null | 'empty' };
    nodeAttributes: { [key: string]: { [key: string]: any } | null };
    edges: GraphEdge[];
    subgraphs: { [parent: string]: string[] };
} {
    // Initialize with appropriate internal nodes
    const nodes: string[] = [];
    const nodeTypes: { [key: string]: string } = {};
    const nodeLineNumbers: { [key: string]: number } = {};
    
    if (baseType === 'Loop') {
        nodes.push('controller', 'terminate');
        nodeTypes['controller'] = 'Controller';
        nodeTypes['terminate'] = 'TerminateNode';
    } else {
        nodes.push('entry', 'exit');
        nodeTypes['entry'] = 'entry';
        nodeTypes['exit'] = 'exit';
    }
    
    const nodeCtx: NodeParseContext = {
        nodes,
        nodeTypes,
        nodeLineNumbers,
        variableToNodeName: {},
        nodePullKeys: {},
        nodePushKeys: {},
        nodeAttributes: {},
        subgraphParents: {}
    };
    
    const edges: GraphEdge[] = [];
    const edgeCtx: EdgeParseContext = {
        edges,
        variableToNodeName: nodeCtx.variableToNodeName,
        nodes,
        subgraphParents: {}
    };
    
    const subgraphs: { [parent: string]: string[] } = {};
    
    // Parse the build method
    parseBuildMethod(buildMethod, code, nodeCtx, edgeCtx, subgraphs);
    
    return {
        nodes,
        nodeTypes,
        nodeLineNumbers,
        nodePullKeys: nodeCtx.nodePullKeys,
        nodePushKeys: nodeCtx.nodePushKeys,
        nodeAttributes: nodeCtx.nodeAttributes,
        edges,
        subgraphs
    };
}
