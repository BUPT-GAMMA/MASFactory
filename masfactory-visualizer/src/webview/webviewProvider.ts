import * as vscode from 'vscode';
import * as path from 'path';
import { GraphParser } from '../parser/parser';
import type { VisualizerUiCommand, RuntimeHub, RuntimeUiMessage } from '../runtime/runtimeHub';
import { buildWebviewHtml } from './webviewHtml';
import { ControlFlowStateStore, type ViewKind } from './controlFlowStateStore';
import { RuntimeSessionPanelManager } from './runtimeSessionPanelManager';
import { VibeDocumentService } from './vibeDocumentService';
import { openFileLocation } from './openFileLocation';
import { registerWebviewMessageHandling } from './webviewMessageRouter';
import { PreviewGraphService } from './previewGraphService';
import { PROTOCOL_VERSION } from '../shared/protocolVersion';

type WebviewProviderOptions = {
    ensureParserReady?: () => Promise<void>;
};

function isVibeDocument(document: vscode.TextDocument | undefined): document is vscode.TextDocument {
    if (!document) {
        return false;
    }
    const languageId = document.languageId;
    if (languageId === 'json' || languageId === 'jsonc' || languageId === 'aml') {
        return true;
    }
    return document.uri.fsPath.toLowerCase().endsWith('.aml');
}

function isAmlDocument(document: vscode.TextDocument | undefined): document is vscode.TextDocument {
    if (!document) {return false;}
    return document.languageId === 'aml' || document.uri.fsPath.toLowerCase().endsWith('.aml');
}

/**
 * Manages webview panels and sidebar views for graph visualization
 */
export class WebviewProvider implements vscode.WebviewViewProvider {
    private panel: vscode.WebviewPanel | undefined;
    private editorPanel: vscode.WebviewPanel | undefined;
    private sidebarView: vscode.WebviewView | undefined;
    private readonly context: vscode.ExtensionContext;
    private static readonly STORAGE_KEY_LAST_ACTIVE_PY = 'masfactory-visualizer.lastActivePythonDocumentUri';
    private static readonly STORAGE_KEY_LAST_ACTIVE_VIBE = 'masfactory-visualizer.lastActiveVibeDocumentUri';
    private readonly controlFlowState: ControlFlowStateStore;
    // Track the last active Python document to avoid clearing graph when clicking on preview panel
    private lastActivePythonDocument: vscode.TextDocument | undefined;
    // Track the last active graph_design JSON or AML document for the Vibe tab
    private lastActiveVibeDocument: vscode.TextDocument | undefined;
    private readonly runtimeHub?: RuntimeHub;
    private readonly runtimePanels?: RuntimeSessionPanelManager;
    private readonly vibeDocs: VibeDocumentService;
    private readonly previewGraph: PreviewGraphService;
    private latestVibeDocumentToken = 0;
    private readonly pendingAmlGraphIdsByUri = new Map<string, string>();

    constructor(
        context: vscode.ExtensionContext,
        parser: GraphParser,
        runtimeHub?: RuntimeHub,
        options: WebviewProviderOptions = {}
    ) {
        this.context = context;
        this.runtimeHub = runtimeHub;
        this.controlFlowState = new ControlFlowStateStore(context);
        this.vibeDocs = new VibeDocumentService(this.safePostMessage.bind(this));
        this.previewGraph = new PreviewGraphService({
            parser,
            controlFlowState: this.controlFlowState,
            safePostMessage: this.safePostMessage.bind(this),
            ensureParserReady: options.ensureParserReady
        });

        if (this.runtimeHub) {
            this.runtimePanels = new RuntimeSessionPanelManager(
                this.context,
                this.runtimeHub,
                this.safePostMessage.bind(this),
                (webview, subscriberId) => this.setupWebviewMessageHandling(webview, subscriberId)
            );
            this.runtimeHub.on('uiMessage', (message: RuntimeUiMessage) => {
                this.postToAllWebviews(message);
                this.runtimePanels?.handleRuntimeUiMessage(message);
            });
        }
    }

    /**
     * Set the last active Python document
     */
    public setLastActivePythonDocument(document: vscode.TextDocument): void {
        this.lastActivePythonDocument = document;
        try {
            void this.context.workspaceState.update(
                WebviewProvider.STORAGE_KEY_LAST_ACTIVE_PY,
                document.uri.toString()
            );
        } catch {
            // ignore
        }
    }

