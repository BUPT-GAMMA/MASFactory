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
import { BASE_TYPES, collectClassBases, getNodeText, parseDictArgument, parseKeysArgument } from './astUtils';
import { NodeParseContext } from './nodeParser';
import { EdgeParseContext, isEdgeCreationMethod } from './edgeParser';
import { mergeParserFeatures, type ParserFeatures } from './features';
import { findBuildMethodAndBaseType, parseBuildMethod, ControlFlowContext } from './buildMethodParser';
import { findRootGraphVariable, findFunctionWithRootGraph } from './rootGraphFinder';
import { parseModuleLevel, parseFunctionBody } from './moduleLevelParser';
import { parseImports, modulePathToFilePaths, isCompositeComponent, isBaseFrameworkType, ImportInfo } from './importResolver';
import { parseComponentStructure, parseTemplateStructure, buildTemplateStructure, ComponentStructure } from './componentParser';
import { ParsedNodeTemplate, tryParseNodeTemplateAssignment } from './templateParser';
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

interface ParsedPythonFile {
    filePath: string;
    code: string;
    rootNode: TSNode;
    imports: Map<string, ImportInfo>;
    mtimeMs?: number;
}

interface TemplateResolverEnv {
    preferredName?: string;
    code: string;
    rootNode: TSNode;
    imports: Map<string, ImportInfo>;
    sourceFilePath?: string;
    templateBindings: { [name: string]: ParsedNodeTemplate };
    exprBindings: { [name: string]: TSNode };
    depth: number;
    visited: Set<string>;
}

interface StandaloneTemplateScopeEnv {
    code: string;
    rootNode: TSNode;
    imports: Map<string, ImportInfo>;
    sourceFilePath?: string;
    templateBindings: { [name: string]: ParsedNodeTemplate };
    exprBindings: { [name: string]: TSNode };
}

interface StandaloneRenderableCandidate {
    id: string;
    kind: 'template' | 'assignment';
    graphKind?: 'Graph' | 'Loop' | 'RootGraph';
    template?: ParsedNodeTemplate;
    lineNumber?: number;
    sourceRootNode?: TSNode;
    parseScopeNode?: TSNode;
    scopeKind?: 'module' | 'function';
    sourceCode?: string;
    sourceFilePath?: string;
    sourceImports?: Map<string, ImportInfo>;
    sourceGraphVariable?: string;
}

interface GraphScopeMatch {
    bodyNode: TSNode;
    graphKind: 'Graph' | 'Loop' | 'RootGraph';
    rootGraphVariable: string;
    lineNumber: number;
    methodName?: string;
}

interface ResolvedCallableDefinition {
    callableDef: TSNode;
    callableKind: 'function' | 'method';
    callableName: string;
    code: string;
    rootNode: TSNode;
    imports: Map<string, ImportInfo>;
    filePath?: string;
    ownerName?: string;
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
    private parsedFileCache: Map<string, ParsedPythonFile> = new Map();
    private imports: Map<string, ImportInfo> = new Map();
    private lastSourceFilePath: string | undefined;
    // Track builder function calls found during parsing (loopName -> builderInfo)
    private pendingBuilderCalls: Map<string, { functionName: string; modulePath: string }> = new Map();
    private features: ParserFeatures = mergeParserFeatures(null);

    constructor() {}

