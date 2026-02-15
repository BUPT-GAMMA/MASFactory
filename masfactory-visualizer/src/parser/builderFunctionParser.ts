/**
 * Builder Function Parser
 * 
 * Handles parsing of "builder function" pattern where subgraph structure
 * is defined in a separate function that receives the parent node as parameter.
 * 
 * Example pattern:
 *   def build_agent_config_loop(loop: Loop, model: Model, ...) -> None:
 *       prompt_agent = loop.create_node(Agent, name="prompt_generator", ...)
 *       loop.edge_from_controller(receiver=prompt_agent, ...)
 */
import type { Node as TSNode } from 'web-tree-sitter';
import { createPythonParser } from './treeSitter';

import { GraphEdge } from './types';
import { queryNodes, getNodeText } from './astUtils';
import { NodeParseContext, parseCreateNode } from './nodeParser';
import { EdgeParseContext, parseEdgeCreation, isEdgeCreationMethod } from './edgeParser';

export interface BuilderFunctionInfo {
    functionName: string;
    parentParamName: string;  // e.g., "loop" in build_agent_config_loop(loop: Loop, ...)
    parentParamType: string;  // e.g., "Loop"
    hasComplexStructure: boolean;
}

export interface BuilderFunctionStructure {
    nodes: string[];
    nodeTypes: { [key: string]: string };
    nodeLineNumbers: { [key: string]: number };  // Line numbers in source file
    edges: GraphEdge[];
    subgraphs: { [parent: string]: string[] };
    hasComplexStructure: boolean;
    sourceFilePath?: string;  // Absolute path of the source file (set by parser)
    nodePullKeys?: { [key: string]: { [key: string]: string } | null | 'empty' };
    nodePushKeys?: { [key: string]: { [key: string]: string } | null | 'empty' };
}

/**
 * Detect if a file contains a builder function pattern
 * A builder function:
 *   1. Has first parameter typed as Loop or Graph (or subclass)
 *   2. Contains calls like param.create_node(), param.create_edge()
 */
export function detectBuilderFunction(code: string): BuilderFunctionInfo | null {
    const parser = createPythonParser();
    if (!parser) return null;
    
    try {
        const tree = parser.parse(code);
        if (!tree) return null;
        const rootNode = tree.rootNode;
        
        // Find function definitions at module level
        const functionDefs = queryNodes(rootNode, 'function_definition');
        
        for (const funcDef of functionDefs) {
            // Skip nested functions (only check top-level)
            if (funcDef.parent?.type !== 'module') continue;
            
            const nameNode = funcDef.childForFieldName('name');
            if (!nameNode) continue;
            
            const funcName = getNodeText(nameNode, code);
            
            // Get parameters
            const paramsNode = funcDef.childForFieldName('parameters');
            if (!paramsNode) continue;
            
            // Check first parameter - should be typed as Loop/Graph
            const firstParam = getFirstTypedParameter(paramsNode, code);
            if (!firstParam) continue;
            
            // Check if the type hints to Loop, Graph, or their subclasses
            const graphTypes = ['Loop', 'Graph', 'RootGraph', 'HubGraph', 'MeshGraph'];
            if (!graphTypes.some(t => firstParam.type.includes(t))) continue;
            
            // Check if function body contains calls on the first parameter
            const body = funcDef.childForFieldName('body');
            if (!body) continue;
            
            const bodyText = getNodeText(body, code);
            const hasCreateNodeCalls = bodyText.includes(`${firstParam.name}.create_node`);
            const hasEdgeCalls = bodyText.includes(`${firstParam.name}.create_edge`) ||
                                 bodyText.includes(`${firstParam.name}.edge_from_`);
            
            if (hasCreateNodeCalls || hasEdgeCalls) {
                // Check for complex structure (for/if)
                const hasComplexStructure = checkForComplexStructure(body);
                
                return {
                    functionName: funcName,
                    parentParamName: firstParam.name,
                    parentParamType: firstParam.type,
                    hasComplexStructure
                };
            }
        }
        
        return null;
    } catch (error) {
        console.error('[BuilderFunctionParser] Error detecting builder function:', error);
        return null;
    }
}

/**
 * Parse a builder function and extract its subgraph structure
 */
