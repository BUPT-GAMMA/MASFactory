export interface GraphEdge {
  from: string;
  to: string;
  label?: string;
  keys?: string[];
  keysDetails?: Record<string, string>;
  lineNumber?: number;
  filePath?: string;
  variableName?: string;
}

export interface GraphAttributesSummary {
  initialAttributes: Record<string, string>;
  pullKeys: Record<string, string>;
  pushKeys: Record<string, string>;
  runtimeAttributes: Record<string, string>;
}

export interface GraphData {
  nodes: string[];
  nodeTypes?: Record<string, string>;
  edges: GraphEdge[];
  subgraphs?: Record<string, string[]>;
  subgraphTypes?: Record<string, string>;
  subgraphParents?: Record<string, string>;
  nodeLineNumbers?: Record<string, number>;
  nodeFilePaths?: Record<string, string>;
  // MASFactory pull_keys/push_keys semantics:
  // - null => all keys
  // - 'empty' => explicitly no keys (i.e., {})
  // - object => explicit key mapping
  nodePullKeys?: Record<string, Record<string, unknown> | null | 'empty'>;
  nodePushKeys?: Record<string, Record<string, unknown> | null | 'empty'>;
  nodeAttributes?: Record<string, Record<string, unknown> | null>;
  nodeAliases?: Record<string, string[]>;
  graphAttributesSummary?: Record<string, GraphAttributesSummary>;

  // Optional fields from MASFactory "graph design" JSON flows (auto_graph / vibe_graph):
  nodeInputKeys?: Record<string, Record<string, unknown>>;
  nodeOutputKeys?: Record<string, Record<string, unknown>>;
  nodeInstructions?: Record<string, string>;
  nodePromptTemplates?: Record<string, string>;

  // Standalone NodeTemplate preview support (multiple templates in one file)
  templateCandidates?: string[];
  selectedTemplate?: string;
}