    private getParser(): TreeSitterParser | null {
        if (this.parser) {return this.parser;}
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

    /**
     * Resolve a Python symbol path such as
     * `applications.chatdev.components.phase.phase.DemandAnalysisPhase`.
     *
     * AML implementation bindings do not live inside Python import statements, so they
     * bypass the normal import map and enter the same external component parser here.
     */
    async getComponentStructureByPythonPath(
        pythonPath: string,
        ctx?: ResolutionContext
    ): Promise<ComponentStructure | null> {
        const value = String(pythonPath || '').trim().replace(/^python:/, '');
        let modulePath = '';
        let className = '';
        if (value.includes(':')) {
            const parts = value.split(':');
            modulePath = parts[0] || '';
            className = parts.slice(1).join(':') || '';
        } else {
            const lastDot = value.lastIndexOf('.');
            if (lastDot > 0 && lastDot < value.length - 1) {
                modulePath = value.slice(0, lastDot);
                className = value.slice(lastDot + 1);
            }
        }
        if (!modulePath || !className) {
            return null;
        }
        const nodeType = `${modulePath}.${className}`;
        return await this.parseExternalComponent(value, {
            ...ctx,
            imports: new Map<string, ImportInfo>([
                [
                    value,
                    {
                        modulePath,
                        className
                    }
                ],
                [
                    nodeType,
                    {
                        modulePath,
                        className
                    }
                ]
            ])
        });
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
            if (visited.has(visitKey)) {break;}
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
                    if (!code) {continue;}
                    const parser = this.getParser();
                    const tree = parser ? parser.parse(code) : null;
                    const rootNode = tree?.rootNode || null;
                    const fileImports = rootNode ? parseImports(rootNode, code) : new Map<string, ImportInfo>();

                    console.log(`[Parser] Found component candidate for ${nodeType} at ${filePath}`);
                    const structure = parseComponentStructure(code, currentClassName);
                    if (structure) {
                        structure.sourceFilePath = filePath;
                        structure.sourceImports = fileImports;
                        this.componentCache.set(cacheKey, structure);

                        // Inheritance fallback:
                        // Some components (e.g., HumanTesterGraph) don't implement build(), and rely on a base class build().
                        // If parsing __init__ yields no meaningful internal structure, try base classes.
                        const looksEmpty = structure.nodes.length <= 2 && structure.edges.length === 0;
                        if ((structure.parsedMethodName === '__init__' || looksEmpty) && structure.baseClasses && structure.baseClasses.length > 0) {
                            try {
                                const localVisited = new Set<string>();

                                const resolveBaseInSameFile = (baseClassText: string): ComponentStructure | null => {
                                    const normalized = baseClassText.includes('.')
                                        ? baseClassText.split('.').pop()!
                                        : baseClassText;
                                    if (!normalized || isBaseFrameworkType(normalized)) {return null;}
                                    if (localVisited.has(normalized)) {return null;}
                                    localVisited.add(normalized);

                                    const local = parseComponentStructure(code, normalized);
                                    if (local) {
                                        local.sourceFilePath = filePath;
                                        local.sourceImports = fileImports;
                                        const empty = local.nodes.length <= 2 && local.edges.length === 0;
                                        if (!empty) {return local;}
                                        if (local.baseClasses && local.baseClasses.length > 0) {
                                            for (const bc of local.baseClasses) {
                                                const nested = resolveBaseInSameFile(bc);
                                                if (nested && nested.nodes.length > 2) {return nested;}
                                            }
                                        }
                                    }

                                    const tmpl = parseTemplateStructure(code, normalized);
                                    if (tmpl) {
                                        tmpl.sourceFilePath = filePath;
                                        tmpl.sourceImports = fileImports;
                                        const empty = tmpl.nodes.length <= 2 && tmpl.edges.length === 0;
                                        if (!empty) {return tmpl;}
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

                        if (looksEmpty && rootNode) {
                            const wrappedStructure = this.tryParseWrappedRenderableStructure(
                                rootNode,
                                code,
                                currentClassName,
                                fileImports,
                                filePath
                            );
                            if (wrappedStructure && wrappedStructure.nodes.length > 0) {
                                wrappedStructure.sourceImports = fileImports;
                                this.componentCache.set(cacheKey, wrappedStructure);
                                return wrappedStructure;
                            }
                        }

                        return structure;
                    }

                    // Declarative NodeTemplate-based components:
                    // e.g., ProfileGenerationGraph = NodeTemplate(Graph, nodes=[...], edges=[...])
                    const templateStructure = parseTemplateStructure(code, currentClassName);
                    if (templateStructure) {
                        templateStructure.sourceFilePath = filePath;
                        templateStructure.sourceImports = fileImports;
                        this.componentCache.set(cacheKey, templateStructure);
                        return templateStructure;
                    }

                    if (rootNode) {
                        const wrappedStructure = this.tryParseWrappedRenderableStructure(
                            rootNode,
                            code,
                            currentClassName,
                            fileImports,
                            filePath
                        );
                        if (wrappedStructure) {
                            wrappedStructure.sourceImports = fileImports;
                            this.componentCache.set(cacheKey, wrappedStructure);
                            return wrappedStructure;
                        }
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
        if (!modulePathText.startsWith('.')) {return modulePathText;}
        if (!sourceFilePath) {return modulePathText;}

        try {
            const root = effectiveRoot || this.workspaceRoot;
            if (!root) {return modulePathText;}
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
        if (!targetModuleText.startsWith('.')) {return targetModuleText;}

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
            if (first) {return first;}
        }
        if (sourceFilePath) {
            const normalized = sourceFilePath.replace(/\\/g, '/');
            const parts = normalized.split('/').filter(Boolean);
            const srcIndex = parts.lastIndexOf('src');
            if (srcIndex !== -1 && parts[srcIndex + 1]) {
                return parts[srcIndex + 1];
            }
            if (parts.includes('masfactory')) {return 'masfactory';}
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
            if (parent === dir) {break;}
            dir = parent;
        }

        // Fallback: if no repo marker is found, still allow locating a package root.
        dir = path.dirname(sourceFilePath);
        for (let i = 0; i < 25; i++) {
            if (hasPkgDir(dir)) {return dir;}
            const parent = path.dirname(dir);
            if (parent === dir) {break;}
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
            if (workspace) {roots.push(workspace);}
        } else {
            if (workspace) {roots.push(workspace);}
            if (derived) {roots.push(derived);}
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
            if (!tree) {return null;}
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
            if (!root) {return null;}

            const fromModulePath = this.filePathToModulePath(fromFilePath, root);

            // Match either by key (no alias) or by original className (aliased import).
            for (const [key, info] of exports.entries()) {
                if (info.isModule) {continue;}
                if (key !== symbolName && info.className !== symbolName) {continue;}

                const resolvedModule = this.resolveRelativeModulePath(fromFilePath, fromModulePath, info.modulePath);
                return { modulePath: resolvedModule, className: info.className };
            }
        } catch (e) {
            console.log('[Parser] Re-export resolution failed:', e);
        }
        return null;
    }

    private getCallArgs(callNode: TSNode): TSNode[] {
        const argsNode = callNode.childForFieldName('arguments');
        if (!argsNode) {return [];}
        return argsNode.namedChildren.filter((n): n is TSNode => !!n && n.type !== 'comment');
    }

    private getPositionalArgs(args: TSNode[]): TSNode[] {
        return args.filter((arg) => arg.type !== 'keyword_argument' && arg.type !== 'comment');
    }

    private getKeywordArgMap(args: TSNode[], code: string): Map<string, TSNode> {
        const map = new Map<string, TSNode>();
        for (const arg of args) {
            if (arg.type !== 'keyword_argument') {continue;}
            const nameNode = arg.childForFieldName('name');
            const valueNode = arg.childForFieldName('value');
            if (!nameNode || !valueNode) {continue;}
            map.set(getNodeText(nameNode, code).trim(), valueNode);
        }
        return map;
    }

    private normalizeLookupKeys(raw: string): string[] {
        const out: string[] = [];
        const push = (value: string) => {
            const next = String(value || '').trim();
            if (!next || out.includes(next)) {return;}
            out.push(next);
        };
        const trimmed = String(raw || '').trim();
        push(trimmed);
        if (trimmed.startsWith('self._')) {push(trimmed.replace('self._', ''));}
        if (trimmed.startsWith('self.')) {push(trimmed.replace('self.', ''));}
        const last = trimmed.split('.').pop() || '';
        push(last);
        if (last.startsWith('_')) {push(last.slice(1));}
        return out;
    }

    private getParsedPythonFile(filePath: string): ParsedPythonFile | null {
        try {
            const stats = fs.statSync(filePath);
            const cached = this.parsedFileCache.get(filePath);
            if (cached && cached.mtimeMs !== undefined && cached.mtimeMs === stats.mtimeMs) {
                return cached;
            }

            const parser = this.getParser();
            if (!parser) {return null;}
            const code = fs.readFileSync(filePath, 'utf-8');
            const tree = parser.parse(code);
            if (!tree) {return null;}

            const parsed: ParsedPythonFile = {
                filePath,
                code,
                rootNode: tree.rootNode,
                imports: parseImports(tree.rootNode, code),
                mtimeMs: stats.mtimeMs
            };
            this.parsedFileCache.set(filePath, parsed);
            return parsed;
        } catch {
            return null;
        }
    }

    private findTopLevelFunctionInRoot(rootNode: TSNode, code: string, functionName: string): TSNode | null {
        const target = String(functionName || '').trim();
        if (!target) {return null;}
        for (const child of rootNode.children) {
            if (!child) {continue;}
            const fn =
                child.type === 'decorated_definition'
                    ? child.namedChildren.find((n): n is TSNode => !!n && n.type === 'function_definition') || null
                    : child.type === 'function_definition'
                        ? child
                        : null;
            if (!fn) {continue;}
            const nameNode = fn.childForFieldName('name');
            if (nameNode && getNodeText(nameNode, code).trim() === target) {return fn;}
        }
        return null;
    }

    private findTopLevelAssignmentRight(rootNode: TSNode, code: string, names: string[]): TSNode | null {
        const wanted = new Set(names.map((n) => String(n || '').trim()).filter(Boolean));
        if (wanted.size === 0) {return null;}
        for (const child of rootNode.children) {
            if (!child || child.type !== 'expression_statement') {continue;}
            const first = child.namedChildren[0];
            if (!first || (first.type !== 'assignment' && first.type !== 'typed_assignment')) {continue;}
            const left = first.childForFieldName('left');
            const right = first.childForFieldName('right');
            if (!left || !right) {continue;}
            if (wanted.has(getNodeText(left, code).trim())) {return right;}
        }
        return null;
    }

    private unwrapNamedDefinition(
        node: TSNode | null | undefined,
        type: 'function_definition' | 'class_definition'
    ): TSNode | null {
        if (!node) {return null;}
        if (node.type === type) {return node;}
        if (node.type !== 'decorated_definition') {return null;}
        return node.namedChildren.find((child): child is TSNode => !!child && child.type === type) || null;
    }

    private getDefinitionName(node: TSNode | null | undefined, code: string): string {
        const nameNode = node?.childForFieldName('name');
        return nameNode ? getNodeText(nameNode, code).trim() : '';
    }

    private findTopLevelClassInRoot(rootNode: TSNode, code: string, className: string): TSNode | null {
        const target = String(className || '').trim();
        if (!target) {return null;}
        for (const child of rootNode.children) {
            const classDef = this.unwrapNamedDefinition(child, 'class_definition');
            if (!classDef) {continue;}
            if (this.getDefinitionName(classDef, code) === target) {return classDef;}
        }
        return null;
    }

    private findMethodInClassNode(classNode: TSNode, code: string, methodName: string): TSNode | null {
        const target = String(methodName || '').trim();
        if (!target) {return null;}
        const body = classNode.childForFieldName('body');
        if (!body) {return null;}
        for (const child of body.namedChildren) {
            const methodDef = this.unwrapNamedDefinition(child, 'function_definition');
            if (!methodDef) {continue;}
            if (this.getDefinitionName(methodDef, code) === target) {return methodDef;}
        }
        return null;
    }

    private getGraphKindFromFunctionText(functionText: string): 'Graph' | 'Loop' | 'RootGraph' | null {
        const normalized = String(functionText || '').trim();
        if (!normalized) {return null;}
        const last = normalized.includes('.') ? normalized.split('.').pop()! : normalized;
        if (last === 'RootGraph') {return 'RootGraph';}
        if (last === 'Loop') {return 'Loop';}
        if (last === 'Graph') {return 'Graph';}
        return null;
    }

    private getGraphKindRank(kind: 'Graph' | 'Loop' | 'RootGraph'): number {
        if (kind === 'RootGraph') {return 3;}
        if (kind === 'Loop') {return 2;}
        return 1;
    }

    private findGraphAssignmentInScope(scopeNode: TSNode, code: string): GraphScopeMatch | null {
        const inspect = (node: TSNode): (GraphScopeMatch & { rank: number }) | null => {
            let best: (GraphScopeMatch & { rank: number }) | null = null;

            for (const child of node.children) {
                if (!child) {continue;}

                if (
                    this.unwrapNamedDefinition(child, 'function_definition') ||
                    this.unwrapNamedDefinition(child, 'class_definition')
                ) {
                    continue;
                }

                if (child.type === 'expression_statement') {
                    const first = child.namedChildren[0];
                    if (first && (first.type === 'assignment' || first.type === 'typed_assignment')) {
                        const left = first.childForFieldName('left');
                        const right = first.childForFieldName('right');
                        if (!left || !right || right.type !== 'call') {continue;}

                        const functionNode = right.childForFieldName('function');
                        const graphKind = functionNode
                            ? this.getGraphKindFromFunctionText(getNodeText(functionNode, code).trim())
                            : null;
                        if (!graphKind) {continue;}

                        const rootGraphVariable = getNodeText(left, code).trim();
                        if (!rootGraphVariable) {continue;}

                        const candidate: GraphScopeMatch & { rank: number } = {
                            bodyNode: node,
                            graphKind,
                            rootGraphVariable,
                            lineNumber: right.startPosition.row + 1,
                            rank: this.getGraphKindRank(graphKind)
                        };
                        if (!best || candidate.rank > best.rank) {
                            best = candidate;
                        }
                        if (candidate.rank >= 3) {
                            return candidate;
                        }
                    }
                }

                if (
                    child.type === 'if_statement' ||
                    child.type === 'for_statement' ||
                    child.type === 'while_statement' ||
                    child.type === 'with_statement'
                ) {
                    const body =
                        child.childForFieldName('body') || child.childForFieldName('consequence');
                    const alt = child.childForFieldName('alternative');
                    const fromBody = body ? inspect(body) : null;
                    if (fromBody && (!best || fromBody.rank > best.rank)) {best = fromBody;}
                    if (best?.rank === 3) {return best;}
                    const fromAlt = alt ? inspect(alt) : null;
                    if (fromAlt && (!best || fromAlt.rank > best.rank)) {best = fromAlt;}
                    if (best?.rank === 3) {return best;}
                    continue;
                }

                if (child.type === 'try_statement') {
                    const fromTry = child.childForFieldName('body')
                        ? inspect(child.childForFieldName('body')!)
                        : null;
                    if (fromTry && (!best || fromTry.rank > best.rank)) {best = fromTry;}
                    if (best?.rank === 3) {return best;}
                    for (const clause of child.namedChildren) {
                        if (!clause) {continue;}
                        if (
                            clause.type !== 'except_clause' &&
                            clause.type !== 'else_clause' &&
                            clause.type !== 'finally_clause'
                        ) {
                            continue;
                        }
                        const clauseBody =
                            clause.childForFieldName('body') ||
                            clause.namedChildren.find((n): n is TSNode => !!n && n.type === 'block') ||
                            null;
                        const fromClause = clauseBody ? inspect(clauseBody) : null;
                        if (fromClause && (!best || fromClause.rank > best.rank)) {best = fromClause;}
                        if (best?.rank === 3) {return best;}
                    }
                    continue;
                }

                if (child.type === 'block') {
                    const fromBlock = inspect(child);
                    if (fromBlock && (!best || fromBlock.rank > best.rank)) {best = fromBlock;}
                    if (best?.rank === 3) {return best;}
                }
            }

            return best;
        };

        const best = inspect(scopeNode);
        if (!best) {return null;}
        return {
            bodyNode: best.bodyNode,
            graphKind: best.graphKind,
            rootGraphVariable: best.rootGraphVariable,
            lineNumber: best.lineNumber
        };
    }

    private getGraphMethodPreference(methodName: string): number {
        const normalized = String(methodName || '').trim().toLowerCase();
        if (!normalized) {return 0;}
        if (normalized === 'build') {return 100;}
        if (normalized === '__init__') {return 90;}
        if (normalized === 'build_graph') {return 80;}
        if (normalized === 'create_graph') {return 75;}
        if (normalized === 'graph') {return 70;}
        if (normalized.includes('graph')) {return 60;}
        if (normalized.startsWith('build')) {return 50;}
        if (normalized.startsWith('create')) {return 40;}
        return 0;
    }

    private findFunctionGraphScope(rootNode: TSNode, code: string, functionName: string): GraphScopeMatch | null {
        const functionDef = this.findTopLevelFunctionInRoot(rootNode, code, functionName);
        if (!functionDef) {return null;}
        const bodyNode = functionDef.childForFieldName('body');
        if (!bodyNode) {return null;}
        return this.findGraphAssignmentInScope(bodyNode, code);
    }

    private findClassGraphScope(
        rootNode: TSNode,
        code: string,
        className: string,
        preferredMethodName?: string
    ): GraphScopeMatch | null {
        const classDef = this.findTopLevelClassInRoot(rootNode, code, className);
        if (!classDef) {return null;}
        const classBody = classDef.childForFieldName('body');
        if (!classBody) {return null;}

        let best: (GraphScopeMatch & { methodPreference: number; rank: number }) | null = null;

        for (const child of classBody.namedChildren) {
            const methodDef = this.unwrapNamedDefinition(child, 'function_definition');
            if (!methodDef) {continue;}
            const methodName = this.getDefinitionName(methodDef, code);
            if (preferredMethodName && methodName !== preferredMethodName) {continue;}
            const bodyNode = methodDef.childForFieldName('body');
            if (!bodyNode) {continue;}
            const match = this.findGraphAssignmentInScope(bodyNode, code);
            if (!match) {continue;}

            const candidate: GraphScopeMatch & { methodPreference: number; rank: number } = {
                ...match,
                bodyNode,
                methodName,
                rank: this.getGraphKindRank(match.graphKind),
                methodPreference: preferredMethodName ? 1000 : this.getGraphMethodPreference(methodName)
            };

            if (
                !best ||
                candidate.rank > best.rank ||
                (candidate.rank === best.rank && candidate.methodPreference > best.methodPreference) ||
                (
                    candidate.rank === best.rank &&
                    candidate.methodPreference === best.methodPreference &&
                    candidate.lineNumber < best.lineNumber
                )
            ) {
                best = candidate;
            }
        }

        if (!best) {return null;}
        return {
            bodyNode: best.bodyNode,
            graphKind: best.graphKind,
            rootGraphVariable: best.rootGraphVariable,
            lineNumber: best.lineNumber,
            methodName: best.methodName
        };
    }

    private createRenderableCandidateFromGraphScope(
        id: string,
        match: GraphScopeMatch,
        sourceRootNode: TSNode,
        code: string,
        imports: Map<string, ImportInfo>,
        sourceFilePath?: string
    ): StandaloneRenderableCandidate {
        return {
            id,
            kind: 'assignment',
            graphKind: match.graphKind,
            lineNumber: match.lineNumber,
            sourceRootNode,
            parseScopeNode: match.bodyNode,
            scopeKind: 'function',
            sourceCode: code,
            sourceFilePath,
            sourceImports: imports,
            sourceGraphVariable: match.rootGraphVariable
        };
    }

    private buildComponentStructureFromGraphData(
        graphData: GraphData,
        sourceFilePath?: string,
        hasComplexStructure: boolean = false
    ): ComponentStructure {
        return {
            nodes: [...(graphData.nodes || [])],
            nodeTypes: { ...(graphData.nodeTypes || {}) },
            nodeLineNumbers: { ...(graphData.nodeLineNumbers || {}) },
            nodePullKeys: { ...(graphData.nodePullKeys || {}) },
            nodePushKeys: { ...(graphData.nodePushKeys || {}) },
            nodeAttributes: { ...(graphData.nodeAttributes || {}) },
            edges: [...(graphData.edges || [])],
            subgraphs: Object.fromEntries(
                Object.entries(graphData.subgraphs || {}).map(([parent, children]) => [parent, [...children]])
            ),
            hasComplexStructure,
            sourceFilePath
        };
    }

    private getGraphDataForRenderableCandidate(candidate: StandaloneRenderableCandidate): GraphData | null {
        if (candidate.kind === 'template' && candidate.template) {
            if (candidate.template.baseKind === 'Node') {
                return null;
            }

            const structure = buildTemplateStructure(
                candidate.template,
                candidate.template.sourceCode || candidate.sourceCode || ''
            );
            if (!structure) {return null;}
            const subgraphParents: { [child: string]: string } = {};
            const subgraphTypes: { [parent: string]: string } = {};
            for (const [parent, children] of Object.entries(structure.subgraphs || {})) {
                for (const child of children || []) {
                    subgraphParents[child] = parent;
                }
                const isLoop =
                    (children || []).some((child) => child.endsWith('_controller') || child.endsWith('_terminate')) ||
                    (children || []).some((child) => structure.nodeTypes?.[child] === 'Controller');
                subgraphTypes[parent] = isLoop ? 'Loop' : 'Graph';
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
                graphType:
                    structure.nodes.includes('controller') && structure.nodes.includes('terminate')
                        ? 'Loop'
                        : 'Graph',
                controlFlow: { forLoops: [], ifConditions: [], dependencies: [] },
                loopControls: {},
                warnings: [],
                pendingBuilderCalls: {}
            };
        }

        if (candidate.kind === 'assignment' && candidate.graphKind) {
            return this.parseStandaloneAssignmentGraph(
                candidate.sourceRootNode!,
                candidate.parseScopeNode || candidate.sourceRootNode!,
                candidate.sourceCode || '',
                candidate.sourceGraphVariable || candidate.id,
                candidate.graphKind,
                undefined,
                candidate.sourceImports,
                candidate.sourceFilePath,
                candidate.scopeKind || 'module'
            );
        }

        return null;
    }

    private tryParseWrappedRenderableStructure(
        rootNode: TSNode,
        code: string,
        symbolName: string,
        imports: Map<string, ImportInfo>,
        sourceFilePath?: string
    ): ComponentStructure | null {
        const functionMatch = this.findFunctionGraphScope(rootNode, code, symbolName);
        if (functionMatch) {
            const graphData = this.parseStandaloneAssignmentGraph(
                rootNode,
                functionMatch.bodyNode,
                code,
                functionMatch.rootGraphVariable,
                functionMatch.graphKind,
                undefined,
                imports,
                sourceFilePath,
                'function'
            );
            if (graphData) {
                const hasComplexStructure =
                    this.extractConditionVariables(functionMatch.bodyNode, code).length > 0 ||
                    Object.keys(this.extractLoopControls(functionMatch.bodyNode, code)).length > 0;
                return this.buildComponentStructureFromGraphData(
                    graphData,
                    sourceFilePath,
                    hasComplexStructure
                );
            }
        }

        const classMatch = this.findClassGraphScope(rootNode, code, symbolName);
        if (classMatch) {
            const graphData = this.parseStandaloneAssignmentGraph(
                rootNode,
                classMatch.bodyNode,
                code,
                classMatch.rootGraphVariable,
                classMatch.graphKind,
                undefined,
                imports,
                sourceFilePath,
                'function'
            );
            if (graphData) {
                const hasComplexStructure =
                    this.extractConditionVariables(classMatch.bodyNode, code).length > 0 ||
                    Object.keys(this.extractLoopControls(classMatch.bodyNode, code)).length > 0;
                return this.buildComponentStructureFromGraphData(
                    graphData,
                    sourceFilePath,
                    hasComplexStructure
                );
            }
        }

        const assignmentRight = this.findTopLevelAssignmentRight(rootNode, code, this.normalizeLookupKeys(symbolName));
        if (assignmentRight?.type === 'call') {
            const resolved = this.resolveFunctionCallToRenderables(assignmentRight, {
                preferredName: symbolName,
                code,
                rootNode,
                imports,
                sourceFilePath,
                templateBindings: {},
                exprBindings: {},
                depth: 0,
                visited: new Set<string>()
            });
            if (resolved?.length === 1) {
                const aliased = this.cloneRenderableCandidateWithAlias(
                    resolved[0],
                    symbolName,
                    assignmentRight.startPosition.row + 1
                );
                const graphData = this.getGraphDataForRenderableCandidate(aliased);
                if (graphData) {
                    return this.buildComponentStructureFromGraphData(graphData, sourceFilePath);
                }
            }
        }

        return null;
    }

    private mergeTemplateScope(parsed: ParsedNodeTemplate, env: TemplateResolverEnv): ParsedNodeTemplate {
        const next: ParsedNodeTemplate = { ...parsed };
        const scopedTemplates = {
            ...(parsed.scopedTemplates || {}),
            ...(env.templateBindings || {})
        };
        const literalValues = {
            ...(parsed.literalValues || {}),
            ...(env.exprBindings || {})
        };
        if (Object.keys(scopedTemplates).length > 0) {next.scopedTemplates = scopedTemplates;}
        if (Object.keys(literalValues).length > 0) {next.literalValues = literalValues;}
        if (!next.sourceFilePath && env.sourceFilePath) {next.sourceFilePath = env.sourceFilePath;}
        if (!next.sourceCode && env.code) {next.sourceCode = env.code;}
        return next;
    }

    private resolveImportedSymbolSource(
        importInfo: ImportInfo,
        sourceFilePath: string | undefined,
        symbolName: string
    ): { file: ParsedPythonFile; symbolName: string } | null {
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

        let currentModulePath = this.resolveModulePathFromContext(
            importInfo.modulePath,
            sourceFilePath,
            contextRoot
        );
        let currentSymbol = symbolName || importInfo.className;
        const visited = new Set<string>();

        for (let depth = 0; depth < 8; depth++) {
            const visitKey = `${currentModulePath}::${currentSymbol}`;
            if (visited.has(visitKey)) {break;}
            visited.add(visitKey);

            const potentialPaths = Array.from(
                new Set(candidateRoots.flatMap((root) => modulePathToFilePaths(currentModulePath, root)))
            );

            let redirected = false;
            for (const filePath of potentialPaths) {
                const parsed = this.getParsedPythonFile(filePath);
                if (!parsed) {continue;}

                const hasFunction = !!this.findTopLevelFunctionInRoot(parsed.rootNode, parsed.code, currentSymbol);
                const hasAssignment = !!this.findTopLevelAssignmentRight(
                    parsed.rootNode,
                    parsed.code,
                    this.normalizeLookupKeys(currentSymbol)
                );
                if (hasFunction || hasAssignment) {
                    return { file: parsed, symbolName: currentSymbol };
                }

                const reexport = currentSymbol
                    ? this.findReexportTarget(filePath, parsed.code, currentSymbol)
                    : null;
                if (reexport) {
                    currentModulePath = reexport.modulePath;
                    currentSymbol = reexport.className;
                    redirected = true;
                    break;
                }
            }

            if (!redirected) {break;}
        }

        return null;
    }

    private resolveCallableDefinition(
        functionNode: TSNode,
        env: TemplateResolverEnv
    ): ResolvedCallableDefinition | null {
        const functionText = getNodeText(functionNode, env.code).trim();
        const normalizedName = functionText.includes('.') ? functionText.split('.').pop()! : functionText;

        const resolveMethodSource = (
            rootNode: TSNode,
            code: string,
            imports: Map<string, ImportInfo>,
            sourceFilePath: string | undefined,
            ownerText: string,
            methodName: string
        ): ResolvedCallableDefinition | null => {
            for (const key of this.normalizeLookupKeys(ownerText)) {
                const localClass = this.findTopLevelClassInRoot(rootNode, code, key);
                if (localClass) {
                    const methodDef = this.findMethodInClassNode(localClass, code, methodName);
                    if (!methodDef) {continue;}
                    return {
                        callableDef: methodDef,
                        callableKind: 'method',
                        callableName: methodName,
                        code,
                        rootNode,
                        imports,
                        filePath: sourceFilePath,
                        ownerName: this.getDefinitionName(localClass, code)
                    };
                }

                const importInfo = this.resolveImportInfoForType(key, imports);
                if (!importInfo) {continue;}
                const source = this.resolveImportedSymbolSource(
                    importInfo,
                    sourceFilePath,
                    importInfo.className || key
                );
                if (!source) {continue;}

                const classNode = this.findTopLevelClassInRoot(
                    source.file.rootNode,
                    source.file.code,
                    source.symbolName || key
                );
                if (!classNode) {continue;}
                const methodDef = this.findMethodInClassNode(classNode, source.file.code, methodName);
                if (!methodDef) {continue;}
                return {
                    callableDef: methodDef,
                    callableKind: 'method',
                    callableName: methodName,
                    code: source.file.code,
                    rootNode: source.file.rootNode,
                    imports: source.file.imports,
                    filePath: source.file.filePath,
                    ownerName: this.getDefinitionName(classNode, source.file.code)
                };
            }

            return null;
        };

        const currentFunction = this.findTopLevelFunctionInRoot(env.rootNode, env.code, normalizedName);
        if (currentFunction) {
            return {
                callableDef: currentFunction,
                callableKind: 'function',
                callableName: normalizedName,
                code: env.code,
                rootNode: env.rootNode,
                imports: env.imports,
                filePath: env.sourceFilePath
            };
        }

        if (functionNode.type === 'attribute') {
            const objectNode =
                functionNode.childForFieldName('object') ||
                functionNode.namedChildren.find((child): child is TSNode => !!child) ||
                null;
            if (objectNode && (objectNode.type === 'identifier' || objectNode.type === 'attribute')) {
                const ownerText = getNodeText(objectNode, env.code).trim();
                const methodSource = resolveMethodSource(
                    env.rootNode,
                    env.code,
                    env.imports,
                    env.sourceFilePath,
                    ownerText,
                    normalizedName
                );
                if (methodSource) {
                    return methodSource;
                }
            }
        }

        const importInfo =
            this.resolveImportInfoForType(functionText, env.imports) ||
            this.resolveImportInfoForType(normalizedName, env.imports);
        if (!importInfo) {return null;}
        const source = this.resolveImportedSymbolSource(
            importInfo,
            env.sourceFilePath,
            importInfo.className || normalizedName
        );
        if (!source) {return null;}

        const importedFunction = this.findTopLevelFunctionInRoot(
            source.file.rootNode,
            source.file.code,
            source.symbolName || normalizedName
        );
        if (importedFunction) {
            return {
                callableDef: importedFunction,
                callableKind: 'function',
                callableName: source.symbolName || normalizedName,
                code: source.file.code,
                rootNode: source.file.rootNode,
                imports: source.file.imports,
                filePath: source.file.filePath
            };
        }

        if (functionNode.type === 'attribute') {
            const objectNode =
                functionNode.childForFieldName('object') ||
                functionNode.namedChildren.find((child): child is TSNode => !!child) ||
                null;
            if (objectNode && (objectNode.type === 'identifier' || objectNode.type === 'attribute')) {
                const ownerText = getNodeText(objectNode, env.code).trim();
                return resolveMethodSource(
                    source.file.rootNode,
                    source.file.code,
                    source.file.imports,
                    source.file.filePath,
                    ownerText,
                    normalizedName
                );
            }
        }

        return null;
    }

    private resolveTemplateExpression(expr: TSNode, env: TemplateResolverEnv): ParsedNodeTemplate | null {
        if (!expr || env.depth > 10) {return null;}

        const rawText = getNodeText(expr, env.code).trim();
        const lookupKeys = this.normalizeLookupKeys(rawText);

        if (expr.type === 'identifier' || expr.type === 'attribute') {
            for (const key of lookupKeys) {
                const template = env.templateBindings[key];
                if (template) {
                    return this.mergeTemplateScope(
                        { ...template, templateName: env.preferredName || template.templateName || key },
                        env
                    );
                }
            }

            for (const key of lookupKeys) {
                const boundExpr = env.exprBindings[key];
                if (boundExpr && boundExpr !== expr) {
                    const resolved = this.resolveTemplateExpression(boundExpr, {
                        ...env,
                        preferredName: env.preferredName || key,
                        depth: env.depth + 1
                    });
                    if (resolved) {return resolved;}
                }
            }

            const assignment = this.findTopLevelAssignmentRight(env.rootNode, env.code, lookupKeys);
            if (assignment && assignment !== expr) {
                const resolved = this.resolveTemplateExpression(assignment, {
                    ...env,
                    preferredName: env.preferredName || lookupKeys[0],
                    depth: env.depth + 1
                });
                if (resolved) {return resolved;}
            }

            for (const key of lookupKeys) {
                const importInfo = this.resolveImportInfoForType(key, env.imports);
                if (!importInfo) {continue;}
                const source = this.resolveImportedSymbolSource(importInfo, env.sourceFilePath, importInfo.className || key);
                if (!source) {continue;}
                const assignmentNode = this.findTopLevelAssignmentRight(
                    source.file.rootNode,
                    source.file.code,
                    this.normalizeLookupKeys(source.symbolName)
                );
                if (!assignmentNode) {continue;}
                const resolved = this.resolveTemplateExpression(assignmentNode, {
                    preferredName: env.preferredName || key,
                    code: source.file.code,
                    rootNode: source.file.rootNode,
                    imports: source.file.imports,
                    sourceFilePath: source.file.filePath,
                    templateBindings: {},
                    exprBindings: {},
                    depth: env.depth + 1,
                    visited: env.visited
                });
                if (resolved) {return resolved;}
            }
            return null;
        }

        if (expr.type !== 'call') {return null;}

        const functionNode = expr.childForFieldName('function');
        if (!functionNode) {return null;}
        const functionText = getNodeText(functionNode, env.code).trim();
        const args = this.getCallArgs(expr);
        const positional = this.getPositionalArgs(args);
        const kw = this.getKeywordArgMap(args, env.code);

        const isNodeTemplateCall = functionText === 'NodeTemplate' || functionText.endsWith('.NodeTemplate');
        if (isNodeTemplateCall) {
            const parsed = tryParseNodeTemplateAssignment(env.preferredName || '__template__', expr, env.code);
            return parsed ? this.mergeTemplateScope(parsed, env) : null;
        }

        const calleeLast = functionText.includes('.') ? functionText.split('.').pop()! : functionText;
        if ((calleeLast === 'Shared' || calleeLast === 'Factory') && positional.length > 0) {
            return this.resolveTemplateExpression(positional[0], {
                ...env,
                depth: env.depth + 1
            });
        }

        if (calleeLast === 'clone' && functionNode.type === 'attribute') {
            const baseExpr =
                functionNode.childForFieldName('object') ||
                functionNode.namedChildren.find((n): n is TSNode => !!n) ||
                null;
            if (baseExpr) {
                const base = this.resolveTemplateExpression(baseExpr, {
                    ...env,
                    depth: env.depth + 1
                });
                if (base) {
                    const next: ParsedNodeTemplate = {
                        ...base,
                        templateName: env.preferredName || base.templateName
                    };
                    if (kw.has('nodes')) {next.nodesArg = kw.get('nodes');}
                    if (kw.has('edges')) {next.edgesArg = kw.get('edges');}
                    if (kw.has('pull_keys')) {next.pullKeys = parseKeysArgument(kw.get('pull_keys')!, env.code);}
                    if (kw.has('push_keys')) {next.pushKeys = parseKeysArgument(kw.get('push_keys')!, env.code);}
                    if (kw.has('attributes')) {next.attributes = parseDictArgument(kw.get('attributes')!, env.code);}
                    if (kw.has('build_func')) {
                        const buildFuncExpr = kw.get('build_func');
                        if (buildFuncExpr) {
                            const fallback = tryParseNodeTemplateAssignment('__tmp__', expr, env.code);
                            if (fallback?.buildFunc) {next.buildFunc = fallback.buildFunc;}
                        }
                    }
                    return this.mergeTemplateScope(next, env);
                }
            }
        }

        return this.resolveFunctionCallToTemplate(expr, env);
    }

    private resolveFunctionCallToTemplate(callNode: TSNode, env: TemplateResolverEnv): ParsedNodeTemplate | null {
        const functionNode = callNode.childForFieldName('function');
        if (!functionNode) {return null;}
        const functionText = getNodeText(functionNode, env.code).trim();
        const normalizedName = functionText.includes('.') ? functionText.split('.').pop()! : functionText;
        const visitKey = `${env.sourceFilePath || '<memory>'}::${functionText}::${getNodeText(callNode, env.code).trim()}`;
        if (env.visited.has(visitKey)) {return null;}
        const callable = this.resolveCallableDefinition(functionNode, env);
        if (!callable) {return null;}

        const fileCode = callable.code;
        const fileRoot = callable.rootNode;
        const fileImports = callable.imports;
        const filePath = callable.filePath;
        const functionDef = callable.callableDef;

        env.visited.add(visitKey);
        try {
            const parametersNode = functionDef.childForFieldName('parameters');
            const paramNames: string[] = [];
            if (parametersNode) {
                for (const child of parametersNode.namedChildren) {
                    if (!child) {continue;}
                    const nameNode =
                        child.type === 'identifier'
                            ? child
                            : child.childForFieldName('name') || child.childForFieldName('pattern');
                    if (!nameNode) {continue;}
                    const name = getNodeText(nameNode, fileCode).trim();
                    if (name && !paramNames.includes(name)) {paramNames.push(name);}
                }
            }
            if (
                callable.callableKind === 'method' &&
                paramNames.length > 0 &&
                (paramNames[0] === 'self' || paramNames[0] === 'cls')
            ) {
                paramNames.shift();
            }

            const args = this.getCallArgs(callNode);
            const positional = this.getPositionalArgs(args);
            const kw = this.getKeywordArgMap(args, env.code);

            const localTemplates: { [name: string]: ParsedNodeTemplate } = {};
            const localExprBindings: { [name: string]: TSNode } = {};

            for (let i = 0; i < paramNames.length; i++) {
                const paramName = paramNames[i];
                const argNode = kw.get(paramName) || positional[i];
                if (!argNode) {continue;}
                localExprBindings[paramName] = argNode;
                const resolved = this.resolveTemplateExpression(argNode, {
                    preferredName: paramName,
                    code: env.code,
                    rootNode: env.rootNode,
                    imports: env.imports,
                    sourceFilePath: env.sourceFilePath,
                    templateBindings: env.templateBindings,
                    exprBindings: env.exprBindings,
                    depth: env.depth + 1,
                    visited: env.visited
                });
                if (resolved) {localTemplates[paramName] = resolved;}
            }

            const bodyNode = functionDef.childForFieldName('body');
            if (!bodyNode) {return null;}

            for (const stmt of bodyNode.children) {
                if (!stmt) {continue;}

                if (stmt.type === 'expression_statement') {
                    const first = stmt.namedChildren[0];
                    if (!first || (first.type !== 'assignment' && first.type !== 'typed_assignment')) {continue;}
                    const left = first.childForFieldName('left');
                    const right = first.childForFieldName('right');
                    if (!left || !right) {continue;}
                    const leftText = getNodeText(left, fileCode).trim();
                    if (!leftText) {continue;}

                    localExprBindings[leftText] = right;
                    const resolved = this.resolveTemplateExpression(right, {
                        preferredName: leftText,
                        code: fileCode,
                        rootNode: fileRoot,
                        imports: fileImports,
                        sourceFilePath: filePath,
                        templateBindings: { ...localTemplates },
                        exprBindings: { ...localExprBindings },
                        depth: env.depth + 1,
                        visited: env.visited
                    });
                    if (resolved) {
                        localTemplates[leftText] = resolved;
                    }
                    continue;
                }

                if (stmt.type === 'return_statement') {
                    const valueNode =
                        stmt.childForFieldName('value') ||
                        stmt.namedChildren.find((n): n is TSNode => !!n) ||
                        null;
                    if (!valueNode) {continue;}
                    const resolved = this.resolveTemplateExpression(valueNode, {
                        preferredName: env.preferredName || normalizedName,
                        code: fileCode,
                        rootNode: fileRoot,
                        imports: fileImports,
                        sourceFilePath: filePath,
                        templateBindings: { ...localTemplates },
                        exprBindings: { ...localExprBindings },
                        depth: env.depth + 1,
                        visited: env.visited
                    });
                    if (resolved) {return resolved;}
                }
            }
        } finally {
            env.visited.delete(visitKey);
        }

        return null;
    }

    private enrichStandaloneTemplateChildren(
        parsed: ParsedNodeTemplate,
        env: StandaloneTemplateScopeEnv
    ): ParsedNodeTemplate {
        if (!parsed.nodesArg) {return parsed;}

        let scopeCode = parsed.sourceCode || env.code;
        let scopeRoot = env.rootNode;
        let scopeImports = env.imports;
        let scopeSourceFilePath = parsed.sourceFilePath || env.sourceFilePath;

        if (parsed.sourceFilePath && parsed.sourceFilePath !== env.sourceFilePath) {
            const source = this.getParsedPythonFile(parsed.sourceFilePath);
            if (source) {
                scopeCode = source.code;
                scopeRoot = source.rootNode;
                scopeImports = source.imports;
                scopeSourceFilePath = source.filePath;
            }
        }

        const scopedTemplates: { [name: string]: ParsedNodeTemplate } = {
            ...(parsed.scopedTemplates || {}),
            ...(env.templateBindings || {})
        };
        const scopedExprBindings: { [name: string]: TSNode } = {
            ...(parsed.literalValues || {}),
            ...(env.exprBindings || {})
        };

        for (const item of parsed.nodesArg.namedChildren) {
            if (!item || item.type !== 'tuple') {continue;}
            const elems = item.namedChildren.filter((n): n is TSNode => !!n && n.type !== 'comment');
            if (elems.length < 2) {continue;}
            const typeNode = elems[1];
            const rawType = getNodeText(typeNode, scopeCode).trim();
            if (!rawType) {continue;}
            if (scopedTemplates[rawType] || scopedTemplates[rawType.includes('.') ? rawType.split('.').pop()! : rawType]) {
                continue;
            }

            const resolved = this.resolveTemplateExpression(typeNode, {
                preferredName: rawType,
                code: scopeCode,
                rootNode: scopeRoot,
                imports: scopeImports,
                sourceFilePath: scopeSourceFilePath,
                templateBindings: scopedTemplates,
                exprBindings: scopedExprBindings,
                depth: 0,
                visited: new Set<string>()
            });
            if (!resolved) {continue;}

            const register = (key: string, value: ParsedNodeTemplate) => {
                const next = String(key || '').trim();
                if (!next) {return;}
                scopedTemplates[next] = value;
            };
            register(rawType, resolved);
            register(resolved.templateName, resolved);
            register(rawType.includes('.') ? rawType.split('.').pop()! : rawType, resolved);
            register(
                resolved.templateName.includes('.') ? resolved.templateName.split('.').pop()! : resolved.templateName,
                resolved
            );
        }

        return {
            ...parsed,
            scopedTemplates,
            literalValues: scopedExprBindings
        };
    }

    private parseStandaloneAssignmentGraph(
        sourceRootNode: TSNode,
        parseScopeNode: TSNode,
        code: string,
        rootGraphVariable: string,
        graphKind: 'Graph' | 'Loop' | 'RootGraph',
        controlFlowCtx?: ControlFlowContext,
        sourceImports?: Map<string, ImportInfo>,
        sourceFilePath?: string,
        scopeKind: 'module' | 'function' = 'module'
    ): GraphData | null {
        const localClassBases = collectClassBases(sourceRootNode, code);
        const baseType =
            graphKind === 'Loop'
                ? BASE_TYPES.LOOP
                : graphKind === 'RootGraph'
                    ? BASE_TYPES.ROOT_GRAPH
                    : BASE_TYPES.GRAPH;
        const result = this.initializeResult(baseType, rootGraphVariable);

        const nodeCtx: NodeParseContext = {
            nodes: result.nodes,
            nodeTypes: result.nodeTypes,
            nodeLineNumbers: result.nodeLineNumbers,
            variableToNodeName: result.variableToNodeName,
            nodePullKeys: result.nodePullKeys,
            nodePushKeys: result.nodePushKeys,
            nodeAttributes: result.nodeAttributes,
            subgraphParents: result.subgraphParents,
            nodeBuildFuncs: {},
            templates: {},
            literalValues: {},
            localClassBases,
            resolveTemplateAssignment: (leftText, callNode, callCode, templates, literalValues) =>
                this.resolveTemplateExpression(callNode, {
                    preferredName: leftText,
                    code: callCode,
                    rootNode: sourceRootNode,
                    imports: new Map(sourceImports || this.imports),
                    sourceFilePath: sourceFilePath || this.lastSourceFilePath,
                    templateBindings: { ...(templates || {}) },
                    exprBindings: { ...(literalValues || {}) },
                    depth: 0,
                    visited: new Set<string>()
                }),
            features: this.features
        };

        const edgeCtx: EdgeParseContext = {
            edges: result.edges,
            variableToNodeName: result.variableToNodeName,
            nodes: result.nodes,
            subgraphParents: result.subgraphParents,
            literalValues: nodeCtx.literalValues,
            features: this.features
        };

        if (scopeKind === 'function') {
            parseFunctionBody(parseScopeNode, code, nodeCtx, edgeCtx, result.subgraphs, rootGraphVariable, controlFlowCtx);
        } else {
            parseModuleLevel(sourceRootNode, code, nodeCtx, edgeCtx, result.subgraphs, rootGraphVariable, controlFlowCtx);
        }

        const pendingSnapshot = new Map(this.pendingBuilderCalls);
        this.pendingBuilderCalls.clear();
        try {
            this.detectBuilderFunctionCalls(code, nodeCtx.variableToNodeName);
            this.addBuildFuncToPendingCalls(nodeCtx.nodeBuildFuncs || {});
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
                graphType: graphKind,
                controlFlow: { forLoops: [], ifConditions: [], dependencies: [] },
                loopControls: {},
                warnings: [],
                pendingBuilderCalls: Object.fromEntries(this.pendingBuilderCalls)
            };
        } finally {
            this.pendingBuilderCalls.clear();
            for (const [key, value] of pendingSnapshot.entries()) {
                this.pendingBuilderCalls.set(key, value);
            }
        }
    }

    private extractPatternBindingNames(patternNode: TSNode, code: string): string[] {
        const out: string[] = [];
        const seen = new Set<string>();
        const push = (raw: string): void => {
            const next = String(raw || '').trim();
            if (!next || next === '_' || seen.has(next)) {return;}
            seen.add(next);
            out.push(next);
        };

        const stack: TSNode[] = [patternNode];
        while (stack.length > 0) {
            const node = stack.pop()!;
            if (node.type === 'identifier' || node.type === 'attribute') {
                push(getNodeText(node, code));
                continue;
            }

            if (
                node.type === 'tuple' ||
                node.type === 'list' ||
                node.type === 'pattern_list' ||
                node.type === 'tuple_pattern' ||
                node.type === 'list_pattern'
            ) {
                for (let i = node.namedChildren.length - 1; i >= 0; i--) {
                    const child = node.namedChildren[i];
                    if (child) {stack.push(child);}
                }
            }
        }

        return out;
    }

    private cloneRenderableCandidateWithAlias(
        candidate: StandaloneRenderableCandidate,
        alias: string,
        lineNumber?: number
    ): StandaloneRenderableCandidate {
        const nextId = String(alias || '').trim();
        if (!nextId) {return candidate;}

        if (candidate.kind === 'template' && candidate.template) {
            return {
                ...candidate,
                id: nextId,
                template: {
                    ...candidate.template,
                    templateName: nextId
                },
                lineNumber: lineNumber ?? candidate.lineNumber ?? candidate.template.lineNumber
            };
        }

        return {
            ...candidate,
            id: nextId,
            lineNumber: lineNumber ?? candidate.lineNumber,
            sourceGraphVariable: candidate.sourceGraphVariable || candidate.id
        };
    }

    private resolveFunctionCallToRenderables(
        callNode: TSNode,
        env: TemplateResolverEnv
    ): StandaloneRenderableCandidate[] | null {
        const functionNode = callNode.childForFieldName('function');
        if (!functionNode) {return null;}

        const functionText = getNodeText(functionNode, env.code).trim();
        const normalizedName = functionText.includes('.') ? functionText.split('.').pop()! : functionText;
        const visitKey = `${env.sourceFilePath || '<memory>'}::renderable::${functionText}::${getNodeText(callNode, env.code).trim()}`;
        if (env.visited.has(visitKey)) {return null;}
        const callable = this.resolveCallableDefinition(functionNode, env);
        if (!callable) {return null;}

        const fileCode = callable.code;
        const fileRoot = callable.rootNode;
        const fileImports = callable.imports;
        const filePath = callable.filePath;
        const functionDef = callable.callableDef;

        env.visited.add(visitKey);
        try {
            const parametersNode = functionDef.childForFieldName('parameters');
            const paramNames: string[] = [];
            if (parametersNode) {
                for (const child of parametersNode.namedChildren) {
                    if (!child) {continue;}
                    const nameNode =
                        child.type === 'identifier'
                            ? child
                            : child.childForFieldName('name') || child.childForFieldName('pattern');
                    if (!nameNode) {continue;}
                    const name = getNodeText(nameNode, fileCode).trim();
                    if (name && !paramNames.includes(name)) {paramNames.push(name);}
                }
            }
            if (
                callable.callableKind === 'method' &&
                paramNames.length > 0 &&
                (paramNames[0] === 'self' || paramNames[0] === 'cls')
            ) {
                paramNames.shift();
            }

            const args = this.getCallArgs(callNode);
            const positional = this.getPositionalArgs(args);
            const kw = this.getKeywordArgMap(args, env.code);

            const localTemplates: { [name: string]: ParsedNodeTemplate } = {};
            const localExprBindings: { [name: string]: TSNode } = {};
            const localCandidates: { [name: string]: StandaloneRenderableCandidate } = {};
            const registerLocalCandidate = (name: string, candidate: StandaloneRenderableCandidate): void => {
                for (const key of this.normalizeLookupKeys(name)) {
                    localCandidates[key] = candidate;
                }
            };
            const lookupLocalCandidate = (raw: string): StandaloneRenderableCandidate | null => {
                for (const key of this.normalizeLookupKeys(raw)) {
                    const candidate = localCandidates[key];
                    if (candidate) {return candidate;}
                }
                return null;
            };
            const bindExpr = (name: string, value: TSNode): void => {
                for (const key of this.normalizeLookupKeys(name)) {
                    localExprBindings[key] = value;
                }
            };
            const lookupExpr = (raw: string): TSNode | null => {
                for (const key of this.normalizeLookupKeys(raw)) {
                    const bound = localExprBindings[key];
                    if (bound) {return bound;}
                }
                return null;
            };
            const resolveNestedEnv = (preferredName?: string): TemplateResolverEnv => ({
                preferredName,
                code: fileCode,
                rootNode: fileRoot,
                imports: fileImports,
                sourceFilePath: filePath,
                templateBindings: { ...env.templateBindings, ...localTemplates },
                exprBindings: { ...env.exprBindings, ...localExprBindings },
                depth: env.depth + 1,
                visited: env.visited
            });
            const resolveReturnValue = (valueNode: TSNode | null | undefined): StandaloneRenderableCandidate[] => {
                if (!valueNode) {return [];}

                if (
                    valueNode.type === 'tuple' ||
                    valueNode.type === 'list' ||
                    valueNode.type === 'expression_list'
                ) {
                    const nested: StandaloneRenderableCandidate[] = [];
                    for (const child of valueNode.namedChildren) {
                        if (!child || child.type === 'comment') {continue;}
                        nested.push(...resolveReturnValue(child));
                    }
                    return nested;
                }

                if (valueNode.type === 'identifier' || valueNode.type === 'attribute') {
                    const raw = getNodeText(valueNode, fileCode).trim();
                    const localCandidate = lookupLocalCandidate(raw);
                    if (localCandidate) {return [localCandidate];}

                    const bound = lookupExpr(raw);
                    if (bound && bound !== valueNode) {
                        const resolved = resolveReturnValue(bound);
                        if (resolved.length > 0) {return resolved;}
                    }

                    const parsed = this.resolveTemplateExpression(valueNode, resolveNestedEnv(raw));
                    if (parsed) {
                        return [
                            {
                                id: parsed.templateName,
                                kind: 'template',
                                template: parsed,
                                lineNumber: parsed.lineNumber
                            }
                        ];
                    }
                    return [];
                }

                if (valueNode.type === 'call') {
                    const parsed = this.resolveTemplateExpression(valueNode, resolveNestedEnv(normalizedName));
                    if (parsed) {
                        return [
                            {
                                id: parsed.templateName,
                                kind: 'template',
                                template: parsed,
                                lineNumber: parsed.lineNumber
                            }
                        ];
                    }

                    const nested = this.resolveFunctionCallToRenderables(valueNode, resolveNestedEnv(normalizedName));
                    return nested || [];
                }

                return [];
            };

            for (let i = 0; i < paramNames.length; i++) {
                const paramName = paramNames[i];
                const argNode = kw.get(paramName) || positional[i];
                if (!argNode) {continue;}
                bindExpr(paramName, argNode);
                const resolved = this.resolveTemplateExpression(argNode, {
                    preferredName: paramName,
                    code: env.code,
                    rootNode: env.rootNode,
                    imports: env.imports,
                    sourceFilePath: env.sourceFilePath,
                    templateBindings: env.templateBindings,
                    exprBindings: env.exprBindings,
                    depth: env.depth + 1,
                    visited: env.visited
                });
                if (resolved) {localTemplates[paramName] = resolved;}
            }

            const bodyNode = functionDef.childForFieldName('body');
            if (!bodyNode) {return null;}

            for (const stmt of bodyNode.children) {
                if (!stmt) {continue;}

                if (stmt.type === 'expression_statement') {
                    const first = stmt.namedChildren[0];
                    if (!first || (first.type !== 'assignment' && first.type !== 'typed_assignment')) {continue;}
                    const left = first.childForFieldName('left');
                    const right = first.childForFieldName('right');
                    if (!left || !right) {continue;}

                    const bindingNames = this.extractPatternBindingNames(left, fileCode);
                    if (bindingNames.length === 1) {
                        bindExpr(bindingNames[0], right);
                    }

                    if (right.type === 'call' && bindingNames.length === 1) {
                        const leftName = bindingNames[0];
                        const fnNode = right.childForFieldName('function');
                        const fnText = fnNode ? getNodeText(fnNode, fileCode).trim() : '';
                        const normalizedFn = fnText.includes('.') ? fnText.split('.').pop()! : fnText;

                        if (normalizedFn === 'Graph' || normalizedFn === 'Loop' || normalizedFn === 'RootGraph') {
                            registerLocalCandidate(leftName, {
                                id: leftName,
                                kind: 'assignment',
                                graphKind: normalizedFn,
                                lineNumber: right.startPosition.row + 1,
                                sourceRootNode: fileRoot,
                                parseScopeNode: bodyNode,
                                scopeKind: 'function',
                                sourceCode: fileCode,
                                sourceFilePath: filePath,
                                sourceImports: fileImports,
                                sourceGraphVariable: leftName
                            });
                            continue;
                        }

                        const parsed =
                            tryParseNodeTemplateAssignment(leftName, right, fileCode) ||
                            this.resolveTemplateExpression(right, resolveNestedEnv(leftName));
                        if (parsed) {
                            localTemplates[leftName] = parsed;
                            registerLocalCandidate(leftName, {
                                id: leftName,
                                kind: 'template',
                                template: {
                                    ...parsed,
                                    templateName: leftName
                                },
                                lineNumber: parsed.lineNumber
                            });
                            continue;
                        }

                        const nested = this.resolveFunctionCallToRenderables(right, resolveNestedEnv(leftName));
                        if (nested?.length === 1) {
                            registerLocalCandidate(
                                leftName,
                                this.cloneRenderableCandidateWithAlias(nested[0], leftName, right.startPosition.row + 1)
                            );
                            continue;
                        }
                    }

                    if (
                        bindingNames.length === 1 &&
                        (right.type === 'identifier' || right.type === 'attribute')
                    ) {
                        const existing = lookupLocalCandidate(getNodeText(right, fileCode).trim());
                        if (existing) {
                            registerLocalCandidate(
                                bindingNames[0],
                                this.cloneRenderableCandidateWithAlias(
                                    existing,
                                    bindingNames[0],
                                    right.startPosition.row + 1
                                )
                            );
                            continue;
                        }
                    }

                    if (bindingNames.length > 1 && right.type === 'call') {
                        const nested = this.resolveFunctionCallToRenderables(right, resolveNestedEnv(bindingNames[0]));
                        if (nested?.length) {
                            const count = Math.min(bindingNames.length, nested.length);
                            for (let i = 0; i < count; i++) {
                                registerLocalCandidate(
                                    bindingNames[i],
                                    this.cloneRenderableCandidateWithAlias(
                                        nested[i],
                                        bindingNames[i],
                                        right.startPosition.row + 1
                                    )
                                );
                            }
                        }
                    }
                    continue;
                }

                if (stmt.type === 'return_statement') {
                    const valueNode =
                        stmt.childForFieldName('value') ||
                        stmt.namedChildren.find((n): n is TSNode => !!n) ||
                        null;
                    const resolved = resolveReturnValue(valueNode);
                    if (resolved.length > 0) {return resolved;}
                }
            }
        } finally {
            env.visited.delete(visitKey);
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
        const localClassBases = collectClassBases(rootNode, code);

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
            localClassBases,
            resolveTemplateAssignment: (leftText, callNode, callCode, templates, literalValues) =>
                this.resolveTemplateExpression(callNode, {
                    preferredName: leftText,
                    code: callCode,
                    rootNode,
                    imports: new Map(this.imports),
                    sourceFilePath,
                    templateBindings: { ...(templates || {}) },
                    exprBindings: { ...(literalValues || {}) },
                    depth: 0,
                    visited: new Set<string>()
                }),
            features: this.features
        };

        const edgeCtx: EdgeParseContext = {
            edges: result.edges,
            variableToNodeName: result.variableToNodeName,
            nodes: result.nodes,
            subgraphParents: result.subgraphParents,
            literalValues: nodeCtx.literalValues,
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

            const standalone = this.tryParseStandaloneTemplateGraph(
                rootNode,
                code,
                opts?.templateName ?? null,
                controlFlowCtx
            );
            const rootGraphVar = findRootGraphVariable(rootNode, code);
            const standaloneCandidates = standalone?.graphCandidates?.length || 0;
            if (
                standalone &&
                (
                    standaloneCandidates > 1 ||
                    !rootGraphVar ||
                    !!opts?.templateName ||
                    (standalone.selectedGraph && standalone.selectedGraph !== rootGraphVar)
                )
            ) {
                this.logParseResult(standalone.nodes, standalone.edges);
                return standalone;
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

        const graphType = buildMethod
            ? this.determineGraphType(className, baseType)
            : this.inferNonClassGraphType(rootNode, code);

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
        if (baseType === BASE_TYPES.ROOT_GRAPH) {return 'RootGraph';}

        const loopTypes: GraphType[] = ['HubGraph', 'MeshGraph', 'Loop'];
        const graphTypes: GraphType[] = [
            'HorizontalGraph',
            'VerticalGraph',
            'AdjacencyMatrixGraph',
            'AdjacencyListGraph',
            'BrainstormingGraph',
            'Graph'
        ];

        if (baseType === BASE_TYPES.LOOP) {
            for (const type of loopTypes) {
                if (className.includes(type)) {
                    return type;
                }
            }
            return 'Loop';
        }

        if (baseType === BASE_TYPES.GRAPH) {
            for (const type of graphTypes) {
                if (type !== 'Graph' && className.includes(type)) {
                    return type;
                }
            }
            return 'Graph';
        }

        return 'unknown';
    }

    private inferNonClassGraphType(rootNode: TSNode, code: string): GraphType {
        const inspect = (node: TSNode | null | undefined): GraphType | null => {
            if (!node) {return null;}

            for (const child of node.children) {
                if (!child) {continue;}

                const functionNode =
                    child.type === 'decorated_definition'
                        ? child.namedChildren.find((n): n is TSNode => !!n && n.type === 'function_definition') || null
                        : child.type === 'function_definition'
                            ? child
                            : null;
                if (functionNode) {
                    const foundInFunction = inspect(functionNode.childForFieldName('body'));
                    if (foundInFunction) {return foundInFunction;}
                    continue;
                }

                if (child.type === 'expression_statement') {
                    const first = child.namedChildren[0];
                    if (first && (first.type === 'assignment' || first.type === 'typed_assignment')) {
                        const right = first.childForFieldName('right');
                        const call = right && right.type === 'call' ? right : null;
                        const functionExpr = call?.childForFieldName('function');
                        const functionText = functionExpr ? getNodeText(functionExpr, code).trim() : '';
                        const normalized = functionText.includes('.') ? functionText.split('.').pop()! : functionText;
                        if (normalized === 'RootGraph') {return 'RootGraph';}
                        if (normalized === 'Loop') {return 'Loop';}
                        if (normalized === 'Graph') {return 'Graph';}
                    }
                }

                if (
                    child.type === 'if_statement' ||
                    child.type === 'for_statement' ||
                    child.type === 'while_statement' ||
                    child.type === 'with_statement'
                ) {
                    const foundInBody = inspect(child.childForFieldName('body') || child.childForFieldName('consequence'));
                    if (foundInBody) {return foundInBody;}
                    const foundInAlt = inspect(child.childForFieldName('alternative'));
                    if (foundInAlt) {return foundInAlt;}
                }

                if (child.type === 'try_statement') {
                    const foundInTry = inspect(child.childForFieldName('body'));
                    if (foundInTry) {return foundInTry;}
                    for (const clause of child.namedChildren) {
                        if (!clause) {continue;}
                        if (clause.type !== 'except_clause' && clause.type !== 'else_clause' && clause.type !== 'finally_clause') {
                            continue;
                        }
                        const foundInClause = inspect(
                            clause.childForFieldName('body') ||
                                clause.namedChildren.find((n): n is TSNode => !!n && n.type === 'block') ||
                                null
                        );
                        if (foundInClause) {return foundInClause;}
                    }
                }

                if (child.type === 'block') {
                    const foundInBlock = inspect(child);
                    if (foundInBlock) {return foundInBlock;}
                }
            }

            return null;
        };

        return inspect(rootNode) || 'unknown';
    }

    private tryParseStandaloneTemplateGraph(
        rootNode: TSNode,
        code: string,
        preferredTemplate: string | null,
        controlFlowCtx?: ControlFlowContext
    ): GraphData | null {
        const candidates: string[] = [];
        const exportedNames: Set<string> = new Set();
        const literalValues: { [name: string]: TSNode } = {};
        const templates: { [name: string]: ParsedNodeTemplate } = {};
        const candidateEntries: { [name: string]: StandaloneRenderableCandidate } = {};

        const stripStringQuotes = (raw: string): string => raw.replace(/^f?["']|["']$/g, '');
        const lastSegment = (name: string): string => (name.includes('.') ? name.split('.').pop()! : name);
        const normalizeTypeName = (raw: string): string => {
            const text = String(raw || '').trim();
            if (!text) {return 'Node';}
            return text.includes('.') ? text.split('.').pop()! : text;
        };
        const registerCandidate = (candidate: StandaloneRenderableCandidate): void => {
            const id = String(candidate.id || '').trim();
            if (!id) {return;}
            candidateEntries[id] = candidate;
            if (!candidates.includes(id)) {
                candidates.push(id);
            }
        };
        const hasEquivalentAssignmentCandidate = (match: GraphScopeMatch): boolean => {
            const sameScope = (node: TSNode | undefined, target: TSNode): boolean => {
                if (!node) {return false;}
                return (
                    node.type === target.type &&
                    node.startPosition.row === target.startPosition.row &&
                    node.startPosition.column === target.startPosition.column &&
                    node.endPosition.row === target.endPosition.row &&
                    node.endPosition.column === target.endPosition.column
                );
            };
            return Object.values(candidateEntries).some((candidate) => {
                return (
                    candidate.kind === 'assignment' &&
                    sameScope(candidate.parseScopeNode, match.bodyNode) &&
                    candidate.sourceGraphVariable === match.rootGraphVariable &&
                    candidate.graphKind === match.graphKind
                );
            });
        };
        const registerTemplate = (parsed: ParsedNodeTemplate): void => {
            const store = (key: string, value: ParsedNodeTemplate) => {
                const next = String(key || '').trim();
                if (!next) {return;}
                templates[next] = value;
            };
            store(parsed.templateName, parsed);
            const normalized = lastSegment(parsed.templateName);
            store(normalized, parsed);
            registerCandidate({
                id: parsed.templateName,
                kind: 'template',
                template: parsed,
                lineNumber: parsed.lineNumber,
                sourceRootNode: rootNode,
                parseScopeNode: rootNode,
                scopeKind: 'module',
                sourceCode: code,
                sourceFilePath: this.lastSourceFilePath,
                sourceImports: new Map(this.imports)
            });
        };
        const registerLiteral = (key: string, value: TSNode): void => {
            const next = String(key || '').trim();
            if (!next) {return;}
            literalValues[next] = value;
        };
        const resolveLiteralNode = (node: TSNode): TSNode => {
            if (node.type !== 'identifier' && node.type !== 'attribute') {return node;}
            const raw = getNodeText(node, code).trim();
            return (
                literalValues[raw] ||
                (raw.startsWith('self._') ? literalValues[raw.replace('self._', '')] : undefined) ||
                (raw.startsWith('self.') ? literalValues[raw.replace('self.', '')] : undefined) ||
                literalValues[lastSegment(raw)] ||
                node
            );
        };
        const parseAllList = (listNode: TSNode): void => {
            for (const item of listNode.namedChildren) {
                if (!item) {continue;}
                if (item.type !== 'string') {continue;}
                exportedNames.add(stripStringQuotes(getNodeText(item, code).trim()));
            }
        };

        for (const child of rootNode.children) {
            if (!child) {continue;}
            if (child.type !== 'expression_statement') {continue;}
            const first = child.namedChildren.filter((n): n is TSNode => !!n)[0];
            if (!first || (first.type !== 'assignment' && first.type !== 'typed_assignment')) {continue;}
            const left = first.childForFieldName('left');
            const right = first.childForFieldName('right');
            if (!left || !right) {continue;}

            const bindingNames = this.extractPatternBindingNames(left, code);
            const leftText = bindingNames[0] || getNodeText(left, code).trim();
            if (leftText.toLowerCase() === '__all__' && right.type === 'list') {
                parseAllList(right);
                continue;
            }

            if (
                bindingNames.length === 1 &&
                (right.type === 'list' || right.type === 'tuple' || right.type === 'dictionary')
            ) {
                registerLiteral(leftText, right);
                if (leftText.startsWith('self._')) {registerLiteral(leftText.replace('self._', ''), right);}
                if (leftText.startsWith('self.')) {registerLiteral(leftText.replace('self.', ''), right);}
                const last = leftText.split('.').pop();
                if (last) {registerLiteral(last, right);}
                if (last?.startsWith('_')) {registerLiteral(last.slice(1), right);}
                continue;
            }

            if (right.type !== 'call') {continue;}

            const functionNode = right.childForFieldName('function');
            const functionText = functionNode ? getNodeText(functionNode, code).trim() : '';
            const normalizedFunction = functionText.includes('.') ? functionText.split('.').pop()! : functionText;
            if (
                bindingNames.length === 1 &&
                (normalizedFunction === 'Graph' || normalizedFunction === 'Loop' || normalizedFunction === 'RootGraph')
            ) {
                registerCandidate({
                    id: leftText,
                    kind: 'assignment',
                    graphKind: normalizedFunction,
                    lineNumber: right.startPosition.row + 1,
                    sourceRootNode: rootNode,
                    parseScopeNode: rootNode,
                    scopeKind: 'module',
                    sourceCode: code,
                    sourceFilePath: this.lastSourceFilePath,
                    sourceImports: new Map(this.imports),
                    sourceGraphVariable: leftText
                });
            }

            if (bindingNames.length === 1) {
                const parsed =
                    tryParseNodeTemplateAssignment(leftText, right, code) ||
                    this.resolveTemplateExpression(right, {
                        preferredName: leftText,
                        code,
                        rootNode,
                        imports: new Map(this.imports),
                        sourceFilePath: this.lastSourceFilePath,
                        templateBindings: { ...templates },
                        exprBindings: { ...literalValues },
                        depth: 0,
                        visited: new Set<string>()
                    });
                if (parsed) {
                    registerTemplate(
                        this.enrichStandaloneTemplateChildren(parsed, {
                            code,
                            rootNode,
                            imports: new Map(this.imports),
                            sourceFilePath: this.lastSourceFilePath,
                            templateBindings: templates,
                            exprBindings: literalValues
                        })
                    );
                    continue;
                }
            }

            const returned = this.resolveFunctionCallToRenderables(right, {
                preferredName: leftText,
                code,
                rootNode,
                imports: new Map(this.imports),
                sourceFilePath: this.lastSourceFilePath,
                templateBindings: { ...templates },
                exprBindings: { ...literalValues },
                depth: 0,
                visited: new Set<string>()
            });
            if (!returned?.length) {continue;}

            if (bindingNames.length <= 1 && returned.length === 1 && leftText) {
                registerCandidate(this.cloneRenderableCandidateWithAlias(returned[0], leftText, right.startPosition.row + 1));
                continue;
            }

            const count = Math.min(bindingNames.length, returned.length);
            for (let i = 0; i < count; i++) {
                registerCandidate(
                    this.cloneRenderableCandidateWithAlias(returned[i], bindingNames[i], right.startPosition.row + 1)
                );
            }
        }

        for (const child of rootNode.children) {
            const functionDef = this.unwrapNamedDefinition(child, 'function_definition');
            if (functionDef) {
                const functionName = this.getDefinitionName(functionDef, code);
                const functionMatch = this.findFunctionGraphScope(rootNode, code, functionName);
                if (functionName && functionMatch && !hasEquivalentAssignmentCandidate(functionMatch)) {
                    registerCandidate(
                        this.createRenderableCandidateFromGraphScope(
                            functionName,
                            functionMatch,
                            rootNode,
                            code,
                            new Map(this.imports),
                            this.lastSourceFilePath
                        )
                    );
                }
                continue;
            }

            const classDef = this.unwrapNamedDefinition(child, 'class_definition');
            if (!classDef) {continue;}
            const className = this.getDefinitionName(classDef, code);
            const classMatch = this.findClassGraphScope(rootNode, code, className);
            if (!className || !classMatch || hasEquivalentAssignmentCandidate(classMatch)) {continue;}
            registerCandidate(
                this.createRenderableCandidateFromGraphScope(
                    className,
                    classMatch,
                    rootNode,
                    code,
                    new Map(this.imports),
                    this.lastSourceFilePath
                )
            );
        }

        if (candidates.length === 0) {return null;}

        const getTemplateStructure = (() => {
            const cache = new Map<string, ComponentStructure | null>();
            return (name: string): ComponentStructure | null => {
                const key = lastSegment(name);
                if (cache.has(key)) {return cache.get(key) || null;}
                const template = templates[name] || templates[key];
                const sourceCode = template?.sourceCode || code;
                const scopedTemplate = template
                    ? {
                          ...template,
                          scopedTemplates: {
                              ...(template.scopedTemplates || {}),
                              ...templates
                          },
                          literalValues: {
                              ...(template.literalValues || {}),
                              ...literalValues
                          },
                          sourceCode
                      }
                    : null;
                const s = scopedTemplate ? buildTemplateStructure(scopedTemplate, sourceCode) : parseTemplateStructure(code, name);
                cache.set(key, s);
                return s;
            };
        })();

        const selectByPreferred = (): string | null => {
            const pref = typeof preferredTemplate === 'string' ? preferredTemplate.trim() : '';
            if (!pref || pref === 'all') {return null;}
            const prefLast = lastSegment(pref);
            return candidates.find((c) => c === pref || lastSegment(c) === prefLast) || null;
        };

        const selectByExports = (): string | null => {
            if (exportedNames.size === 0) {return null;}
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
                if (!s) {continue;}
                for (const t of Object.values(s.nodeTypes || {})) {
                    if (typeof t !== 'string' || !t) {continue;}
                    const to = lastSegment(t);
                    if (!candidateSet.has(to)) {continue;}
                    if (to === from) {continue;}
                    outgoing.get(from)!.add(to);
                }
            }

            const anyDeps = Array.from(outgoing.values()).some((s) => s.size > 0);
            if (!anyDeps) {return null;}

            for (const tos of outgoing.values()) {
                for (const to of tos) {incoming.set(to, (incoming.get(to) || 0) + 1);}
            }

            const roots = candidates.filter((c) => (incoming.get(lastSegment(c)) || 0) === 0);
            if (roots.length === 0) {return null;}
            if (roots.length === 1) {return roots[0];}

            const reachSize = (start: string): number => {
                const seen = new Set<string>();
                const stack = [start];
                while (stack.length > 0) {
                    const cur = stack.pop()!;
                    if (seen.has(cur)) {continue;}
                    seen.add(cur);
                    for (const nxt of outgoing.get(cur) || []) {
                        if (!seen.has(nxt)) {stack.push(nxt);}
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

        const buildGraphDataFromStructure = (
            template: ParsedNodeTemplate,
            structure: ComponentStructure
        ): GraphData => {
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
                loopControls: {},
                warnings: [],
                pendingBuilderCalls: {},
                templateCandidates: candidates.slice(),
                selectedTemplate: template.templateName,
                graphCandidates: candidates.slice(),
                selectedGraph: template.templateName
            };
        };

        const buildNodeTemplateGraphData = (template: ParsedNodeTemplate): GraphData => {
            const nodeId = lastSegment(template.templateName);
            const nodeType = normalizeTypeName(template.nodeClass);
            return {
                nodes: [nodeId],
                nodeTypes: { [nodeId]: nodeType || 'Node' },
                edges: [],
                subgraphs: {},
                subgraphTypes: {},
                subgraphParents: {},
                nodeLineNumbers: { [nodeId]: template.lineNumber || 0 },
                nodePullKeys: {
                    [nodeId]:
                        template.pullKeys !== undefined ? template.pullKeys : nodeType === 'Agent' ? 'empty' : null
                },
                nodePushKeys: {
                    [nodeId]:
                        template.pushKeys !== undefined ? template.pushKeys : nodeType === 'Agent' ? 'empty' : null
                },
                nodeAttributes: { [nodeId]: template.attributes ?? null },
                graphType: 'Graph',
                controlFlow: { forLoops: [], ifConditions: [], dependencies: [] },
                loopControls: {},
                warnings: [],
                pendingBuilderCalls: {},
                templateCandidates: candidates.slice(),
                selectedTemplate: template.templateName,
                graphCandidates: candidates.slice(),
                selectedGraph: template.templateName
            };
        };

        const getCandidateGraphData = (() => {
            const cache = new Map<string, GraphData | null>();
            return (name: string): GraphData | null => {
                const key = lastSegment(name);
                if (cache.has(key)) {return cache.get(key) || null;}

                const candidate = candidateEntries[name];
                if (!candidate) {
                    cache.set(key, null);
                    return null;
                }

                if (candidate.kind === 'template' && candidate.template?.baseKind === 'Node') {
                    const nodeData = buildNodeTemplateGraphData(candidate.template);
                    cache.set(key, nodeData);
                    return nodeData;
                }

                if (candidate.kind === 'template' && candidate.template) {
                    const structure = getTemplateStructure(name);
                    if (!structure) {
                        cache.set(key, null);
                        return null;
                    }

                    const graphData = buildGraphDataFromStructure(candidate.template, structure);
                    cache.set(key, graphData);
                    return graphData;
                }

                if (candidate.kind === 'assignment' && candidate.graphKind) {
                    const graphData = this.parseStandaloneAssignmentGraph(
                        candidate.sourceRootNode || rootNode,
                        candidate.parseScopeNode || candidate.sourceRootNode || rootNode,
                        candidate.sourceCode || code,
                        candidate.sourceGraphVariable || candidate.id,
                        candidate.graphKind,
                        controlFlowCtx,
                        candidate.sourceImports,
                        candidate.sourceFilePath,
                        candidate.scopeKind || 'module'
                    );
                    cache.set(key, graphData);
                    return graphData;
                }

                cache.set(key, null);
                return null;
            };
        })();

        const resolveCandidateIdFromTypeName = (rawType: string): string | null => {
            const next = String(rawType || '').trim();
            if (!next) {return null;}
            const normalized = lastSegment(next);
            return candidates.find((candidate) => candidate === next || lastSegment(candidate) === normalized) || null;
        };

        const resolveCandidateIdForNode = (node: TSNode): string | null => {
            if (node.type === 'identifier' || node.type === 'attribute') {
                const raw = getNodeText(node, code).trim();
                return resolveCandidateIdFromTypeName(raw);
            }
            if (node.type !== 'call') {return null;}
            const resolved = this.resolveTemplateExpression(node, {
                preferredName: '__inline__',
                code,
                rootNode,
                imports: new Map(this.imports),
                sourceFilePath: this.lastSourceFilePath,
                templateBindings: { ...templates },
                exprBindings: { ...literalValues },
                depth: 0,
                visited: new Set<string>()
            });
            if (!resolved) {return null;}
            return resolveCandidateIdFromTypeName(resolved.templateName);
        };

        const collectCandidateDependencies = (candidateId: string): Set<string> => {
            const deps = new Set<string>();
            const candidate = candidateEntries[candidateId];
            if (!candidate) {return deps;}

            if (candidate.kind === 'template' && candidate.template?.nodesArg) {
                const nodesNode = resolveLiteralNode(candidate.template.nodesArg);
                if (nodesNode.type === 'list') {
                    for (const item of nodesNode.namedChildren) {
                        if (!item || item.type !== 'tuple') {continue;}
                        const elems = item.namedChildren.filter(
                            (child): child is TSNode => !!child && child.type !== 'comment'
                        );
                        if (elems.length < 2) {continue;}
                        const depId = resolveCandidateIdForNode(elems[1]);
                        if (!depId || depId === candidateId) {continue;}
                        deps.add(depId);
                    }
                }
            }

            if (candidate.kind === 'assignment') {
                const assignmentNode = this.findTopLevelAssignmentRight(rootNode, code, [candidate.id]);
                if (assignmentNode?.type === 'call') {
                    const args = this.getCallArgs(assignmentNode);
                    const kw = this.getKeywordArgMap(args, code);
                    let nodesNode = kw.get('nodes') || null;
                    if (!nodesNode) {
                        const positional = this.getPositionalArgs(args);
                        nodesNode =
                            positional.find((arg) => resolveLiteralNode(arg).type === 'list') || null;
                    }
                    const resolvedNodes = nodesNode ? resolveLiteralNode(nodesNode) : null;
                    if (resolvedNodes?.type === 'list') {
                        for (const item of resolvedNodes.namedChildren) {
                            if (!item || item.type !== 'tuple') {continue;}
                            const elems = item.namedChildren.filter(
                                (child): child is TSNode => !!child && child.type !== 'comment'
                            );
                            if (elems.length < 2) {continue;}
                            const depId = resolveCandidateIdForNode(elems[1]);
                            if (!depId || depId === candidateId) {continue;}
                            deps.add(depId);
                        }
                    }
                }
            }

            const data = getCandidateGraphData(candidateId);
            if (data) {
                for (const nodeType of Object.values(data.nodeTypes || {})) {
                    const depId = resolveCandidateIdFromTypeName(nodeType);
                    if (!depId || depId === candidateId) {continue;}
                    deps.add(depId);
                }
            }

            return deps;
        };

        const mergeAllCandidates = (selectedIds: string[]): GraphData | null => {
            const merged: GraphData = {
                nodes: [],
                nodeTypes: {},
                edges: [],
                subgraphs: {},
                subgraphTypes: {},
                subgraphParents: {},
                nodeLineNumbers: {},
                nodePullKeys: {},
                nodePushKeys: {},
                nodeAttributes: {},
                graphType: 'Graph',
                controlFlow: { forLoops: [], ifConditions: [], dependencies: [] },
                loopControls: {},
                warnings: [],
                pendingBuilderCalls: {},
                templateCandidates: candidates.slice(),
                selectedTemplate: 'all',
                graphCandidates: candidates.slice(),
                selectedGraph: 'all'
            };

            for (const candidateId of selectedIds) {
                const candidate = candidateEntries[candidateId];
                const data = getCandidateGraphData(candidateId);
                if (!candidate || !data) {continue;}

                if (candidate.kind === 'template' && candidate.template?.baseKind === 'Node') {
                    const nodeData = buildNodeTemplateGraphData(candidate.template);
                    const sourceNode = data.nodes[0];
                    const nodeId = candidateId;
                    if (!merged.nodes.includes(nodeId)) {merged.nodes.push(nodeId);}
                    merged.nodeTypes[nodeId] =
                        nodeData.nodeTypes[sourceNode] ||
                        normalizeTypeName(candidate.template.nodeClass);
                    merged.nodeLineNumbers[nodeId] =
                        candidate.template.lineNumber || nodeData.nodeLineNumbers?.[sourceNode] || 0;
                    merged.nodePullKeys[nodeId] = data.nodePullKeys?.[sourceNode] ?? null;
                    merged.nodePushKeys[nodeId] = data.nodePushKeys?.[sourceNode] ?? null;
                    merged.nodeAttributes[nodeId] = data.nodeAttributes?.[sourceNode] ?? null;
                    continue;
                }

                const wrapperId = candidateId;
                const prefix = `${wrapperId}_`;
                if (!merged.nodes.includes(wrapperId)) {merged.nodes.push(wrapperId);}
                merged.nodeTypes[wrapperId] =
                    candidate.kind === 'template' && candidate.template
                        ? normalizeTypeName(candidate.template.nodeClass) || (data.graphType === 'Loop' ? 'Loop' : 'Graph')
                        : candidate.kind === 'assignment'
                            ? candidate.graphKind || (data.graphType === 'Loop' ? 'Loop' : 'Graph')
                            : data.graphType === 'Loop'
                                ? 'Loop'
                                : 'Graph';
                merged.nodeLineNumbers[wrapperId] = candidate.lineNumber || 0;
                merged.nodePullKeys[wrapperId] =
                    candidate.kind === 'template' && candidate.template ? candidate.template.pullKeys ?? null : null;
                merged.nodePushKeys[wrapperId] =
                    candidate.kind === 'template' && candidate.template ? candidate.template.pushKeys ?? null : null;
                merged.nodeAttributes[wrapperId] =
                    candidate.kind === 'template' && candidate.template ? candidate.template.attributes ?? null : null;
                merged.subgraphs[wrapperId] = [];
                merged.subgraphTypes[wrapperId] =
                    data.graphType === 'RootGraph' ? 'Graph' : data.graphType === 'Loop' ? 'Loop' : 'Graph';

                for (const node of data.nodes) {
                    const prefixed = `${prefix}${node}`;
                    if (!merged.nodes.includes(prefixed)) {merged.nodes.push(prefixed);}
                    merged.nodeTypes[prefixed] = data.nodeTypes[node] || 'Node';
                    merged.nodeLineNumbers[prefixed] = data.nodeLineNumbers?.[node] || 0;
                    merged.nodePullKeys[prefixed] = data.nodePullKeys?.[node] ?? null;
                    merged.nodePushKeys[prefixed] = data.nodePushKeys?.[node] ?? null;
                    merged.nodeAttributes[prefixed] = data.nodeAttributes?.[node] ?? null;
                }

                const topLevelNodes = data.nodes.filter((node) => !data.subgraphParents?.[node]);
                for (const node of topLevelNodes) {
                    const prefixed = `${prefix}${node}`;
                    if (!merged.subgraphs[wrapperId].includes(prefixed)) {merged.subgraphs[wrapperId].push(prefixed);}
                    merged.subgraphParents[prefixed] = wrapperId;
                }

                for (const [parent, children] of Object.entries(data.subgraphs || {})) {
                    const prefixedParent = `${prefix}${parent}`;
                    merged.subgraphs[prefixedParent] = children.map((child) => `${prefix}${child}`);
                    merged.subgraphTypes[prefixedParent] =
                        data.subgraphTypes?.[parent] ||
                        (data.nodeTypes[parent] && data.nodeTypes[parent].includes('Loop') ? 'Loop' : 'Graph');
                    if (data.subgraphParents?.[parent]) {
                        merged.subgraphParents[prefixedParent] = `${prefix}${data.subgraphParents[parent]}`;
                    } else if (topLevelNodes.includes(parent)) {
                        merged.subgraphParents[prefixedParent] = wrapperId;
                    }
                    for (const child of children) {
                        merged.subgraphParents[`${prefix}${child}`] = prefixedParent;
                    }
                }

                for (const edge of data.edges || []) {
                    merged.edges.push({
                        ...edge,
                        from: `${prefix}${edge.from}`,
                        to: `${prefix}${edge.to}`
                    });
                }
            }

            return merged.nodes.length > 0 ? merged : null;
        };

        const explicitSelection = selectByPreferred();
        const defaultSelection =
            candidates.length > 1
                ? 'all'
                : selectByExports() || selectOutermost() || candidates[candidates.length - 1];
        const selected = explicitSelection || defaultSelection;

        const incoming = new Map<string, number>();
        for (const candidate of candidates) {incoming.set(candidate, 0);}
        for (const candidate of candidates) {
            for (const dep of collectCandidateDependencies(candidate)) {
                incoming.set(dep, (incoming.get(dep) || 0) + 1);
            }
        }

        const rootCandidates = candidates.filter((candidate) => {
            const entry = candidateEntries[candidate];
            if (!entry) {return false;}
            return (incoming.get(candidate) || 0) === 0;
        });
        const effectiveAllCandidates = rootCandidates.length > 0 ? rootCandidates : candidates.slice();

        const chosen =
            (selected === 'all' ? mergeAllCandidates(effectiveAllCandidates) : getCandidateGraphData(selected)) || null;
        if (!chosen) {return null;}

        const warnings: string[] = [];

        // Keep warning semantics consistent with the main parser: if the file contains dynamic build logic,
        // the preview may be inaccurate. (Standalone templates are usually static, but keep best-effort.)
        const loopControls = this.extractLoopControls(rootNode, code);
        const conditionControls = this.extractConditionVariables(rootNode, code);
        if (conditionControls.length > 0 || Object.keys(loopControls).length > 0) {
            warnings.push(
                'This file contains dynamic graph construction (Python if/for). Dynamically-constructed graph components may fail to render, or the preview may be inaccurate.'
            );
        }

        chosen.loopControls = loopControls;
        chosen.warnings = [...(chosen.warnings || []), ...warnings];
        chosen.templateCandidates = candidates.slice();
        chosen.graphCandidates = candidates.slice();
        chosen.selectedTemplate = selected;
        chosen.selectedGraph = selected;
        return chosen;
    }

    // ==================== Compatibility Methods ====================

    getConditionVariables(code: string): string[] {
        const parser = this.getParser();
        const tree = parser ? parser.parse(code) : null;
        if (!tree) {return [];}
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
                    if (!child) {continue;}
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
                if (!child) {continue;}
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
                    if (!child) {continue;}
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
                        if (!child) {continue;}
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
                if (!child) {continue;}
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
            if (n.type !== 'integer') {return null;}
            const raw = getNodeText(n, code).replace(/_/g, '');
            const value = Number.parseInt(raw, 10);
            return Number.isFinite(value) ? value : null;
        };

        if (args.length === 1) {
            const end = parseIntNode(args[0]);
            if (end !== null) {iterations = end;}
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
        const ensureTopLevelEndpoints = (kind: GraphType): void => {
            if (kind === 'Loop') {return;}
            if (!nodeCtx.nodes.includes('controller') || !nodeCtx.nodes.includes('terminate')) {return;}
            nodeCtx.nodes.length = 0;
            nodeCtx.nodes.push('entry', 'exit');
            delete nodeCtx.nodeTypes['controller'];
            delete nodeCtx.nodeTypes['terminate'];
            nodeCtx.nodeTypes['entry'] = 'entry';
            nodeCtx.nodeTypes['exit'] = 'exit';
        };

        // First try module-level code
        let rootGraphVariable = findRootGraphVariable(rootNode, code);
        
        if (rootGraphVariable) {
            ensureTopLevelEndpoints(this.inferNonClassGraphType(rootNode, code));
            console.log('[Parser] Found RootGraph at module level');
            console.log(`[Parser] RootGraph variable: ${rootGraphVariable}`);
            parseModuleLevel(rootNode, code, nodeCtx, edgeCtx, subgraphs, rootGraphVariable, controlFlowCtx);
        } else {
            // Try to find RootGraph inside a function (e.g., main())
            const funcWithGraph = findFunctionWithRootGraph(rootNode, code);
            if (funcWithGraph) {
                ensureTopLevelEndpoints(this.inferNonClassGraphType(funcWithGraph.funcBody, code));
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
