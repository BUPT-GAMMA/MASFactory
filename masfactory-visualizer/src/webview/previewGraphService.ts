import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { GraphParser, ResolutionContext } from '../parser/parser';
import { GraphData, GraphEdge, VisualizationSettings, GraphAttributesSummary } from '../parser/types';
import { ControlFlowContext } from '../parser/buildMethodParser';
import { ControlFlowStateStore, type ViewKind } from './controlFlowStateStore';
import { mergePrefixedStructure, type ComponentLikeStructure } from './graphMerge';

export class PreviewGraphService {
  private latestGraphUpdateToken = 0;
  private workspaceRoot: string = '';

  constructor(
    private readonly deps: {
      parser: GraphParser;
      controlFlowState: ControlFlowStateStore;
      safePostMessage: (webview: vscode.Webview, message: unknown) => void;
    }
  ) {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    const root =
      workspaceFolders && workspaceFolders.length > 0 ? workspaceFolders[0].uri.fsPath : '';
    this.setWorkspaceRoot(root);
  }

  clearGraph(reason: string, targets: Array<vscode.Webview | undefined>): void {
    const message = { type: 'clear', reason };
    for (const wv of targets) {
      if (!wv) continue;
      this.deps.safePostMessage(wv, message);
    }
  }

  updateGraph(document: vscode.TextDocument, targets: Array<vscode.Webview | undefined>): void {
    const updateToken = ++this.latestGraphUpdateToken;
    if (document.languageId !== 'python') {
      this.clearGraph(`Not a Python file: ${document.fileName.split('/').pop()}`, targets);
      return;
    }

    const text = document.getText();
    const uriString = document.uri.toString();
    const sourceFilePath = document.uri.fsPath;
    const templateName = this.deps.controlFlowState.getTemplateSelection(uriString);

    // Ensure we have a global loop-iteration config for this URI
    this.deps.controlFlowState.getGlobalLoopConfig(uriString);

    // Update workspace root based on current document
    this.updateWorkspaceRoot(document);

    // Get condition variables from code
    const conditionVariables = this.deps.parser.getConditionVariables(text);

    // Parse graph, then re-parse with stored control-flow selections (if any)
    let graphData = this.deps.parser.parse(text, undefined, sourceFilePath, { templateName });
    this.deps.controlFlowState.mergeGlobalLoopIterations(uriString, graphData.loopControls);

    const iterationConfig = this.deps.controlFlowState.getGlobalLoopConfig(uriString);
    const storedConditions = this.deps.controlFlowState.getGlobalConditionConfig(uriString);
    if (iterationConfig.size > 0 || storedConditions.size > 0) {
      const controlFlowCtx: ControlFlowContext = {
        loopIterations: Object.fromEntries(iterationConfig),
        conditionValues: Object.fromEntries(storedConditions)
      };
      graphData = this.deps.parser.parse(text, controlFlowCtx, sourceFilePath, { templateName });
      this.deps.controlFlowState.mergeGlobalLoopIterations(uriString, graphData.loopControls);
    }

    const resolutionCtx: ResolutionContext = {
      imports: new Map(this.deps.parser.getImports()),
      sourceFilePath
    };

    // Async: expand composite components and builder functions, then send update
    this.expandAllSubgraphs(graphData, resolutionCtx)
      .then((expandedData: GraphData) => {
        if (updateToken !== this.latestGraphUpdateToken) return;
        this.sendGraphUpdate(expandedData, document, conditionVariables, targets);
      })
      .catch((err: Error) => {
        if (updateToken !== this.latestGraphUpdateToken) return;
        console.log('[PreviewGraphService] Error expanding subgraphs:', err);
        this.sendGraphUpdate(graphData, document, conditionVariables, targets);
      });
  }

