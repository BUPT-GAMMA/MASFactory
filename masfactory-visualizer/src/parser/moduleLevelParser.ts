/**
 * Module Level Parser
 * 
 * Parses module-level and function-level graph definitions (without class).
 */
import type { Node as TSNode } from 'web-tree-sitter';
import { getNodeText } from './astUtils';
import { parseCreateNodeWithRootGraph, NodeParseContext } from './nodeParser';
import { parseEdgeCreation, EdgeParseContext } from './edgeParser';
import { findEdgeCreationCall } from './chainedCallParser';
import { ControlFlowContext } from './buildMethodParser';
import { isDeclarativeGraphCall, parseDeclarativeGraphCallIntoContexts } from './declarativeParser';
import { tryParseNodeTemplateAssignment } from './templateParser';

function isAssignmentNode(node: TSNode | null | undefined): node is TSNode {
    return !!node && (node.type === 'assignment' || node.type === 'typed_assignment');
}

/**
 * Parse module-level code (for files without build() method)
 */
export function parseModuleLevel(
    rootNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    rootGraphVariable: string,
    controlFlowCtx?: ControlFlowContext
): void {
    parseStatementsWithRootGraph(rootNode, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx);
}

/**
 * Parse function body for graph construction
 */
export function parseFunctionBody(
    body: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    rootGraphVariable: string,
    controlFlowCtx?: ControlFlowContext
): void {
    console.log('[Parser] Parsing function body');
    parseStatementsWithRootGraph(body, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx);
}

function parseStatementsWithRootGraph(
    blockNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    rootGraphVariable: string,
    controlFlowCtx?: ControlFlowContext,
    depth: number = 0,
    loopIteration?: number
): void {
    if (!nodeCtx.templates) nodeCtx.templates = {};
    if (!nodeCtx.literalValues) nodeCtx.literalValues = {};

    for (const child of blockNode.children) {
        if (!child) continue;
        // Skip nested function definitions
        if (child.type === 'function_definition' && depth > 0) {
            continue;
        }

        if (child.type === 'for_statement') {
            parseForStatementWithRootGraph(child, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth);
            continue;
        }

        if (child.type === 'if_statement') {
            parseIfStatementWithRootGraph(child, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth, loopIteration);
            continue;
        }

        if (child.type === 'while_statement') {
            parseWhileStatementWithRootGraph(child, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth, loopIteration);
            continue;
        }

        if (child.type === 'with_statement') {
            parseWithStatementWithRootGraph(child, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth, loopIteration);
            continue;
        }

        if (child.type === 'try_statement') {
            parseTryStatementWithRootGraph(child, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth, loopIteration);
            continue;
        }

        if (child.type === 'expression_statement') {
            const firstChild = child.namedChildren[0];
            if (isAssignmentNode(firstChild)) {
                parseAssignmentWithRootGraph(firstChild, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, loopIteration);
            } else {
                parseExpressionStatementWithRootGraph(child, code, nodeCtx, edgeCtx, rootGraphVariable, loopIteration);
            }
        }

        if (child.type === 'block') {
            parseStatementsWithRootGraph(child, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth + 1, loopIteration);
        }
    }
}

function parseForStatementWithRootGraph(
    forNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    rootGraphVariable: string,
    controlFlowCtx: ControlFlowContext | undefined,
    depth: number
): void {
    const bodyNode = forNode.childForFieldName('body');
    if (!bodyNode) return;

    const lineNumber = forNode.startPosition.row + 1;

    // Default unroll count
    let iterations = 3;
    if (controlFlowCtx) {
        for (const [loopId, count] of Object.entries(controlFlowCtx.loopIterations)) {
            if (loopId.includes(`_${lineNumber}_`)) {
                iterations = count;
                break;
            }
        }
    }
    for (let i = 0; i < iterations; i++) {
        parseStatementsWithRootGraph(bodyNode, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth + 1, i);
    }
}

function parseIfStatementWithRootGraph(
    ifNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    rootGraphVariable: string,
    controlFlowCtx: ControlFlowContext | undefined,
    depth: number,
    loopIteration?: number
): void {
    const consequenceNode = ifNode.childForFieldName('consequence');
    const alternativeNode = ifNode.childForFieldName('alternative');

    const lineNumber = ifNode.startPosition.row + 1;

    // Determine condition value
    let conditionValue = true;
    if (controlFlowCtx) {
        for (const [condId, value] of Object.entries(controlFlowCtx.conditionValues)) {
            if (condId.includes(`_${lineNumber}_`)) {
                conditionValue = value;
                break;
            }
        }
    }

    if (conditionValue && consequenceNode) {
        parseStatementsWithRootGraph(consequenceNode, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth + 1, loopIteration);
    } else if (!conditionValue && alternativeNode) {
        parseStatementsWithRootGraph(alternativeNode, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth + 1, loopIteration);
    } else if (consequenceNode) {
        // Fallback: if no alternative, still parse consequence
        parseStatementsWithRootGraph(consequenceNode, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth + 1, loopIteration);
    }
}

