import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { GraphParser, ResolutionContext } from '../parser/parser';
import { GraphData, GraphEdge, VisualizationSettings, GraphAttributesSummary } from '../parser/types';
import { ControlFlowContext } from '../parser/buildMethodParser';
import { ControlFlowStateStore, type ViewKind } from './controlFlowStateStore';
import { mergePrefixedStructure, type ComponentLikeStructure } from './graphMerge';

export type AmlImportedDocumentPreview = {
  alias: string;
  filePath: string;
  text: string;
};

export type AmlImplementationTarget = {
  filePath: string;
  line?: number;
  column?: number;
};

export type AmlPreviewData = {
  implementationGraphs: Record<string, GraphData>;
  implementationTargets: Record<string, AmlImplementationTarget>;
  importedDocuments: Record<string, AmlImportedDocumentPreview>;
};

export class PreviewGraphService {
  private latestGraphUpdateToken = 0;
  private workspaceRoot: string = '';

  constructor(
    private readonly deps: {
      parser: GraphParser;
      controlFlowState: ControlFlowStateStore;
      safePostMessage: (webview: vscode.Webview, message: unknown) => void;
      ensureParserReady?: () => Promise<void>;
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
      if (!wv) {continue;}
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
        if (updateToken !== this.latestGraphUpdateToken) {return;}
        this.sendGraphUpdate(expandedData, document, conditionVariables, targets);
      })
      .catch((err: Error) => {
        if (updateToken !== this.latestGraphUpdateToken) {return;}
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
    if (updateToken !== this.latestGraphUpdateToken) {return;}
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
    if (updateToken !== this.latestGraphUpdateToken) {return;}
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
    if (updateToken !== this.latestGraphUpdateToken) {return;}
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
      if (!wv) {continue;}
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
    if (nextRoot === this.workspaceRoot) {return;}
    this.workspaceRoot = nextRoot;
    this.deps.parser.setFileReader(this.createFileReader(nextRoot), nextRoot);
  }

  private updateWorkspaceRoot(document: vscode.TextDocument): void {
    const workspaceFolder = vscode.workspace.getWorkspaceFolder(document.uri);
    if (!workspaceFolder) {return;}
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

    const { isCompositeComponent, isBaseFrameworkType } = require('../parser/importResolver');

    const MAX_PASSES = 6;
    const MAX_TOTAL_EXPANSIONS = 200;
    let totalExpansions = 0;

    for (let pass = 0; pass < MAX_PASSES; pass++) {
      let expandedThisPass = 0;

      for (const [nodeName, nodeType] of Object.entries(graphData.nodeTypes)) {
        if (totalExpansions >= MAX_TOTAL_EXPANSIONS) {break;}
        if (['entry', 'exit', 'controller', 'terminate'].includes(nodeName)) {continue;}
        if (nodeName.endsWith('_controller') || nodeName.endsWith('_terminate')) {continue;}
        if (nodeName.endsWith('_entry') || nodeName.endsWith('_exit')) {continue;}

        const normalizedType = String(nodeType || '');
        if (!normalizedType) {continue;}
        if (isBaseFrameworkType(normalizedType)) {continue;}

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
            if (!graphData.warnings) {graphData.warnings = [];}
            graphData.warnings.push(
              `Composite component '${nodeName}' (${nodeType}) contains dynamic control flow; preview may be incomplete.`
            );
          }
        } else if (isCompositeComponent(normalizedType)) {
          if (!graphData.warnings) {graphData.warnings = [];}
          graphData.warnings.push(
            `Composite component '${nodeName}' (${nodeType}) could not be expanded; showing as a black box (preview may be incomplete).`
          );
        }
      }

      if (expandedThisPass === 0) {break;}
    }

