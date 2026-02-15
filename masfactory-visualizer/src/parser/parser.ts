/**
 * MASFactory Graph Parser - Main Entry Point
 * 
 * This module provides AST-based parsing for Python code containing MASFactory graph definitions.
 * It uses Tree-sitter for accurate syntax tree analysis.
 */
import * as fs from 'fs';
import * as path from 'path';
import type { Node as TSNode, Parser as TreeSitterParser } from 'web-tree-sitter';

import { GraphData, GraphEdge, ControlFlowInfo, GraphType } from './types';
import { BASE_TYPES, getNodeText } from './astUtils';
import { NodeParseContext } from './nodeParser';
import { EdgeParseContext, isEdgeCreationMethod } from './edgeParser';
import { mergeParserFeatures, type ParserFeatures } from './features';
import { findBuildMethodAndBaseType, parseBuildMethod, ControlFlowContext } from './buildMethodParser';
import { findRootGraphVariable, findFunctionWithRootGraph } from './rootGraphFinder';
import { parseModuleLevel, parseFunctionBody } from './moduleLevelParser';
import { parseImports, modulePathToFilePaths, isCompositeComponent, isBaseFrameworkType, ImportInfo } from './importResolver';
import { parseComponentStructure, parseTemplateStructure, ComponentStructure } from './componentParser';
import { tryParseNodeTemplateAssignment } from './templateParser';
import { 
    detectBuilderFunction, 
    parseBuilderFunction, 
    extractBuilderFunctionCalls,
    BuilderFunctionInfo,
    BuilderFunctionStructure 
} from './builderFunctionParser';
import { expandComposedGraphInstances } from './graphInstanceExpander';
import { createPythonParser } from './treeSitter';

interface BuilderCacheEntry {
    structure: BuilderFunctionStructure | null;
    sourceFilePath?: string;
    mtimeMs?: number;
}

export interface ResolutionContext {
    imports?: Map<string, ImportInfo>;
    sourceFilePath?: string;
}

// File reader callback type for cross-file parsing
export type FileReaderCallback = (filePath: string) => Promise<string | null>;

/**
 * MASFactory Graph Parser
 * Parses Python code and extracts graph structure using Tree-sitter AST
 */
export class GraphParser {
    private parser: TreeSitterParser | null = null;
    private fileReader: FileReaderCallback | null = null;
    private workspaceRoot: string = '';
    /**
     * Cache for resolved component structures.
     *
     * Keyed by `${absoluteFilePath}::${exportedSymbolName}` to avoid collisions where two
     * different modules export the same symbol name (common in multi-repo or script-style layouts).
     */
    private componentCache: Map<string, ComponentStructure | null> = new Map();
    private builderCache: Map<string, BuilderCacheEntry> = new Map();
    private imports: Map<string, ImportInfo> = new Map();
    private lastSourceFilePath: string | undefined;
    // Track builder function calls found during parsing (loopName -> builderInfo)
    private pendingBuilderCalls: Map<string, { functionName: string; modulePath: string }> = new Map();
    private features: ParserFeatures = mergeParserFeatures(null);

    constructor() {}

    private getParser(): TreeSitterParser | null {
        if (this.parser) return this.parser;
        const parser = createPythonParser();
        if (parser) {
            this.parser = parser;
        }
        return parser;
    }

    /**
     * Configure parser behavior flags for forward compatibility.
     * Defaults preserve current behavior.
     */
    setFeatures(features?: ParserFeatures | null): void {
        this.features = mergeParserFeatures(features || null);
    }

    /**
     * Set the file reader callback for cross-file parsing
     */
    setFileReader(reader: FileReaderCallback, workspaceRoot: string): void {
        this.fileReader = reader;
        this.workspaceRoot = workspaceRoot;
    }

    /**
     * Get imports map (for use by nodeParser)
     */
    getImports(): Map<string, ImportInfo> {
        return this.imports;
    }

    getLastSourceFilePath(): string | undefined {
        return this.lastSourceFilePath;
    }

    /**
     * Get component structure from cache or parse it
     */
    async getComponentStructure(nodeType: string, ctx?: ResolutionContext): Promise<ComponentStructure | null> {
        return await this.parseExternalComponent(nodeType, ctx);
    }

    private getComponentCacheKey(filePath: string, className: string): string {
        return `${filePath}::${className}`;
    }

