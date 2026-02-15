/**
 * Import Resolver - Resolves Python import statements to file paths
 */
import type { Node as TSNode } from 'web-tree-sitter';
import { getNodeText, queryNodes } from './astUtils';

export interface ImportInfo {
    modulePath: string;      // e.g., "masfactory.components.compound_graph"
    className: string;       // e.g., "InstructorAssistantGraph"
    alias?: string;          // e.g., "IAG" if "from xxx import YYY as IAG"
    isModule?: boolean;      // true if this entry represents `import module as alias`
}

/**
 * Parse all import statements from the AST
 */
export function parseImports(rootNode: TSNode, code: string): Map<string, ImportInfo> {
    const imports = new Map<string, ImportInfo>();
    
    // Handle "import xxx [as yyy]" statements (module imports)
    const importNodes = queryNodes(rootNode, 'import_statement');
    for (const importNode of importNodes) {
        for (const child of importNode.namedChildren) {
            if (!child) continue;
            if (child.type === 'aliased_import') {
                const nameNode = child.childForFieldName('name');
                const aliasNode = child.childForFieldName('alias');
                if (!nameNode || !aliasNode) continue;
                const modulePath = getNodeText(nameNode, code);
                const alias = getNodeText(aliasNode, code);
                imports.set(alias, { modulePath, className: '', alias, isModule: true });
            } else if (child.type === 'dotted_name') {
                const modulePath = getNodeText(child, code);
                // Only store non-dotted imports (e.g., "import masfactory") to avoid alias ambiguity.
                if (!modulePath.includes('.')) {
                    imports.set(modulePath, { modulePath, className: '', alias: modulePath, isModule: true });
                }
            }
        }
    }

    // Find all import_from_statement nodes
    // e.g., "from masfactory.components.compound_graph import InstructorAssistantGraph"
    const importFromNodes = queryNodes(rootNode, 'import_from_statement');
    
    for (const importNode of importFromNodes) {
        const moduleNameNode = importNode.childForFieldName('module_name');
        if (!moduleNameNode) continue;
        
        const modulePath = getNodeText(moduleNameNode, code);
        
        // Get imported names
        for (const child of importNode.namedChildren) {
            if (!child) continue;
            if (child.type === 'aliased_import') {
                // from xxx import YYY as ZZZ
                const nameNode = child.childForFieldName('name');
                const aliasNode = child.childForFieldName('alias');
                if (nameNode) {
                    const className = getNodeText(nameNode, code);
                    const alias = aliasNode ? getNodeText(aliasNode, code) : undefined;
                    const key = alias || className;
                    imports.set(key, { modulePath, className, alias, isModule: false });
                }
            } else if (child.type === 'import_list') {
                // from xxx import (YYY, ZZZ as AAA)
                for (const item of child.namedChildren) {
                    if (!item) continue;
                    if (item.type === 'aliased_import') {
                        const nameNode = item.childForFieldName('name');
                        const aliasNode = item.childForFieldName('alias');
                        if (!nameNode) continue;
                        const className = getNodeText(nameNode, code);
                        const alias = aliasNode ? getNodeText(aliasNode, code) : undefined;
                        const key = alias || className;
                        imports.set(key, { modulePath, className, alias, isModule: false });
                        continue;
                    }
                    if (item.type === 'dotted_name') {
                        const className = getNodeText(item, code);
                        imports.set(className, { modulePath, className, isModule: false });
                    }
                }
            } else if (child.type === 'dotted_name' && child !== moduleNameNode) {
                // from xxx import YYY
                const className = getNodeText(child, code);
                imports.set(className, { modulePath, className, isModule: false });
            }
        }
    }
    
    return imports;
}

/**
 * Convert Python module path to potential file paths
 * e.g., "masfactory.components.compound_graph" -> ["masfactory/components/compound_graph.py", ...]
 */
export function modulePathToFilePaths(modulePath: string, workspaceRoot: string): string[] {
    const parts = modulePath.split('.');
    const paths: string[] = [];
    
    // Direct path: masfactory/components/compound_graph.py
    const directPath = parts.join('/') + '.py';
    paths.push(directPath);
    
    // Package path: masfactory/components/compound_graph/__init__.py
    const packagePath = parts.join('/') + '/__init__.py';
    paths.push(packagePath);
    
    // Try with src/ prefix
    paths.push('src/' + directPath);
    paths.push('src/' + packagePath);
    
    return paths.map(p => workspaceRoot + '/' + p);
}

/**
 * Base graph/loop types - these are framework-provided primitive types
 * They should NOT be treated as composite components that need cross-file parsing
 */
const BASE_FRAMEWORK_TYPES = [
    'Loop',
    'Graph',
    'RootGraph',
    'Node',
    'Agent',
    'SingleAgent',
    'CustomNode',
    'LogicSwitch',
    'AgentSwitch'
];

/**
 * Types that have internal structure (entry/exit or controller/terminate)
 * These create subgraph visualizations
 */
const GRAPH_STRUCTURE_TYPES = [
    'Loop',
    'Graph',
    'RootGraph',
    'HubGraph',
    'MeshGraph',
    'VerticalGraph',
    'HorizontalGraph',
    'AdjacencyListGraph',
    'AdjacencyMatrixGraph',
    // Composite types that inherit from Graph/Loop
    'InstructorAssistantGraph',
    'BrainstormingGraph',
    'AutoGraph',
    'VerticalDecisionGraph',
    'VerticalSolverFirstDecisionGraph'
];

/**
 * Check if a type is a base framework primitive (should NOT be expanded)
 */
export function isBaseFrameworkType(nodeType: string): boolean {
    const normalized = nodeType.includes('.') ? nodeType.split('.').pop()! : nodeType;
    return BASE_FRAMEWORK_TYPES.includes(normalized);
}

/**
 * Check if a class is a composite component that needs cross-file parsing
 * A composite component is any type that:
 * 1. Has internal structure (inherits from Graph/Loop)
 * 2. Is NOT a base framework primitive type
 * This means any custom class that inherits from Graph/Loop should be parsed
 */
export function isCompositeComponent(nodeType: string): boolean {
    const normalized = nodeType.includes('.') ? nodeType.split('.').pop()! : nodeType;
    // If it's a base framework type, it's not composite
    if (BASE_FRAMEWORK_TYPES.includes(normalized)) {
        return false;
    }
    // If it has graph structure (is in GRAPH_STRUCTURE_TYPES or ends with Graph/Loop pattern),
    // it's likely a composite component
    if (GRAPH_STRUCTURE_TYPES.includes(normalized)) {
        return true;
    }
    // Also detect custom types that might inherit from Graph/Loop by naming convention
    if (normalized.endsWith('Graph') || normalized.endsWith('Loop') || normalized.endsWith('Workflow')) {
        return true;
    }
    return false;
}

/**
 * Check if a type has internal structure (entry/exit or controller/terminate)
 */
export function hasInternalStructure(nodeType: string): boolean {
    const normalized = nodeType.includes('.') ? nodeType.split('.').pop()! : nodeType;
    return GRAPH_STRUCTURE_TYPES.includes(normalized) || 
           normalized.endsWith('Graph') || 
           normalized.endsWith('Loop');
}