export function parseBuilderFunction(
    code: string,
    functionName?: string
): BuilderFunctionStructure | null {
    const parser = createPythonParser();
    if (!parser) return null;
    
    try {
        const tree = parser.parse(code);
        if (!tree) return null;
        const rootNode = tree.rootNode;
        
        // Find the target function
        const functionDefs = queryNodes(rootNode, 'function_definition');
        let targetFunc: TSNode | null = null;
        let parentParamName = '';
        let parentParamType = '';
        
        for (const funcDef of functionDefs) {
            if (funcDef.parent?.type !== 'module') continue;
            
            const nameNode = funcDef.childForFieldName('name');
            if (!nameNode) continue;
            
            const funcName = getNodeText(nameNode, code);
            
            // If function name specified, match it; otherwise find first builder function
            if (functionName && funcName !== functionName) continue;
            
            const paramsNode = funcDef.childForFieldName('parameters');
            if (!paramsNode) continue;
            
            const firstParam = getFirstTypedParameter(paramsNode, code);
            if (!firstParam) continue;
            
            const graphTypes = ['Loop', 'Graph', 'RootGraph', 'HubGraph', 'MeshGraph'];
            if (graphTypes.some(t => firstParam.type.includes(t))) {
                targetFunc = funcDef;
                parentParamName = firstParam.name;
                parentParamType = firstParam.type;
                break;
            }
        }
        
        if (!targetFunc) {
            console.log(`[BuilderFunctionParser] No builder function found${functionName ? ` named ${functionName}` : ''}`);
            return null;
        }
        
        const body = targetFunc.childForFieldName('body');
        if (!body) return null;
        
        // Check for complex structure
        const hasComplexStructure = checkForComplexStructure(body);
        if (hasComplexStructure) {
            console.log(`[BuilderFunctionParser] Function has complex structure (for/if)`);
            return {
                nodes: [],
                nodeTypes: {},
                nodeLineNumbers: {},
                edges: [],
                subgraphs: {},
                hasComplexStructure: true
            };
        }
        
        // Determine base type for internal node initialization
        const baseType = parentParamType.includes('Loop') ? 'Loop' : 'Graph';
        
        // Initialize result with appropriate internal nodes
        const nodes: string[] = [];
        const nodeTypes: { [key: string]: string } = {};
        
        if (baseType === 'Loop') {
            nodes.push('controller', 'terminate');
            nodeTypes['controller'] = 'Controller';
            nodeTypes['terminate'] = 'TerminateNode';
        } else {
            nodes.push('entry', 'exit');
            nodeTypes['entry'] = 'entry';
            nodeTypes['exit'] = 'exit';
        }
        
        // Create parsing contexts - use parentParamName as "self" equivalent
        const nodeCtx: NodeParseContext = {
            nodes,
            nodeTypes,
            nodeLineNumbers: {},
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
        
        // Parse function body with special handling for parentParamName as "self"
        parseBuilderFunctionBody(body, code, nodeCtx, edgeCtx, subgraphs, parentParamName);
        
        console.log(`[BuilderFunctionParser] Parsed: ${nodes.length} nodes, ${edges.length} edges`);
        
        return {
            nodes,
            nodeTypes,
            nodeLineNumbers: nodeCtx.nodeLineNumbers,
            edges,
            subgraphs,
            hasComplexStructure: false,
            nodePullKeys: nodeCtx.nodePullKeys,
            nodePushKeys: nodeCtx.nodePushKeys
        };
    } catch (error) {
        console.error('[BuilderFunctionParser] Error parsing builder function:', error);
        return null;
    }
}

/**
 * Get first typed parameter from function parameters
 */
function getFirstTypedParameter(
    paramsNode: TSNode,
    code: string
): { name: string; type: string } | null {
    for (const child of paramsNode.namedChildren) {
        if (!child) continue;
        if (child.type === 'typed_parameter') {
            const nameNode = child.children.find((c): c is TSNode => !!c && c.type === 'identifier');
            const typeNode = child.childForFieldName('type');
            
            if (nameNode && typeNode) {
                return {
                    name: getNodeText(nameNode, code),
                    type: getNodeText(typeNode, code)
                };
            }
        }
    }
    return null;
}

/**
 * Check if function body contains complex control flow (for/if) at top level
 * that would affect node/edge creation.
 * 
 * We only check direct children of the function body, not nested function definitions.
 * This allows helper functions like validate_prompt_keys to have their own if/for
 * without marking the entire builder function as "complex".
 */
function checkForComplexStructure(body: TSNode): boolean {
    // Debug: log all direct children types
    const childTypes = body.namedChildren.filter((c): c is TSNode => !!c).map(c => c.type);
    console.log(`[BuilderFunctionParser] Body children types: ${childTypes.join(', ')}`);
    
    // Only check direct statements in the function body, not nested functions
    for (const child of body.namedChildren) {
        if (!child) continue;
        // Skip function definitions - they can have their own if/for
        if (child.type === 'function_definition') {
            console.log(`[BuilderFunctionParser] Skipping nested function definition`);
            continue;
        }
        
        // If there's a top-level if/for that's not inside a function definition
        if (child.type === 'if_statement' || child.type === 'for_statement') {
            // Check if this if/for contains create_node or create_edge calls
            const childText = child.text || '';
            if (childText.includes('create_node') || childText.includes('create_edge') ||
                childText.includes('edge_from_') || childText.includes('edge_to_')) {
                console.log(`[BuilderFunctionParser] Found dynamic structure: ${child.type} with node/edge creation`);
                return true;
            }
            console.log(`[BuilderFunctionParser] Found ${child.type} but no node/edge creation in it`);
        }
        
        // Check expression statements for if/for that wraps create calls
        if (child.type === 'expression_statement') {
            const firstChild = child.namedChildren.filter((n): n is TSNode => !!n)[0];
            if (firstChild && (firstChild.type === 'if_statement' || firstChild.type === 'for_statement')) {
                const exprText = firstChild.text || '';
                if (exprText.includes('create_node') || exprText.includes('create_edge')) {
                    console.log(`[BuilderFunctionParser] Found dynamic structure in expression_statement`);
                    return true;
                }
            }
        }
    }
    
    console.log(`[BuilderFunctionParser] No complex structure found`);
    return false;
}

/**
 * Parse builder function body, treating parentParamName as "self"
 */
function parseBuilderFunctionBody(
    body: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    parentParamName: string
): void {
    // Calculate line offset: the original line number where the function body starts
    // This is needed because we reparse the body text separately, losing original line info
    const bodyStartLine = body.startPosition.row;
    nodeCtx.lineOffset = bodyStartLine;
    edgeCtx.lineOffset = bodyStartLine;
    
    // Rewrite the code to temporarily replace parentParamName.xxx with self.xxx
    // This allows reusing existing parsing logic
    const bodyText = getNodeText(body, code);
    const rewrittenCode = bodyText.replace(
        new RegExp(`\\b${parentParamName}\\.`, 'g'),
        'self.'
    );
    
    // Parse the rewritten code
    const parser = createPythonParser();
    if (!parser) return;
    const tree = parser.parse(rewrittenCode);
    if (!tree) return;
    
    // Directly iterate through statements in the module
    // (parseBuildMethod expects a function_definition node, but we have a module)
    parseStatementsDirectly(tree.rootNode, rewrittenCode, nodeCtx, edgeCtx, subgraphs);
}

/**
 * Parse statements directly from a module node
 */
function parseStatementsDirectly(
    moduleNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] }
): void {
    for (const child of moduleNode.namedChildren) {
        if (!child) continue;
        // Skip nested function definitions (helper functions)
        if (child.type === 'function_definition') {
            continue;
        }
        
        // Skip comments
        if (child.type === 'comment') {
            continue;
        }
        
        // Parse expression statements (which contain assignments or calls)
        if (child.type === 'expression_statement') {
            const firstChild = child.namedChildren[0];
            if (!firstChild) continue;
            
            if (firstChild.type === 'assignment' || firstChild.type === 'typed_assignment') {
                parseBuilderAssignment(firstChild, code, nodeCtx, edgeCtx, subgraphs);
            } else if (firstChild.type === 'call') {
                parseBuilderCall(firstChild, code, edgeCtx);
            }
        }
    }
}

