/**
 * RootGraph Finder
 * 
 * Utilities for finding RootGraph instantiation in Python code.
 */
import type { Node as TSNode } from 'web-tree-sitter';
import { getNodeText } from './astUtils';

function isRootGraphCallee(functionText: string): boolean {
    // Accept RootGraph(...) and qualified forms like masfactory.RootGraph(...)
    return functionText === 'RootGraph' || functionText.endsWith('.RootGraph');
}

function isAssignmentNode(node: TSNode): boolean {
    return node.type === 'assignment' || node.type === 'typed_assignment';
}

/**
 * Result of finding RootGraph in a function
 */
export interface FunctionWithRootGraph {
    funcName: string;
    funcBody: TSNode;
    rootGraphVar: string;
}

/**
 * Find RootGraph variable in module-level code
 */
export function findRootGraphVariable(rootNode: TSNode, code: string): string {
    // Recursively search module-level statements (including if-blocks),
    // but do NOT descend into function/class definitions.
    function searchStatements(node: TSNode): string {
        for (const child of node.children) {
            if (!child) continue;
            if (child.type === 'function_definition' || child.type === 'class_definition') {
                continue;
            }

            if (child.type === 'expression_statement') {
                const firstChild = child.namedChildren[0];
                if (firstChild && isAssignmentNode(firstChild)) {
                    const rightSide = firstChild.childForFieldName('right');
                    if (rightSide && rightSide.type === 'call') {
                        const funcNode = rightSide.childForFieldName('function');
                        if (funcNode) {
                            const funcText = getNodeText(funcNode, code);
                            if (isRootGraphCallee(funcText)) {
                                const leftSide = firstChild.childForFieldName('left');
                                if (leftSide) {
                                    return getNodeText(leftSide, code);
                                }
                            }
                        }
                    }
                }
            }

            // Handle control-flow blocks at module level (e.g., if __name__ == "__main__")
            if (child.type === 'try_statement') {
                const body = child.childForFieldName('body');
                if (body) {
                    const found = searchStatements(body);
                    if (found) return found;
                }

                for (const clause of child.namedChildren) {
                    if (!clause) continue;
                    if (clause.type !== 'except_clause' && clause.type !== 'else_clause' && clause.type !== 'finally_clause') {
                        continue;
                    }
                    const clauseBody =
                        clause.childForFieldName('body') ||
                        clause.namedChildren.find((n): n is TSNode => !!n && n.type === 'block') ||
                        null;
                    if (clauseBody) {
                        const found = searchStatements(clauseBody);
                        if (found) return found;
                    }
                }
            }

            if (child.type === 'if_statement' || child.type === 'for_statement' || child.type === 'while_statement' || child.type === 'with_statement') {
                const body = child.childForFieldName('body') || child.childForFieldName('consequence');
                if (body) {
                    const found = searchStatements(body);
                    if (found) return found;
                }
                const alternative = child.childForFieldName('alternative');
                if (alternative) {
                    const found = searchStatements(alternative);
                    if (found) return found;
                }
            }

            if (child.type === 'block') {
                const found = searchStatements(child);
                if (found) return found;
            }
        }
        return '';
    }

    return searchStatements(rootNode);
}

/**
 * Find a function that contains RootGraph instantiation
 */
export function findFunctionWithRootGraph(
    rootNode: TSNode, 
    code: string
): FunctionWithRootGraph | null {
    const functionNodes: TSNode[] = [];

    // Module-level functions
    for (const child of rootNode.children) {
        if (!child) continue;
        if (child.type === 'function_definition') {
            functionNodes.push(child);
        }
    }

    // Class methods (one level deep)
    for (const child of rootNode.children) {
        if (!child) continue;
        if (child.type !== 'class_definition') continue;
        const classBody = child.childForFieldName('body');
        if (!classBody) continue;
        for (const inner of classBody.namedChildren) {
            if (!inner) continue;
            if (inner.type === 'function_definition') {
                functionNodes.push(inner);
            }
        }
    }

    for (const funcNode of functionNodes) {
        const nameNode = funcNode.childForFieldName('name');
        const body = funcNode.childForFieldName('body');
        if (!nameNode || !body) continue;

        const funcName = nameNode.text;

        // Search for RootGraph in function body (top-level assignments)
        for (const stmt of body.children) {
            if (!stmt) continue;
            if (stmt.type !== 'expression_statement') continue;
            const firstChild = stmt.namedChildren[0];
            if (!firstChild || !isAssignmentNode(firstChild)) continue;

            const rightSide = firstChild.childForFieldName('right');
            if (!rightSide || rightSide.type !== 'call') continue;

            const funcCall = rightSide.childForFieldName('function');
            if (!funcCall) continue;

            const funcText = getNodeText(funcCall, code);
            if (!isRootGraphCallee(funcText)) continue;

            const leftSide = firstChild.childForFieldName('left');
            if (!leftSide) continue;

            return {
                funcName,
                funcBody: body,
                rootGraphVar: getNodeText(leftSide, code)
            };
        }
    }
    return null;
}
