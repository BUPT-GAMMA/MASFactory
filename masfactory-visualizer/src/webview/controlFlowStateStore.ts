import * as vscode from 'vscode';

export type LoopControlInfo = { label: string; variable: string; defaultIterations: number };

export type ViewKind = 'panel' | 'sidebar';

type LoopConfigMap = Map<string, Map<string, number>>;
type ConditionConfigMap = Map<string, Map<string, boolean>>;

export class ControlFlowStateStore {
    private static readonly STORAGE_KEY_LOOP_ITERATIONS = 'masfactory-visualizer.loopIterationsByUri';
    private static readonly STORAGE_KEY_CONDITION_VALUES = 'masfactory-visualizer.conditionValuesByUri';
    private static readonly STORAGE_KEY_TEMPLATE_SELECTION = 'masfactory-visualizer.templateSelectionByUri';

    private readonly globalLoopIterationsByUri: LoopConfigMap = new Map();
    private readonly globalConditionValuesByUri: ConditionConfigMap = new Map();
    private readonly templateSelectionByUri: Map<string, string> = new Map();

    private readonly viewConditionsByUri: Record<ViewKind, ConditionConfigMap> = {
        panel: new Map(),
        sidebar: new Map()
    };
    private readonly viewLoopIterationsByUri: Record<ViewKind, LoopConfigMap> = {
        panel: new Map(),
        sidebar: new Map()
    };

    constructor(private readonly context: vscode.ExtensionContext) {
        this.loadPersisted();
    }

    public getGlobalLoopConfig(uri: string): Map<string, number> {
        let config = this.globalLoopIterationsByUri.get(uri);
        if (!config) {
            config = new Map<string, number>();
            this.globalLoopIterationsByUri.set(uri, config);
        }
        return config;
    }

    public getGlobalConditionConfig(uri: string): Map<string, boolean> {
        const stored = this.globalConditionValuesByUri.get(uri);
        return stored ? new Map(stored) : new Map();
    }

    public getTemplateSelection(uri: string): string | null {
        const v = this.templateSelectionByUri.get(uri);
        return v && v.trim() ? v : null;
    }

    public setTemplateSelection(uri: string, templateName: string | null): void {
        const next = typeof templateName === 'string' ? templateName.trim() : '';
        if (next) this.templateSelectionByUri.set(uri, next);
        else this.templateSelectionByUri.delete(uri);
        this.persist();
    }

    public mergeGlobalLoopIterations(uri: string, loopControls?: Record<string, LoopControlInfo>): void {
        const config = this.getGlobalLoopConfig(uri);
        this.mergeLoopIterationsIntoConfig(config, loopControls);
    }

    public getViewLoopConfig(uri: string, kind: ViewKind): Map<string, number> {
        const storage = this.viewLoopIterationsByUri[kind];
        let cfg = storage.get(uri);
        if (!cfg) {
            cfg = new Map<string, number>();
            storage.set(uri, cfg);
        }
        return cfg;
    }

    public getViewConditionConfig(uri: string, kind: ViewKind): Map<string, boolean> {
        const storage = this.viewConditionsByUri[kind];
        const stored = storage.get(uri);
        return stored ? new Map(stored) : new Map();
    }

    public setViewConditions(uri: string, kind: ViewKind, conditions: Record<string, boolean>): Map<string, boolean> {
        const map = this.buildConditionMap(conditions);
        this.viewConditionsByUri[kind].set(uri, new Map(map));
        this.globalConditionValuesByUri.set(uri, new Map(map));
        this.persist();
        return map;
    }

    public setViewLoopIterations(
        uri: string,
        kind: ViewKind,
        loopIterations: Record<string, number>,
        maxIterations: number
    ): Map<string, number> {
        const cfg = this.getViewLoopConfig(uri, kind);
        cfg.clear();
        for (const [loopId, value] of Object.entries(loopIterations)) {
            const numeric = Number(value);
            if (!Number.isFinite(numeric)) continue;
            const clamped = Math.max(1, Math.min(maxIterations, Math.floor(numeric)));
            cfg.set(loopId, clamped);
        }

        const global = this.getGlobalLoopConfig(uri);
        global.clear();
        for (const [loopId, value] of cfg.entries()) global.set(loopId, value);
        this.persist();
        return new Map(cfg);
    }