    /**
     * Parse an external component's structure
     */
    private async parseExternalComponent(nodeType: string, ctx?: ResolutionContext): Promise<ComponentStructure | null> {
        if (!this.fileReader) {
            console.log(`[Parser] No file reader set, cannot parse external component ${nodeType}`);
            return null;
        }

        const imports = ctx?.imports ?? this.imports;
        const sourceFilePath = ctx?.sourceFilePath ?? this.lastSourceFilePath;

        // Resolve import info for this type (supports:
        // - direct symbol imports: HubGraph
        // - qualified access: masfactory.HubGraph / pkg.mod.HubGraph
        // - module alias: cg.HubGraph where "import ... as cg"
        const importInfo = this.resolveImportInfoForType(nodeType, imports);
        if (!importInfo) {
            console.log(`[Parser] No import info found for ${nodeType}`);
            return null;
        }

        const candidateRoots = this.getCandidateWorkspaceRoots(sourceFilePath, importInfo.modulePath);
        const contextRoot =
            (sourceFilePath
                ? candidateRoots.find((root) => {
                      try {
                          void this.filePathToModulePath(sourceFilePath, root);
                          return true;
                      } catch {
                          return false;
                      }
                  })
                : undefined) || this.workspaceRoot;

        // Follow re-exports (e.g., "from masfactory import HubGraph" -> masfactory/__init__.py re-exports from deeper module)
        let currentModulePath = this.resolveModulePathFromContext(importInfo.modulePath, sourceFilePath, contextRoot);
        let currentClassName = importInfo.className;
        const visited = new Set<string>();

        for (let depth = 0; depth < 10; depth++) {
            const visitKey = `${currentModulePath}::${currentClassName}`;
            if (visited.has(visitKey)) break;
            visited.add(visitKey);

            const potentialPaths = Array.from(
                new Set(candidateRoots.flatMap((root) => modulePathToFilePaths(currentModulePath, root)))
            );
            let redirected = false;

            for (const filePath of potentialPaths) {
                try {
                    const cacheKey = this.getComponentCacheKey(filePath, currentClassName);
                    if (this.componentCache.has(cacheKey)) {
                        const cached = this.componentCache.get(cacheKey)!;
                        if (cached) {
                            console.log(`[Parser] Using cached component for ${nodeType} at ${filePath}`);
                            return cached;
                        }
                        // Cached negative lookup: we already checked this file for this symbol.
                        continue;
                    }

                    const code = await this.fileReader(filePath);
                    if (!code) continue;

                    console.log(`[Parser] Found component candidate for ${nodeType} at ${filePath}`);
                    const structure = parseComponentStructure(code, currentClassName);
                    if (structure) {
                        structure.sourceFilePath = filePath;
                        this.componentCache.set(cacheKey, structure);

                        // Inheritance fallback:
                        // Some components (e.g., HumanTesterGraph) don't implement build(), and rely on a base class build().
                        // If parsing __init__ yields no meaningful internal structure, try base classes.
                        const looksEmpty = structure.nodes.length <= 2 && structure.edges.length === 0;
                        if ((structure.parsedMethodName === '__init__' || looksEmpty) && structure.baseClasses && structure.baseClasses.length > 0) {
                            try {
                                const parser = this.getParser();
                                const tree = parser ? parser.parse(code) : null;
                                const fileImports = tree ? parseImports(tree.rootNode, code) : new Map<string, ImportInfo>();
                                const localVisited = new Set<string>();

                                const resolveBaseInSameFile = (baseClassText: string): ComponentStructure | null => {
                                    const normalized = baseClassText.includes('.')
                                        ? baseClassText.split('.').pop()!
                                        : baseClassText;
                                    if (!normalized || isBaseFrameworkType(normalized)) return null;
                                    if (localVisited.has(normalized)) return null;
                                    localVisited.add(normalized);

                                    const local = parseComponentStructure(code, normalized);
                                    if (local) {
                                        local.sourceFilePath = filePath;
                                        const empty = local.nodes.length <= 2 && local.edges.length === 0;
                                        if (!empty) return local;
                                        if (local.baseClasses && local.baseClasses.length > 0) {
                                            for (const bc of local.baseClasses) {
                                                const nested = resolveBaseInSameFile(bc);
                                                if (nested && nested.nodes.length > 2) return nested;
                                            }
                                        }
                                    }

                                    const tmpl = parseTemplateStructure(code, normalized);
                                    if (tmpl) {
                                        tmpl.sourceFilePath = filePath;
                                        const empty = tmpl.nodes.length <= 2 && tmpl.edges.length === 0;
                                        if (!empty) return tmpl;
                                    }

                                    return null;
                                };

                                for (const baseClassText of structure.baseClasses) {
                                    const normalized = baseClassText.includes('.')
                                        ? baseClassText.split('.').pop()!
                                        : baseClassText;
                                    if (!normalized || isBaseFrameworkType(normalized)) {
                                        continue;
                                    }

                                    const localBase = resolveBaseInSameFile(baseClassText);
                                    if (localBase && localBase.nodes.length > 2) {
                                        console.log(
                                            `[Parser] Using in-file base-class build() for ${currentClassName}: resolved from ${baseClassText}`
                                        );
                                        this.componentCache.set(cacheKey, localBase);
                                        return localBase;
                                    }

                                    const baseStructure = await this.getComponentStructure(baseClassText, {
                                        imports: fileImports,
                                        sourceFilePath: filePath
                                    });

                                    if (baseStructure && baseStructure.nodes.length > 2) {
                                        console.log(
                                            `[Parser] Using base-class build() for ${currentClassName}: resolved from ${baseClassText}`
                                        );
                                        this.componentCache.set(cacheKey, baseStructure);
                                        return baseStructure;
                                    }
                                }
                            } catch (e) {
                                console.log(`[Parser] Inheritance fallback failed for ${currentClassName}:`, e);
                            }
                        }

                        return structure;
                    }

                    // Declarative NodeTemplate-based components:
                    // e.g., ProfileGenerationGraph = NodeTemplate(Graph, nodes=[...], edges=[...])
                    const templateStructure = parseTemplateStructure(code, currentClassName);
                    if (templateStructure) {
                        templateStructure.sourceFilePath = filePath;
                        this.componentCache.set(cacheKey, templateStructure);
                        return templateStructure;
                    }

                    const reexport = this.findReexportTarget(filePath, code, currentClassName);
                    if (reexport) {
                        currentModulePath = reexport.modulePath;
                        currentClassName = reexport.className;
                        redirected = true;
                        break;
                    }

                    // We were able to read the file, but couldn't find a definition for this symbol (and it's not a re-export).
                    this.componentCache.set(cacheKey, null);
                } catch {
                    // ignore and try next path
                }
            }

            if (!redirected) {
                break;
            }
        }

        console.log(`[Parser] Could not resolve component source for ${nodeType}`);
        return null;
    }

    private resolveImportInfoForType(nodeType: string, imports: Map<string, ImportInfo>): ImportInfo | null {
        const direct = imports.get(nodeType);
        if (direct && !direct.isModule) {
            return direct;
        }

        if (!nodeType.includes('.')) {
            return null;
        }

        const lastDot = nodeType.lastIndexOf('.');
        const qualifier = nodeType.slice(0, lastDot);
        const symbol = nodeType.slice(lastDot + 1);

        // Module alias: "cg.HubGraph" where imports has entry for "cg" with isModule=true
        const moduleImport = imports.get(qualifier);
        if (moduleImport && moduleImport.isModule) {
            return { modulePath: moduleImport.modulePath, className: symbol };
        }

        // Fully-qualified module path: "masfactory.components.composed_graph.HubGraph"
        return { modulePath: qualifier, className: symbol };
    }

    private resolveModulePathFromContext(
        modulePathText: string,
        sourceFilePath?: string,
        effectiveRoot?: string
    ): string {
        if (!modulePathText.startsWith('.')) return modulePathText;
        if (!sourceFilePath) return modulePathText;

        try {
            const root = effectiveRoot || this.workspaceRoot;
            if (!root) return modulePathText;
            const fromModulePath = this.filePathToModulePath(sourceFilePath, root);
            return this.resolveRelativeModulePath(sourceFilePath, fromModulePath, modulePathText);
        } catch {
            return modulePathText;
        }
    }

    private filePathToModulePath(filePath: string, root: string): string {
        const relative = path.relative(root, filePath).replace(/\\/g, '/');
        // Guard against attempts to resolve module paths for files outside the chosen root.
        // When `relative` contains "..", converting to a dotted module path becomes ambiguous
        // and breaks relative-import resolution.
        if (relative.startsWith('..') || relative.includes('/..')) {
            throw new Error(`filePathToModulePath: ${filePath} is outside root ${root}`);
        }
        let noExt = relative.replace(/\.py$/, '');
        if (noExt.endsWith('/__init__')) {
            noExt = noExt.slice(0, -'/__init__'.length);
        }
        return noExt
            .split('/')
            .filter(Boolean)
            .join('.');
    }

