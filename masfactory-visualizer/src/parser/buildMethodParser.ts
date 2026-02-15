/**
 * Build Method Parser
 * 
 * Parses class-based graph definitions with build() method.
 */
import type { Node as TSNode } from 'web-tree-sitter';
import { getNodeText, queryNodes, getBaseClasses, BASE_TYPES, GRAPH_BASE_TYPES } from './astUtils';
import { parseCreateNode, NodeParseContext } from './nodeParser';
import { parseEdgeCreation, isEdgeCreationMethod, EdgeParseContext } from './edgeParser';
import { findEdgeCreationCall } from './chainedCallParser';
import { ControlFlowInfo } from './types';
import { tryParseNodeTemplateAssignment } from './templateParser';

/**
 * Result of finding build method
 */
export interface BuildMethodInfo {
    buildMethod: TSNode | null;
    baseType: string;
    className: string;
}

/**
 * Find build method and determine base class type
 */
export function findBuildMethodAndBaseType(node: TSNode): BuildMethodInfo {
    let buildMethod: TSNode | null = null;
    let baseType: string = BASE_TYPES.NONE;
    let className: string = '';

    const classNodes = queryNodes(node, 'class_definition');
    
    for (const classNode of classNodes) {
        const bases = getBaseClasses(classNode);
        const nameNode = classNode.childForFieldName('name');
        const currentClassName = nameNode ? nameNode.text : '';
        
        // Check if this class inherits from a graph base type
        for (const base of bases) {
            if (GRAPH_BASE_TYPES.some(t => base.includes(t))) {
                className = currentClassName;
                
                if (base.includes('Loop')) {
                    baseType = BASE_TYPES.LOOP;
                } else if (base.includes('RootGraph')) {
                    baseType = BASE_TYPES.ROOT_GRAPH;
                } else if (base.includes('Graph')) {
                    baseType = BASE_TYPES.GRAPH;
                }
                
                // Find build method in this class
                const body = classNode.childForFieldName('body');
                if (body) {
                    let initMethod: TSNode | null = null;
                    for (const child of body.children) {
                        if (!child) continue;
                        if (child.type === 'decorated_definition' || child.type === 'function_definition') {
                            const funcDef = child.type === 'decorated_definition' 
                                ? child.children.find((c): c is TSNode => !!c && c.type === 'function_definition')
                                : child;
                            if (funcDef) {
                                const funcName = funcDef.childForFieldName('name');
                                if (funcName && funcName.text === 'build') {
                                    buildMethod = funcDef;
                                    break;
                                }
                                if (funcName && funcName.text === '__init__') {
                                    initMethod = funcDef;
                                }
                            }
                        }
                    }
                    if (!buildMethod && initMethod) {
                        buildMethod = initMethod;
                    }
                }
                
                if (buildMethod) break;
            }
        }
        
        if (buildMethod) break;
    }

    return { buildMethod, baseType, className };
}

/**
 * Context for control flow parsing
 */
export interface ControlFlowContext {
    /** User-specified loop iterations */
    loopIterations: { [loopId: string]: number };
    /** User-specified condition values */
    conditionValues: { [conditionId: string]: boolean };
}

/**
 * Parse build method body and extract control flow info
 */
export function parseBuildMethod(
    buildMethod: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    controlFlowCtx?: ControlFlowContext
): ControlFlowInfo {
    const body = buildMethod.childForFieldName('body');
    if (!body) return {};

    // Parse statements
    parseStatements(body, code, nodeCtx, edgeCtx, subgraphs, 0, controlFlowCtx);
    
    return {};
}

/**
 * Parse statements recursively with control flow expansion
 */
function parseStatements(
    blockNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    depth: number,
    controlFlowCtx?: ControlFlowContext,
    loopIteration?: number  // Current iteration index when inside a loop
): void {
    for (const child of blockNode.children) {
        if (!child) continue;
        // Skip nested function definitions
        if (child.type === 'function_definition' && depth > 0) {
            continue;
        }

        // Handle for statements - mark as inside control flow
        if (child.type === 'for_statement') {
            parseForStatement(child, code, nodeCtx, edgeCtx, subgraphs, depth, controlFlowCtx);
            continue;
        }

        // Handle if statements - mark as inside control flow
        if (child.type === 'if_statement') {
            parseIfStatement(child, code, nodeCtx, edgeCtx, subgraphs, depth, controlFlowCtx, loopIteration);
            continue;
        }

        if (child.type === 'while_statement') {
            parseWhileStatement(child, code, nodeCtx, edgeCtx, subgraphs, depth, controlFlowCtx, loopIteration);
            continue;
        }

        if (child.type === 'with_statement') {
            parseWithStatement(child, code, nodeCtx, edgeCtx, subgraphs, depth, controlFlowCtx, loopIteration);
            continue;
        }

        if (child.type === 'try_statement') {
            parseTryStatement(child, code, nodeCtx, edgeCtx, subgraphs, depth, controlFlowCtx, loopIteration);
            continue;
        }

        // Parse assignment statements
        if (child.type === 'assignment') {
            parseAssignment(child, code, nodeCtx, edgeCtx, subgraphs, loopIteration);
        }
        // Parse expression statements
        else if (child.type === 'expression_statement') {
            parseExpressionStatement(child, code, nodeCtx, edgeCtx, subgraphs, loopIteration);
        }

        // Recursively parse block statements
        if (child.type === 'block') {
            parseStatements(child, code, nodeCtx, edgeCtx, subgraphs, depth + 1, controlFlowCtx, loopIteration);
        }
    }
}

