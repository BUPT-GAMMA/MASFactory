export type ParserFeatures = {
    /**
     * Parse and expand external builder functions (def build_xxx(loop/graph,...)).
     */
    builderFunctions?: boolean;
    /**
     * Enable declarative graph parsing (NodeTemplate(Graph/Loop, nodes=[...], edges=[...])).
     */
    declarativeGraphs?: boolean;
    /**
     * Enable NodeTemplate-based graph discovery/expansion.
     */
    nodeTemplates?: boolean;
    /**
     * Expand composed-graph instances (AdjacencyList/Matrix/etc) from literal args.
     */
    composedGraphInstances?: boolean;
} & Record<string, boolean | undefined>;

export const DEFAULT_PARSER_FEATURES = {
    builderFunctions: true,
    declarativeGraphs: true,
    nodeTemplates: true,
    composedGraphInstances: true
} satisfies ParserFeatures;

export function mergeParserFeatures(overrides?: ParserFeatures | null): ParserFeatures {
    return { ...DEFAULT_PARSER_FEATURES, ...(overrides || {}) };
}

