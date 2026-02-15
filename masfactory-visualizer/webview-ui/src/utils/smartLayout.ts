import type { Core } from 'cytoscape';
import dagre from 'dagre';

export type SmartLayoutDirection = 'LR' | 'TB';
export type SmartLayoutPrefer = SmartLayoutDirection | 'AUTO';

export interface SmartLayoutOptions {
  preferDirection?: SmartLayoutPrefer;
  /**
   * When true, skips parameter search and uses a single fast config.
   * Useful for very large graphs.
   */
  fastOnly?: boolean;
}

type NodeMeta = {
  id: string;
  label: string;
  type: string;
  isParent: boolean;
  isCollapsed: boolean;
};

type LayoutSnapshot = {
  nodeMeta: Record<string, NodeMeta>;
  parentById: Record<string, string>;
  childrenByParent: Record<string, string[]>;
  edges: Array<{ from: string; to: string }>;
};

const ROOT_KEY = '__root__';

function isFiniteNumber(x: unknown): x is number {
  return typeof x === 'number' && Number.isFinite(x);
}

function estimateNodeSize(meta: NodeMeta): { width: number; height: number } {
  const type = String(meta.type || '');
  const label = String(meta.label || meta.id || '');

  if (type === 'entry' || type === 'exit' || type === 'Controller' || type === 'TerminateNode') {
    return { width: 70, height: 35 };
  }

  const lines = label.split('\n');
  const maxLine = Math.max(1, ...lines.map((l) => l.length));
  const charWidth = 7.2;
  const lineHeight = 14;
  const paddingX = 34;
  const paddingY = 26;
  const width = Math.max(90, Math.min(520, Math.round(maxLine * charWidth + paddingX)));
  const height = Math.max(40, Math.min(260, Math.round(lines.length * lineHeight + paddingY)));
  return { width, height };
}

function collectSnapshot(cy: Core): LayoutSnapshot {
  const nodes = cy
    .nodes()
    .filter((n) => n && n.isNode && n.isNode() && n.visible() && n.style('display') !== 'none');

  const nodeMeta: Record<string, NodeMeta> = {};
  const parentById: Record<string, string> = {};
  const childrenByParent: Record<string, string[]> = {};

  const ensure = (parentId: string) => {
    const key = parentId || ROOT_KEY;
    if (!childrenByParent[key]) childrenByParent[key] = [];
    return childrenByParent[key];
  };

  nodes.forEach((n) => {
    const id = n.id();
    const parent = String((n.data('parent') as any) || '');
    const meta: NodeMeta = {
      id,
      label: String((n.data('label') as any) || id),
      type: String((n.data('type') as any) || ''),
      isParent: !!(n.isParent && n.isParent()),
      isCollapsed: n.hasClass('collapsed')
    };
    nodeMeta[id] = meta;
    if (parent) parentById[id] = parent;
    ensure(parent).push(id);
  });

  for (const key of Object.keys(childrenByParent)) {
    childrenByParent[key].sort();
  }

  const edges = cy
    .edges()
    .filter((e) => e && e.visible() && e.source().visible() && e.target().visible())
    .map((e) => ({ from: e.source().id(), to: e.target().id() }));

  return { nodeMeta, parentById, childrenByParent, edges };
}

function directChildOfContainer(
  containerId: string | null,
  nodeId: string,
  parentById: Record<string, string>
): string | null {
  let cur = nodeId;
  for (let i = 0; i < 64; i++) {
    const parent = parentById[cur] || '';
    if (!containerId) {
      if (!parent) return cur;
    } else {
      if (parent === containerId) return cur;
    }
    if (!parent) return null;
    cur = parent;
  }
  return null;
}