  async handleConditionChanged(args: {
    webview: vscode.Webview;
    viewKind: ViewKind;
    documentUri: string | undefined;
    conditions: { [key: string]: boolean };
  }): Promise<void> {
    const updateToken = ++this.latestGraphUpdateToken;
    const doc = await this.getDocumentForMessage(args.documentUri);
    if (!doc || doc.languageId !== 'python') {
      return;
    }

    const text = doc.getText();
    const uriString = doc.uri.toString();
    const sourceFilePath = doc.uri.fsPath;
    const templateName = this.deps.controlFlowState.getTemplateSelection(uriString);

    // Keep workspace-root/import resolution in sync with the current document.
    this.updateWorkspaceRoot(doc);

    const iterationConfig = this.deps.controlFlowState.getViewLoopConfig(uriString, args.viewKind);
    const conditionMap = this.deps.controlFlowState.setViewConditions(uriString, args.viewKind, args.conditions);

    // Parse with specified conditions
    let graphData = this.deps.parser.parseWithConditions(
      text,
      conditionMap,
      iterationConfig,
      sourceFilePath,
      { templateName }
    );
    this.deps.controlFlowState.mergeViewLoopControls(uriString, args.viewKind, graphData.loopControls);

    const resolutionCtx: ResolutionContext = {
      imports: new Map(this.deps.parser.getImports()),
      sourceFilePath
    };

    try {
      graphData = await this.expandAllSubgraphs(graphData, resolutionCtx);
    } catch (err) {
      console.log('[PreviewGraphService] Error expanding subgraphs (conditionChanged):', err);
    }

    // Compute graph attribute overlays for this update path too.
    this.computeGraphAttributesSummary(graphData);

    // Get user configuration
    const config = vscode.workspace.getConfiguration('masfactory-visualizer');
    const customSettings: VisualizationSettings = {
      useCustomColors: config.get('useCustomColors', false),
      nodeBackgroundColor: config.get('nodeBackgroundColor', ''),
      nodeTextColor: config.get('nodeTextColor', ''),
      nodeBorderColor: config.get('nodeBorderColor', ''),
      edgeColor: config.get('edgeColor', '')
    };

    // Send updated graph back to the webview that triggered the change
    if (updateToken !== this.latestGraphUpdateToken) return;
    this.deps.safePostMessage(args.webview, {
      type: 'update',
      data: graphData,
      settings: customSettings,
      documentUri: uriString,
      conditionVariables: this.deps.parser.getConditionVariables(text),
      loopControls: graphData.loopControls ?? {},
      loopWarnings: graphData.loopWarnings ?? [],
      loopIterations: Object.fromEntries(iterationConfig),
      adjacencyGraphControls: graphData.adjacencyGraphControls ?? {}
    });
  }