/**
 * Parse for statement with loop expansion
 */
function parseForStatement(
    forNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    depth: number,
    controlFlowCtx?: ControlFlowContext
): void {
    const bodyNode = forNode.childForFieldName('body');
    if (!bodyNode) return;
    
    const lineNumber = forNode.startPosition.row + 1;
    
    // Determine iteration count
    let iterations = 3; // Default
    if (controlFlowCtx) {
        // Find matching loop by line number
        for (const [loopId, count] of Object.entries(controlFlowCtx.loopIterations)) {
            if (loopId.includes(`_${lineNumber}_`)) {
                iterations = count;
                break;
            }
        }
    }
    
    // Expand loop by parsing body multiple times
    for (let i = 0; i < iterations; i++) {
        parseStatements(bodyNode, code, nodeCtx, edgeCtx, subgraphs, depth + 1, controlFlowCtx, i);
    }
}

/**
 * Parse if statement with condition evaluation
 */
function parseIfStatement(
    ifNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    depth: number,
    controlFlowCtx?: ControlFlowContext,
    loopIteration?: number
): void {
    const consequenceNode = ifNode.childForFieldName('consequence');
    const alternativeNode = ifNode.childForFieldName('alternative');
    
    const lineNumber = ifNode.startPosition.row + 1;
    
    // Determine condition value
    let conditionValue = true; // Default
    if (controlFlowCtx) {
        // Find matching condition by line number
        for (const [condId, value] of Object.entries(controlFlowCtx.conditionValues)) {
            if (condId.includes(`_${lineNumber}_`)) {
                conditionValue = value;
                break;
            }
        }
    }
    
    if (conditionValue && consequenceNode) {
        // Parse if body
        parseStatements(consequenceNode, code, nodeCtx, edgeCtx, subgraphs, depth + 1, controlFlowCtx, loopIteration);
    } else if (!conditionValue && alternativeNode) {
        // Parse else body
        parseStatements(alternativeNode, code, nodeCtx, edgeCtx, subgraphs, depth + 1, controlFlowCtx, loopIteration);
    }
}

function parseWhileStatement(
    whileNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    depth: number,
    controlFlowCtx?: ControlFlowContext,
    loopIteration?: number
): void {
    const bodyNode = whileNode.childForFieldName('body');
    if (bodyNode) {
        parseStatements(bodyNode, code, nodeCtx, edgeCtx, subgraphs, depth + 1, controlFlowCtx, loopIteration);
    }

    const alternative = whileNode.childForFieldName('alternative');
    if (alternative) {
        const elseBody =
            alternative.childForFieldName('body') ||
            alternative.namedChildren.find((n): n is TSNode => !!n && n.type === 'block');
        if (elseBody) {
            parseStatements(elseBody, code, nodeCtx, edgeCtx, subgraphs, depth + 1, controlFlowCtx, loopIteration);
        }
    }
}

function parseWithStatement(
    withNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    depth: number,
    controlFlowCtx?: ControlFlowContext,
    loopIteration?: number
): void {
    const bodyNode = withNode.childForFieldName('body');
    if (!bodyNode) return;
    parseStatements(bodyNode, code, nodeCtx, edgeCtx, subgraphs, depth + 1, controlFlowCtx, loopIteration);
}

function parseTryStatement(
    tryNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    depth: number,
    controlFlowCtx?: ControlFlowContext,
    loopIteration?: number
): void {
    const bodyNode = tryNode.childForFieldName('body');
    if (bodyNode) {
        parseStatements(bodyNode, code, nodeCtx, edgeCtx, subgraphs, depth + 1, controlFlowCtx, loopIteration);
    }

    for (const clause of tryNode.namedChildren) {
        if (!clause) continue;
        if (clause.type !== 'except_clause' && clause.type !== 'else_clause' && clause.type !== 'finally_clause') {
            continue;
        }
        const clauseBody =
            clause.childForFieldName('body') ||
            clause.namedChildren.find((n): n is TSNode => !!n && n.type === 'block');
        if (clauseBody) {
            parseStatements(clauseBody, code, nodeCtx, edgeCtx, subgraphs, depth + 1, controlFlowCtx, loopIteration);
        }
    }
}

/**
 * Parse expression statement
 */