    /**
     * Check if the given document is the last active Python document
     */
    public isLastActivePythonDocument(document: vscode.TextDocument): boolean {
        return this.lastActivePythonDocument?.uri.toString() === document.uri.toString();
    }

    /**
     * Set the last active Vibe document
     */
    public setLastActiveVibeDocument(document: vscode.TextDocument): void {
        this.lastActiveVibeDocument = document;
        try {
            void this.context.workspaceState.update(
                WebviewProvider.STORAGE_KEY_LAST_ACTIVE_VIBE,
                document.uri.toString()
            );
        } catch {
            // ignore
        }
    }

    /**
     * Check if the given document is the last active Vibe document
     */
    public isLastActiveVibeDocument(document: vscode.TextDocument): boolean {
        return this.lastActiveVibeDocument?.uri.toString() === document.uri.toString();
    }

    /**
     * Push the current Vibe document text to webviews for parsing/rendering.
     */
    public updateVibeDocument(document: vscode.TextDocument): void {
        const updateToken = ++this.latestVibeDocumentToken;
        const text = document.getText();
        const message = {
            type: 'vibeDocument',
            documentUri: document.uri.toString(),
            fileName: path.basename(document.uri.fsPath),
            text,
            languageId: document.languageId,
            amlGraphId: this.findRequestedAmlGraphId(document),
        };

        if (isAmlDocument(document)) {
            this.postVibeDocumentMessage(message);
            void this.previewGraph.resolveAmlPreviewData(document)
                .then((previewData) => {
                    if (updateToken !== this.latestVibeDocumentToken) {return;}
                    if (
                        Object.keys(previewData.implementationGraphs).length === 0 &&
                        Object.keys(previewData.importedDocuments).length === 0 &&
                        Object.keys(previewData.implementationTargets).length === 0
                    ) {
                        return;
                    }
                    this.postVibeDocumentMessage({
                        ...message,
                        implementationGraphs: previewData.implementationGraphs,
                        implementationTargets: previewData.implementationTargets,
                        importedDocuments: previewData.importedDocuments
                    });
                })
                .catch((error: unknown) => {
                    console.log('[MASFactory Visualizer] Failed to resolve AML preview data:', error);
                });
            return;
        }

        this.postVibeDocumentMessage(message);
    }

    private findRequestedAmlGraphId(document: vscode.TextDocument): string | undefined {
        const uri = document.uri.toString();
        const requested = this.pendingAmlGraphIdsByUri.get(uri) || '';
        if (requested) {
            this.pendingAmlGraphIdsByUri.delete(uri);
            return requested;
        }
        return undefined;
    }

    private postVibeDocumentMessage(message: unknown): void {
        // Update main panel if it exists
        if (this.panel) {
            this.safePostMessage(this.panel.webview, message);
        }

        // Update editor panel if it exists
        if (this.editorPanel) {
            this.safePostMessage(this.editorPanel.webview, message);
        }

        // Update sidebar if it exists
        if (this.sidebarView) {
            this.safePostMessage(this.sidebarView.webview, message);
        }
    }

    /**
     * Get the last active Python document
     */
    public getLastActivePythonDocument(): vscode.TextDocument | undefined {
        return this.lastActivePythonDocument;
    }

    /**
     * Handle Visualizer UI commands coming from a connected Python process.
     *
     * These commands are best-effort UX helpers and must never throw.
     */
    public async handleVisualizerUiCommand(cmd: VisualizerUiCommand): Promise<void> {
        try {
            if (!cmd || typeof cmd !== 'object') {return;}
            if (cmd.kind === 'openFile') {
                await this.openFileInVisualizer({
                    filePath: cmd.filePath,
                    view: cmd.view,
                    reveal: cmd.reveal,
                    preserveFocus: cmd.preserveFocus
                });
            }
        } catch (err) {
            console.warn('[MASFactory Visualizer] Failed to handle visualizer UI command:', err);
        }
    }

