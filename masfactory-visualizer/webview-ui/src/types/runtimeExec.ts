export type NodeExecutionStatus = 'running' | 'ok' | 'error';

export interface NodeExecution {
  runId: string;
  startedAt: number;
  endedAt?: number;
  status: NodeExecutionStatus;
  inputs?: unknown;
  outputs?: unknown;
  metrics?: unknown;
  error?: string;
}

export interface ExecutionState {
  runningNodes: string[];
  nodeHistory: Record<string, NodeExecution[]>;
}