function parseExpressionStatement(
    node: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    loopIteration?: number
): void {
    const firstChild = node.namedChildren[0];
    if (!firstChild) return;

    // Check if it's an assignment
    if (firstChild.type === 'assignment' || firstChild.type === 'typed_assignment') {
        parseAssignment(firstChild, code, nodeCtx, edgeCtx, subgraphs, loopIteration);
        return;
    }

    // Check if it's a call expression
    if (firstChild.type !== 'call') return;

    // Try to find edge creation call (handles chained calls like .hooks.register())
    const edgeCall = findEdgeCreationCall(firstChild);
    if (edgeCall) {
        const functionNode = edgeCall.childForFieldName('function');
        if (functionNode) {
            const functionText = getNodeText(functionNode, code);
            parseEdgeCreation(edgeCall, code, edgeCtx, functionText);
        }
        return;
    }

    // Fallback: direct edge creation method
    const functionNode = firstChild.childForFieldName('function');
    if (!functionNode) return;

    const functionText = getNodeText(functionNode, code);
    
    // Parse edge creation calls
    if (isEdgeCreationMethod(functionText)) {
        parseEdgeCreation(firstChild, code, edgeCtx, functionText);
    }
}

/**
 * Parse assignment statement
 */
function parseAssignment(
    node: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    loopIteration?: number
): void {
    if (!nodeCtx.templates) nodeCtx.templates = {};
    if (!nodeCtx.literalValues) nodeCtx.literalValues = {};

    const leftSide = node.childForFieldName('left');
    const rightSide = node.childForFieldName('right');
    
    if (!leftSide || !rightSide) return;

    // Handle simple variable aliasing: node_b = node_a (or self._node_b = node_a)
    // This is common in complex workflows and should preserve variable->node resolution for edges.
    if (rightSide.type !== 'call') {
        // Record literal bindings (used by declarative parsing for Graph/Loop args inside nodes=[...]).
        const leftTextRaw = getNodeText(leftSide, code).trim();
        if (
            leftTextRaw &&
            (rightSide.type === 'list' || rightSide.type === 'tuple' || rightSide.type === 'dictionary')
        ) {
            const store = (key: string) => {
                if (!key) return;
                nodeCtx.literalValues![key] = rightSide;
            };
            store(leftTextRaw);
            if (leftTextRaw.startsWith('self._')) store(leftTextRaw.replace('self._', ''));
            if (leftTextRaw.startsWith('self.')) store(leftTextRaw.replace('self.', ''));
            const last = leftTextRaw.split('.').pop();
            if (last) store(last);
            if (last && last.startsWith('_')) store(last.slice(1));
        }

        const isSimpleRef = (n: TSNode): boolean =>
            n.type === 'identifier' || n.type === 'attribute';

        if (isSimpleRef(leftSide) && isSimpleRef(rightSide)) {
            const leftText = getNodeText(leftSide, code).trim();
            const rightText = getNodeText(rightSide, code).trim();
            if (leftText && rightText) {
                // Resolve RHS through current variable->node mapping (best-effort).
                const rhsResolved =
                    nodeCtx.variableToNodeName[rightText] ||
                    (rightText.startsWith('self._')
                        ? nodeCtx.variableToNodeName[rightText.replace('self._', '')]
                        : undefined) ||
                    (rightText.startsWith('self.')
                        ? nodeCtx.variableToNodeName[rightText.replace('self.', '')]
                        : undefined);

                if (rhsResolved) {
                    nodeCtx.variableToNodeName[leftText] = rhsResolved;
                }
            }
        }

        return;
    }

    // Check if right side is a call
    const functionNode = rightSide.childForFieldName('function');
    if (!functionNode) return;

    const functionText = getNodeText(functionNode, code);

    // Track NodeTemplate assignments for later template kind resolution inside this build() method.
    if (functionText === 'NodeTemplate' || functionText.endsWith('.NodeTemplate')) {
        const leftText = getNodeText(leftSide, code).trim();
        const parsed = tryParseNodeTemplateAssignment(leftText, rightSide, code);
        if (parsed) {
            nodeCtx.templates[parsed.templateName] = parsed;
        }
    }

    if (functionText.endsWith('.create_node')) {
        parseCreateNode(leftSide, rightSide, code, nodeCtx, loopIteration, subgraphs);
    } else {
        // Try to find edge creation call (handles chained calls)
        const edgeCall = findEdgeCreationCall(rightSide);
        if (edgeCall) {
            const edgeFunctionNode = edgeCall.childForFieldName('function');
            if (edgeFunctionNode) {
                const edgeFunctionText = getNodeText(edgeFunctionNode, code);
                parseEdgeCreation(edgeCall, code, edgeCtx, edgeFunctionText);
            }
        } else if (isEdgeCreationMethod(functionText)) {
            parseEdgeCreation(rightSide, code, edgeCtx, functionText);
        }
    }
}