    private revealOrCreateVisualizerWebview(preserveFocus: boolean): void {
        if (this.editorPanel) {
            this.editorPanel.reveal(this.editorPanel.viewColumn ?? vscode.ViewColumn.One, preserveFocus);
            return;
        }
        if (this.panel) {
            this.panel.reveal(undefined, preserveFocus);
            return;
        }
        // Prefer reusing the sidebar view if it's already active, rather than opening a new tab.
        if (this.sidebarView) {
            const sidebarView = this.sidebarView as vscode.WebviewView & {
                show?: (preserveFocus?: boolean) => void;
            };
            sidebarView.show?.(preserveFocus);
            return;
        }

        this.createOrShowPanel();
    }

    private async openFileInVisualizer(opts: {
        filePath: string;
        view: 'auto' | 'preview' | 'vibe';
        reveal: boolean;
        preserveFocus: boolean;
    }): Promise<void> {
        const filePath = typeof opts.filePath === 'string' ? opts.filePath : '';
        if (!filePath) {return;}

        const viewRaw = typeof opts.view === 'string' ? opts.view.toLowerCase() : 'auto';
        const view: 'auto' | 'preview' | 'vibe' =
            viewRaw === 'preview' ? 'preview' : viewRaw === 'vibe' ? 'vibe' : 'auto';

        if (opts.reveal !== false) {
            this.revealOrCreateVisualizerWebview(!!opts.preserveFocus);
        }

        let doc: vscode.TextDocument;
        try {
            doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
        } catch (err) {
            void vscode.window.showWarningMessage(`MASFactory Visualizer: Failed to open file: ${filePath}`);
            return;
        }

        const resolvedView: 'preview' | 'vibe' =
            view === 'auto'
                ? isVibeDocument(doc)
                    ? 'vibe'
                    : 'preview'
                : view;

        // Keep the appropriate "last active" doc so webviews can rehydrate correctly.
        if (resolvedView === 'vibe' && isVibeDocument(doc)) {
            this.setLastActiveVibeDocument(doc);
            this.updateVibeDocument(doc);
            this.postToAllWebviews({ type: 'uiSetActiveTab', tab: 'drag' });
        } else {
            this.setLastActivePythonDocument(doc);
            this.updateGraph(doc);
            this.postToAllWebviews({ type: 'uiSetActiveTab', tab: 'preview' });
        }

        // Best-effort: open the document in the main editor so the user can edit it.
        // For Vibe, we keep focus in Visualizer by default.
        try {
            await vscode.window.showTextDocument(doc, {
                viewColumn: vscode.ViewColumn.One,
                preserveFocus: !!opts.preserveFocus,
                preview: false
            });
        } catch {
            // ignore
        }
    }

    /**
     * Create or show the main webview panel
     */
    public createOrShowPanel(): void {
        if (!this.panel) {
            this.panel = vscode.window.createWebviewPanel(
                'masfactoryVisualizer',
                'MASFactory Visualizer',
                vscode.ViewColumn.Beside,
                {
                    enableScripts: true,
                    retainContextWhenHidden: true,
                    localResourceRoots: [
                        vscode.Uri.joinPath(this.context.extensionUri, 'media')
                    ]
                }
            );

            this.panel.webview.html = buildWebviewHtml({
                webview: this.panel.webview,
                extensionPath: this.context.extensionPath,
                extensionUri: this.context.extensionUri
            });
            this.setupWebviewMessageHandling(this.panel.webview, 'mainPanel');

            // Clean up when panel is closed
            this.panel.onDidDispose(() => {
                try {
                    this.runtimeHub?.releaseSubscriber('mainPanel');
                } catch {
                    // ignore
                }
                this.panel = undefined;
            });

            // Initial update: prefer the active editor document, otherwise fall back to last known documents.
            const activeDoc = vscode.window.activeTextEditor?.document;
            if (activeDoc?.languageId === 'python') {
                this.setLastActivePythonDocument(activeDoc);
                this.updateGraph(activeDoc);
            } else if (isVibeDocument(activeDoc)) {
                this.setLastActiveVibeDocument(activeDoc);
                this.updateVibeDocument(activeDoc);
            } else {
                const pythonDoc = this.lastActivePythonDocument;
                const vibeDoc = this.lastActiveVibeDocument;
                if (pythonDoc) {this.updateGraph(pythonDoc);}
                if (vibeDoc) {this.updateVibeDocument(vibeDoc);}
            }
        } else {
            this.panel.reveal();
        }
    }