    private resolveRelativeModulePath(fromFilePath: string, fromModulePath: string, targetModuleText: string): string {
        if (!targetModuleText.startsWith('.')) return targetModuleText;

        const match = targetModuleText.match(/^\.+/);
        const dotCount = match ? match[0].length : 0;
        const rest = targetModuleText.slice(dotCount);

        const isInit = fromFilePath.replace(/\\/g, '/').endsWith('/__init__.py');
        const currentPackage = isInit
            ? fromModulePath
            : fromModulePath.split('.').slice(0, -1).join('.');

        let parts = currentPackage ? currentPackage.split('.') : [];
        const upLevels = Math.max(0, dotCount - 1);
        if (upLevels > 0) {
            parts = parts.slice(0, Math.max(0, parts.length - upLevels));
        }

        const restParts = rest ? rest.split('.').filter(Boolean) : [];
        return [...parts, ...restParts].filter(Boolean).join('.');
    }

    private inferTopPackage(modulePath: string | undefined, sourceFilePath?: string): string | undefined {
        if (modulePath && !modulePath.startsWith('.')) {
            const first = modulePath.split('.').filter(Boolean)[0];
            if (first) return first;
        }
        if (sourceFilePath) {
            const normalized = sourceFilePath.replace(/\\/g, '/');
            const parts = normalized.split('/').filter(Boolean);
            const srcIndex = parts.lastIndexOf('src');
            if (srcIndex !== -1 && parts[srcIndex + 1]) {
                return parts[srcIndex + 1];
            }
            if (parts.includes('masfactory')) return 'masfactory';
        }
        return undefined;
    }

    private findProjectRootForFile(sourceFilePath: string, topPackage?: string): string | null {
        const pkg = topPackage || 'masfactory';
        let dir = path.dirname(sourceFilePath);

        const hasPkgDir = (candidate: string): boolean => {
            return (
                fs.existsSync(path.join(candidate, pkg)) ||
                fs.existsSync(path.join(candidate, 'src', pkg))
            );
        };

        for (let i = 0; i < 25; i++) {
            const marker =
                fs.existsSync(path.join(dir, '.git')) ||
                fs.existsSync(path.join(dir, 'pyproject.toml')) ||
                fs.existsSync(path.join(dir, 'setup.py'));
            if (marker && hasPkgDir(dir)) {
                return dir;
            }

            const parent = path.dirname(dir);
            if (parent === dir) break;
            dir = parent;
        }

        // Fallback: if no repo marker is found, still allow locating a package root.
        dir = path.dirname(sourceFilePath);
        for (let i = 0; i < 25; i++) {
            if (hasPkgDir(dir)) return dir;
            const parent = path.dirname(dir);
            if (parent === dir) break;
            dir = parent;
        }

        return null;
    }

    private getCandidateWorkspaceRoots(sourceFilePath?: string, modulePath?: string): string[] {
        const roots: string[] = [];

        let derived: string | null = null;
        if (sourceFilePath) {
            const topPackage = this.inferTopPackage(modulePath, sourceFilePath);
            derived = this.findProjectRootForFile(sourceFilePath, topPackage);
        }

        const workspace = this.workspaceRoot || '';

        // Prefer a derived root when the source file sits outside the VS Code workspace folder.
        // This happens frequently when users open files via absolute paths or multi-repo layouts.
        if (derived && (!workspace || path.relative(workspace, sourceFilePath ?? '').startsWith('..'))) {
            roots.push(derived);
            if (workspace) roots.push(workspace);
        } else {
            if (workspace) roots.push(workspace);
            if (derived) roots.push(derived);
        }

        // Python allows importing sibling modules when a script is executed directly (the script's
        // directory is added to sys.path). Support that common pattern for preview resolution too.
        if (sourceFilePath) {
            roots.push(path.dirname(sourceFilePath));
        }

        // De-duplicate while keeping order.
        return Array.from(new Set(roots.filter(Boolean)));
    }

    private findReexportTarget(
        fromFilePath: string,
        fileCode: string,
        symbolName: string
    ): { modulePath: string; className: string } | null {
        try {
            // Parse the exporting file and inspect its imports to see whether it re-exports the symbol.
            const parser = this.getParser();
            const tree = parser ? parser.parse(fileCode) : null;
            if (!tree) return null;
            const rootNode = tree.rootNode;
            const exports = parseImports(rootNode, fileCode);

            // Derive absolute module path for relative imports.
            const roots = this.getCandidateWorkspaceRoots(fromFilePath);
            const root = roots.find((r) => {
                try {
                    // Ensure file is inside this root.
                    void this.filePathToModulePath(fromFilePath, r);
                    return true;
                } catch {
                    return false;
                }
            });
            if (!root) return null;

            const fromModulePath = this.filePathToModulePath(fromFilePath, root);

            // Match either by key (no alias) or by original className (aliased import).
            for (const [key, info] of exports.entries()) {
                if (info.isModule) continue;
                if (key !== symbolName && info.className !== symbolName) continue;

                const resolvedModule = this.resolveRelativeModulePath(fromFilePath, fromModulePath, info.modulePath);
                return { modulePath: resolvedModule, className: info.className };
            }
        } catch (e) {
            console.log('[Parser] Re-export resolution failed:', e);
        }
        return null;
    }