function countInversions(arr: number[]): number {
  const tmp = new Array<number>(arr.length);
  const sortCount = (l: number, r: number): number => {
    if (r - l <= 1) return 0;
    const m = (l + r) >> 1;
    let inv = sortCount(l, m) + sortCount(m, r);
    let i = l;
    let j = m;
    let k = l;
    while (i < m || j < r) {
      if (j >= r || (i < m && arr[i] <= arr[j])) {
        tmp[k++] = arr[i++];
      } else {
        tmp[k++] = arr[j++];
        inv += m - i;
      }
    }
    for (let t = l; t < r; t++) arr[t] = tmp[t]!;
    return inv;
  };
  return sortCount(0, arr.length);
}

function estimateCrossingsByLayers(
  nodes: string[],
  edges: Array<{ from: string; to: string }>,
  posById: Record<string, { x: number; y: number }>,
  rankDir: SmartLayoutDirection,
  rankSep: number
): number {
  if (nodes.length === 0 || edges.length === 0) return 0;
  const primary = (id: string) => (rankDir === 'LR' ? posById[id].x : posById[id].y);
  const secondary = (id: string) => (rankDir === 'LR' ? posById[id].y : posById[id].x);
  const threshold = Math.max(20, Math.round((rankSep || 90) / 2));

  const coords = nodes
    .map((id) => ({ id, p: primary(id) }))
    .filter((o) => isFiniteNumber(o.p));
  coords.sort((a, b) => a.p - b.p);
  const layerById: Record<string, number> = {};
  let layer = 0;
  let lastP: number | null = null;
  coords.forEach((o) => {
    if (lastP === null) {
      layerById[o.id] = layer;
      lastP = o.p;
      return;
    }
    if (Math.abs(o.p - lastP) > threshold) {
      layer++;
      lastP = o.p;
    }
    layerById[o.id] = layer;
  });

  const byLayer = new Map<number, Array<{ su: number; tv: number }>>();
  for (const e of edges) {
    const lu = layerById[e.from];
    const lv = layerById[e.to];
    if (lu === undefined || lv === undefined) continue;
    if (lv !== lu + 1) continue;
    const list = byLayer.get(lu) || [];
    list.push({ su: secondary(e.from), tv: secondary(e.to) });
    byLayer.set(lu, list);
  }

  let crossings = 0;
  for (const list of byLayer.values()) {
    list.sort((a, b) => a.su - b.su);
    crossings += countInversions(list.map((x) => x.tv));
  }
  return crossings;
}

function estimateBackEdges(
  edges: Array<{ from: string; to: string }>,
  posById: Record<string, { x: number; y: number }>,
  rankDir: SmartLayoutDirection
): number {
  let back = 0;
  for (const e of edges) {
    const a = posById[e.from];
    const b = posById[e.to];
    if (!a || !b) continue;
    const delta = rankDir === 'LR' ? b.x - a.x : b.y - a.y;
    if (delta < -1) back++;
  }
  return back;
}

function estimateEdgeLength(edges: Array<{ from: string; to: string }>, posById: Record<string, { x: number; y: number }>): number {
  let sum = 0;
  for (const e of edges) {
    const a = posById[e.from];
    const b = posById[e.to];
    if (!a || !b) continue;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    sum += Math.sqrt(dx * dx + dy * dy);
  }
  return sum;
}

function runDagre(
  nodes: string[],
  edges: Array<{ from: string; to: string }>,
  sizeById: Record<string, { width: number; height: number }>,
  cfg: { rankDir: SmartLayoutDirection; ranker: string; nodeSep: number; edgeSep: number; rankSep: number }
): Record<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph({ multigraph: true });
  g.setGraph({
    rankdir: cfg.rankDir,
    ranker: cfg.ranker,
    nodesep: cfg.nodeSep,
    edgesep: cfg.edgeSep,
    ranksep: cfg.rankSep,
    marginx: 0,
    marginy: 0
  });
  g.setDefaultEdgeLabel(() => ({}));

  for (const id of nodes) {
    const s = sizeById[id] || { width: 100, height: 50 };
    g.setNode(id, { width: Math.max(10, s.width), height: Math.max(10, s.height) });
  }

  const seen = new Set<string>();
  let idx = 0;
  for (const e of edges) {
    const key = `${e.from}->${e.to}`;
    if (seen.has(key)) continue;
    seen.add(key);
    g.setEdge(e.from, e.to, {}, `e${idx++}`);
  }

  try {
    dagre.layout(g);
  } catch {
    // ignore
  }

  const pos: Record<string, { x: number; y: number }> = {};
  for (const id of nodes) {
    const n = g.node(id) as any;
    if (n && isFiniteNumber(n.x) && isFiniteNumber(n.y)) pos[id] = { x: n.x, y: n.y };
    else pos[id] = { x: 0, y: 0 };
  }

  const allZero = nodes.every((id) => pos[id].x === 0 && pos[id].y === 0);
  if (allZero) {
    const cols = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
    nodes.forEach((id, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      pos[id] = { x: col * 220, y: row * 140 };
    });
  }

  return pos;
}

