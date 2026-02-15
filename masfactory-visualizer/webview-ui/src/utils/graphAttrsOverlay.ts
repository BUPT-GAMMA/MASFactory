import type { Core, NodeSingular } from 'cytoscape';
import type { GraphData, GraphAttributesSummary } from '../types/graph';

function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function hasAnySummary(summary: GraphAttributesSummary | null | undefined): boolean {
  if (!summary) return false;
  const has = (obj: unknown) => !!obj && typeof obj === 'object' && !Array.isArray(obj) && Object.keys(obj as any).length > 0;
  return has(summary.initialAttributes) || has(summary.pullKeys) || has(summary.pushKeys) || has(summary.runtimeAttributes);
}

function generateOverlayHtml(summary: GraphAttributesSummary, graphName: string): string | null {
  if (!hasAnySummary(summary)) return null;

  const sections: Array<{ kind: string; label: string; icon: string; keys: string[] }> = [
    { kind: 'initial', label: 'Initial', icon: '⚙️', keys: Object.keys(summary.initialAttributes || {}) },
    { kind: 'pull', label: 'Pull', icon: '📥', keys: Object.keys(summary.pullKeys || {}) },
    { kind: 'push', label: 'Push', icon: '📤', keys: Object.keys(summary.pushKeys || {}) },
    { kind: 'runtime', label: 'Node Push', icon: '🔄', keys: Object.keys(summary.runtimeAttributes || {}) }
  ].filter((s) => s.keys.length > 0);

  if (sections.length === 0) return null;

  let html = '<div class="graph-attrs-header">';
  html += `<div class="graph-attrs-title">📊 ${escapeHtml(graphName)}</div>`;
  html += '<button class="graph-attrs-toggle" type="button" title="Collapse/expand">▾</button>';
  html += '</div>';
  html += '<div class="graph-attrs-content">';

  for (const section of sections) {
    html += '<div class="graph-attrs-section">';
    html += `<div class="graph-attrs-section-label ${section.kind}">${escapeHtml(section.icon)} ${escapeHtml(
      section.label
    )}:</div>`;
    for (const key of section.keys) {
      html += `<span class="graph-attrs-key ${section.kind}">${escapeHtml(key)}</span>`;
    }
    html += '</div>';
  }

  html += '</div>';
  return html;
}

export type GraphAttrsOverlayDocState = { overlayCollapsed: Record<string, boolean> };

export class GraphAttrsOverlayManager {
  private cy: Core | null = null;
  private readonly container: HTMLElement;
  private readonly getDocState: () => GraphAttrsOverlayDocState | null;
  private readonly setCollapsed: (graphId: string, collapsed: boolean) => void;

  private overlayNodeIds: string[] = [];
  private overlayNodeIdSet: Set<string> = new Set();
  private rootOverlayIds: string[] = [];
  private overlayUpdateScheduled = false;
  private overlayUpdateAll = false;
  private overlayUpdateNodeIds: Set<string> = new Set();
  private boundClick: ((ev: MouseEvent) => void) | null = null;

  constructor(opts: {
    container: HTMLElement;
    getDocState: () => GraphAttrsOverlayDocState | null;
    setCollapsed: (graphId: string, collapsed: boolean) => void;
  }) {
    this.container = opts.container;
    this.getDocState = opts.getDocState;
    this.setCollapsed = opts.setCollapsed;
    this.bindToggleListener();
  }

  attach(cy: Core): void {
    this.cy = cy;
  }

  dispose(): void {
    this.cy = null;
    this.overlayNodeIds = [];
    this.overlayNodeIdSet.clear();
    this.rootOverlayIds = [];
    this.overlayUpdateNodeIds.clear();
    this.overlayUpdateAll = false;
    this.overlayUpdateScheduled = false;
    this.container.innerHTML = '';
    if (this.boundClick) {
      this.container.removeEventListener('click', this.boundClick);
      this.boundClick = null;
    }
  }

