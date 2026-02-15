import type { Core } from 'cytoscape';

export type CyContainerSize = { w: number; h: number };

export type CyVisibilityObserverOptions = {
  getCy: () => Core | null;
  getContainer: () => HTMLElement | null;
  thresholdPx?: number;
  onHidden?: (cy: Core, size: CyContainerSize, prevSize: CyContainerSize) => void;
  onVisible?: (cy: Core, size: CyContainerSize, prevSize: CyContainerSize) => void;
  onResize?: (cy: Core, size: CyContainerSize, prevSize: CyContainerSize) => void;
};

export type CyVisibilityObserverHandle = {
  disconnect: () => void;
};

export function attachCyVisibilityObserver(opts: CyVisibilityObserverOptions): CyVisibilityObserverHandle {
  const threshold = typeof opts.thresholdPx === 'number' && Number.isFinite(opts.thresholdPx) ? opts.thresholdPx : 20;
  let lastSize: CyContainerSize = { w: 0, h: 0 };
  let raf: number | null = null;
  const observer = new ResizeObserver(() => {
    const cy = opts.getCy();
    const container = opts.getContainer();
    if (!cy || !container) return;
    if (raf !== null) {
      try {
        cancelAnimationFrame(raf);
      } catch {
        // ignore
      }
      raf = null;
    }
    raf = requestAnimationFrame(() => {
      raf = null;
      const cy2 = opts.getCy();
      const container2 = opts.getContainer();
      if (!cy2 || !container2) return;
      const size: CyContainerSize = { w: container2.clientWidth ?? 0, h: container2.clientHeight ?? 0 };
      const prev = lastSize;
      lastSize = size;
      const wasVisible = prev.w >= threshold && prev.h >= threshold;
      const nowVisible = size.w >= threshold && size.h >= threshold;

      if (wasVisible && !nowVisible) {
        try {
          opts.onHidden?.(cy2, size, prev);
        } catch {
          // ignore
        }
      }

      try {
        cy2.resize();
      } catch {
        // ignore
      }

      try {
        opts.onResize?.(cy2, size, prev);
      } catch {
        // ignore
      }

      if (!wasVisible && nowVisible) {
        try {
          opts.onVisible?.(cy2, size, prev);
        } catch {
          // ignore
        }
      }
    });
  });

  const container = opts.getContainer();
  if (container) {
    lastSize = { w: container.clientWidth ?? 0, h: container.clientHeight ?? 0 };
    observer.observe(container);
  }

  return {
    disconnect: () => {
      try {
        observer.disconnect();
      } catch {
        // ignore
      }
      if (raf !== null) {
        try {
          cancelAnimationFrame(raf);
        } catch {
          // ignore
        }
        raf = null;
      }
    }
  };
}