type ContainerResult = {
  positions: Record<string, { x: number; y: number }>;
  size: { width: number; height: number };
  score: number;
};

function layoutContainer(
  containerId: string | null,
  snapshot: LayoutSnapshot,
  cfg: { rankDir: SmartLayoutDirection; ranker: string; nodeSep: number; edgeSep: number; rankSep: number },
  memo: Map<string, ContainerResult>
): ContainerResult {
  const key = containerId || ROOT_KEY;
  const cached = memo.get(key);
  if (cached) return cached;

  const children = (snapshot.childrenByParent[key] || []).slice();
  const childSet = new Set(children);
  const childResults: Record<string, ContainerResult> = {};

  for (const child of children) {
    const meta = snapshot.nodeMeta[child];
    const isContainer = !!(
      meta &&
      meta.isParent &&
      !meta.isCollapsed &&
      (snapshot.childrenByParent[child] || []).length > 0
    );
    if (isContainer) {
      childResults[child] = layoutContainer(child, snapshot, cfg, memo);
    }
  }

  const sizeById: Record<string, { width: number; height: number }> = {};
  const containerPadding = 70;
  for (const child of children) {
    const meta = snapshot.nodeMeta[child] || { id: child, label: child, type: '', isParent: false, isCollapsed: false };
    if (childResults[child]) {
      const sz = childResults[child].size;
      sizeById[child] = { width: Math.max(140, sz.width + containerPadding), height: Math.max(120, sz.height + containerPadding) };
    } else {
      sizeById[child] = estimateNodeSize(meta);
    }
  }

  const edgesBetween: Array<{ from: string; to: string }> = [];
  for (const e of snapshot.edges) {
    const a = directChildOfContainer(containerId, e.from, snapshot.parentById);
    const b = directChildOfContainer(containerId, e.to, snapshot.parentById);
    if (!a || !b || a === b) continue;
    if (!childSet.has(a) || !childSet.has(b)) continue;
    edgesBetween.push({ from: a, to: b });
  }

  const posByChild = children.length > 0 ? runDagre(children, edgesBetween, sizeById, cfg) : {};

  // Center around (0,0)
  let minX = Infinity,
    maxX = -Infinity,
    minY = Infinity,
    maxY = -Infinity;
  for (const child of children) {
    const p = posByChild[child];
    const s = sizeById[child] || { width: 100, height: 50 };
    minX = Math.min(minX, p.x - s.width / 2);
    maxX = Math.max(maxX, p.x + s.width / 2);
    minY = Math.min(minY, p.y - s.height / 2);
    maxY = Math.max(maxY, p.y + s.height / 2);
  }
  const cx = isFiniteNumber(minX) && isFiniteNumber(maxX) ? (minX + maxX) / 2 : 0;
  const cyy = isFiniteNumber(minY) && isFiniteNumber(maxY) ? (minY + maxY) / 2 : 0;
  for (const child of children) {
    posByChild[child].x -= cx;
    posByChild[child].y -= cyy;
  }

  const positions: Record<string, { x: number; y: number }> = {};
  if (containerId) positions[containerId] = { x: 0, y: 0 };
  for (const child of children) {
    const p = posByChild[child];
    const nested = childResults[child]?.positions;
    if (nested) {
      for (const [nid, np] of Object.entries(nested)) {
        positions[nid] = { x: p.x + np.x, y: p.y + np.y };
      }
    } else {
      positions[child] = { x: p.x, y: p.y };
    }
  }

  const contentW = Number.isFinite(minX) && Number.isFinite(maxX) ? Math.max(0, maxX - minX) : 0;
  const contentH = Number.isFinite(minY) && Number.isFinite(maxY) ? Math.max(0, maxY - minY) : 0;
  const size = { width: Math.max(240, Math.round(contentW + 90)), height: Math.max(180, Math.round(contentH + 90)) };

  const crossings = estimateCrossingsByLayers(children, edgesBetween, posByChild, cfg.rankDir, cfg.rankSep);
  const backEdges = estimateBackEdges(edgesBetween, posByChild, cfg.rankDir);
  const edgeLen = estimateEdgeLength(edgesBetween, posByChild);
  const localScore = crossings * 1000 + backEdges * 220 + edgeLen * 0.08;
  const nestedScore = Object.values(childResults).reduce((acc, r) => acc + (r.score || 0), 0);

  const result: ContainerResult = { positions, size, score: localScore + nestedScore };
  memo.set(key, result);
  return result;
}