function parseWhileStatementWithRootGraph(
    whileNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    rootGraphVariable: string,
    controlFlowCtx: ControlFlowContext | undefined,
    depth: number,
    loopIteration?: number
): void {
    const bodyNode = whileNode.childForFieldName('body');
    if (bodyNode) {
        parseStatementsWithRootGraph(bodyNode, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth + 1, loopIteration);
    }

    const alternative = whileNode.childForFieldName('alternative');
    if (alternative) {
        // alternative is typically an else_clause; parse its block body
        const elseBody =
            alternative.childForFieldName('body') ||
            alternative.namedChildren.find((n): n is TSNode => !!n && n.type === 'block');
        if (elseBody) {
            parseStatementsWithRootGraph(elseBody, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth + 1, loopIteration);
        }
    }
}

function parseWithStatementWithRootGraph(
    withNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    rootGraphVariable: string,
    controlFlowCtx: ControlFlowContext | undefined,
    depth: number,
    loopIteration?: number
): void {
    const bodyNode = withNode.childForFieldName('body');
    if (!bodyNode) return;
    parseStatementsWithRootGraph(bodyNode, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth + 1, loopIteration);
}

function parseTryStatementWithRootGraph(
    tryNode: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    rootGraphVariable: string,
    controlFlowCtx: ControlFlowContext | undefined,
    depth: number,
    loopIteration?: number
): void {
    const bodyNode = tryNode.childForFieldName('body');
    if (bodyNode) {
        parseStatementsWithRootGraph(bodyNode, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth + 1, loopIteration);
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
            parseStatementsWithRootGraph(clauseBody, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx, depth + 1, loopIteration);
        }
    }
}

/**
 * Parse assignment with RootGraph variable tracking
 */