    /**
     * Parse Python code and extract graph structure
     * @param controlFlowCtx - Optional control flow context with user-specified loop iterations and condition values
     */
    parse(
        code: string,
        controlFlowCtx?: ControlFlowContext,
        sourceFilePath?: string,
        opts?: { templateName?: string | null }
    ): GraphData {
        this.lastSourceFilePath = sourceFilePath;
        const parser = this.getParser();
        const tree = parser ? parser.parse(code) : null;
        if (!tree) {
            const result = this.initializeResult(BASE_TYPES.GRAPH, '');
            return {
                nodes: result.nodes,
                nodeTypes: result.nodeTypes,
                edges: result.edges,
                subgraphs: result.subgraphs,
                subgraphTypes: result.subgraphTypes,
                subgraphParents: result.subgraphParents,
                nodeLineNumbers: result.nodeLineNumbers,
                nodePullKeys: result.nodePullKeys,
                nodePushKeys: result.nodePushKeys,
                nodeAttributes: result.nodeAttributes,
                warnings: [
                    'Python parser is still initializing (Tree-sitter). Please wait a moment or click Refresh.'
                ]
            };
        }
        const rootNode = tree.rootNode;

        // Parse import statements for cross-file resolution
        this.imports = parseImports(rootNode, code);
        console.log(`[Parser] Found ${this.imports.size} imports`);
        
        // Clear pending builder calls from previous parse
        this.pendingBuilderCalls.clear();
        
        // Check if this is a builder function file
        const builderInfo = detectBuilderFunction(code);
        if (builderInfo && this.features.builderFunctions !== false) {
            console.log(`[Parser] Detected builder function: ${builderInfo.functionName}`);
            return this.parseBuilderFunctionFile(code, builderInfo);
        }

        // Find build method and determine base type
        const { buildMethod, baseType, className } = findBuildMethodAndBaseType(rootNode);
        
        // Initialize result containers
        const result = this.initializeResult(baseType, className);
        
        // Create parsing contexts
        const nodeCtx: NodeParseContext = {
            nodes: result.nodes,
            nodeTypes: result.nodeTypes,
            nodeLineNumbers: result.nodeLineNumbers,
            variableToNodeName: result.variableToNodeName,
            nodePullKeys: result.nodePullKeys,
            nodePushKeys: result.nodePushKeys,
            nodeAttributes: result.nodeAttributes,
            subgraphParents: result.subgraphParents,
            nodeBuildFuncs: {},  // Track build_func parameters
            templates: {},        // Track local NodeTemplate definitions
            literalValues: {},    // Track simple literal bindings for declarative graphs
            features: this.features
        };

        const edgeCtx: EdgeParseContext = {
            edges: result.edges,
            variableToNodeName: result.variableToNodeName,
            nodes: result.nodes,
            subgraphParents: result.subgraphParents,
            features: this.features
        };

        // Parse based on code structure
        let controlFlow: ControlFlowInfo = { forLoops: [], ifConditions: [], dependencies: [] };
        
        if (buildMethod) {
            console.log('[Parser] Found build() method, parsing it');
            controlFlow = parseBuildMethod(buildMethod, code, nodeCtx, edgeCtx, result.subgraphs, controlFlowCtx);
            
            // Detect builder function calls (e.g., build_agent_config_loop(loop=self._xxx))
            this.detectBuilderFunctionCalls(code, nodeCtx.variableToNodeName);
            
            // Also add build_func parameters as pending builder calls
            this.addBuildFuncToPendingCalls(nodeCtx.nodeBuildFuncs || {});
        } else {
            this.parseNonClassCode(rootNode, code, nodeCtx, edgeCtx, result.subgraphs, controlFlowCtx);
            // Non-class code (module-level or function-based build) can still contain builder calls and build_func templates.
            this.detectBuilderFunctionCalls(code, nodeCtx.variableToNodeName);
            this.addBuildFuncToPendingCalls(nodeCtx.nodeBuildFuncs || {});

            // Fallback for new declarative style: many files define ONLY a module-level NodeTemplate(Graph/Loop, nodes=[...], edges=[...])
            // (e.g., ProfileGenerationGraph = NodeTemplate(Graph, ...)).
            // In this case there is no RootGraph() instantiation nor a class build(), so we preview the template itself.
            if (
                this.features.declarativeGraphs !== false &&
                this.features.nodeTemplates !== false &&
                result.edges.length === 0 &&
                result.nodes.length <= 2
            ) {
                const fallback = this.tryParseStandaloneTemplateGraph(rootNode, code, opts?.templateName ?? null);
                if (fallback) {
                    this.logParseResult(fallback.nodes, fallback.edges);
                    return fallback;
                }
            }
        }

        // Best-effort: expand composed-graph instances from literal args
        // (e.g., AdjacencyListGraph/AdjacencyMatrixGraph node_args_list + adjacency_list/matrix)
        if (this.features.composedGraphInstances !== false) {
            try {
                expandComposedGraphInstances(rootNode, code, nodeCtx, edgeCtx, result.subgraphs);
            } catch (e) {
                console.log('[Parser] Warning: composed-graph expansion failed:', e);
            }
        }

        this.logParseResult(result.nodes, result.edges);

        // Extract loop controls for UI (loop iteration selector)
        let loopControls: GraphData['loopControls'];
        let conditionControlsForWarnings: string[] = [];
        if (buildMethod) {
            const body = buildMethod.childForFieldName('body');
            loopControls = this.extractLoopControls(body ?? buildMethod, code);
            conditionControlsForWarnings = this.extractConditionVariables(body ?? buildMethod, code);
        } else {
            const rootGraphVar = findRootGraphVariable(rootNode, code);
            if (rootGraphVar) {
                loopControls = this.extractLoopControls(rootNode, code);
                conditionControlsForWarnings = this.extractConditionVariables(rootNode, code);
            } else {
                const funcWithGraph = findFunctionWithRootGraph(rootNode, code);
                loopControls = funcWithGraph
                    ? this.extractLoopControls(funcWithGraph.funcBody, code)
                    : this.extractLoopControls(rootNode, code);
                conditionControlsForWarnings = funcWithGraph
                    ? this.extractConditionVariables(funcWithGraph.funcBody, code)
                    : this.extractConditionVariables(rootNode, code);
            }
        }

        // Determine graph type from class name
        const graphType = this.determineGraphType(className, baseType);

        const warnings: string[] = [];
        if (conditionControlsForWarnings.length > 0 || (loopControls && Object.keys(loopControls).length > 0)) {
            warnings.push(
                'This file contains dynamic graph construction (Python if/for). Dynamically-constructed graph components may fail to render, or the preview may be inaccurate.'
            );
        }

        return {
            nodes: result.nodes,
            nodeTypes: result.nodeTypes,
            edges: result.edges,
            subgraphs: result.subgraphs,
            subgraphTypes: result.subgraphTypes,
            subgraphParents: result.subgraphParents,
            nodeLineNumbers: result.nodeLineNumbers,
            nodePullKeys: result.nodePullKeys,
            nodePushKeys: result.nodePushKeys,
            nodeAttributes: result.nodeAttributes,
            graphType: graphType,
            controlFlow: controlFlow,
            loopControls: loopControls,
            warnings,
            // Store pending builder calls for async expansion
            pendingBuilderCalls: Object.fromEntries(this.pendingBuilderCalls)
        };
    }
    
    /**
     * Parse a builder function file (contains def build_xxx(loop: Loop, ...))
     */
    private parseBuilderFunctionFile(code: string, builderInfo: BuilderFunctionInfo): GraphData {
        const structure = parseBuilderFunction(code, builderInfo.functionName);
        
        if (!structure || builderInfo.hasComplexStructure) {
            console.log(`[Parser] Builder function has complex structure or failed to parse`);
            // Return minimal structure for complex/failed cases
            const baseType = builderInfo.parentParamType.includes('Loop') ? 'Loop' : 'Graph';
            return this.createEmptyGraphData(baseType, builderInfo.functionName);
        }
        
        // Determine graph type based on parameter type
        const graphType: GraphType = builderInfo.parentParamType.includes('Loop') ? 'Loop' : 'Graph';
        
        return {
            nodes: structure.nodes,
            nodeTypes: structure.nodeTypes,
            edges: structure.edges,
            subgraphs: structure.subgraphs,
            subgraphTypes: {},
            subgraphParents: {},
            nodeLineNumbers: structure.nodeLineNumbers,  // Use line numbers from parsed structure
            nodePullKeys: {},
            nodePushKeys: {},
            nodeAttributes: {},
            graphType: graphType,
            controlFlow: { forLoops: [], ifConditions: [], dependencies: [] },
            warnings: structure.hasComplexStructure ? ['Builder function contains dynamic structure (for/if)'] : []
        };
    }
    
