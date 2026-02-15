import cytoscape, { type Core, type ElementDefinition, type Stylesheet } from 'cytoscape';
import { ensureCyDagreRegistered } from './cyDagre';
import {
  captureSelectionSnapshot,
  captureViewportSnapshot,
  restoreSelectionSnapshot,
  restoreViewportSnapshot,
  type SelectionSnapshot,
  type ViewportSnapshot
} from './cyViewport';
import { attachCyVisibilityObserver, type CyVisibilityObserverHandle } from './cyVisibilityObserver';

export type CyGraphRendererInit = {
  getContainer: () => HTMLElement | null;
  style: Stylesheet[] | Stylesheet;
  minZoom?: number;
  maxZoom?: number;
  wheelSensitivity?: number;
  thresholdPx?: number;
  /**
   * Called when the canvas becomes visible and a pending layout is requested.
   */
  layout?: (cy: Core) => void;
  /**
   * Called after the cytoscape instance is created.
   */
  onAfterInit?: (cy: Core) => void;
  /**
   * Called after we restore viewport / run pending layout on show.
   */
  onVisible?: (cy: Core) => void;
  /**
   * Called before the instance is destroyed.
   */
  onBeforeDestroy?: (cy: Core) => void;
  /**
   * Called on every container resize (after `cy.resize()`).
   */
  onResize?: (cy: Core) => void;
};

export type CyGraphRendererSet = {
  preserveViewport?: boolean;
  preserveSelection?: boolean;
  /**
   * When true, runs `layout()` if visible; otherwise defers until visible.
   */
  layout?: boolean;
};

function isContainerVisible(container: HTMLElement | null, thresholdPx: number): boolean {
  if (!container) return false;
  const w = container.clientWidth ?? 0;
  const h = container.clientHeight ?? 0;
  return w >= thresholdPx && h >= thresholdPx;
}

export class CyGraphRenderer {
  private readonly getContainer: () => HTMLElement | null;
  private readonly thresholdPx: number;
  private style: Stylesheet[] | Stylesheet;
  private readonly layoutFn: ((cy: Core) => void) | null;
  private readonly onAfterInit: ((cy: Core) => void) | null;
  private readonly onVisible: ((cy: Core) => void) | null;
  private readonly onBeforeDestroy: ((cy: Core) => void) | null;
  private readonly onResize: ((cy: Core) => void) | null;

  private cy: Core | null = null;
  private observer: CyVisibilityObserverHandle | null = null;
  private lastVisibleViewport: ViewportSnapshot | null = null;
  private pendingLayout = false;
  private readonly minZoom: number;
  private readonly maxZoom: number;
  private readonly wheelSensitivity: number;

  constructor(opts: CyGraphRendererInit) {
    this.getContainer = opts.getContainer;
    this.thresholdPx = typeof opts.thresholdPx === 'number' && Number.isFinite(opts.thresholdPx) ? opts.thresholdPx : 20;
    this.style = opts.style;
    this.layoutFn = typeof opts.layout === 'function' ? opts.layout : null;
    this.onAfterInit = typeof opts.onAfterInit === 'function' ? opts.onAfterInit : null;
    this.onVisible = typeof opts.onVisible === 'function' ? opts.onVisible : null;
    this.onBeforeDestroy = typeof opts.onBeforeDestroy === 'function' ? opts.onBeforeDestroy : null;
    this.onResize = typeof opts.onResize === 'function' ? opts.onResize : null;
    this.minZoom = typeof opts.minZoom === 'number' && Number.isFinite(opts.minZoom) ? opts.minZoom : 0.3;
    this.maxZoom = typeof opts.maxZoom === 'number' && Number.isFinite(opts.maxZoom) ? opts.maxZoom : 3;
    this.wheelSensitivity =
      typeof opts.wheelSensitivity === 'number' && Number.isFinite(opts.wheelSensitivity) ? opts.wheelSensitivity : 1.5;
  }