  async handleLoopIterationsChanged(args: {
    webview: vscode.Webview;
    viewKind: ViewKind;
    documentUri: string | undefined;
    loopIterations: { [key: string]: number };
    conditions?: { [key: string]: boolean };
  }): Promise<void> {
    const updateToken = ++this.latestGraphUpdateToken;
    const doc = await this.getDocumentForMessage(args.documentUri);
    if (!doc || doc.languageId !== 'python') {
      return;
    }

    const uriString = doc.uri.toString();
    const sourceFilePath = doc.uri.fsPath;
    const templateName = this.deps.controlFlowState.getTemplateSelection(uriString);

    // Keep workspace-root/import resolution in sync with the current document.
    this.updateWorkspaceRoot(doc);

    const storedConfig = this.deps.controlFlowState.getViewLoopConfig(uriString, args.viewKind);
    this.deps.controlFlowState.setViewLoopIterations(
      uriString,
      args.viewKind,
      args.loopIterations,
      this.deps.parser.getMaxLoopIterations()
    );

    const text = doc.getText();

    const conditionVariables = this.deps.parser.getConditionVariables(text);
    let conditionMap: Map<string, boolean>;
    if (args.conditions && Object.keys(args.conditions).length > 0) {
      conditionMap = this.deps.controlFlowState.setViewConditions(uriString, args.viewKind, args.conditions);
    } else {
      const stored = this.deps.controlFlowState.getViewConditionConfig(uriString, args.viewKind);
      conditionMap = this.deps.controlFlowState.setViewConditions(uriString, args.viewKind, Object.fromEntries(stored));
    }

    let graphData = this.deps.parser.parseWithConditions(text, conditionMap, storedConfig, sourceFilePath, {
      templateName
    });
    this.deps.controlFlowState.mergeViewLoopControls(uriString, args.viewKind, graphData.loopControls);

    const resolutionCtx: ResolutionContext = {
      imports: new Map(this.deps.parser.getImports()),
      sourceFilePath
    };

    try {
      graphData = await this.expandAllSubgraphs(graphData, resolutionCtx);
    } catch (err) {
      console.log('[PreviewGraphService] Error expanding subgraphs (loopIterationsChanged):', err);
    }

    // Compute graph attribute overlays for this update path too.
    this.computeGraphAttributesSummary(graphData);

    const config = vscode.workspace.getConfiguration('masfactory-visualizer');
    const customSettings: VisualizationSettings = {
      useCustomColors: config.get('useCustomColors', false),
      nodeBackgroundColor: config.get('nodeBackgroundColor', ''),
      nodeTextColor: config.get('nodeTextColor', ''),
      nodeBorderColor: config.get('nodeBorderColor', ''),
      edgeColor: config.get('edgeColor', '')
    };

    // Send updated graph back to the webview that triggered the change
    if (updateToken !== this.latestGraphUpdateToken) return;
    this.deps.safePostMessage(args.webview, {
      type: 'update',
      data: graphData,
      settings: customSettings,
      documentUri: uriString,
      conditionVariables,
      loopControls: graphData.loopControls ?? {},
      loopWarnings: graphData.loopWarnings ?? [],
      loopIterations: Object.fromEntries(storedConfig),
      adjacencyGraphControls: graphData.adjacencyGraphControls ?? {}
    });
  }

  async handleAdjacencyGraphChanged(args: {
    webview: vscode.Webview;
    viewKind: ViewKind;
    documentUri: string | undefined;
    graphVariable: string;
    edges: Array<{ from: number; to: number; keys?: { [key: string]: string } }>;
    conditions?: { [key: string]: boolean };
    loopIterations?: { [key: string]: number };
  }): Promise<void> {
    const updateToken = ++this.latestGraphUpdateToken;
    const doc = await this.getDocumentForMessage(args.documentUri);
    if (!doc || doc.languageId !== 'python') {
      return;
    }

    const uriString = doc.uri.toString();
    const sourceFilePath = doc.uri.fsPath;
    const templateName = this.deps.controlFlowState.getTemplateSelection(uriString);

    // Keep workspace-root/import resolution in sync with the current document.
    this.updateWorkspaceRoot(doc);

    const storedConfig = this.deps.controlFlowState.getViewLoopConfig(uriString, args.viewKind);
    const loopRecord =
      args.loopIterations && Object.keys(args.loopIterations).length > 0
        ? args.loopIterations
        : Object.fromEntries(storedConfig.entries());
    this.deps.controlFlowState.setViewLoopIterations(
      uriString,
      args.viewKind,
      loopRecord,
      this.deps.parser.getMaxLoopIterations()
    );

    const text = doc.getText();

    const conditionVariables = this.deps.parser.getConditionVariables(text);
    let conditionMap: Map<string, boolean>;
    if (args.conditions && Object.keys(args.conditions).length > 0) {
      conditionMap = this.deps.controlFlowState.setViewConditions(uriString, args.viewKind, args.conditions);
    } else {
      const stored = this.deps.controlFlowState.getViewConditionConfig(uriString, args.viewKind);
      conditionMap = this.deps.controlFlowState.setViewConditions(uriString, args.viewKind, Object.fromEntries(stored));
    }

    // Parse graph with conditions and loop iterations
    let graphData = this.deps.parser.parseWithConditions(text, conditionMap, storedConfig, sourceFilePath, {
      templateName
    });
    this.deps.controlFlowState.mergeViewLoopControls(uriString, args.viewKind, graphData.loopControls);

    // Apply user-defined adjacency graph structure
    if (graphData.adjacencyGraphControls && graphData.adjacencyGraphControls[args.graphVariable] && args.edges) {
      graphData = this.applyAdjacencyGraphStructure(graphData, args.graphVariable, args.edges);
    }

    const resolutionCtx: ResolutionContext = {
      imports: new Map(this.deps.parser.getImports()),
      sourceFilePath
    };

    try {
      graphData = await this.expandAllSubgraphs(graphData, resolutionCtx);
    } catch (err) {
      console.log('[PreviewGraphService] Error expanding subgraphs (adjacencyGraphChanged):', err);
    }

    // Compute graph attribute overlays for this update path too.
    this.computeGraphAttributesSummary(graphData);

    const config = vscode.workspace.getConfiguration('masfactory-visualizer');
    const customSettings: VisualizationSettings = {
      useCustomColors: config.get('useCustomColors', false),
      nodeBackgroundColor: config.get('nodeBackgroundColor', ''),
      nodeTextColor: config.get('nodeTextColor', ''),
      nodeBorderColor: config.get('nodeBorderColor', ''),
      edgeColor: config.get('edgeColor', '')
    };

    // Send updated graph back to the webview that triggered the change
    if (updateToken !== this.latestGraphUpdateToken) return;
    this.deps.safePostMessage(args.webview, {
      type: 'update',
      data: graphData,
      settings: customSettings,
      documentUri: uriString,
      conditionVariables,
      loopControls: graphData.loopControls ?? {},
      loopWarnings: graphData.loopWarnings ?? [],
      loopIterations: Object.fromEntries(storedConfig),
      adjacencyGraphControls: graphData.adjacencyGraphControls ?? {}
    });
  }

