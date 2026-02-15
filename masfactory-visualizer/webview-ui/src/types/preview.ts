import type { GraphData } from './graph';

export type VisualizationSettings = {
  useCustomColors?: boolean;
  nodeBackgroundColor?: string;
  nodeTextColor?: string;
  nodeBorderColor?: string;
  edgeColor?: string;
};

export type LoopControlInfo = {
  label: string;
  variable: string;
  defaultIterations: number;
};

export type AdjacencyGraphControl = {
  graphType: 'AdjacencyListGraph' | 'AdjacencyMatrixGraph';
  nodeCount: number;
  nodeInfo: Array<{ index: number; name: string; type: string }>;
  lineNumber: number;
  label: string;
};

export type PreviewUpdatePayload = {
  documentUri: string;
  data: GraphData;
  settings?: VisualizationSettings;
  conditionVariables?: string[];
  loopControls?: Record<string, LoopControlInfo>;
  loopWarnings?: string[];
  loopIterations?: Record<string, number>;
  adjacencyGraphControls?: Record<string, AdjacencyGraphControl>;
};

export type PreviewClearPayload = {
  reason?: string;
};