function parseAssignmentWithRootGraph(
    node: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    subgraphs: { [parent: string]: string[] },
    rootGraphVariable: string,
    loopIteration?: number
): void {
    const leftSide = node.childForFieldName('left');
    const rightSide = node.childForFieldName('right');
    
    if (!leftSide || !rightSide) return;

    // Record best-effort literal bindings (used by declarative parser to resolve identifier->list/dict).
    if (rightSide.type !== 'call') {
        const leftText = getNodeText(leftSide, code).trim();
        if (leftText && (rightSide.type === 'list' || rightSide.type === 'tuple' || rightSide.type === 'dictionary')) {
            const store = (key: string) => {
                if (!key) return;
                nodeCtx.literalValues![key] = rightSide;
            };
            store(leftText);
            if (leftText.startsWith('self._')) store(leftText.replace('self._', ''));
            if (leftText.startsWith('self.')) store(leftText.replace('self.', ''));
            const last = leftText.split('.').pop();
            if (last) store(last);
            if (last && last.startsWith('_')) store(last.slice(1));
        }

        // Handle simple variable aliasing: node_b = node_a (or self._node_b = node_a)
        const isSimpleRef = (n: TSNode): boolean =>
            n.type === 'identifier' || n.type === 'attribute';

        if (isSimpleRef(leftSide) && isSimpleRef(rightSide)) {
            const leftText = getNodeText(leftSide, code).trim();
            const rightText = getNodeText(rightSide, code).trim();
            if (leftText && rightText) {
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

    if (rightSide.type === 'call') {
        const functionNode = rightSide.childForFieldName('function');
        if (!functionNode) return;

        const functionText = getNodeText(functionNode, code);

        // Track local NodeTemplate assignments for later type resolution (declarative graphs)
        if (functionText === 'NodeTemplate' || functionText.endsWith('.NodeTemplate')) {
            const leftText = getNodeText(leftSide, code).trim();
            const parsed = tryParseNodeTemplateAssignment(leftText, rightSide, code);
            if (parsed) {
                if (!nodeCtx.templates) nodeCtx.templates = {};
                nodeCtx.templates[parsed.templateName] = parsed;
            }
        }

        // Declarative RootGraph(..., nodes=[...], edges=[...])
        const leftText = getNodeText(leftSide, code).trim();
        if (leftText === rootGraphVariable && isDeclarativeGraphCall(functionText)) {
            parseDeclarativeGraphCallIntoContexts(
                rightSide,
                code,
                nodeCtx,
                edgeCtx,
                subgraphs,
                nodeCtx.templates,
                { isRootGraph: true }
            );
            return;
        }

        if (functionText.endsWith('.create_node')) {
            parseCreateNodeWithRootGraph(leftSide, rightSide, code, nodeCtx, subgraphs, rootGraphVariable, loopIteration);
        } else {
            // Check for edge creation in chained calls
            const edgeCall = findEdgeCreationCall(rightSide);
            if (edgeCall) {
                const edgeFunctionNode = edgeCall.childForFieldName('function');
                if (edgeFunctionNode) {
                    const edgeFunctionText = getNodeText(edgeFunctionNode, code);
                    parseEdgeCreation(edgeCall, code, edgeCtx, edgeFunctionText);
                }
            }
        }
    }
}

/**
 * Parse expression statement with RootGraph variable tracking
 */
function parseExpressionStatementWithRootGraph(
    node: TSNode,
    code: string,
    nodeCtx: NodeParseContext,
    edgeCtx: EdgeParseContext,
    rootGraphVariable: string,
    loopIteration?: number
): void {
    const callNode = node.namedChildren[0];
    if (!callNode || callNode.type !== 'call') return;

    // Handle direct create_node() call without assignment (best-effort)
    const functionNode = callNode.childForFieldName('function');
    if (functionNode) {
        const functionText = getNodeText(functionNode, code);
        if (functionText.endsWith('.create_node')) {
            // Synthesize a stable name from "name=" or the positional name argument.
            // This is useful for patterns like: root.create_node(..., name="X", ...)
            const syntheticVar = `__expr_node_${callNode.startPosition.row + 1}`;
            const syntheticLeft = callNode; // placeholder; parseCreateNodeWithRootGraph needs a left node
            // Use the call node itself as a fake left-side to reuse logic: getNodeText() will be the call text,
            // so we pass a minimal identifier node instead by falling back to syntheticVar in nodeParser.
            // We implement the logic here by creating an assignment-like string is complex; instead, just skip.
            //
            // NOTE: For non-assigned create_node calls, nodeParser currently requires a left-side node.
            // We handle these calls separately by creating a minimal node entry based on the extracted name.
            const argsNode = callNode.childForFieldName('arguments');
            if (argsNode) {
                const args = argsNode.namedChildren.filter((a): a is TSNode => !!a);
                if (args.length > 0) {
                    // Extract node type from first positional or cls/node_type keyword
                    let nodeType = 'Node';
                    const positional = args.filter(a => a.type !== 'keyword_argument' && a.type !== 'comment');
                    if (positional.length > 0) {
                        const firstPosText = getNodeText(positional[0], code).trim();
                        if (!firstPosText.startsWith('**')) {
                            nodeType = firstPosText;
                        }
                    }
                    for (const arg of args) {
                        if (arg.type !== 'keyword_argument') continue;
                        const nameNode = arg.childForFieldName('name');
                        const valueNode = arg.childForFieldName('value');
                        if (!nameNode || !valueNode) continue;
                        const k = getNodeText(nameNode, code);
                        if ((k === 'cls' || k === 'node_type') && nodeType === 'Node') {
                            nodeType = getNodeText(valueNode, code).trim();
                        }
                    }

                    // Extract name from name= or second positional
                    let nodeName = '';
                    for (const arg of args) {
                        if (arg.type !== 'keyword_argument') continue;
                        const nameNode = arg.childForFieldName('name');
                        const valueNode = arg.childForFieldName('value');
                        if (!nameNode || !valueNode) continue;
                        const k = getNodeText(nameNode, code);
                        if (k === 'name') {
                            nodeName = getNodeText(valueNode, code).trim().replace(/^f?["']|["']$/g, '');
                            break;
                        }
                    }
                    if (!nodeName && positional.length >= 2) {
                        nodeName = getNodeText(positional[1], code).trim().replace(/^f?["']|["']$/g, '');
                    }
                    if (!nodeName) {
                        nodeName = syntheticVar;
                    }
                    if (loopIteration !== undefined) {
                        nodeName = `${nodeName}_${loopIteration}`;
                    }
                    if (!nodeCtx.nodes.includes(nodeName)) {
                        nodeCtx.nodes.push(nodeName);
                        nodeCtx.nodeTypes[nodeName] = nodeType;
                        nodeCtx.nodeLineNumbers[nodeName] = callNode.startPosition.row + 1;
                        // No variableToNodeName mapping (no assignment)
                    }
                }
            }
        }
    }

    // Handle chained calls
    const edgeCall = findEdgeCreationCall(callNode);
    if (edgeCall) {
        const functionNode = edgeCall.childForFieldName('function');
        if (functionNode) {
            const functionText = getNodeText(functionNode, code);
            parseEdgeCreation(edgeCall, code, edgeCtx, functionText);
        }
    }
}
