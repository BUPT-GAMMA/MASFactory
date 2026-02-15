/**
 * Node parsing logic for MASFactory graphs
 */
import type { Node as TSNode } from 'web-tree-sitter';
import { extractMethodCall, getNodeText, isNonNullNode, parseDictArgument, parseKeysArgument } from './astUtils';
import { ParsedNodeTemplate } from './templateParser';
import type { ParserFeatures } from './features';

// Loop-based graph types (have controller/terminate internal nodes)
const LOOP_TYPES = [
    'Loop',
    'HubGraph',
    'MeshGraph', 
    'InstructorAssistantGraph',
    'PingPongGraph',
    'VerticalDecisionGraph'
];

// Graph-based types (have entry/exit internal nodes)
const GRAPH_TYPES = [
    'Graph',
    'VerticalGraph',
    'HorizontalGraph',
    'AdjacencyListGraph',
    'AdjacencyMatrixGraph',
    'VerticalSolverFirstDecisionGraph',
    'BrainstormingGraph',
    'AutoGraph',
    'SimpleWorkflow'
];

/**
 * Check if a node type is a Loop-based type
 */
function resolveTemplateBaseKind(
    nodeType: string,
    templates?: { [name: string]: ParsedNodeTemplate }
): 'Graph' | 'Loop' | 'Node' | null {
    if (!templates) return null;
    const direct = templates[nodeType];
    if (direct) return direct.baseKind;
    const normalized = nodeType.includes('.') ? nodeType.split('.').pop()! : nodeType;
    const byLast = templates[normalized];
    return byLast ? byLast.baseKind : null;
}

function isLoopType(nodeType: string, templates?: { [name: string]: ParsedNodeTemplate }): boolean {
    const normalized = nodeType.includes('.') ? nodeType.split('.').pop()! : nodeType;
    const templateKind = resolveTemplateBaseKind(nodeType, templates);
    if (templateKind === 'Loop') return true;
    return LOOP_TYPES.includes(normalized) || normalized.endsWith('Loop');
}

/**
 * Check if a node type is a Graph-based type (subgraph with entry/exit)
 */
function isGraphType(nodeType: string, templates?: { [name: string]: ParsedNodeTemplate }): boolean {
    const normalized = nodeType.includes('.') ? nodeType.split('.').pop()! : nodeType;
    const templateKind = resolveTemplateBaseKind(nodeType, templates);
    if (templateKind === 'Graph') return true;
    if (GRAPH_TYPES.includes(normalized)) return true;
    // Best-effort: treat custom graph/workflow classes as subgraphs unless explicitly a Loop.
    if (normalized.endsWith('Workflow')) return true;
    if (normalized.endsWith('Graph')) return !isLoopType(normalized, templates);
    return false;
}

export interface BuildFuncInfo {
    functionName: string;      // The actual builder function name
    modulePath: string;        // Module path from import (if imported)
    type: 'partial' | 'lambda' | 'closure' | 'direct';  // How the function is referenced
}

export interface NodeParseContext {
    nodes: string[];
    nodeTypes: { [key: string]: string };
    nodeLineNumbers: { [key: string]: number };
    variableToNodeName: { [variable: string]: string };
    nodePullKeys: { [key: string]: { [key: string]: string } | null | 'empty' };
    nodePushKeys: { [key: string]: { [key: string]: string } | null | 'empty' };
    nodeAttributes: { [key: string]: { [key: string]: any } | null };
    subgraphParents?: { [key: string]: string };
    // build_func parameter info for nodes (new feature)
    nodeBuildFuncs?: { [nodeName: string]: BuildFuncInfo };
    // Local NodeTemplate registry (for resolving template base kinds in declarative graphs)
    templates?: { [name: string]: ParsedNodeTemplate };
    // Best-effort literal bindings for declarative graphs (e.g., sub_nodes = [...], sub_edges = [...])
    // Used to resolve identifier references inside nodes=[...] / edges=[...] literals.
    literalValues?: { [name: string]: TSNode };
    // Line offset for reparsed code (used in builder function parsing)
    lineOffset?: number;
    /**
     * Parser feature flags (optional) for forward compatibility.
     * New parsing behaviors should be guarded behind flags with safe defaults.
     */
    features?: ParserFeatures;
}

function getPositionalArgs(args: TSNode[]): TSNode[] {
    return args.filter(arg => arg.type !== 'keyword_argument' && arg.type !== 'comment');
}