    return graphData;
  }

  private mergeComponentStructure(graphData: GraphData, parentNode: string, structure: any): void {
    mergePrefixedStructure(graphData, parentNode, structure as ComponentLikeStructure, { mode: 'replace' });
  }

  async resolveAmlPreviewData(document: vscode.TextDocument): Promise<AmlPreviewData> {
    this.updateWorkspaceRoot(document);
    const sourceText = document.getText();
    const importedDocuments = this.resolveAmlImportedDocuments(sourceText, document.uri.fsPath);
    const bindingSourceFiles = new Map<string, string>();
    for (const binding of this.extractPythonImplementationBindings(sourceText)) {
      bindingSourceFiles.set(binding, document.uri.fsPath);
    }
    for (const imported of Object.values(importedDocuments)) {
      for (const binding of this.extractPythonImplementationBindings(imported.text)) {
        if (!bindingSourceFiles.has(binding)) {
          bindingSourceFiles.set(binding, imported.filePath);
        }
      }
    }

    const implementationGraphs: Record<string, GraphData> = {};
    const implementationTargets: Record<string, AmlImplementationTarget> = {};
    let canResolvePythonBindings = true;
    if (bindingSourceFiles.size > 0 && this.deps.ensureParserReady) {
      try {
        await this.deps.ensureParserReady();
      } catch (error) {
        canResolvePythonBindings = false;
        console.log('[PreviewGraphService] AML implementation expansion skipped because parser initialization failed:', error);
      }
    }

    if (canResolvePythonBindings) {
      for (const [binding, sourceFilePath] of bindingSourceFiles.entries()) {
        try {
          const resolved = await this.resolveAmlImplementationGraph(binding, sourceFilePath);
          if (resolved?.target) {
            implementationTargets[binding] = resolved.target;
          }
          if (resolved?.graphData && resolved.graphData.nodes.length > 0) {
            implementationGraphs[binding] = resolved.graphData;
          }
        } catch (error) {
          console.log(`[PreviewGraphService] AML implementation expansion failed for ${binding}:`, error);
        }
      }
    }

    return { implementationGraphs, implementationTargets, importedDocuments };
  }

  async resolveAmlImplementationGraphs(document: vscode.TextDocument): Promise<Record<string, GraphData>> {
    const previewData = await this.resolveAmlPreviewData(document);
    return previewData.implementationGraphs;
  }

  private extractPythonImplementationBindings(text: string): string[] {
    const bindings: string[] = [];
    const seen = new Set<string>();
    const tagPattern = /<(graph|loop)\b[^>]*\bimplementation\s*=\s*(["'])(.*?)\2/gi;
    for (const match of text.matchAll(tagPattern)) {
      const value = String(match[3] || '').trim();
      if (!value.startsWith('python:')) {continue;}
      if (seen.has(value)) {continue;}
      seen.add(value);
      bindings.push(value);
    }
    return bindings;
  }

  private extractAmlImports(text: string): Array<{ alias: string; src: string }> {
    const imports: Array<{ alias: string; src: string }> = [];
    const pattern = /<import\b([^>]*?)\/?>/gi;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text))) {
      const attrs = match[1] || '';
      const alias = this.extractXmlAttribute(attrs, 'alias');
      const src = this.extractXmlAttribute(attrs, 'src');
      if (!alias || !src) {continue;}
      imports.push({ alias, src });
    }
    return imports;
  }

  private extractXmlAttribute(attrs: string, name: string): string {
    const escapedName = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const pattern = new RegExp(`\\b${escapedName}\\s*=\\s*(['"])(.*?)\\1`, 'i');
    const match = pattern.exec(attrs);
    return String(match?.[2] || '').trim();
  }

  private resolveAmlImportPath(src: string, sourceFilePath: string): string | null {
    const value = String(src || '').trim();
    if (!value) {return null;}
    try {
      if (/^file:\/\//i.test(value)) {
        return vscode.Uri.parse(value).fsPath;
      }
      if (path.isAbsolute(value)) {
        return value;
      }
      const candidates = [
        path.resolve(path.dirname(sourceFilePath), value),
        this.workspaceRoot ? path.resolve(this.workspaceRoot, value) : ''
      ].filter(Boolean);
      for (const candidate of candidates) {
        if (fs.existsSync(candidate)) {
          return candidate;
        }
      }
      return candidates[0] || null;
    } catch {
      return null;
    }
  }

  private resolveAmlImportedDocuments(
    sourceText: string,
    sourceFilePath: string
  ): Record<string, AmlImportedDocumentPreview> {
    const out: Record<string, AmlImportedDocumentPreview> = {};
    const visitedFiles = new Set<string>();
    const MAX_DEPTH = 8;

    const visit = (text: string, filePath: string, depth: number): void => {
      if (depth > MAX_DEPTH) {return;}
      for (const item of this.extractAmlImports(text)) {
        const resolved = this.resolveAmlImportPath(item.src, filePath);
        if (!resolved) {continue;}
        let importedText = '';
        try {
          importedText = fs.readFileSync(resolved, 'utf-8');
        } catch {
          continue;
        }

        if (!out[item.alias]) {
          out[item.alias] = { alias: item.alias, filePath: resolved, text: importedText };
        }

        const normalized = path.resolve(resolved);
        if (visitedFiles.has(normalized)) {continue;}
        visitedFiles.add(normalized);
        visit(importedText, resolved, depth + 1);
      }
    };

    visitedFiles.add(path.resolve(sourceFilePath));
    visit(sourceText, sourceFilePath, 0);
    return out;
  }

  private async resolveAmlImplementationGraph(
    binding: string,
    sourceFilePath: string
  ): Promise<{ graphData: GraphData; target: AmlImplementationTarget } | null> {
    const structure = await this.deps.parser.getComponentStructureByPythonPath(binding, {
      sourceFilePath
    });
    if (!structure || structure.nodes.length === 0) {
      return null;
    }

    const graphData = this.componentStructureToGraphData(structure, binding);
    const ctx: ResolutionContext = {
      imports: structure.sourceImports ? new Map(structure.sourceImports) : new Map(),
      sourceFilePath: structure.sourceFilePath || sourceFilePath
    };

    const expanded = await this.expandAllSubgraphs(graphData, ctx);
    this.computeGraphAttributesSummary(expanded);
    return { graphData: expanded, target: this.implementationTargetFromStructure(structure, sourceFilePath) };
  }

  private implementationTargetFromStructure(
    structure: ComponentLikeStructure,
    fallbackSourceFilePath: string
  ): AmlImplementationTarget {
    const filePath = structure.sourceFilePath || fallbackSourceFilePath;
    const lineNumbers = Object.values(structure.nodeLineNumbers || {})
      .map((line) => Number(line))
      .filter((line) => Number.isFinite(line) && line > 0);
    const line = lineNumbers.length > 0 ? Math.min(...lineNumbers) : undefined;
    return {
      filePath,
      line,
      column: 1
    };
  }

  private componentStructureToGraphData(structure: ComponentLikeStructure, binding: string): GraphData {
    const subgraphs: Record<string, string[]> = {};
    const subgraphParents: Record<string, string> = {};
    const subgraphTypes: Record<string, string> = {};

    for (const [parent, children] of Object.entries(structure.subgraphs || {})) {
      subgraphs[parent] = Array.isArray(children) ? [...children] : [];
      for (const child of subgraphs[parent]) {
        subgraphParents[child] = parent;
      }

      const childTypes = subgraphs[parent].map((child) => String(structure.nodeTypes?.[child] || ''));
      const looksLoop =
        childTypes.includes('Controller') ||
        childTypes.includes('TerminateNode') ||
        subgraphs[parent].some((child) => child === 'controller' || child === 'terminate');
      subgraphTypes[parent] = looksLoop ? 'Loop' : 'Graph';
    }

    return {
      nodes: Array.isArray(structure.nodes) ? [...structure.nodes] : [],
      nodeTypes: { ...(structure.nodeTypes || {}) },
      edges: Array.isArray(structure.edges) ? [...structure.edges] : [],
      subgraphs,
      subgraphTypes,
      subgraphParents,
      nodeLineNumbers: { ...(structure.nodeLineNumbers || {}) },
      nodeFilePaths: structure.nodeFilePaths ? { ...structure.nodeFilePaths } : undefined,
      nodePullKeys: { ...(structure.nodePullKeys || {}) },
      nodePushKeys: { ...(structure.nodePushKeys || {}) },
      nodeAttributes: { ...(structure.nodeAttributes || {}) },
      graphType: subgraphTypes.root === 'Loop' || structure.nodes.includes('controller') ? 'Loop' : 'Graph',
      warnings: structure.hasComplexStructure
        ? [`AML implementation '${binding}' contains dynamic control flow; preview may be incomplete.`]
        : [],
      loopControls: {},
      pendingBuilderCalls: {}
    };
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
          if (!graphData.warnings) {graphData.warnings = [];}
          graphData.warnings.push(
            `Builder function '${builderInfo.functionName}' contains dynamic control flow; preview may be incomplete.`
          );
        } else {
          console.log(
            `[PreviewGraphService] Builder ${builderInfo.functionName} parse failed; keeping ${nodeName} as black box`
          );
          if (!graphData.warnings) {graphData.warnings = [];}
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

      if (!fromNode || !toNode) {continue;}

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

    if (!graphData.subgraphs) {graphData.subgraphs = {};}
    if (!graphData.subgraphTypes) {graphData.subgraphTypes = {};}
    if (!graphData.subgraphParents) {graphData.subgraphParents = {};}

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