  private sendGraphUpdate(
    graphData: GraphData,
    document: vscode.TextDocument,
    conditionVariables: string[],
    targets: Array<vscode.Webview | undefined>
  ): void {
    const uriString = document.uri.toString();

    // Compute graph attributes summary before sending
    this.computeGraphAttributesSummary(graphData);

    // Get user configuration
    const config = vscode.workspace.getConfiguration('masfactory-visualizer');
    const customSettings: VisualizationSettings = {
      useCustomColors: config.get('useCustomColors', false),
      nodeBackgroundColor: config.get('nodeBackgroundColor', ''),
      nodeTextColor: config.get('nodeTextColor', ''),
      nodeBorderColor: config.get('nodeBorderColor', ''),
      edgeColor: config.get('edgeColor', '')
    };

    // Prepare message to send to webview
    const message = {
      type: 'update',
      data: graphData,
      settings: customSettings,
      documentUri: document.uri.toString(),
      conditionVariables: conditionVariables,
      loopControls: graphData.loopControls ?? {},
      loopWarnings: graphData.loopWarnings ?? [],
      loopIterations: Object.fromEntries(this.deps.controlFlowState.getGlobalLoopConfig(uriString)),
      adjacencyGraphControls: graphData.adjacencyGraphControls ?? {}
    };

    for (const wv of targets) {
      if (!wv) continue;
      this.deps.safePostMessage(wv, message);
    }
  }

  private async expandAllSubgraphs(graphData: GraphData, ctx: ResolutionContext): Promise<GraphData> {
    // First expand composite components (cross-file class definitions)
    let result = await this.expandCompositeComponents(graphData, ctx);

    // Then expand builder function structures
    result = await this.expandBuilderFunctions(result, ctx);

    return result;
  }

  private createFileReader(workspaceRoot: string) {
    return async (filePath: string): Promise<string | null> => {
      try {
        // Try direct path first
        if (fs.existsSync(filePath)) {
          return fs.readFileSync(filePath, 'utf-8');
        }

        // Try workspace-relative paths
        const workspacePaths = [path.join(workspaceRoot, filePath), path.join(workspaceRoot, 'src', filePath)];

        for (const p of workspacePaths) {
          if (fs.existsSync(p)) {
            return fs.readFileSync(p, 'utf-8');
          }
        }

        return null;
      } catch {
        return null;
      }
    };
  }

