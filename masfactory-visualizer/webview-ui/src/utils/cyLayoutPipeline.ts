import type { Core } from 'cytoscape';
import { applySmartLayout } from './smartLayout';
import { ensureCyNonDegenerateLayout, isCyLayoutDegenerate } from './cyLayoutFallback';

export type SmartDagreLayoutOptions = {
  preferDirection?: 'AUTO' | 'TB' | 'LR';
  fitPadding?: number;
  dagreRankDir?: 'TB' | 'LR';
  dagreNodeSep?: number;
  dagreRankSep?: number;
};

export function safeFit(cy: Core, padding = 30): void {
  const doFit = () => {
    try {
      cy.resize();
    } catch {
      // ignore
    }
    try {
      // Be explicit about the collection to avoid any arg-overload ambiguity.
      cy.fit(cy.elements(), padding);
    } catch {
      // ignore
    }
  };

  doFit();
  try {
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(() => doFit());
    }
  } catch {
    // ignore
  }
}

export function applySmartDagreLayout(cy: Core, opts?: SmartDagreLayoutOptions): void {
  const preferDirection = opts?.preferDirection ?? 'AUTO';
  const fitPadding = typeof opts?.fitPadding === 'number' && Number.isFinite(opts.fitPadding) ? opts.fitPadding : 30;
  const dagreRankDir = opts?.dagreRankDir ?? 'TB';
  const dagreNodeSep = typeof opts?.dagreNodeSep === 'number' && Number.isFinite(opts.dagreNodeSep) ? opts.dagreNodeSep : 40;
  const dagreRankSep = typeof opts?.dagreRankSep === 'number' && Number.isFinite(opts.dagreRankSep) ? opts.dagreRankSep : 65;

  try {
    applySmartLayout(cy, { preferDirection });
  } catch {
    // ignore
  }

  if (isCyLayoutDegenerate(cy)) {
    try {
      cy.layout({ name: 'dagre', rankDir: dagreRankDir, nodeSep: dagreNodeSep, rankSep: dagreRankSep }).run();
    } catch {
      // ignore
    }
  }

  if (isCyLayoutDegenerate(cy)) {
    ensureCyNonDegenerateLayout(cy);
  }

  safeFit(cy, fitPadding);
}
