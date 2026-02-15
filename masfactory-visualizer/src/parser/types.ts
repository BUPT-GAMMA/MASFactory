/**
 * Type definitions for graph parsing
 */

/**
 * Represents an edge in the graph
 */
export interface GraphEdge {
    from: string;
    to: string;
    label?: string;
    keys?: string[];  // Array of all keys
    keysDetails?: { [key: string]: string };  // Complete key: value mapping
    lineNumber?: number;  // Line number where the edge is defined
    filePath?: string;  // File path where the edge is defined (for cross-file navigation)
    variableName?: string;  // Variable name assigned to this edge (if any)
}

/**
 * Known graph types that have special topology generation
 */
export type GraphType = 
    | 'HorizontalGraph'      // Linear pipeline: entry → n1 → n2 → ... → exit
    | 'VerticalGraph'        // Fan-out: entry → all nodes (parallel) → aggregator? → exit
    | 'AdjacencyMatrixGraph' // Custom topology via adjacency matrix
    | 'AdjacencyListGraph'   // Custom topology via adjacency list
    | 'HubGraph'             // Hub-spoke: supervisor + router + workers
    | 'MeshGraph'            // Mesh: agents + router in loop
    | 'BrainstormingGraph'   // Critics parallel + solver
    | 'RootGraph'            // Generic root graph
    | 'Graph'                // Generic graph
    | 'Loop'                 // Loop with controller
    | 'unknown';             // Unknown type

/**
 * Represents the complete graph data structure
 */
export interface GraphData {
    nodes: string[];
    nodeTypes: { [key: string]: string };
    edges: GraphEdge[];
    subgraphs: { [parent: string]: string[] };
    subgraphTypes: { [parent: string]: string };
    subgraphParents: { [child: string]: string };  // Track which parent contains each subgraph
    nodeLineNumbers: { [key: string]: number };  // Line numbers where nodes are defined
    nodeFilePaths?: { [key: string]: string };  // File paths where nodes are defined (for cross-file navigation)
    nodePullKeys: { [key: string]: { [key: string]: any } | null | 'empty' };  // pull_keys for each node: dict, None (all), or {} (empty)
    nodePushKeys: { [key: string]: { [key: string]: any } | null | 'empty' };  // push_keys for each node: dict, None (all), or {} (empty)
    nodeAttributes: { [key: string]: { [key: string]: any } | null };  // attributes for each node: initial node variables
    nodeAliases?: { [nodeName: string]: string[] };  // aliases for each node (reverse mapping from node name to alias variable names)
    /** The specific graph type (class name) for topology generation */
    graphType?: GraphType;
    // Optional: loop controls discovered in code, used by webview to render selectors
    loopControls?: { [loopId: string]: { label: string; variable: string; defaultIterations: number } };
    loopWarnings?: string[];
    warnings?: string[];  // Non-critical parsing warnings (e.g., unresolved node references)
    // Optional: adjacency graph controls discovered in code, used by webview to render structure builders
    adjacencyGraphControls?: { [graphVariable: string]: {
        graphType: 'AdjacencyListGraph' | 'AdjacencyMatrixGraph';
        nodeCount: number;  // Total nodes (including entry/exit at 0 and n-1)
        nodeInfo: Array<{ index: number; name: string; type: string }>;  // Node info for indices 1 to n-2
        lineNumber: number;
        label: string;  // Display label for the control
    } };
    // Control flow information for dynamic graph construction
    controlFlow?: ControlFlowInfo;
    // Pending builder function calls that need async expansion
    // Map from loop/graph variable name to builder function info
    pendingBuilderCalls?: { [loopVarName: string]: { functionName: string; modulePath: string } };
    // Graph-level attributes summary for each graph/subgraph
    // Key is graph node name, value contains categorized attributes
    graphAttributesSummary?: { [graphName: string]: GraphAttributesSummary };

    /**
     * When previewing standalone declarative NodeTemplate graphs, the parser may discover
     * multiple candidate templates in the same file.
     *
     * The UI can surface these candidates and let the user choose which one to preview.
     */
    templateCandidates?: string[];
    selectedTemplate?: string;
}

/**
 * Summary of attributes for a graph/subgraph
 * Used to display an attributes box on each graph
 */
export interface GraphAttributesSummary {
    // Initial attributes set via attributes={...} parameter
    initialAttributes: { [key: string]: string };
    // Keys pulled from parent via pull_keys={...} parameter
    pullKeys: { [key: string]: string };
    // Keys pushed to parent via push_keys={...} parameter (graph-level)
    pushKeys: { [key: string]: string };
    // Runtime attributes: push_keys from internal nodes that aren't in initial/pull/push
    runtimeAttributes: { [key: string]: string };
}

/**
 * Control flow information (simplified - no dynamic simulation)
 */
export interface ControlFlowInfo {
    // Placeholder for future use if needed
}

/**
 * User configuration settings for visualization
 */
export interface VisualizationSettings {
    useCustomColors?: boolean;
    nodeBackgroundColor?: string;
    nodeTextColor?: string;
    nodeBorderColor?: string;
    edgeColor?: string;
}