    /**
     * Create empty graph data for cases where parsing fails
     */
    private createEmptyGraphData(baseType: string, name: string): GraphData {
        const nodes: string[] = [];
        const nodeTypes: { [key: string]: string } = {};
        
        if (baseType === 'Loop') {
            nodes.push('controller', 'terminate');
            nodeTypes['controller'] = 'Controller';
            nodeTypes['terminate'] = 'TerminateNode';
        } else {
            nodes.push('entry', 'exit');
            nodeTypes['entry'] = 'entry';
            nodeTypes['exit'] = 'exit';
        }
        
        return {
            nodes,
            nodeTypes,
            edges: [],
            subgraphs: {},
            subgraphTypes: {},
            subgraphParents: {},
            nodeLineNumbers: {},
            nodePullKeys: {},
            nodePushKeys: {},
            nodeAttributes: {},
            graphType: baseType === 'Loop' ? 'Loop' : 'Graph',
            controlFlow: { forLoops: [], ifConditions: [], dependencies: [] },
            warnings: ['Could not parse graph structure']
        };
    }
    
    /**
     * Get pending builder function calls from last parse
     * Used by webviewProvider to expand subgraphs asynchronously
     */
    getPendingBuilderCalls(): Map<string, { functionName: string; modulePath: string }> {
        return this.pendingBuilderCalls;
    }
    
    /**
     * Parse a builder function from external file and return its structure
     */
    async getBuilderFunctionStructure(
        functionName: string,
        modulePath: string,
        ctx?: ResolutionContext
    ): Promise<BuilderFunctionStructure | null> {
        const sourceFilePath = ctx?.sourceFilePath ?? this.lastSourceFilePath;
        const candidateRoots = this.getCandidateWorkspaceRoots(sourceFilePath, modulePath);
        const contextRoot =
            (sourceFilePath
                ? candidateRoots.find((root) => {
                      try {
                          void this.filePathToModulePath(sourceFilePath, root);
                          return true;
                      } catch {
                          return false;
                      }
                  })
                : undefined) || this.workspaceRoot;

        const resolvedModulePath = this.resolveModulePathFromContext(modulePath, sourceFilePath, contextRoot);
        console.log(
            `[Parser] getBuilderFunctionStructure called: ${functionName} from ${modulePath} (resolved: ${resolvedModulePath})`
        );
        
        if (!this.fileReader) {
            console.log(`[Parser] No file reader set, cannot parse builder function ${functionName}`);
            return null;
        }

        // Try to find the source file across all candidate roots.
        const potentialPaths = Array.from(
            new Set(
                candidateRoots.flatMap((root) => {
                    const paths = modulePathToFilePaths(resolvedModulePath, root);
                    // Also try: modulePath may be a package, and functionName may be a file within it
                    // e.g., modulePath="masfactory.x.y.workflows", functionName="build_agent_config_loop"
                    //       -> try "masfactory/x/y/workflows/build_agent_config_loop.py"
                    const parts = resolvedModulePath.split('.');
                    const packageDir = parts.join('/');
                    paths.push(`${root}/${packageDir}/${functionName}.py`);
                    return paths;
                })
            )
        );
        
        console.log(`[Parser] Looking for builder function ${functionName} in paths:`, potentialPaths);
        
        for (const filePath of potentialPaths) {
            console.log(`[Parser] Trying path: ${filePath}`);
            try {
                const code = await this.fileReader(filePath);
                if (code) {
                    console.log(`[Parser] Found file at ${filePath}, code length: ${code.length}`);
                    
                    // Use absolute file path as cache key (not module path) to avoid cross-workspace conflicts
                    const cacheKey = `${filePath}::${functionName}`;
                    
                    // Check cache with mtime validation
                    const cachedEntry = this.builderCache.get(cacheKey);
                    if (cachedEntry && cachedEntry.structure && cachedEntry.sourceFilePath) {
                        try {
                            const stats = fs.statSync(filePath);
                            if (cachedEntry.mtimeMs !== undefined && stats.mtimeMs === cachedEntry.mtimeMs) {
                                console.log(`[Parser] Returning cached builder ${functionName}: ${cachedEntry.structure.nodes.length} nodes (file: ${filePath})`);
                                return cachedEntry.structure;
                            }
                            console.log(`[Parser] Builder file changed for ${functionName}, re-parsing`);
                        } catch (error) {
                            console.log(`[Parser] Unable to stat file ${filePath}, re-parsing`);
                        }
                    }
                    
                    // Parse the builder function
                    const structure = parseBuilderFunction(code, functionName);
                    if (structure && structure.nodes.length > 0) {
                        // Set the source file path for navigation
                        structure.sourceFilePath = filePath;
                        console.log(`[Parser] Successfully parsed ${functionName}: ${structure.nodes.length} nodes, file: ${filePath}`);
                        let mtimeMs: number | undefined;
                        try {
                            const stats = fs.statSync(filePath);
                            mtimeMs = stats.mtimeMs;
                        } catch (error) {
                            console.log(`[Parser] Unable to read timestamp for ${filePath}, caching without mtime`, error);
                        }
                        this.builderCache.set(cacheKey, {
                            structure,
                            sourceFilePath: filePath,
                            mtimeMs
                        });
                        return structure;
                    } else {
                        console.log(`[Parser] Function ${functionName} not found in ${filePath}, trying next path...`);
                        // Continue to try other paths
                    }
                } else {
                    console.log(`[Parser] File not found or empty: ${filePath}`);
                }
            } catch (error) {
                console.log(`[Parser] Error reading ${filePath}:`, error);
            }
        }
        
        console.log(`[Parser] Could not find source file for builder function ${functionName}`);
        return null;
    }
    
    /**
     * Determine the specific graph type from class name
     */
    private determineGraphType(className: string, baseType: string): GraphType {
        const knownTypes: GraphType[] = [
            'HorizontalGraph', 'VerticalGraph', 'AdjacencyMatrixGraph', 
            'AdjacencyListGraph', 'HubGraph', 'MeshGraph', 'BrainstormingGraph',
            'RootGraph', 'Graph', 'Loop'
        ];
        
        for (const type of knownTypes) {
            if (className.includes(type)) {
                return type;
            }
        }
        
        if (baseType === BASE_TYPES.LOOP) return 'Loop';
        if (baseType === BASE_TYPES.ROOT_GRAPH) return 'RootGraph';
        if (baseType === BASE_TYPES.GRAPH) return 'Graph';
        
        return 'unknown';
    }