  rebuild(graph: GraphData | null): void {
    this.container.innerHTML = '';
    this.overlayNodeIds = [];
    this.overlayNodeIdSet.clear();
    this.rootOverlayIds = [];

    const cy = this.cy;
    if (!cy || !graph) return;

    cy.nodes().forEach((node) => {
      const summary = node.data('graphAttributesSummary') as GraphAttributesSummary | undefined;
      if (!summary) return;
      const html = generateOverlayHtml(summary, node.id());
      if (!html) return;

      const overlay = document.createElement('div');
      overlay.className = 'graph-attrs-overlay';
      overlay.id = `graph-attrs-${node.id()}`;
      overlay.innerHTML = html;
      overlay.style.transform = 'translateX(-100%)';
      overlay.style.willChange = 'left, top';

      const isCollapsed = !!this.getDocState()?.overlayCollapsed?.[node.id()];
      if (isCollapsed) {
        overlay.classList.add('collapsed');
        const toggle = overlay.querySelector('.graph-attrs-toggle');
        if (toggle) toggle.textContent = '▸';
      }

      this.container.appendChild(overlay);
      this.overlayNodeIds.push(node.id());
      this.overlayNodeIdSet.add(node.id());
    });

    const summaryData = graph.graphAttributesSummary || {};
    for (const graphName of Object.keys(summaryData)) {
      const existingOverlay = document.getElementById(`graph-attrs-${graphName}`);
      if (existingOverlay) continue;
      const nodeEl = cy.getElementById(graphName);
      if (nodeEl && nodeEl.length > 0) continue;

      const summary = summaryData[graphName];
      const html = generateOverlayHtml(summary, graphName);
      if (!html) continue;

      const overlay = document.createElement('div');
      overlay.className = 'graph-attrs-overlay graph-attrs-root';
      overlay.id = `graph-attrs-${graphName}`;
      overlay.innerHTML = html;

      const isCollapsed = !!this.getDocState()?.overlayCollapsed?.[graphName];
      if (isCollapsed) {
        overlay.classList.add('collapsed');
        const toggle = overlay.querySelector('.graph-attrs-toggle');
        if (toggle) toggle.textContent = '▸';
      }

      this.container.appendChild(overlay);
      this.rootOverlayIds.push(graphName);
    }

    this.scheduleUpdate('all');
  }

  scheduleUpdate(modeOrNodeIds: 'all' | string | string[] | null): void {
    const cy = this.cy;
    if (!cy) return;

    if (!modeOrNodeIds || modeOrNodeIds === 'all') {
      this.overlayUpdateAll = true;
    } else if (Array.isArray(modeOrNodeIds)) {
      for (const id of modeOrNodeIds) {
        if (typeof id === 'string' && id) this.overlayUpdateNodeIds.add(id);
      }
    } else if (typeof modeOrNodeIds === 'string') {
      this.overlayUpdateNodeIds.add(modeOrNodeIds);
    }

    if (this.overlayUpdateScheduled) return;
    this.overlayUpdateScheduled = true;
    requestAnimationFrame(() => {
      this.overlayUpdateScheduled = false;
      const cyNow = this.cy;
      if (!cyNow) {
        this.overlayUpdateAll = false;
        this.overlayUpdateNodeIds.clear();
        return;
      }

      if (this.overlayUpdateAll) {
        this.updateAllOverlayPositions();
      } else {
        for (const id of this.overlayUpdateNodeIds) {
          const node = cyNow.getElementById(id);
          if (node && node.length > 0) this.updateOverlayPositionForNode(node);
        }
      }

      this.overlayUpdateAll = false;
      this.overlayUpdateNodeIds.clear();
    });
  }

  private bindToggleListener(): void {
    if (this.boundClick) return;
    this.boundClick = (ev: MouseEvent) => {
      try {
        const target = ev.target;
        if (!target || !(target instanceof HTMLElement)) return;
        if (!target.classList.contains('graph-attrs-toggle')) return;

        const overlay = target.closest('.graph-attrs-overlay');
        if (!overlay) return;
        const id = overlay.id || '';
        if (!id.startsWith('graph-attrs-')) return;
        const graphId = id.slice('graph-attrs-'.length);
        if (!graphId) return;

        const collapsed = overlay.classList.toggle('collapsed');
        target.textContent = collapsed ? '▸' : '▾';
        this.setCollapsed(graphId, collapsed);

        if (overlay.classList.contains('graph-attrs-root')) {
          this.scheduleUpdate('all');
        } else {
          this.scheduleUpdate(graphId);
        }
      } catch {
        // ignore
      }
    };
    this.container.addEventListener('click', this.boundClick);
  }

  private updateOverlayPositionForNode(node: NodeSingular): void {
    const cy = this.cy;
    if (!cy || !node) return;
    const overlay = document.getElementById(`graph-attrs-${node.id()}`);
    if (!overlay) return;

    const bb = node.renderedBoundingBox();
    overlay.style.left = `${bb.x2 - 8}px`;
    overlay.style.top = `${bb.y1 + 8}px`;

    if (node.hasClass('collapsed') || !node.visible()) {
      overlay.classList.add('hidden');
    } else {
      overlay.classList.remove('hidden');
    }
  }

  private updateAllOverlayPositions(): void {
    const cy = this.cy;
    if (!cy) return;

    for (const nodeId of this.overlayNodeIds) {
      const node = cy.getElementById(nodeId);
      if (!node || node.length === 0) continue;
      this.updateOverlayPositionForNode(node);
    }

    for (const graphName of this.rootOverlayIds) {
      const overlay = document.getElementById(`graph-attrs-${graphName}`);
      if (overlay && overlay.classList.contains('graph-attrs-root')) {
        overlay.style.left = '10px';
        overlay.style.top = '10px';
      }
    }
  }
}

