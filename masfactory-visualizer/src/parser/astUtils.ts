/**
 * AST Utility functions for Tree-sitter parsing
 */
import type { Node as TSNode } from 'web-tree-sitter';

export function isNonNullNode(node: TSNode | null): node is TSNode {
    return node !== null;
}

/**
 * Get text content of an AST node
 */
export function getNodeText(node: TSNode | null, code: string): string {
    if (!node) return '';
    return code.substring(node.startIndex, node.endIndex);
}

/**
 * Query all nodes of a specific type in the AST
 */
export function queryNodes(node: TSNode, type: string): TSNode[] {
    const results: TSNode[] = [];
    
    function traverse(n: TSNode) {
        if (n.type === type) {
            results.push(n);
        }
        for (const child of n.children) {
            if (!child) continue;
            traverse(child);
        }
    }
    
    traverse(node);
    return results;
}

/**
 * Get base classes from a class definition node
 */
export function getBaseClasses(classNode: TSNode): string[] {
    const bases: string[] = [];
    const argList = classNode.childForFieldName('superclasses');
    if (argList) {
        for (const child of argList.namedChildren) {
            if (!child) continue;
            if (child.type === 'identifier') {
                bases.push(child.text);
            } else if (child.type === 'attribute') {
                // Handle module.ClassName
                bases.push(child.text);
            }
        }
    }
    return bases;
}

/**
 * Parse dictionary argument (for keys, pull_keys, push_keys)
 */
export function parseDictArgument(node: TSNode, code: string): { [key: string]: string } | null {
    if (node.type === 'dictionary') {
        const result: { [key: string]: string } = {};
        for (const child of node.namedChildren) {
            if (!child) continue;
            if (child.type === 'pair') {
                const key = child.childForFieldName('key');
                const value = child.childForFieldName('value');
                if (key && value) {
                    const keyText = getNodeText(key, code).replace(/^["']|["']$/g, '');
                    const valueText = getNodeText(value, code).replace(/^["']|["']$/g, '');
                    result[keyText] = valueText;
                }
            }
        }
        return Object.keys(result).length > 0 ? result : null;
    }
    return null;
}

/**
 * Parse keys-like argument for Node pull_keys/push_keys semantics.
 *
 * - `None` => null
 * - `{}`   => 'empty' (explicitly no keys)
 * - `{...}` => object mapping
 */
export function parseKeysArgument(
    node: TSNode,
    code: string
): { [key: string]: string } | null | 'empty' {
    if (node.type === 'none') {
        return null;
    }
    if (node.type === 'dictionary') {
        const parsed = parseDictArgument(node, code);
        return parsed ?? 'empty';
    }
    return null;
}

/**
 * Graph base type constants
 */
export const BASE_TYPES = {
    NONE: 'none',
    ROOT_GRAPH: 'RootGraph',
    GRAPH: 'Graph',
    LOOP: 'Loop'
} as const;

export const GRAPH_BASE_TYPES = ['Graph', 'RootGraph', 'Loop'];

/**
 * Extract caller and method name from a method call text
 * e.g., "self._agent_config_loop.edge_from_controller" -> { caller: "self._agent_config_loop", method: "edge_from_controller" }
 * e.g., "graph.create_node" -> { caller: "graph", method: "create_node" }
 */
export function extractMethodCall(functionText: string): { caller: string; method: string } | null {
    const lastDotIndex = functionText.lastIndexOf('.');
    if (lastDotIndex === -1) {
        return null;
    }
    return {
        caller: functionText.substring(0, lastDotIndex),
        method: functionText.substring(lastDotIndex + 1)
    };
}
