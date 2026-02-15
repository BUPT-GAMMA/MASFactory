/**
 * Chained Call Parser
 * 
 * Handles parsing of chained method calls like:
 * graph.create_edge(...).hooks.register(...)
 */
import type { Node as TSNode } from 'web-tree-sitter';

/** Edge creation method names */
const EDGE_CREATION_METHODS = [
    'create_edge',
    'edge_from_entry',
    'edge_to_exit',
    'edge_from_controller',
    'edge_to_controller',
    'edge_to_terminate_node'
];

/**
 * Find edge creation call in a potentially chained call expression
 * e.g., graph.create_edge(...).hooks.register(...) -> returns the create_edge call
 */
export function findEdgeCreationCall(node: TSNode): TSNode | null {
    if (node.type !== 'call') return null;

    const functionNode = node.childForFieldName('function');
    if (!functionNode) return null;

    if (functionNode.type === 'attribute') {
        const attrName = functionNode.childForFieldName('attribute');
        const objectNode = functionNode.childForFieldName('object');
        
        if (attrName) {
            const methodName = attrName.text;
            
            // Check if this attribute is an edge creation method
            if (EDGE_CREATION_METHODS.includes(methodName)) {
                return node;
            }
            
            // Check if the object contains a call (chained call)
            if (objectNode) {
                const innerCall = findCallInAttributeChain(objectNode);
                if (innerCall) {
                    return findEdgeCreationCall(innerCall);
                }
            }
        }
    }

    return null;
}

/**
 * Find a call node inside an attribute chain
 * e.g., graph.create_edge(...).hooks -> returns the create_edge(...) call
 */
export function findCallInAttributeChain(node: TSNode): TSNode | null {
    if (node.type === 'call') {
        return node;
    }
    
    if (node.type === 'attribute') {
        const objectNode = node.childForFieldName('object');
        if (objectNode) {
            return findCallInAttributeChain(objectNode);
        }
    }
    
    return null;
}