export function applySmartLayout(cy: Core, options: SmartLayoutOptions = {}): { direction: SmartLayoutDirection } {
  const snapshot = collectSnapshot(cy);
  const nodeCount = Object.keys(snapshot.nodeMeta).length;
  const edgeCount = snapshot.edges.length;

  const isLarge = nodeCount > 220 || edgeCount > 520;
  const prefer = (options.preferDirection || 'AUTO') as SmartLayoutPrefer;
  const rankDirs: SmartLayoutDirection[] =
    prefer === 'LR' || prefer === 'TB' ? [prefer] : (['LR', 'TB'] as SmartLayoutDirection[]);
  const rankers = options.fastOnly || isLarge ? ['network-simplex'] : ['network-simplex', 'tight-tree', 'longest-path'];

  const baseNodeSep = nodeCount > 120 ? 90 : nodeCount > 60 ? 75 : 60;
  const baseRankSep = nodeCount > 120 ? 120 : nodeCount > 60 ? 105 : 90;

  let best: { score: number; cfg: any; result: ContainerResult } | null = null;
  for (const rankDir of rankDirs) {
    for (const ranker of rankers) {
      const cfg = { rankDir, ranker, nodeSep: baseNodeSep, edgeSep: 26, rankSep: baseRankSep };
      const memo = new Map<string, ContainerResult>();
      const result = layoutContainer(null, snapshot, cfg, memo);
      const score = isFiniteNumber(result.score) ? result.score : Number.POSITIVE_INFINITY;
      if (!best || score < best.score) best = { score, cfg, result };
    }
  }

  if (!best) return { direction: 'LR' };

  // Prefer LR unless meaningfully worse (stable reading direction).
  if (prefer === 'AUTO' && best.cfg.rankDir !== 'LR') {
    const cfg = { ...best.cfg, rankDir: 'LR' as SmartLayoutDirection };
    const memo = new Map<string, ContainerResult>();
    const result = layoutContainer(null, snapshot, cfg, memo);
    const score = isFiniteNumber(result.score) ? result.score : Number.POSITIVE_INFINITY;
    if (score <= best.score * 1.05) best = { score, cfg, result };
  }

  const positions = best.result.positions;
  cy.batch(() => {
    for (const [id, p] of Object.entries(positions)) {
      const n = cy.getElementById(id);
      if (!n || n.empty()) continue;
      if (!isFiniteNumber(p.x) || !isFiniteNumber(p.y)) continue;
      try {
        n.position({ x: p.x, y: p.y });
      } catch {
        // ignore
      }
    }
  });

  return { direction: best.cfg.rankDir as SmartLayoutDirection };
}