    private tryParseStandaloneTemplateGraph(
        rootNode: TSNode,
        code: string,
        preferredTemplate: string | null
    ): GraphData | null {
        const candidates: string[] = [];
        const exportedNames: Set<string> = new Set();

        const stripStringQuotes = (raw: string): string => raw.replace(/^f?["']|["']$/g, '');
        const parseAllList = (listNode: TSNode): void => {
            for (const item of listNode.namedChildren) {
                if (!item) continue;
                if (item.type !== 'string') continue;
                exportedNames.add(stripStringQuotes(getNodeText(item, code).trim()));
            }
        };

        for (const child of rootNode.children) {
            if (!child) continue;
            if (child.type !== 'expression_statement') continue;
            const first = child.namedChildren.filter((n): n is TSNode => !!n)[0];
            if (!first || (first.type !== 'assignment' && first.type !== 'typed_assignment')) continue;
            const left = first.childForFieldName('left');
            const right = first.childForFieldName('right');
            if (!left || !right) continue;

            const leftText = getNodeText(left, code).trim();
            if (leftText.toLowerCase() === '__all__' && right.type === 'list') {
                parseAllList(right);
                continue;
            }

            if (right.type !== 'call') continue;
            const fn = right.childForFieldName('function');
            if (!fn) continue;
            const fnText = getNodeText(fn, code).trim();
            if (fnText !== 'NodeTemplate' && !fnText.endsWith('.NodeTemplate')) continue;

            const parsed = tryParseNodeTemplateAssignment(leftText, right, code);
            if (!parsed) continue;
            if (parsed.baseKind !== 'Graph' && parsed.baseKind !== 'Loop') continue;
            candidates.push(parsed.templateName);
        }

        if (candidates.length === 0) return null;

        const lastSegment = (name: string): string => (name.includes('.') ? name.split('.').pop()! : name);

        const getTemplateStructure = (() => {
            const cache = new Map<string, ComponentStructure | null>();
            return (name: string): ComponentStructure | null => {
                const key = lastSegment(name);
                if (cache.has(key)) return cache.get(key) || null;
                const s = parseTemplateStructure(code, name);
                cache.set(key, s);
                return s;
            };
        })();

        const selectByPreferred = (): string | null => {
            const pref = typeof preferredTemplate === 'string' ? preferredTemplate.trim() : '';
            if (!pref) return null;
            const prefLast = lastSegment(pref);
            return candidates.find((c) => c === pref || lastSegment(c) === prefLast) || null;
        };

        const selectByExports = (): string | null => {
            if (exportedNames.size === 0) return null;
            return candidates.find((c) => exportedNames.has(c) || exportedNames.has(lastSegment(c))) || null;
        };

        const selectOutermost = (): string | null => {
            // Determine which NodeTemplate wraps others by looking for templates referenced as node types.
            const candidateKeys = candidates.map((c) => lastSegment(c));
            const candidateSet = new Set(candidateKeys);
            const incoming = new Map<string, number>();
            const outgoing = new Map<string, Set<string>>();
            for (const k of candidateKeys) {
                incoming.set(k, 0);
                outgoing.set(k, new Set());
            }

            for (const c of candidates) {
                const from = lastSegment(c);
                const s = getTemplateStructure(c);
                if (!s) continue;
                for (const t of Object.values(s.nodeTypes || {})) {
                    if (typeof t !== 'string' || !t) continue;
                    const to = lastSegment(t);
                    if (!candidateSet.has(to)) continue;
                    if (to === from) continue;
                    outgoing.get(from)!.add(to);
                }
            }

            const anyDeps = Array.from(outgoing.values()).some((s) => s.size > 0);
            if (!anyDeps) return null;

            for (const tos of outgoing.values()) {
                for (const to of tos) incoming.set(to, (incoming.get(to) || 0) + 1);
            }

            const roots = candidates.filter((c) => (incoming.get(lastSegment(c)) || 0) === 0);
            if (roots.length === 0) return null;
            if (roots.length === 1) return roots[0];

            const reachSize = (start: string): number => {
                const seen = new Set<string>();
                const stack = [start];
                while (stack.length > 0) {
                    const cur = stack.pop()!;
                    if (seen.has(cur)) continue;
                    seen.add(cur);
                    for (const nxt of outgoing.get(cur) || []) {
                        if (!seen.has(nxt)) stack.push(nxt);
                    }
                }
                return seen.size;
            };

            let best: string | null = null;
            let bestReach = -1;
            let bestIndex = -1;
            for (const c of roots) {
                const key = lastSegment(c);
                const reach = reachSize(key);
                const idx = candidates.indexOf(c);
                if (reach > bestReach || (reach === bestReach && idx > bestIndex)) {
                    best = c;
                    bestReach = reach;
                    bestIndex = idx;
                }
            }
            return best;
        };

        const selected =
            selectByPreferred() ||
            selectByExports() ||
            selectOutermost() ||
            candidates[candidates.length - 1];

        const structure = getTemplateStructure(selected);
        if (!structure) return null;

        const subgraphParents: { [child: string]: string } = {};
        const subgraphTypes: { [parent: string]: string } = {};
        for (const [parent, children] of Object.entries(structure.subgraphs || {})) {
            for (const child of children || []) {
                subgraphParents[child] = parent;
            }

            const isLoop =
                (children || []).some((c) => c.endsWith('_controller') || c.endsWith('_terminate')) ||
                (children || []).some((c) => structure.nodeTypes?.[c] === 'Controller');
            subgraphTypes[parent] = isLoop ? 'Loop' : 'Graph';
        }

        const graphType: GraphType =
            structure.nodes.includes('controller') && structure.nodes.includes('terminate')
                ? 'Loop'
                : 'Graph';

        const warnings: string[] = [];
        if (candidates.length > 1) {
            warnings.push(
                `Multiple NodeTemplate graphs found (${candidates
                    .map((c) => lastSegment(c))
                    .join(', ')}); previewing ${lastSegment(selected)}. Use the Template selector to switch.`
            );
        }

        // Keep warning semantics consistent with the main parser: if the file contains dynamic build logic,
        // the preview may be inaccurate. (Standalone templates are usually static, but keep best-effort.)
        const loopControls = this.extractLoopControls(rootNode, code);
        const conditionControls = this.extractConditionVariables(rootNode, code);
        if (conditionControls.length > 0 || Object.keys(loopControls).length > 0) {
            warnings.push(
                'This file contains dynamic graph construction (Python if/for). Dynamically-constructed graph components may fail to render, or the preview may be inaccurate.'
            );
        }

        return {
            nodes: structure.nodes,
            nodeTypes: structure.nodeTypes,
            edges: structure.edges,
            subgraphs: structure.subgraphs,
            subgraphTypes,
            subgraphParents,
            nodeLineNumbers: structure.nodeLineNumbers,
            nodePullKeys: structure.nodePullKeys,
            nodePushKeys: structure.nodePushKeys,
            nodeAttributes: structure.nodeAttributes,
            graphType,
            controlFlow: { forLoops: [], ifConditions: [], dependencies: [] },
            loopControls,
            warnings,
            pendingBuilderCalls: {},
            templateCandidates: candidates.slice(),
            selectedTemplate: selected
        };
    }

    // ==================== Compatibility Methods ====================

    getConditionVariables(code: string): string[] {
        const parser = this.getParser();
        const tree = parser ? parser.parse(code) : null;
        if (!tree) return [];
        const rootNode = tree.rootNode;

        const { buildMethod } = findBuildMethodAndBaseType(rootNode);
        if (buildMethod) {
            const body = buildMethod.childForFieldName('body');
            return this.extractConditionVariables(body ?? buildMethod, code);
        }

        const rootGraphVar = findRootGraphVariable(rootNode, code);
        if (rootGraphVar) {
            return this.extractConditionVariables(rootNode, code);
        }

        const funcWithGraph = findFunctionWithRootGraph(rootNode, code);
        if (funcWithGraph) {
            return this.extractConditionVariables(funcWithGraph.funcBody, code);
        }

        return this.extractConditionVariables(rootNode, code);
    }

    parseWithConditions(
        code: string,
        conditionValues: Map<string, boolean>,
        loopIterations?: Map<string, number>,
        sourceFilePath?: string,
        opts?: { templateName?: string | null }
    ): GraphData {
        const ctx: ControlFlowContext = {
            loopIterations: Object.fromEntries(loopIterations ?? new Map<string, number>()),
            conditionValues: Object.fromEntries(conditionValues)
        };
        return this.parse(code, ctx, sourceFilePath, opts);
    }

    flattenSubgraphs(data: GraphData): GraphData {
        return data;
    }

    getMaxLoopIterations(): number {
        return 8;
    }

    // ==================== Private Methods ====================

    /**
     * Initialize result containers based on base type
     */
    private initializeResult(baseType: string, className: string) {
        const nodes: string[] = [];
        const nodeTypes: { [key: string]: string } = {};
        
        if (baseType === BASE_TYPES.LOOP) {
            nodes.push('controller', 'terminate');
            nodeTypes['controller'] = 'Controller';
            nodeTypes['terminate'] = 'TerminateNode';
            console.log(`[Parser] Detected Loop class: ${className}, adding controller/terminate nodes`);
        } else {
            nodes.push('entry', 'exit');
            console.log(`[Parser] Detected ${baseType || 'workflow'} class: ${className || 'module-level'}, adding entry/exit nodes`);
        }

        return {
            nodes,
            nodeTypes,
            edges: [] as GraphEdge[],
            subgraphs: {} as { [parent: string]: string[] },
            subgraphTypes: {} as { [parent: string]: string },
            subgraphParents: {} as { [child: string]: string },
            nodeLineNumbers: {} as { [key: string]: number },
            variableToNodeName: {} as { [variable: string]: string },
            nodePullKeys: {} as { [key: string]: { [key: string]: string } | null | 'empty' },
            nodePushKeys: {} as { [key: string]: { [key: string]: string } | null | 'empty' },
            nodeAttributes: {} as { [key: string]: { [key: string]: any } | null }
        };
    }

    private extractConditionVariables(scopeNode: TSNode, code: string): string[] {
        const conditions: string[] = [];

        const containsGraphMutation = (node: TSNode): boolean => {
            const stack: TSNode[] = [node];
            while (stack.length > 0) {
                const current = stack.pop()!;
                if (current.type === 'call') {
                    const funcNode = current.childForFieldName('function');
                    if (funcNode) {
                        const fnText = getNodeText(funcNode, code).trim();
                        const isCreateNode =
                            fnText.endsWith('.create_node') ||
                            fnText === 'create_node';
                        const isCreateEdge =
                            isEdgeCreationMethod(fnText) ||
                            fnText === 'create_edge' ||
                            fnText === 'edge_from_entry' ||
                            fnText === 'edge_to_exit' ||
                            fnText === 'edge_from_controller' ||
                            fnText === 'edge_to_controller' ||
                            fnText === 'edge_to_terminate_node';
                        if (isCreateNode || isCreateEdge) {
                            return true;
                        }
                    }
                }
                for (const child of current.children) {
                    if (!child) continue;
                    stack.push(child);
                }
            }
            return false;
        };

        // Simple AST walk for if_statement nodes within the scope.
        // (We intentionally keep this lightweight; the parser itself does the heavy lifting.)
        const stack: TSNode[] = [scopeNode];
        while (stack.length > 0) {
            const node = stack.pop()!;
            if (node.type === 'if_statement') {
                const consequenceNode = node.childForFieldName('consequence');
                const alternativeNode = node.childForFieldName('alternative');

                // Only surface conditions that can affect the graph structure (create_node/edge calls).
                const relevant =
                    (consequenceNode && containsGraphMutation(consequenceNode)) ||
                    (alternativeNode && containsGraphMutation(alternativeNode));
                if (relevant) {
                    const lineNumber = node.startPosition.row + 1;
                    const condNode = node.childForFieldName('condition');
                    const condTextRaw = condNode ? getNodeText(condNode, code).trim() : 'condition';
                    const condText = condTextRaw.replace(/\s+/g, ' ');
                    conditions.push(`if_${lineNumber}_${condText}`);
                }
            }
            for (const child of node.children) {
                if (!child) continue;
                stack.push(child);
            }
        }

        return conditions;
    }

    private extractLoopControls(
        scopeNode: TSNode,
        code: string
    ): { [loopId: string]: { label: string; variable: string; defaultIterations: number } } {
        const controls: { [loopId: string]: { label: string; variable: string; defaultIterations: number } } = {};
        const maxIterations = this.getMaxLoopIterations();

        const containsGraphMutation = (node: TSNode): boolean => {
            const stack: TSNode[] = [node];
            while (stack.length > 0) {
                const current = stack.pop()!;
                if (current.type === 'call') {
                    const funcNode = current.childForFieldName('function');
                    if (funcNode) {
                        const fnText = getNodeText(funcNode, code).trim();
                        const isCreateNode =
                            fnText.endsWith('.create_node') ||
                            fnText === 'create_node';
                        const isCreateEdge =
                            isEdgeCreationMethod(fnText) ||
                            fnText === 'create_edge' ||
                            fnText === 'edge_from_entry' ||
                            fnText === 'edge_to_exit' ||
                            fnText === 'edge_from_controller' ||
                            fnText === 'edge_to_controller' ||
                            fnText === 'edge_to_terminate_node';
                        if (isCreateNode || isCreateEdge) {
                            return true;
                        }
                    }
                }
                for (const child of current.children) {
                    if (!child) continue;
                    stack.push(child);
                }
            }
            return false;
        };

        const stack: TSNode[] = [scopeNode];
        while (stack.length > 0) {
            const node = stack.pop()!;
            if (node.type === 'for_statement') {
                const bodyNode = node.childForFieldName('body');
                if (!bodyNode || !containsGraphMutation(bodyNode)) {
                    // Only surface loops that affect graph structure in the UI.
                    // The main parser still executes them for best-effort expansion.
                    for (const child of node.children) {
                        if (!child) continue;
                        stack.push(child);
                    }
                    continue;
                }

                const lineNumber = node.startPosition.row + 1;
                const leftNode = node.childForFieldName('left');
                const rightNode = node.childForFieldName('right');
                const leftText = leftNode ? getNodeText(leftNode, code).trim() : 'i';
                const rightText = rightNode ? getNodeText(rightNode, code).trim() : 'iterable';

                const loopId = `for_${lineNumber}_${leftText}`;
                const defaultIterations = this.inferDefaultLoopIterations(node, code, maxIterations);
                controls[loopId] = {
                    label: `for @L${lineNumber}: ${leftText} in ${rightText}`,
                    variable: leftText,
                    defaultIterations
                };
            }
            for (const child of node.children) {
                if (!child) continue;
                stack.push(child);
            }
        }

        return controls;
    }

    private inferDefaultLoopIterations(forNode: TSNode, code: string, maxIterations: number): number {
        // Default when we cannot infer.
        let iterations = 3;

        const rightNode = forNode.childForFieldName('right');
        if (!rightNode || rightNode.type !== 'call') {
            return Math.max(1, Math.min(maxIterations, iterations));
        }

        const funcNode = rightNode.childForFieldName('function');
        const funcText = funcNode ? getNodeText(funcNode, code).trim() : '';
        if (funcText !== 'range') {
            return Math.max(1, Math.min(maxIterations, iterations));
        }

        const argsNode = rightNode.childForFieldName('arguments');
        if (!argsNode) {
            return Math.max(1, Math.min(maxIterations, iterations));
        }

        const args = argsNode.namedChildren.filter(
            (a): a is TSNode => !!a && a.type !== 'comment' && a.type !== 'keyword_argument'
        );
        if (args.length === 0) {
            return Math.max(1, Math.min(maxIterations, iterations));
        }

        const parseIntNode = (n: TSNode): number | null => {
            if (n.type !== 'integer') return null;
            const raw = getNodeText(n, code).replace(/_/g, '');
            const value = Number.parseInt(raw, 10);
            return Number.isFinite(value) ? value : null;
        };

        if (args.length === 1) {
            const end = parseIntNode(args[0]);
            if (end !== null) iterations = end;
        } else {
            // range(start, end, step?) -> approximate as end - start
            const start = parseIntNode(args[0]);
            const end = parseIntNode(args[1]);
            if (start !== null && end !== null) {
                iterations = Math.max(0, end - start);
            } else if (end !== null) {
                iterations = end;
            }
        }

        return Math.max(1, Math.min(maxIterations, iterations));
    }

    /**
     * Parse non-class code (module-level or function-level)
     */
    private parseNonClassCode(
        rootNode: TSNode,
        code: string,
        nodeCtx: NodeParseContext,
        edgeCtx: EdgeParseContext,
        subgraphs: { [parent: string]: string[] },
        controlFlowCtx?: ControlFlowContext
    ): void {
        // First try module-level code
        let rootGraphVariable = findRootGraphVariable(rootNode, code);
        
        if (rootGraphVariable) {
            console.log('[Parser] Found RootGraph at module level');
            console.log(`[Parser] RootGraph variable: ${rootGraphVariable}`);
            parseModuleLevel(rootNode, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx);
        } else {
            // Try to find RootGraph inside a function (e.g., main())
            const funcWithGraph = findFunctionWithRootGraph(rootNode, code);
            if (funcWithGraph) {
                console.log(`[Parser] Found RootGraph inside function: ${funcWithGraph.funcName}`);
                console.log(`[Parser] RootGraph variable: ${funcWithGraph.rootGraphVar}`);
                parseFunctionBody(funcWithGraph.funcBody, code, nodeCtx, edgeCtx, subgraphs, funcWithGraph.rootGraphVar, controlFlowCtx);
            } else {
                console.log('[Parser] No RootGraph found in module or functions');
            }
        }
    }

    /**
     * Detect builder function calls in code and record them for async expansion
     */
    private detectBuilderFunctionCalls(
        code: string,
        variableToNodeName: { [variable: string]: string }
    ): void {
        const builderCalls = extractBuilderFunctionCalls(code, this.imports);
        
        for (const [varName, info] of builderCalls) {
            // varName is already normalized (e.g., "_edge_config_loop" from "self._edge_config_loop")
            // Try to resolve to actual node name via variableToNodeName
            
            // The original variable was self.xxx or self._xxx, so try both forms
            const fullVar = `self.${varName}`;
            const nodeName = variableToNodeName[fullVar] || variableToNodeName[varName];
            
            if (!nodeName) {
                console.log(`[Parser] Skipping builder call ${info.functionName}: variable '${varName}' not found in variableToNodeName`);
                continue;
            }
            
            this.pendingBuilderCalls.set(nodeName, {
                functionName: info.functionName,
                modulePath: info.modulePath
            });
            
            console.log(`[Parser] Recorded builder call: ${info.functionName} for node ${nodeName}`);
        }
    }
    
    /**
     * Add build_func parameters to pending builder calls
     * This handles the new build_func=partial(...), build_func=lambda..., etc. pattern
     */
    private addBuildFuncToPendingCalls(
        nodeBuildFuncs: { [nodeName: string]: { functionName: string; modulePath: string; type: string } }
    ): void {
        for (const [nodeName, info] of Object.entries(nodeBuildFuncs)) {
            // Skip if already registered by detectBuilderFunctionCalls
            if (this.pendingBuilderCalls.has(nodeName)) {
                console.log(`[Parser] Node ${nodeName} already has builder call, skipping build_func`);
                continue;
            }
            
            // Resolve module path from imports if not set
            let modulePath = info.modulePath;
            if (!modulePath && this.imports.has(info.functionName)) {
                const importInfo = this.imports.get(info.functionName);
                modulePath = importInfo?.modulePath || '';
            }
            
            this.pendingBuilderCalls.set(nodeName, {
                functionName: info.functionName,
                modulePath: modulePath
            });
            
            console.log(`[Parser] Recorded build_func: ${info.functionName} (${info.type}) for node ${nodeName}, module: ${modulePath}`);
        }
    }
    
    /**
     * Log parse results
     */
    private logParseResult(nodes: string[], edges: GraphEdge[]): void {
        console.log(`[Parser] Parse complete: ${nodes.length} nodes, ${edges.length} edges`);
        console.log(`[Parser] Nodes: ${JSON.stringify(nodes)}`);
        console.log(`[Parser] Edges: ${JSON.stringify(edges.map(e => `${e.from}->${e.to}`))}`);
    }
}