  private setWorkspaceRoot(workspaceRoot: string): void {
    const nextRoot = workspaceRoot || '';
    if (nextRoot === this.workspaceRoot) return;
    this.workspaceRoot = nextRoot;
    this.deps.parser.setFileReader(this.createFileReader(nextRoot), nextRoot);
  }

  private updateWorkspaceRoot(document: vscode.TextDocument): void {
    const workspaceFolder = vscode.workspace.getWorkspaceFolder(document.uri);
    if (!workspaceFolder) return;
    this.setWorkspaceRoot(workspaceFolder.uri.fsPath);
  }

  private async getDocumentForMessage(documentUri?: string): Promise<vscode.TextDocument | null> {
    if (documentUri) {
      try {
        return await vscode.workspace.openTextDocument(vscode.Uri.parse(documentUri));
      } catch {
        // fall back to active editor
      }
    }
    const editor = vscode.window.activeTextEditor;
    return editor ? editor.document : null;
  }

  private async expandCompositeComponents(graphData: GraphData, ctx: ResolutionContext): Promise<GraphData> {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { isCompositeComponent, isBaseFrameworkType } = require('../parser/importResolver');

    const MAX_PASSES = 6;
    const MAX_TOTAL_EXPANSIONS = 200;
    let totalExpansions = 0;

    for (let pass = 0; pass < MAX_PASSES; pass++) {
      let expandedThisPass = 0;

      for (const [nodeName, nodeType] of Object.entries(graphData.nodeTypes)) {
        if (totalExpansions >= MAX_TOTAL_EXPANSIONS) break;
        if (['entry', 'exit', 'controller', 'terminate'].includes(nodeName)) continue;
        if (nodeName.endsWith('_controller') || nodeName.endsWith('_terminate')) continue;
        if (nodeName.endsWith('_entry') || nodeName.endsWith('_exit')) continue;

        const normalizedType = String(nodeType || '');
        if (!normalizedType) continue;
        if (isBaseFrameworkType(normalizedType)) continue;

        const existingChildren = graphData.subgraphs?.[nodeName];
        if (existingChildren && existingChildren.length > 2) {
          continue;
        }

        const structure = await this.deps.parser.getComponentStructure(normalizedType, ctx);

        if (structure && structure.nodes.length > 2) {
          this.mergeComponentStructure(graphData, nodeName, structure);
          expandedThisPass++;
          totalExpansions++;
          if (structure.hasComplexStructure) {
            if (!graphData.warnings) graphData.warnings = [];
            graphData.warnings.push(
              `Composite component '${nodeName}' (${nodeType}) contains dynamic control flow; preview may be incomplete.`
            );
          }
        } else if (isCompositeComponent(normalizedType)) {
          if (!graphData.warnings) graphData.warnings = [];
          graphData.warnings.push(
            `Composite component '${nodeName}' (${nodeType}) could not be expanded; showing as a black box (preview may be incomplete).`
          );
        }
      }

      if (expandedThisPass === 0) break;
    }

    return graphData;
  }

  private mergeComponentStructure(graphData: GraphData, parentNode: string, structure: any): void {
    mergePrefixedStructure(graphData, parentNode, structure as ComponentLikeStructure, { mode: 'replace' });
  }