function getKeywordArgMap(
    args: TSNode[],
    code: string
): Map<string, TSNode> {
    const map = new Map<string, TSNode>();
    for (const arg of args) {
        if (arg.type !== 'keyword_argument') continue;
        const argNameNode = arg.childForFieldName('name');
        const argValueNode = arg.childForFieldName('value');
        if (!argNameNode || !argValueNode) continue;
        const argName = getNodeText(argNameNode, code);
        map.set(argName, argValueNode);
    }
    return map;
}

function extractNodeTypeFromCreateNodeArgs(args: TSNode[], code: string): string {
    const positional = getPositionalArgs(args);
    // Common: create_node(NodeType, ...)
    if (positional.length > 0) {
        const first = positional[0];
        const text = getNodeText(first, code).trim();
        // Ignore "**kwargs" style splats (dynamic; no explicit type here)
        if (!text.startsWith('**')) {
            return text;
        }
    }

    // Also support keyword style: create_node(cls=NodeType, ...) / create_node(node_type=NodeType, ...)
    const kw = getKeywordArgMap(args, code);
    const clsNode = kw.get('cls') || kw.get('node_type');
    if (clsNode) {
        return getNodeText(clsNode, code).trim();
    }

    return 'Node';
}

function extractNodeNameFromArgs(
    args: TSNode[],
    code: string,
    fallbackName: string
): string {
    const kw = getKeywordArgMap(args, code);
    const nameNode = kw.get('name');
    if (nameNode) {
        return extractNodeNameFromExpression(nameNode, code, fallbackName);
    }

    // Common: create_node(NodeType, "name", ...)
    const positional = getPositionalArgs(args);
    if (positional.length >= 2) {
        return extractNodeNameFromExpression(positional[1], code, fallbackName);
    }

    return fallbackName;
}