/**
 * Parse an assignment in builder function
 */
function parseBuilderAssignment(
    node: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] }
): void {
    const leftSide = node.childForFieldName('left');
    const rightSide = node.childForFieldName('right');
    
    if (!leftSide || !rightSide) return;
    
    if (rightSide.type === 'call') {
        const functionNode = rightSide.childForFieldName('function');
        if (!functionNode) return;
        
        const functionText = getNodeText(functionNode, code);
        
        if (functionText.endsWith('.create_node') || functionText === 'self.create_node') {
            parseCreateNode(leftSide, rightSide, code, nodeCtx, undefined, subgraphs);
        } else if (isEdgeCreationMethod(functionText)) {
            parseEdgeCreation(rightSide, code, edgeCtx, functionText);
        }
    }
}

/**
 * Parse a standalone call in builder function (edge creation)
 */
function parseBuilderCall(
    callNode: TSNode,
    code: string,
    edgeCtx: EdgeParseContext
): void {
    const functionNode = callNode.childForFieldName('function');
    if (!functionNode) return;
    
    const functionText = getNodeText(functionNode, code);
    
    if (isEdgeCreationMethod(functionText)) {
        parseEdgeCreation(callNode, code, edgeCtx, functionText);
    }
}

/**
 * Check if a node is inside a lambda expression
 */