    /**
     * Open graph preview in main editor area (as a tab that can be dragged out)
     */
    public openGraphInEditorTab(): void {
        if (!this.editorPanel) {
            this.editorPanel = vscode.window.createWebviewPanel(
                'masfactoryVisualizerEditor',
                'Graph Preview',
                vscode.ViewColumn.One,  // Open in main editor area
                {
                    enableScripts: true,
                    retainContextWhenHidden: true,
                    localResourceRoots: [
                        vscode.Uri.joinPath(this.context.extensionUri, 'media')
                    ]
                }
            );

            this.editorPanel.webview.html = buildWebviewHtml({
                webview: this.editorPanel.webview,
                extensionPath: this.context.extensionPath,
                extensionUri: this.context.extensionUri
            });
            this.setupWebviewMessageHandling(this.editorPanel.webview, 'editorPanel');

            // Clean up when panel is closed
            this.editorPanel.onDidDispose(() => {
                try {
                    this.runtimeHub?.releaseSubscriber('editorPanel');
                } catch {
                    // ignore
                }
                this.editorPanel = undefined;
            });

            // Update graph: prefer last active Python document over current active editor
            const activeDoc = vscode.window.activeTextEditor?.document;
            if (activeDoc?.languageId === 'python') {
                this.setLastActivePythonDocument(activeDoc);
                this.updateGraph(activeDoc);
            } else if (isVibeDocument(activeDoc)) {
                this.setLastActiveVibeDocument(activeDoc);
                this.updateVibeDocument(activeDoc);
            } else {
                const pythonDoc = this.lastActivePythonDocument;
                const vibeDoc = this.lastActiveVibeDocument;
                if (pythonDoc) {this.updateGraph(pythonDoc);}
                if (vibeDoc) {this.updateVibeDocument(vibeDoc);}
            }
        } else {
            this.editorPanel.reveal(vscode.ViewColumn.One);
        }
    }

    /**
     * Restore editor panel from serialized state (called when VSCode restarts)
     */
    public restoreEditorPanel(panel: vscode.WebviewPanel, state: any): void {
        this.editorPanel = panel;
        
        // Setup the restored panel
        panel.webview.options = {
            enableScripts: true,
            localResourceRoots: [
                vscode.Uri.joinPath(this.context.extensionUri, 'media')
            ]
        };
        
        panel.webview.html = buildWebviewHtml({
            webview: panel.webview,
            extensionPath: this.context.extensionPath,
            extensionUri: this.context.extensionUri
        });
        this.setupWebviewMessageHandling(panel.webview, 'editorPanel');
        
        // Clean up when panel is closed
        panel.onDidDispose(() => {
            try {
                this.runtimeHub?.releaseSubscriber('editorPanel');
            } catch {
                // ignore
            }
            this.editorPanel = undefined;
        });
        
        // Restore: prefer serialized documentUri, otherwise fall back to workspaceState.
        void (async () => {
            const tryRestoreFromUri = async (uriStr: string | undefined): Promise<boolean> => {
                if (!uriStr) {return false;}
                try {
                    const doc = await vscode.workspace.openTextDocument(vscode.Uri.parse(uriStr));
                    if (doc.languageId === 'python') {
                        this.setLastActivePythonDocument(doc);
                        this.updateGraph(doc);
                        return true;
                    }
                    if (isVibeDocument(doc)) {
                        this.setLastActiveVibeDocument(doc);
                        this.updateVibeDocument(doc);
                        return true;
                    }
                } catch {
                    // ignore
                }
                return false;
            };

            const stateUri = typeof state?.documentUri === 'string' ? String(state.documentUri) : undefined;
            if (await tryRestoreFromUri(stateUri)) {return;}

            const lastPy = this.context.workspaceState.get<string>(WebviewProvider.STORAGE_KEY_LAST_ACTIVE_PY);
            if (await tryRestoreFromUri(lastPy)) {return;}

            const lastVibe = this.context.workspaceState.get<string>(WebviewProvider.STORAGE_KEY_LAST_ACTIVE_VIBE);
            if (await tryRestoreFromUri(lastVibe)) {return;}

            this.restoreFromActiveEditor();
        })();
    }
    