  private async expandBuilderFunctions(graphData: GraphData, ctx: ResolutionContext): Promise<GraphData> {
    const pendingCalls = graphData.pendingBuilderCalls;
    if (!pendingCalls || Object.keys(pendingCalls).length === 0) {
      return graphData;
    }

    console.log(`[PreviewGraphService] Found ${Object.keys(pendingCalls).length} builder function calls to expand`);

    for (const [nodeName, builderInfo] of Object.entries(pendingCalls)) {
      console.log(`[PreviewGraphService] Expanding builder ${builderInfo.functionName} for ${nodeName}`);

      try {
        const structure = await this.deps.parser.getBuilderFunctionStructure(
          builderInfo.functionName,
          builderInfo.modulePath,
          ctx
        );

        if (structure && !structure.hasComplexStructure && structure.nodes.length > 2) {
          console.log(`[PreviewGraphService] Builder ${builderInfo.functionName} parsed: ${structure.nodes.length} nodes`);
          this.mergeBuilderStructure(graphData, nodeName, structure);
        } else if (structure && structure.hasComplexStructure) {
          console.log(
            `[PreviewGraphService] Builder ${builderInfo.functionName} has complex structure; keeping ${nodeName} as black box`
          );
          if (!graphData.warnings) graphData.warnings = [];
          graphData.warnings.push(
            `Builder function '${builderInfo.functionName}' contains dynamic control flow; preview may be incomplete.`
          );
        } else {
          console.log(
            `[PreviewGraphService] Builder ${builderInfo.functionName} parse failed; keeping ${nodeName} as black box`
          );
          if (!graphData.warnings) graphData.warnings = [];
          graphData.warnings.push(
            `Builder function '${builderInfo.functionName}' could not be expanded; showing as a black box (preview may be incomplete).`
          );
        }
      } catch (error) {
        console.error(`[PreviewGraphService] Error expanding builder ${builderInfo.functionName}:`, error);
      }
    }

    return graphData;
  }

  private mergeBuilderStructure(graphData: GraphData, parentNode: string, structure: any): void {
    mergePrefixedStructure(graphData, parentNode, structure as ComponentLikeStructure, { mode: 'add' });
  }

  private computeGraphAttributesSummary(graphData: GraphData): void {
    const summary: { [graphName: string]: GraphAttributesSummary } = {};

    const graphNodes = new Set<string>();
    if (graphData.subgraphs) {
      for (const parent of Object.keys(graphData.subgraphs)) {
        graphNodes.add(parent);
      }
    }

    for (const [nodeName, nodeType] of Object.entries(graphData.nodeTypes)) {
      if (
        nodeType.includes('Loop') ||
        nodeType.includes('Graph') ||
        nodeType === 'RootGraph' ||
        nodeType === 'HorizontalGraph' ||
        nodeType === 'VerticalGraph' ||
        nodeType === 'AdjacencyMatrixGraph' ||
        nodeType === 'AdjacencyListGraph' ||
        nodeType === 'HubGraph' ||
        nodeType === 'MeshGraph' ||
        nodeType === 'BrainstormingGraph'
      ) {
        graphNodes.add(nodeName);
      }
    }

    for (const graphName of graphNodes) {
      const initialAttributes: { [key: string]: string } = {};
      const pullKeys: { [key: string]: string } = {};
      const pushKeys: { [key: string]: string } = {};
      const runtimeAttributes: { [key: string]: string } = {};

      if (graphData.nodeAttributes && graphData.nodeAttributes[graphName]) {
        const attrs = graphData.nodeAttributes[graphName];
        if (attrs && typeof attrs === 'object') {
          for (const [key, value] of Object.entries(attrs)) {
            initialAttributes[key] = String(value);
          }
        }
      }

      if (graphData.nodePullKeys && graphData.nodePullKeys[graphName]) {
        const keys = graphData.nodePullKeys[graphName];
        if (keys && typeof keys === 'object') {
          for (const [key, value] of Object.entries(keys)) {
            pullKeys[key] = String(value);
          }
        }
      }

      if (graphData.nodePushKeys && graphData.nodePushKeys[graphName]) {
        const keys = graphData.nodePushKeys[graphName];
        if (keys && typeof keys === 'object') {
          for (const [key, value] of Object.entries(keys)) {
            pushKeys[key] = String(value);
          }
        }
      }

      const internalNodes = graphData.subgraphs?.[graphName] || [];
      for (const childNode of internalNodes) {
        if (graphData.nodePushKeys && graphData.nodePushKeys[childNode]) {
          const nodePushKeys = graphData.nodePushKeys[childNode];
          if (nodePushKeys && typeof nodePushKeys === 'object') {
            for (const [key, value] of Object.entries(nodePushKeys)) {
              if (!(key in initialAttributes) && !(key in pullKeys) && !(key in pushKeys)) {
                runtimeAttributes[key] = String(value);
              }
            }
          }
        }
      }

      if (
        Object.keys(initialAttributes).length > 0 ||
        Object.keys(pullKeys).length > 0 ||
        Object.keys(pushKeys).length > 0 ||
        Object.keys(runtimeAttributes).length > 0
      ) {
        summary[graphName] = { initialAttributes, pullKeys, pushKeys, runtimeAttributes };
      }
    }

    graphData.graphAttributesSummary = summary;
    console.log(
      `[PreviewGraphService] Computed graph attributes summary for ${Object.keys(summary).length} graphs`
    );
  }