function extractNodeNameFromExpression(
    node: TSNode,
    code: string,
    fallbackName: string
): string {
    const raw = getNodeText(node, code).trim();

    if (node.type === 'string') {
        // Handles both "x" and f"x" forms (tree-sitter treats f-strings as string too)
        const stripped = raw.replace(/^f?["']|["']$/g, '');
        // If it still looks dynamic, fallback
        if (stripped.includes('{') || stripped.includes('self.')) {
            return fallbackName;
        }
        return stripped;
    }

    if (node.type === 'binary_operator') {
        // String concatenation like: self.name + "_suffix"
        const parts = raw.split('+').map(p => p.trim());
        const suffixPart = parts.find(p => p.startsWith('"') || p.startsWith("'"));
        if (suffixPart) {
            const suffix = suffixPart.replace(/^["']|["']$/g, '');
            return fallbackName + suffix;
        }
        return fallbackName;
    }

    // Dynamic name (identifier, attribute, f-string with expressions, etc.)
    const stripped = raw.replace(/^f?["']|["']$/g, '');
    if (stripped.includes('{') || stripped.includes('self.')) {
        return fallbackName;
    }
    return stripped || fallbackName;
}

/**
 * Parse create_node call and extract node information
 * @param loopIteration - If inside a loop, the current iteration index (used for unique naming)
 * @param subgraphs - Optional subgraphs map to track parent-child relationships
 */
export function parseCreateNode(
    leftSide: TSNode,
    callNode: TSNode,
    code: string,
    ctx: NodeParseContext,
    loopIteration?: number,
    subgraphs?: { [parent: string]: string[] }
): void {
    // Get variable name (e.g., self._dag_designer_agent or test_loop)
    const variableName = getNodeText(leftSide, code);
    
    // Check if this is a subgraph node by examining the function call
    const functionNode = callNode.childForFieldName('function');
    if (!functionNode) return;
    
    const functionText = getNodeText(functionNode, code);
    let parentGraph = '';
    
    // Extract parent graph from function call using unified utility
    const methodCall = extractMethodCall(functionText);
    if (methodCall && methodCall.method === 'create_node') {
        const parentVar = methodCall.caller;
        if (parentVar !== 'self') {
            // Try to resolve the parent variable
            console.log(`[Parser] Looking up parent variable: ${parentVar}, variableToNodeName keys: ${Object.keys(ctx.variableToNodeName).join(', ')}`);
            if (ctx.variableToNodeName[parentVar]) {
                parentGraph = ctx.variableToNodeName[parentVar];
                console.log(`[Parser] Found parent mapping: ${parentVar} -> ${parentGraph}`);
            } else if (parentVar.startsWith('self._')) {
                // Handle self._xxx pattern - try looking up the full variable name first
                const fullVar = parentVar;
                if (ctx.variableToNodeName[fullVar]) {
                    parentGraph = ctx.variableToNodeName[fullVar];
                    console.log(`[Parser] Found parent via full variable: ${fullVar} -> ${parentGraph}`);
                } else {
                    // Fallback to stripped name
                    parentGraph = parentVar.replace('self._', '');
                    console.log(`[Parser] Using stripped parent name: ${parentGraph}`);
                }
            } else if (parentVar.startsWith('self.')) {
                // Handle self.xxx pattern
                if (ctx.variableToNodeName[parentVar]) {
                    parentGraph = ctx.variableToNodeName[parentVar];
                } else {
                    parentGraph = parentVar.replace('self.', '');
                }
            } else {
                parentGraph = parentVar;
            }
        }
    }
    
    // Get arguments
    const argsNode = callNode.childForFieldName('arguments');
    if (!argsNode) return;

    const args = argsNode.namedChildren.filter(isNonNullNode);
    if (args.length === 0) return;

    const fallbackBaseName = variableName.replace('self._', '').replace('self.', '');

    // Extract node type and base name (support positional + keyword styles)
    const nodeType = extractNodeTypeFromCreateNodeArgs(args, code);
    const rawNodeName = extractNodeNameFromArgs(args, code, fallbackBaseName);

    // Namespace node names by parent graph to avoid collisions across subgraphs.
    // MASFactory allows identical node names in different Graph/Loop instances.
    // We encode the containment path into the node ID: parent_child (recursively).
    let nodeName = parentGraph ? `${parentGraph}_${rawNodeName}` : rawNodeName;

    // Add loop iteration suffix if inside a graph-building loop
    if (loopIteration !== undefined) {
        nodeName = `${nodeName}_${loopIteration}`;
    }

    // Always map variable -> resolved node name (even if node already exists).
    ctx.variableToNodeName[variableName] = nodeName;

    // Parse other keyword params using the final, namespaced nodeName
    const kw = getKeywordArgMap(args, code);
    const pullKeysNode = kw.get('pull_keys');
    if (pullKeysNode) {
        ctx.nodePullKeys[nodeName] = parseKeysArgument(pullKeysNode, code);
    }
    const pushKeysNode = kw.get('push_keys');
    if (pushKeysNode) {
        ctx.nodePushKeys[nodeName] = parseKeysArgument(pushKeysNode, code);
    }
    const attributesNode = kw.get('attributes');
    if (attributesNode) {
        ctx.nodeAttributes[nodeName] = parseDictArgument(attributesNode, code);
    }
    const buildFuncNode = kw.get('build_func');
    if (buildFuncNode) {
        const buildFuncInfo = parseBuildFuncArgument(buildFuncNode, code);
        if (buildFuncInfo) {
            if (!ctx.nodeBuildFuncs) {
                ctx.nodeBuildFuncs = {};
            }
            ctx.nodeBuildFuncs[nodeName] = buildFuncInfo;
            console.log(
                `[Parser] Found build_func for ${nodeName}: ${buildFuncInfo.functionName} (type: ${buildFuncInfo.type})`
            );
        }
    }

    // Add node
    if (!ctx.nodes.includes(nodeName)) {
        ctx.nodes.push(nodeName);
        ctx.nodeTypes[nodeName] = nodeType;
        // Add lineOffset for reparsed code (builder function parsing)
        const lineOffset = ctx.lineOffset || 0;
        ctx.nodeLineNumbers[nodeName] = leftSide.startPosition.row + 1 + lineOffset;
        
        // Track subgraph relationship if we have a parent
        if (parentGraph && subgraphs) {
            if (!subgraphs[parentGraph]) {
                subgraphs[parentGraph] = [];
            }
            subgraphs[parentGraph].push(nodeName);
            if (ctx.subgraphParents) {
                ctx.subgraphParents[nodeName] = parentGraph;
            }
        }
        
        // Add internal nodes based on graph type
        if (isLoopType(nodeType, ctx.templates)) {
            // Loop-based types have controller and terminate internal nodes
            const controllerName = `${nodeName}_controller`;
            const terminateName = `${nodeName}_terminate`;
            
            if (!ctx.nodes.includes(controllerName)) {
                ctx.nodes.push(controllerName);
                ctx.nodeTypes[controllerName] = 'Controller';
            }
            if (!ctx.nodes.includes(terminateName)) {
                ctx.nodes.push(terminateName);
                ctx.nodeTypes[terminateName] = 'TerminateNode';
            }
            
            // Add internal nodes to subgraph
            if (subgraphs) {
                if (!subgraphs[nodeName]) {
                    subgraphs[nodeName] = [];
                }
                subgraphs[nodeName].push(controllerName, terminateName);
                if (ctx.subgraphParents) {
                    ctx.subgraphParents[controllerName] = nodeName;
                    ctx.subgraphParents[terminateName] = nodeName;
                }
            }
        } else if (isGraphType(nodeType, ctx.templates)) {
            // Graph-based types have entry and exit internal nodes
            const entryName = `${nodeName}_entry`;
            const exitName = `${nodeName}_exit`;
            
            if (!ctx.nodes.includes(entryName)) {
                ctx.nodes.push(entryName);
                ctx.nodeTypes[entryName] = 'entry';
            }
            if (!ctx.nodes.includes(exitName)) {
                ctx.nodes.push(exitName);
                ctx.nodeTypes[exitName] = 'exit';
            }
            
            // Add internal nodes to subgraph
            if (subgraphs) {
                if (!subgraphs[nodeName]) {
                    subgraphs[nodeName] = [];
                }
                subgraphs[nodeName].push(entryName, exitName);
                if (ctx.subgraphParents) {
                    ctx.subgraphParents[entryName] = nodeName;
                    ctx.subgraphParents[exitName] = nodeName;
                }
            }
        }
        
        console.log(`[Parser] Found node: ${nodeName} (type: ${nodeType}, variable: ${variableName}${parentGraph ? `, parent: ${parentGraph}` : ''})`);
    }
}

/**
 * Parse create_node call with RootGraph variable tracking (module-level)
 */
export function parseCreateNodeWithRootGraph(
    leftSide: TSNode,
    callNode: TSNode,
    code: string,
    ctx: NodeParseContext,
    subgraphs: { [parent: string]: string[] },
    rootGraphVariable: string,
    loopIteration?: number
): void {
    const variableName = getNodeText(leftSide, code);
    
    const functionNode = callNode.childForFieldName('function');
    if (!functionNode) return;
    
    const functionText = getNodeText(functionNode, code);
    
    // Extract parent graph from function call
    const methodCall = extractMethodCall(functionText);
    if (!methodCall || methodCall.method !== 'create_node') return;
    const parentVar = methodCall.caller;
    let parentGraph = '';
    
    // Determine parent graph
    if (parentVar === rootGraphVariable) {
        parentGraph = '';  // Top-level node
    } else if (ctx.variableToNodeName[parentVar]) {
        parentGraph = ctx.variableToNodeName[parentVar];
    } else {
        parentGraph = parentVar;
    }
    
    // Get arguments
    const argsNode = callNode.childForFieldName('arguments');
    if (!argsNode) return;

    const args = argsNode.namedChildren.filter(isNonNullNode);
    if (args.length === 0) return;

    // Extract node type and base name (support positional + keyword styles)
    const nodeType = extractNodeTypeFromCreateNodeArgs(args, code);
    const rawNodeName = extractNodeNameFromArgs(args, code, variableName);

    // Namespace by parent graph to avoid collisions across subgraphs
    let nodeName = parentGraph ? `${parentGraph}_${rawNodeName}` : rawNodeName;

    if (loopIteration !== undefined) {
        nodeName = `${nodeName}_${loopIteration}`;
    }

    // Always map variable to resolved node name
    ctx.variableToNodeName[variableName] = nodeName;

    // Parse other keyword params using the final nodeName
    const kw = getKeywordArgMap(args, code);
    const pullKeysNode = kw.get('pull_keys');
    if (pullKeysNode) {
        ctx.nodePullKeys[nodeName] = parseKeysArgument(pullKeysNode, code);
    }
    const pushKeysNode = kw.get('push_keys');
    if (pushKeysNode) {
        ctx.nodePushKeys[nodeName] = parseKeysArgument(pushKeysNode, code);
    }
    const attributesNode = kw.get('attributes');
    if (attributesNode) {
        ctx.nodeAttributes[nodeName] = parseDictArgument(attributesNode, code);
    }

    // Add node
    if (!ctx.nodes.includes(nodeName)) {
        ctx.nodes.push(nodeName);
        ctx.nodeTypes[nodeName] = nodeType;
        ctx.nodeLineNumbers[nodeName] = leftSide.startPosition.row + 1;
        
        // Track subgraph relationship
        if (parentGraph && ctx.subgraphParents) {
            ctx.subgraphParents[nodeName] = parentGraph;
            if (!subgraphs[parentGraph]) {
                subgraphs[parentGraph] = [];
            }
            subgraphs[parentGraph].push(nodeName);
        }
        
        // Add internal nodes based on graph type
        if (isLoopType(nodeType, ctx.templates)) {
            // Loop-based types have controller and terminate internal nodes
            const controllerName = `${nodeName}_controller`;
            const terminateName = `${nodeName}_terminate`;
            
            if (!ctx.nodes.includes(controllerName)) {
                ctx.nodes.push(controllerName);
                ctx.nodeTypes[controllerName] = 'Controller';
            }
            if (!ctx.nodes.includes(terminateName)) {
                ctx.nodes.push(terminateName);
                ctx.nodeTypes[terminateName] = 'TerminateNode';
            }
            
            // Add internal nodes to subgraph
            if (!subgraphs[nodeName]) {
                subgraphs[nodeName] = [];
            }
            subgraphs[nodeName].push(controllerName, terminateName);
            if (ctx.subgraphParents) {
                ctx.subgraphParents[controllerName] = nodeName;
                ctx.subgraphParents[terminateName] = nodeName;
            }
        } else if (isGraphType(nodeType, ctx.templates)) {
            // Graph-based types have entry and exit internal nodes
            const entryName = `${nodeName}_entry`;
            const exitName = `${nodeName}_exit`;
            
            if (!ctx.nodes.includes(entryName)) {
                ctx.nodes.push(entryName);
                ctx.nodeTypes[entryName] = 'entry';
            }
            if (!ctx.nodes.includes(exitName)) {
                ctx.nodes.push(exitName);
                ctx.nodeTypes[exitName] = 'exit';
            }
            
            // Add internal nodes to subgraph
            if (!subgraphs[nodeName]) {
                subgraphs[nodeName] = [];
            }
            subgraphs[nodeName].push(entryName, exitName);
            if (ctx.subgraphParents) {
                ctx.subgraphParents[entryName] = nodeName;
                ctx.subgraphParents[exitName] = nodeName;
            }
        }
        
        console.log(`[Parser] Found node: ${nodeName} (type: ${nodeType}${parentGraph ? `, parent: ${parentGraph}` : ''})`);
    }
}

/**
 * Parse build_func argument and extract function information
 * Supports three forms:
 * 1. partial(func, ...) - functools.partial
 * 2. lambda xxx: func(xxx, ...) - lambda expression
 * 3. func_name - direct function reference (closure or imported function)
 */
function parseBuildFuncArgument(argValue: TSNode, code: string): BuildFuncInfo | null {
    const valueText = getNodeText(argValue, code);
    
    // Case 1: partial(func, ...)
    if (argValue.type === 'call') {
        const funcNode = argValue.childForFieldName('function');
        const funcName = funcNode ? getNodeText(funcNode, code) : '';
        
        if (funcName === 'partial') {
            // Get the first argument of partial() which is the actual function
            const argsNode = argValue.childForFieldName('arguments');
            const firstArg = argsNode?.namedChildren?.filter(isNonNullNode)[0];
            if (firstArg) {
                const actualFuncName = getNodeText(firstArg, code);
                console.log(`[Parser] Parsed partial(): function=${actualFuncName}`);
                return {
                    functionName: actualFuncName,
                    modulePath: '', // Will be resolved via imports
                    type: 'partial'
                };
            }
        }
    }
    
    // Case 2: lambda xxx: func(xxx, ...)
    if (argValue.type === 'lambda') {
        const body = argValue.childForFieldName('body');
        if (body && body.type === 'call') {
            const funcNode = body.childForFieldName('function');
            if (funcNode) {
                const funcName = getNodeText(funcNode, code);
                console.log(`[Parser] Parsed lambda: function=${funcName}`);
                return {
                    functionName: funcName,
                    modulePath: '', // Will be resolved via imports
                    type: 'lambda'
                };
            }
        }
    }
    
    // Case 3: Direct function reference (closure or imported function)
    if (argValue.type === 'identifier') {
        const funcName = valueText;
        console.log(`[Parser] Parsed direct function reference: ${funcName}`);
        return {
            functionName: funcName,
            modulePath: '', // Will be resolved via imports or local definition
            type: 'direct'
        };
    }
    
    // Case 4: Attribute access like module.func
    if (argValue.type === 'attribute') {
        const funcName = valueText;
        console.log(`[Parser] Parsed attribute function reference: ${funcName}`);
        return {
            functionName: funcName,
            modulePath: '',
            type: 'direct'
        };
    }
    
    console.log(`[Parser] Could not parse build_func: ${valueText} (type: ${argValue.type})`);
    return null;
}