  public getCy(): Core | null {
    return this.cy;
  }

  public init(): Core | null {
    if (this.cy) return this.cy;
    const container = this.getContainer();
    if (!container) return null;

    ensureCyDagreRegistered();
    this.cy = cytoscape({
      container,
      elements: [],
      style: this.style,
      layout: { name: 'preset' },
      minZoom: this.minZoom,
      maxZoom: this.maxZoom,
      wheelSensitivity: this.wheelSensitivity
    });

    this.observer = attachCyVisibilityObserver({
      getCy: () => this.cy,
      getContainer: () => this.getContainer(),
      thresholdPx: this.thresholdPx,
      onHidden: (core) => {
        this.lastVisibleViewport = captureViewportSnapshot(core);
      },
      onVisible: (core) => {
        if (this.pendingLayout) {
          this.pendingLayout = false;
          if (this.layoutFn) {
            try {
              this.layoutFn(core);
            } catch {
              // ignore
            }
          }
        } else if (this.lastVisibleViewport) {
          restoreViewportSnapshot(core, this.lastVisibleViewport);
          try {
            if (typeof requestAnimationFrame === 'function') {
              requestAnimationFrame(() => {
                if (!this.cy || this.cy !== core) return;
                try {
                  core.resize();
                } catch {
                  // ignore
                }
                restoreViewportSnapshot(core, this.lastVisibleViewport);
              });
            }
          } catch {
            // ignore
          }
        }
        try {
          this.onVisible?.(core);
        } catch {
          // ignore
        }
      },
      onResize: (core) => {
        try {
          this.onResize?.(core);
        } catch {
          // ignore
        }
      }
    });

    try {
      this.onAfterInit?.(this.cy);
    } catch {
      // ignore
    }

    return this.cy;
  }

  public setStyle(style: Stylesheet[] | Stylesheet): void {
    this.style = style;
    if (!this.cy) return;
    try {
      this.cy.style(style);
    } catch {
      // ignore
    }
  }

  public setElements(elements: ElementDefinition[], opts?: CyGraphRendererSet): void {
    const cy = this.init();
    if (!cy) return;

    const preserveViewport = !!opts?.preserveViewport;
    const preserveSelection = !!opts?.preserveSelection;
    const wantsLayout = opts?.layout !== undefined ? !!opts.layout : true;

    const visible = isContainerVisible(this.getContainer(), this.thresholdPx);

    const viewportSnap: ViewportSnapshot | null = preserveViewport ? captureViewportSnapshot(cy) : null;
    const selectionSnap: SelectionSnapshot | null = preserveSelection ? captureSelectionSnapshot(cy) : null;

    cy.batch(() => {
      cy.elements().remove();
      cy.add(elements);
    });

    if (wantsLayout) {
      if (visible) {
        if (this.layoutFn) {
          try {
            this.layoutFn(cy);
          } catch {
            // ignore
          }
        }
      } else {
        this.pendingLayout = true;
      }
    }

    if (viewportSnap) restoreViewportSnapshot(cy, viewportSnap);
    if (selectionSnap) restoreSelectionSnapshot(cy, selectionSnap);
  }

  public destroy(): void {
    const cy = this.cy;
    this.cy = null;
    this.pendingLayout = false;
    this.lastVisibleViewport = null;

    try {
      this.observer?.disconnect();
    } catch {
      // ignore
    }
    this.observer = null;

    if (cy) {
      try {
        this.onBeforeDestroy?.(cy);
      } catch {
        // ignore
      }
      try {
        cy.destroy();
      } catch {
        // ignore
      }
    }
  }

  public setPendingLayout(): void {
    if (!this.cy) return;
    const visible = isContainerVisible(this.getContainer(), this.thresholdPx);
    if (!visible) {
      this.pendingLayout = true;
      return;
    }
    if (!this.layoutFn) return;
    try {
      this.layoutFn(this.cy);
    } catch {
      // ignore
    }
  }
}