    /**
     * Helper to restore graph from active editor
     */
    private restoreFromActiveEditor(): void {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {return;}
        if (editor.document.languageId === 'python') {
            this.setLastActivePythonDocument(editor.document);
            this.updateGraph(editor.document);
            return;
        }
        if (isVibeDocument(editor.document)) {
            this.setLastActiveVibeDocument(editor.document);
            this.updateVibeDocument(editor.document);
        }
    }

    /**
     * Implementation of WebviewViewProvider interface for sidebar
     */
    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        context: vscode.WebviewViewResolveContext,
        token: vscode.CancellationToken
    ): void | Thenable<void> {
        this.sidebarView = webviewView;
        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [
                vscode.Uri.joinPath(this.context.extensionUri, 'media')
            ]
        };

        try {
            webviewView.webview.html = buildWebviewHtml({
                webview: webviewView.webview,
                extensionPath: this.context.extensionPath,
                extensionUri: this.context.extensionUri
            });
            this.setupWebviewMessageHandling(webviewView.webview, 'sidebarView');

            webviewView.onDidDispose(() => {
                try {
                    this.runtimeHub?.releaseSubscriber('sidebarView');
                } catch {
                    // ignore
                }
                this.sidebarView = undefined;
            });

            // Update graph if there's an active editor
            const doc = vscode.window.activeTextEditor?.document;
            if (doc?.languageId === 'python') {
                this.updateGraph(doc);
            } else if (isVibeDocument(doc)) {
                this.updateVibeDocument(doc);
            }
        } catch (error) {
            console.error('[MASFactory Visualizer] Error resolving webview:', error);
            vscode.window.showErrorMessage(`MASFactory Visualizer: failed to initialize view - ${error}`);
        }
    }

    /**
     * Clear graph and show a message
     */
    public clearGraph(reason: string): void {
        this.previewGraph.clearGraph(reason, this.getPrimaryWebviews());
    }

    /**
     * Update graph visualization based on document content
     */
    public updateGraph(document: vscode.TextDocument): void {
        if (document.languageId === 'python') {
            // Keep track of the latest Python document even when the webview has focus,
            // so "webviewReady" can trigger a correct initial render.
            this.lastActivePythonDocument = document;
        }
        this.previewGraph.updateGraph(document, this.getPrimaryWebviews());
    }

    private getPrimaryWebviews(): Array<vscode.Webview | undefined> {
        return [this.panel?.webview, this.editorPanel?.webview, this.sidebarView?.webview];
    }

    /**
     * Setup message handling for webview
     */
    private setupWebviewMessageHandling(webview: vscode.Webview, subscriberId: string): void {
        registerWebviewMessageHandling({
            context: this.context,
            webview,
            subscriberId,
                handlers: {
                    navigateToLine: (uriString, lineNumber) => this.handleNavigateToLine(uriString, lineNumber),
                    templateSelectionChanged: (documentUri, templateName) =>
                        this.handleTemplateSelectionChanged(documentUri, templateName),
                    conditionChanged: (wv, documentUri, conditions) =>
                        this.previewGraph.handleConditionChanged({
                            webview: wv,
                            viewKind: this.getViewKind(wv),
                        documentUri,
                        conditions
                    }),
                loopIterationsChanged: (wv, documentUri, loopIterations, conditions) =>
                    this.previewGraph.handleLoopIterationsChanged({
                        webview: wv,
                        viewKind: this.getViewKind(wv),
                        documentUri,
                        loopIterations: loopIterations || {},
                        conditions
                    }),
                adjacencyGraphChanged: (wv, documentUri, graphVariable, edges, conditions, loopIterations) =>
                    this.previewGraph.handleAdjacencyGraphChanged({
                        webview: wv,
                        viewKind: this.getViewKind(wv),
                        documentUri,
                        graphVariable,
                        edges,
                        conditions,
                        loopIterations
                    }),
                refreshGraph: (documentUri) => this.handleRefreshGraph(documentUri),
                resetViewState: (documentUri) => this.handleResetViewState(documentUri),
                webviewReady: () => this.handleWebviewReady(),
                runtimeWebviewReady: (wv) => this.runtimePanels?.handleRuntimeWebviewReady(wv),
                runtimeSubscribe: (sessionId) => this.runtimeHub?.subscribe(sessionId, subscriberId),
                runtimeUnsubscribe: (sessionId) => this.runtimeHub?.unsubscribe(sessionId, subscriberId),
                runtimeOpenSession: (sessionId) => {
                    if (!this.runtimePanels) {
                        void vscode.window.showWarningMessage('MASFactory Visualizer: runtime hub is not available.');
                        return;
                    }
                    this.runtimePanels.openRuntimeSessionPanel(sessionId);
                },
                runtimeHumanResponse: (sessionId, requestId, content) =>
                    this.runtimeHub?.sendHumanResponse(sessionId, requestId, content),
                runtimeExportSession: (sessionId, format, content, fileName) =>
                    this.handleRuntimeExportSession(sessionId, format, content, fileName),
                openFileLocation: (filePath, line, column, targetTab, amlGraphId) =>
                    this.handleOpenFileLocation(filePath, line, column, targetTab, amlGraphId),
                vibeSave: (wv, documentUri, text, extraWrites) => this.vibeDocs.save(wv, { documentUri, text, extraWrites }),
                vibeReload: async (documentUri) => {
                    const doc = await this.vibeDocs.reload({ documentUri });
                    if (!doc) {return;}
                    this.setLastActiveVibeDocument(doc);
                    this.updateVibeDocument(doc);
                }
            }
        });
    }

    private handleOpenFileLocation(
        filePath?: unknown,
        line?: unknown,
        column?: unknown,
        targetTab?: unknown,
        amlGraphId?: unknown
    ): void {
        const tab = targetTab === 'preview' || targetTab === 'drag' || targetTab === 'vibe' ? targetTab : undefined;
        const graphId = typeof amlGraphId === 'string' && amlGraphId.trim() ? amlGraphId.trim() : undefined;

        openFileLocation(filePath, line, column, {
            onOpened: (doc) => {
                if (graphId && isAmlDocument(doc)) {
                    this.pendingAmlGraphIdsByUri.set(doc.uri.toString(), graphId);
                }
                if (tab === 'preview' && doc.languageId === 'python') {
                    this.setLastActivePythonDocument(doc);
                    this.updateGraph(doc);
                    this.postToAllWebviews({ type: 'uiSetActiveTab', tab: 'preview' });
                    return;
                }
                if ((tab === 'drag' || tab === 'vibe') && isVibeDocument(doc)) {
                    this.setLastActiveVibeDocument(doc);
                    this.updateVibeDocument(doc);
                    this.postToAllWebviews({ type: 'uiSetActiveTab', tab });
                }
            }
        });
    }

    /**
     * Handle webview ready message - trigger initial graph update
     */
    private handleWebviewReady(): void {
        const activeDoc = vscode.window.activeTextEditor?.document;

        const pythonDoc =
            this.lastActivePythonDocument ||
            (activeDoc?.languageId === 'python' ? activeDoc : undefined);

        const vibeDoc =
            this.lastActiveVibeDocument ||
            (isVibeDocument(activeDoc) ? activeDoc : undefined);

        if (!pythonDoc && !vibeDoc) {return;}
        console.log('[WebviewProvider] Webview ready, triggering initial update');
        if (pythonDoc) {this.updateGraph(pythonDoc);}
        if (vibeDoc) {this.updateVibeDocument(vibeDoc);}
    }

    private postToAllWebviews(message: unknown): void {
        if (this.panel) {
            this.safePostMessage(this.panel.webview, message);
        }
        if (this.editorPanel) {
            this.safePostMessage(this.editorPanel.webview, message);
        }
        if (this.sidebarView) {
            this.safePostMessage(this.sidebarView.webview, message);
        }
        this.runtimePanels?.forEachSessionPanel((panel) => {
            this.safePostMessage(panel.webview, message);
        });
    }

    private getViewKind(webview: vscode.Webview): ViewKind {
        const isPanelWebview =
            (this.panel && webview === this.panel.webview) ||
            (this.editorPanel && webview === this.editorPanel.webview);
        return isPanelWebview ? 'panel' : 'sidebar';
    }

    private async handleResetViewState(documentUri: string | undefined): Promise<void> {
        if (!documentUri) {return;}

        // Clear persisted control-flow selections for this file.
        this.controlFlowState.clearUri(documentUri);

        try {
            const doc = await vscode.workspace.openTextDocument(vscode.Uri.parse(documentUri));
            if (doc.languageId === 'python') {
                this.lastActivePythonDocument = doc;
                this.updateGraph(doc);
            }
        } catch {
            // ignore
        }
    }

    private async handleTemplateSelectionChanged(
        documentUri: string | undefined,
        templateName: string | null
    ): Promise<void> {
        if (!documentUri) {return;}
        this.controlFlowState.setTemplateSelection(documentUri, templateName);
        await this.handleRefreshGraph(documentUri);
    }

    private async handleRefreshGraph(documentUri: string | undefined): Promise<void> {
        if (!documentUri) {return;}

        try {
            const doc = await vscode.workspace.openTextDocument(vscode.Uri.parse(documentUri));
            if (doc.languageId === 'python') {
                this.lastActivePythonDocument = doc;
                this.updateGraph(doc);
            }
        } catch {
            // ignore
        }
    }

    /**
     * Handle navigation to specific line in source code
     * @param uriString - The URI of the file to navigate to
     * @param lineNumber - The 1-based line number
     */
    private handleNavigateToLine(uriString: string, lineNumber: number): void {
        const uri = vscode.Uri.parse(uriString);
        const zeroBasedLineNumber = lineNumber - 1; // VS Code uses 0-based line numbers

        vscode.workspace.openTextDocument(uri).then(doc => {
            // Use ViewColumn.One to ensure the file opens in the main editor area
            // This prevents opening in a separate window when Graph Preview is in a different window
            vscode.window.showTextDocument(doc, {
                viewColumn: vscode.ViewColumn.One,
                preserveFocus: false  // Focus the editor after opening
            }).then(editor => {
                const position = new vscode.Position(zeroBasedLineNumber, 0);
                editor.selection = new vscode.Selection(position, position);
                editor.revealRange(
                    new vscode.Range(position, position),
                    vscode.TextEditorRevealType.InCenter
                );
            });
        });
    }

    private async handleRuntimeExportSession(
        sessionId: string,
        format: 'json' | 'markdown',
        content: string,
        fileName?: string
    ): Promise<void> {
        const sid = typeof sessionId === 'string' ? sessionId.trim() : '';
        const text = typeof content === 'string' ? content : '';
        if (!sid || !text) {return;}

        const normalizedFormat = format === 'markdown' ? 'markdown' : 'json';
        const suggestedNameRaw =
            typeof fileName === 'string' && fileName.trim()
                ? fileName.trim()
                : `session-${sid}.${normalizedFormat === 'markdown' ? 'md' : 'json'}`;
        const suggestedName = suggestedNameRaw.replace(/[\\/:*?"<>|]+/g, '_');

        const target = await vscode.window.showSaveDialog({
            saveLabel: normalizedFormat === 'markdown' ? 'Export Markdown' : 'Export JSON',
            defaultUri: vscode.Uri.file(path.join(vscode.workspace.rootPath || this.context.extensionPath, suggestedName)),
            filters:
                normalizedFormat === 'markdown'
                    ? { Markdown: ['md'] }
                    : { JSON: ['json'] }
        });
        if (!target) {return;}

        try {
            const encoder = new TextEncoder();
            await vscode.workspace.fs.writeFile(target, encoder.encode(text));
            void vscode.window.showInformationMessage(
                `MASFactory Visualizer: exported session ${sid} to ${path.basename(target.fsPath)}`
            );
        } catch (err) {
            void vscode.window.showErrorMessage(
                `MASFactory Visualizer: failed to export session ${sid}: ${String(err)}`
            );
        }
    }

    private safePostMessage(target: vscode.Webview, message: unknown): void {
        try {
            if (message && typeof message === 'object' && !Array.isArray(message)) {
                const record = message as Record<string, unknown>;
                if (record.protocolVersion === undefined) {
                    target.postMessage({ protocolVersion: PROTOCOL_VERSION, ...record });
                    return;
                }
            }
            target.postMessage(message);
        } catch (error) {
            console.warn('[MASFactory Visualizer] Failed to post message to webview:', error);
        }
    }
}
