export type GraphIssue = { message: string; nodes: string[]; edges: number[] };

export function isSameLevelEdge(
  from: string,
  to: string,
  g: { Nodes?: any[] }
): boolean;

export function validateGraphDesign(g: {
  Nodes?: any[];
  Edges?: any[];
}): { issues: GraphIssue[]; invalidNodes: Set<string>; invalidEdges: Set<number> };