  private applyAdjacencyGraphStructure(
    graphData: GraphData,
    graphVariable: string,
    edges: Array<{ from: number; to: number; keys?: { [key: string]: string } }>
  ): GraphData {
    const control = graphData.adjacencyGraphControls?.[graphVariable];
    if (!control) {
      return graphData;
    }

    const { nodeCount, nodeInfo, lineNumber } = control;

    // Extract graph name from control
    const graphName = control.label.split(' (')[0];

    const newNodeNames: string[] = [];

    for (const node of nodeInfo) {
      const nodeName = node.name;
      if (!graphData.nodes.includes(nodeName)) {
        graphData.nodes.push(nodeName);
        newNodeNames.push(nodeName);
      }
      graphData.nodeTypes[nodeName] = node.type;
      graphData.nodeLineNumbers[nodeName] = lineNumber;
      graphData.nodePullKeys[nodeName] = 'empty';
      graphData.nodePushKeys[nodeName] = 'empty';
      graphData.nodeAttributes[nodeName] = null;
    }

    const newEdges: GraphEdge[] = [];
    for (const edgeSpec of edges) {
      // Skip edges involving entry (0) or exit (n-1)
      if (
        edgeSpec.from === 0 ||
        edgeSpec.to === nodeCount - 1 ||
        edgeSpec.from === nodeCount - 1 ||
        edgeSpec.to === 0
      ) {
        continue;
      }

      const fromNode = nodeInfo.find((n) => n.index === edgeSpec.from);
      const toNode = nodeInfo.find((n) => n.index === edgeSpec.to);

      if (!fromNode || !toNode) continue;

      const edge: GraphEdge = {
        from: fromNode.name,
        to: toNode.name,
        lineNumber,
        filePath: graphData.edges.find((e) => e.lineNumber === lineNumber)?.filePath
      };

      if (edgeSpec.keys) {
        edge.keysDetails = edgeSpec.keys;
        edge.keys = Object.keys(edgeSpec.keys);
        edge.label = edge.keys.join('\n');
      }

      newEdges.push(edge);
    }

    const filteredEdges = graphData.edges.filter(
      (e) => !nodeInfo.some((n) => n.name === e.from) || !nodeInfo.some((n) => n.name === e.to)
    );
    graphData.edges = [...filteredEdges, ...newEdges];

    if (!graphData.subgraphs) graphData.subgraphs = {};
    if (!graphData.subgraphTypes) graphData.subgraphTypes = {};
    if (!graphData.subgraphParents) graphData.subgraphParents = {};

    if (graphData.subgraphs[graphName] && newNodeNames.length > 0) {
      for (const nodeName of newNodeNames) {
        if (!graphData.subgraphs[graphName].includes(nodeName)) {
          graphData.subgraphs[graphName].push(nodeName);
        }
      }
    } else if (newNodeNames.length > 0) {
      graphData.subgraphs[graphName] = [...newNodeNames];
      graphData.subgraphTypes[graphName] = control.graphType;
    }

    return graphData;
  }
}