function isInsideLambda(node: TSNode): boolean {
    let current = node.parent;
    while (current) {
        if (current.type === 'lambda') {
            return true;
        }
        current = current.parent;
    }
    return false;
}

/**
 * Extract builder function calls from code
 * This detects direct calls to imported functions that receive a node variable as first argument.
 * 
 * Example patterns detected:
 *   some_builder_func(self._my_loop, model=self._model, ...)
 *   configure_graph(graph=self._subgraph, ...)
 * 
 * Note: Calls inside lambda expressions are skipped (they are handled by build_func parsing)
 * 
 * Returns map of: loopVariableName -> { functionName, modulePath }
 */
export function extractBuilderFunctionCalls(
    code: string,
    imports: Map<string, { modulePath: string; className: string }>
): Map<string, { functionName: string; modulePath: string; loopVarName: string }> {
    const parser = createPythonParser();
    const result = new Map<string, { functionName: string; modulePath: string; loopVarName: string }>();
    if (!parser) return result;
    
    try {
        const tree = parser.parse(code);
        if (!tree) return result;
        const rootNode = tree.rootNode;
        
        // Find all call expressions
        const callNodes = queryNodes(rootNode, 'call');
        
        for (const callNode of callNodes) {
            // Skip calls inside lambda expressions - they are handled by build_func parsing
            if (isInsideLambda(callNode)) {
                continue;
            }
            
            const funcNode = callNode.childForFieldName('function');
            if (!funcNode) continue;
            
            const funcName = getNodeText(funcNode, code);
            
            // Check if this function is imported (could be any name, not just build_xxx)
            const importInfo = imports.get(funcName);
            if (!importInfo) continue;
            
            // Get the first argument (should be a node variable like self._xxx or self.xxx)
            const argsNode = callNode.childForFieldName('arguments');
            if (!argsNode) continue;
            
            // Extract first positional argument or any keyword argument that looks like a node reference
            let nodeVarName = '';
            for (const arg of argsNode.namedChildren) {
                if (!arg) continue;
                if (arg.type === 'keyword_argument') {
                    const argValue = arg.childForFieldName('value');
                    if (argValue) {
                        const valueText = getNodeText(argValue, code);
                        // Check if argument value looks like a node reference (self._xxx or self.xxx)
                        if (valueText.startsWith('self._') || valueText.startsWith('self.')) {
                            nodeVarName = valueText;
                            break;
                        }
                    }
                } else if (!nodeVarName && arg.type !== 'comment') {
                    // First positional argument
                    const argText = getNodeText(arg, code);
                    // Only accept if it looks like a node reference
                    if (argText.startsWith('self._') || argText.startsWith('self.')) {
                        nodeVarName = argText;
                    }
                }
            }
            
            if (nodeVarName) {
                // Normalize variable name (self._xxx -> _xxx, self.xxx -> xxx for matching)
                const normalizedName = nodeVarName.replace('self.', '');
                
                result.set(normalizedName, {
                    functionName: funcName,
                    modulePath: importInfo.modulePath,
                    loopVarName: nodeVarName
                });
                
                console.log(`[BuilderFunctionParser] Found builder call: ${funcName}(${nodeVarName})`);
            }
        }
        
        return result;
    } catch (error) {
        console.error('[BuilderFunctionParser] Error extracting builder calls:', error);
        return result;
    }
}