    public mergeViewLoopControls(uri: string, kind: ViewKind, loopControls?: Record<string, LoopControlInfo>): void {
        const cfg = this.getViewLoopConfig(uri, kind);
        this.mergeLoopIterationsIntoConfig(cfg, loopControls);
    }

    public clearUri(uri: string): void {
        this.globalLoopIterationsByUri.delete(uri);
        this.globalConditionValuesByUri.delete(uri);
        this.templateSelectionByUri.delete(uri);
        for (const kind of Object.keys(this.viewConditionsByUri) as ViewKind[]) {
            this.viewConditionsByUri[kind].delete(uri);
            this.viewLoopIterationsByUri[kind].delete(uri);
        }
        this.persist();
    }

    private mergeLoopIterationsIntoConfig(config: Map<string, number>, loopControls?: Record<string, LoopControlInfo>): void {
        if (!loopControls) {
            config.clear();
            return;
        }

        const existingKeys = new Set(Object.keys(loopControls));
        for (const [loopId, info] of Object.entries(loopControls)) {
            if (!config.has(loopId)) config.set(loopId, info.defaultIterations);
        }

        for (const key of Array.from(config.keys())) {
            if (!existingKeys.has(key)) config.delete(key);
        }
    }

    private buildConditionMap(conditions: Record<string, boolean>): Map<string, boolean> {
        const map = new Map<string, boolean>();
        for (const [key, value] of Object.entries(conditions)) map.set(key, value === true);
        return map;
    }

    private loadPersisted(): void {
        try {
            const storedLoops = this.context.workspaceState.get<Record<string, Record<string, number>>>(
                ControlFlowStateStore.STORAGE_KEY_LOOP_ITERATIONS
            );
            if (storedLoops && typeof storedLoops === 'object') {
                for (const [uri, loops] of Object.entries(storedLoops)) {
                    const m = new Map<string, number>();
                    if (loops && typeof loops === 'object') {
                        for (const [loopId, value] of Object.entries(loops)) {
                            const numeric = Number(value);
                            if (Number.isFinite(numeric)) m.set(loopId, numeric);
                        }
                    }
                    if (m.size > 0) this.globalLoopIterationsByUri.set(uri, m);
                }
            }

            const storedConds = this.context.workspaceState.get<Record<string, Record<string, boolean>>>(
                ControlFlowStateStore.STORAGE_KEY_CONDITION_VALUES
            );
            if (storedConds && typeof storedConds === 'object') {
                for (const [uri, conds] of Object.entries(storedConds)) {
                    const m = new Map<string, boolean>();
                    if (conds && typeof conds === 'object') {
                        for (const [condId, value] of Object.entries(conds)) {
                            m.set(condId, value === true);
                        }
                    }
                    if (m.size > 0) this.globalConditionValuesByUri.set(uri, m);
                }
            }

            const storedTemplates = this.context.workspaceState.get<Record<string, string>>(
                ControlFlowStateStore.STORAGE_KEY_TEMPLATE_SELECTION
            );
            if (storedTemplates && typeof storedTemplates === 'object') {
                for (const [uri, name] of Object.entries(storedTemplates)) {
                    if (typeof name === 'string' && name.trim()) this.templateSelectionByUri.set(uri, name.trim());
                }
            }
        } catch {
            // ignore
        }
    }

    private persist(): void {
        try {
            const loopsOut: Record<string, Record<string, number>> = {};
            for (const [uri, cfg] of this.globalLoopIterationsByUri.entries()) {
                loopsOut[uri] = Object.fromEntries(cfg.entries());
            }
            void this.context.workspaceState.update(ControlFlowStateStore.STORAGE_KEY_LOOP_ITERATIONS, loopsOut);

            const condsOut: Record<string, Record<string, boolean>> = {};
            for (const [uri, cfg] of this.globalConditionValuesByUri.entries()) {
                condsOut[uri] = Object.fromEntries(cfg.entries());
            }
            void this.context.workspaceState.update(ControlFlowStateStore.STORAGE_KEY_CONDITION_VALUES, condsOut);

            const templatesOut: Record<string, string> = {};
            for (const [uri, name] of this.templateSelectionByUri.entries()) {
                if (name && name.trim()) templatesOut[uri] = name.trim();
            }
            void this.context.workspaceState.update(ControlFlowStateStore.STORAGE_KEY_TEMPLATE_SELECTION, templatesOut);
        } catch {
            // ignore
        }
    }
}
