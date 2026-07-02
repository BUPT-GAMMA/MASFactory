<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch, nextTick } from 'vue';
import { useVibeStore, type VibeEdgeSpec, type VibeGraphDesign, type VibeLayout, type VibeNodeSpec, type VibeNodeType } from '../stores/vibe';
import { postMessage } from '../bridge/vscode';
import VibeGraphEditor from './VibeGraphEditor.vue';
import KeyValueEditor from './KeyValueEditor.vue';
import { useUiStore } from '../stores/ui';
import { isSameLevelEdge, validateGraphDesign } from '../utils/vibeValidation';
import { AML_ROOT_ATTRIBUTES_XML_KEY } from '../utils/amlGraphDesign';
import {
  baseNameForType,
  defaultSpec,
  findNodeSpec,
  generateUniqueName,
  isInternalNodeId
} from '../utils/vibeEditorHelpers';

const vibe = useVibeStore();
const ui = useUiStore();
const props = withDefaults(defineProps<{ title?: string }>(), {
  title: 'Vibe Graphing'
});

type Selection =
  | { kind: 'none' }
  | { kind: 'node'; id: string }
  | { kind: 'edge'; index: number };

const selection = ref<Selection>({ kind: 'none' });

const doc = computed(() => vibe.activeDoc);
const uri = computed(() => doc.value?.uri || null);
const graph = computed(() => vibe.activeGraph);
const canUndo = computed(() => !!uri.value && vibe.canUndo(uri.value));
const canRedo = computed(() => !!uri.value && vibe.canRedo(uri.value));
const isAmlDoc = computed(() => doc.value?.documentKind === 'aml');
const canEditSourceGraph = computed(() => {
  const d = doc.value;
  return !!d && !!graph.value && !d.parseError && (d.documentKind === 'graph_design' || d.documentKind === 'aml');
});
const isStructureReadonly = computed(() => !canEditSourceGraph.value);

const graphFormat = computed<'v3' | 'legacy'>(() => {
  const g = graph.value;
  const nodes = g && Array.isArray(g.Nodes) ? g.Nodes : [];
  const hasV3 = nodes.some(
    (n) => !!n && typeof n === 'object' && ('code' in (n as any) || 'branches' in (n as any))
  );
  const hasLegacy = nodes.some(
    (n) =>
      !!n &&
      typeof n === 'object' &&
      ('forward_body' in (n as any) || 'condition_bindings' in (n as any))
  );
  if (hasV3 && !hasLegacy) return 'v3';
  if (hasLegacy && !hasV3) return 'legacy';
  return hasV3 ? 'v3' : 'legacy';
});

const palette: Array<{ type: VibeNodeType; label: string }> = [
  { type: 'Agent', label: 'Agent' },
  { type: 'CustomNode', label: 'CustomNode' },
  { type: 'Graph', label: 'Graph' },
  { type: 'Loop', label: 'Loop' },
  { type: 'LogicSwitch', label: 'LogicSwitch' },
  { type: 'AgentSwitch', label: 'AgentSwitch' }
];

function onDragStart(e: DragEvent, type: string) {
  if (isStructureReadonly.value) return;
  try {
    e.dataTransfer?.setData('application/x-masfactory-visualizer-vibe-component', type);
    e.dataTransfer?.setData('text/plain', type);
    e.dataTransfer!.effectAllowed = 'copy';
  } catch {
    // ignore
  }
}

function onDropComponent(payload: { componentType: string; x: number; y: number; parent?: string }) {
  if (isStructureReadonly.value) return;
  const g = graph.value;
  const u = uri.value;
  if (!g || !u) return;
  const type = String(payload.componentType || '') as VibeNodeType;
  const base = baseNameForType(type);
  const parent = payload.parent && canEditNodeName(payload.parent) ? payload.parent : undefined;
  const externalOwner = parent ? externalRefOwnerForNodeName(parent) : null;
  const nameBase = externalOwner ? `${externalOwner.name}__${base}` : base;
  const name = generateUniqueName(g, nameBase);
  const spec = defaultSpec(type, name, parent, graphFormat.value);
  if (externalOwner) {
    markExternalRefNode(spec, externalOwner, localNameForExternalNode(name, externalOwner.name));
  }
  vibe.addNode(u, spec, { x: payload.x, y: payload.y });
  selection.value = { kind: 'node', id: name };
}

function onSelectNode(nodeId: string) {
  attributesError.value = null;
  selection.value = { kind: 'node', id: nodeId };
}

function onSelectEdge(edgeIndex: number) {
  attributesError.value = null;
  selection.value = { kind: 'edge', index: edgeIndex };
}

function onClearSelection() {
  attributesError.value = null;
  selection.value = { kind: 'none' };
}

function onNodePosition(nodeId: string, pos: { x: number; y: number }) {
  const u = uri.value;
  if (!u) return;
  vibe.updateLayout(u, nodeId, pos);
}

function onLayoutSnapshot(payload: { docUri: string; sig: string; reason: 'auto' | 'force' | 'recovery'; layout: VibeLayout }) {
  const active = uri.value;
  const target = String(payload?.docUri || '').trim() || active;
  if (!target) return;
  // Ignore stale async snapshots for a different document.
  if (active && target !== active) return;
  vibe.applyAutoLayout(target, payload.layout, payload.sig);
}

function onNodeParentChanged(payload: { nodeId: string; parent?: string }) {
  if (isStructureReadonly.value || !canEditNodeName(payload.nodeId)) return;
  const nextParent = normalizeParentForNode(payload.nodeId, payload.parent);
  if (payload.parent && !nextParent) return;
  const u = uri.value;
  if (!u) return;
  vibe.updateNodeParent(u, payload.nodeId, nextParent);
}

function changeCurrentNodeType(nextType: string): void {
  if (!selectedNodeEditable.value) return;
  const u = uri.value;
  const n = selectedNode.value;
  if (!u || !n) return;
  vibe.changeNodeType(u, n.name, nextType);
}

function changeCurrentNodeParent(nextParent: string): void {
  if (!selectedNodeEditable.value) return;
  const u = uri.value;
  const n = selectedNode.value;
  if (!u || !n) return;
  vibe.updateNodeParent(u, n.name, normalizeParentForNode(n.name, nextParent));
}

function onCreateEdge(payload: { from: string; to: string }) {
  if (isStructureReadonly.value || !canEditEndpoint(payload.from) || !canEditEndpoint(payload.to)) return;
  const g = graph.value;
  const u = uri.value;
  if (!g || !u) return;
  const idx = Array.isArray(g.Edges) ? g.Edges.length : 0;
  const edge: VibeEdgeSpec = { from: payload.from, to: payload.to };
  const externalOwner = sharedExternalRefOwnerForEndpoints(payload.from, payload.to);
  if (externalOwner) {
    markExternalRefEdge(edge, externalOwner);
  }
  vibe.addEdge(u, edge);
  selection.value = { kind: 'edge', index: idx };
}

const selectedNode = computed(() => {
  const g = graph.value;
  if (!g) return null;
  if (selection.value.kind !== 'node') return null;
  return findNodeSpec(g, selection.value.id);
});

function isDerivedNodeSpec(node: VibeNodeSpec | null | undefined): boolean {
  return !!node && !!(node as any).__aml_from_implementation;
}

function isExternalRefNodeSpec(node: VibeNodeSpec | null | undefined): boolean {
  return !!node && !!(node as any).__aml_from_ref;
}

function isExternalRefContainer(node: VibeNodeSpec | null | undefined): boolean {
  return !!node && !!(node as any).__aml_ref_filePath && !!(node as any).__aml_ref_graphId;
}

function endpointBase(endpoint: string): string {
  const value = String(endpoint || '');
  const idx = value.indexOf('.');
  return idx === -1 ? value : value.slice(0, idx);
}

function canEditNodeSpec(node: VibeNodeSpec | null | undefined): boolean {
  const name = String((node as any)?.name || '');
  return canEditSourceGraph.value && !!node && !!name && !isInternalNodeId(name) && !isDerivedNodeSpec(node);
}

function canEditNodeName(nodeName: string): boolean {
  const g = graph.value;
  if (!g) return false;
  return canEditNodeSpec(findNodeSpec(g, endpointBase(nodeName)));
}

function canEditEndpoint(endpoint: string): boolean {
  const ep = String(endpoint || '').trim();
  if (!canEditSourceGraph.value || !ep) return false;
  if (ep === 'entry' || ep === 'exit') return true;
  const idx = ep.indexOf('.');
  if (idx !== -1) {
    const suffix = ep.slice(idx + 1);
    if (suffix === 'entry' || suffix === 'exit' || suffix === 'controller' || suffix === 'terminate') {
      return canEditNodeName(ep.slice(0, idx));
    }
  }
  return canEditNodeName(ep);
}

function localNameForExternalNode(nodeName: string, ownerName: string): string {
  const name = String(nodeName || '').trim();
  const prefix = `${ownerName}__`;
  return name.startsWith(prefix) ? name.slice(prefix.length) : name;
}

function externalRefOwnerForNodeName(nodeName: string): VibeNodeSpec | null {
  const g = graph.value;
  if (!g) return null;
  const base = endpointBase(nodeName);
  const node = findNodeSpec(g, base);
  if (!node) return null;
  if (isExternalRefContainer(node) && !isExternalRefNodeSpec(node)) return node;
  const ownerName = String((node as any).__aml_external_parent || '').trim();
  if (ownerName) {
    const owner = findNodeSpec(g, ownerName);
    return isExternalRefContainer(owner) ? owner : null;
  }
  const parent = typeof node.parent === 'string' && node.parent.trim() ? node.parent.trim() : '';
  return parent ? externalRefOwnerForNodeName(parent) : null;
}

function externalRefOwnerForEndpoint(endpoint: string): VibeNodeSpec | null {
  const g = graph.value;
  if (!g) return null;
  const ep = String(endpoint || '').trim();
  if (!ep || ep === 'entry' || ep === 'exit') return null;
  const idx = ep.indexOf('.');
  if (idx !== -1) {
    const base = ep.slice(0, idx);
    const suffix = ep.slice(idx + 1);
    if (suffix === 'entry' || suffix === 'exit' || suffix === 'controller' || suffix === 'terminate') {
      const node = findNodeSpec(g, base);
      return isExternalRefContainer(node) ? node : externalRefOwnerForNodeName(base);
    }
  }
  const node = findNodeSpec(g, endpointBase(ep));
  return isExternalRefNodeSpec(node) ? externalRefOwnerForNodeName(ep) : null;
}

function sharedExternalRefOwnerForEndpoints(from: string, to: string): VibeNodeSpec | null {
  const fromOwner = externalRefOwnerForEndpoint(from);
  const toOwner = externalRefOwnerForEndpoint(to);
  if (!fromOwner || !toOwner) return null;
  return fromOwner.name === toOwner.name ? fromOwner : null;
}

function markExternalRefNode(spec: VibeNodeSpec, owner: VibeNodeSpec, localName: string): void {
  const ownerAny = owner as any;
  (spec as any).__aml_from_ref = true;
  (spec as any).__aml_ref = ownerAny.ref || ownerAny.__aml_ref;
  (spec as any).__aml_ref_graphId = ownerAny.__aml_ref_graphId;
  (spec as any).__aml_ref_filePath = ownerAny.__aml_ref_filePath;
  (spec as any).__aml_ref_line = ownerAny.__aml_ref_line;
  (spec as any).__aml_external_parent = owner.name;
  (spec as any).__aml_external_local_name = localName || spec.name;
  if (typeof spec.label === 'string' && spec.label === spec.name) {
    spec.label = localName || spec.name;
  }
}

function markExternalRefEdge(edge: VibeEdgeSpec, owner: VibeNodeSpec): void {
  const ownerAny = owner as any;
  (edge as any).__aml_from_ref = true;
  (edge as any).__aml_ref = ownerAny.ref || ownerAny.__aml_ref;
  (edge as any).__aml_ref_graphId = ownerAny.__aml_ref_graphId;
  (edge as any).__aml_ref_filePath = ownerAny.__aml_ref_filePath;
  (edge as any).__aml_ref_line = ownerAny.__aml_ref_line;
  (edge as any).__aml_external_parent = owner.name;
}

function normalizeParentForNode(nodeName: string, rawParent?: string): string | undefined {
  const g = graph.value;
  if (!g) return undefined;
  const parent = String(rawParent || '').trim();
  const owner = externalRefOwnerForNodeName(nodeName);
  if (!owner) {
    if (!parent || parent === 'root') return undefined;
    const parentNode = findNodeSpec(g, parent);
    if (isExternalRefContainer(parentNode) || isExternalRefNodeSpec(parentNode)) return undefined;
    return parent;
  }
  if (!parent || parent === 'root') return owner.name;
  if (parent === owner.name) return owner.name;
  const parentOwner = externalRefOwnerForNodeName(parent);
  return parentOwner?.name === owner.name ? parent : owner.name;
}

const parentOptions = computed(() => {
  const g = graph.value;
  if (!g) return ['root'];
  const nodes = Array.isArray(g.Nodes) ? g.Nodes : [];
  const selectedExternalOwner =
    selection.value.kind === 'node' ? externalRefOwnerForNodeName(selection.value.id) : null;
  if (selectedExternalOwner) {
    const opts: string[] = [selectedExternalOwner.name];
    for (const n of nodes) {
      if (!n || typeof n !== 'object') continue;
      const t = String((n as any).type || '');
      if (t !== 'Graph' && t !== 'Loop') continue;
      const name = String((n as any).name || '').trim();
      if (!name || name === selectedExternalOwner.name) continue;
      const owner = externalRefOwnerForNodeName(name);
      if (owner?.name === selectedExternalOwner.name) opts.push(name);
    }
    return Array.from(new Set(opts));
  }
  const opts: string[] = ['root'];
  for (const n of nodes) {
    if (!n || typeof n !== 'object') continue;
    const t = String((n as any).type || '');
    if (t !== 'Graph' && t !== 'Loop') continue;
    if (isDerivedNodeSpec(n as VibeNodeSpec)) continue;
    if (isExternalRefContainer(n as VibeNodeSpec) || isExternalRefNodeSpec(n as VibeNodeSpec)) continue;
    const name = String((n as any).name || '').trim();
    if (!name) continue;
    opts.push(name);
  }
  return Array.from(new Set(opts));
});

const selectedNodeIsInternal = computed(() => {
  return selection.value.kind === 'node' ? isInternalNodeId(selection.value.id) : false;
});

const selectedNodeIsDerived = computed(() => isDerivedNodeSpec(selectedNode.value));
const selectedNodeEditable = computed(() => canEditNodeSpec(selectedNode.value));
const canEditRootAttributes = computed(() => isAmlDoc.value && canEditSourceGraph.value);

const customNodeUsesCode = computed(() => {
  const n = selectedNode.value as any;
  if (!n) return false;
  const t = String(n.type || '');
  if (t !== 'CustomNode') return false;
  if (n.code !== undefined) return true;
  return graphFormat.value === 'v3' && n.forward_body === undefined;
});

const attributesError = ref<string | null>(null);
const rootAttributesError = ref<string | null>(null);
const warningsCollapsed = ref(false);

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}

// --- Layout sizing (Details panel width) ---
const layoutRef = ref<HTMLDivElement | null>(null);
const detailWidth = ref<number>(340);
const DETAIL_WIDTH_KEY = 'masfactory-visualizer.vibe.detailWidth';
const DETAIL_WIDTH_MIN = 280;
const DETAIL_CANVAS_MIN = 240;
const DETAIL_WIDTH_MAX = 920;
let resizeDetailMove: ((e: MouseEvent) => void) | null = null;
let resizeDetailUp: ((e: MouseEvent) => void) | null = null;

function loadDetailWidth(): void {
  try {
    const raw = localStorage.getItem(DETAIL_WIDTH_KEY);
    const n = Number(raw);
    if (Number.isFinite(n) && n > 0) {
      detailWidth.value = clamp(Math.round(n), DETAIL_WIDTH_MIN, DETAIL_WIDTH_MAX);
    }
  } catch {
    // ignore
  }
}

function persistDetailWidth(): void {
  try {
    localStorage.setItem(DETAIL_WIDTH_KEY, String(detailWidth.value));
  } catch {
    // ignore
  }
}

function resetDetailWidth(): void {
  detailWidth.value = 340;
  persistDetailWidth();
}

function startResizeDetail(e: MouseEvent): void {
  if (e.button !== 0) return;
  if (!layoutRef.value) return;
  e.preventDefault();
  e.stopPropagation();

  const root = layoutRef.value;
  const rect = root.getBoundingClientRect();
  const maxFromContainer = Math.max(
    DETAIL_WIDTH_MIN,
    Math.floor(rect.width - 220 - DETAIL_CANVAS_MIN)
  );
  const max = clamp(maxFromContainer, DETAIL_WIDTH_MIN, DETAIL_WIDTH_MAX);

  const applyAt = (clientX: number) => {
    const r = root.getBoundingClientRect();
    const next = clamp(Math.round(r.right - clientX), DETAIL_WIDTH_MIN, max);
    detailWidth.value = next;
  };

  const prevCursor = document.body.style.cursor;
  const prevUserSelect = document.body.style.userSelect;
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';

  applyAt(e.clientX);

  resizeDetailMove = (evt: MouseEvent) => {
    applyAt(evt.clientX);
  };
  resizeDetailUp = () => {
    if (resizeDetailMove) window.removeEventListener('mousemove', resizeDetailMove, true);
    if (resizeDetailUp) window.removeEventListener('mouseup', resizeDetailUp, true);
    resizeDetailMove = null;
    resizeDetailUp = null;
    document.body.style.cursor = prevCursor;
    document.body.style.userSelect = prevUserSelect;
    persistDetailWidth();
  };

  window.addEventListener('mousemove', resizeDetailMove, true);
  window.addEventListener('mouseup', resizeDetailUp, true);
}

const layoutStyle = computed(() => {
  const w = clamp(detailWidth.value, DETAIL_WIDTH_MIN, DETAIL_WIDTH_MAX);
  if (isStructureReadonly.value) {
    return {
      gridTemplateColumns: `minmax(0, 1fr) ${w}px`
    } as Record<string, string>;
  }
  return {
    gridTemplateColumns: `220px minmax(0, 1fr) ${w}px`
  } as Record<string, string>;
});

// --- Large text modal editor (Agent.instructions, Agent.prompt_template) ---
type LargeEditorField = 'instructions' | 'prompt_template';
const editorModalOpen = ref(false);
const editorField = ref<LargeEditorField>('instructions');
const editorNodeName = ref<string>('');
const editorTitle = ref<string>('');
const editorDraft = ref<string>('');
const editorReadonly = ref(false);
const editorTextareaRef = ref<HTMLTextAreaElement | null>(null);

function openLargeEditor(field: LargeEditorField): void {
  const n = selectedNode.value;
  if (!n) return;
  if (n.type !== 'Agent') return;
  editorField.value = field;
  editorNodeName.value = String(n.name || '');
  editorTitle.value = `${field} — ${editorNodeName.value}`;
  editorDraft.value = String((n as any)[field] || '');
  editorReadonly.value = !selectedNodeEditable.value;
  editorModalOpen.value = true;
  void nextTick(() => {
    try {
      editorTextareaRef.value?.focus();
    } catch {
      // ignore
    }
  });
}

function closeLargeEditor(): void {
  editorModalOpen.value = false;
}

function updateNodeByName(nodeName: string, patch: Partial<VibeNodeSpec>): void {
  if (isStructureReadonly.value || !canEditNodeName(nodeName)) return;
  const u = uri.value;
  const g = graph.value;
  if (!u || !g || !nodeName) return;
  const nodes = Array.isArray(g.Nodes) ? g.Nodes : [];
  const cur = nodes.find((it) => it && it.name === nodeName) || null;
  if (!cur) return;
  const next = { ...cur, ...patch } as VibeNodeSpec;
  vibe.updateNodeSpec(u, nodeName, next);
}

function saveLargeEditor(): void {
  if (editorReadonly.value) {
    editorModalOpen.value = false;
    return;
  }
  const nodeName = editorNodeName.value;
  if (!nodeName) {
    editorModalOpen.value = false;
    return;
  }
  const patch: Partial<VibeNodeSpec> = { [editorField.value]: editorDraft.value } as any;
  updateNodeByName(nodeName, patch);
  editorModalOpen.value = false;
}

const selectedEdge = computed(() => {
  const g = graph.value;
  if (!g) return null;
  if (selection.value.kind !== 'edge') return null;
  const idx = selection.value.index;
  const edges = Array.isArray(g.Edges) ? g.Edges : [];
  const e = edges[idx];
  return e ? { ...e, _index: idx } : null;
});

const selectedEdgeIsDerived = computed(
  () => !!(selectedEdge.value as any)?.__aml_from_implementation
);
const selectedEdgeEditable = computed(() => canEditSourceGraph.value && !selectedEdgeIsDerived.value);
const detailReadonly = computed(() => {
  if (selection.value.kind === 'none') return isAmlDoc.value && !canEditRootAttributes.value;
  if (selection.value.kind === 'node') return !selectedNodeEditable.value;
  if (selection.value.kind === 'edge') return !selectedEdgeEditable.value;
  return isStructureReadonly.value;
});

function updateSelectedNode(patch: Partial<VibeNodeSpec>) {
  if (!selectedNodeEditable.value) return;
  const u = uri.value;
  const g = graph.value;
  const n = selectedNode.value;
  if (!u || !g || !n) return;
  const next = { ...n, ...patch };
  vibe.updateNodeSpec(u, n.name, next);
}

function numericLocation(value: unknown): number | undefined {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : undefined;
}

function findNavigationNode(nodeId: string): VibeNodeSpec | null {
  const g = graph.value;
  if (!g || !nodeId) return null;
  const direct = findNodeSpec(g, nodeId);
  if (direct) return direct;
  return findNodeSpec(g, endpointBase(nodeId));
}

function onNodeDoubleClick(nodeId: string) {
  const node = findNavigationNode(nodeId) as any;
  if (!node) return;

  const implementationFilePath = String(node.__aml_implementation_filePath || '').trim();
  if (implementationFilePath) {
    postMessage({
      type: 'openFileLocation',
      filePath: implementationFilePath,
      line: numericLocation(node.__aml_implementation_line),
      column: numericLocation(node.__aml_implementation_column),
      targetTab: 'preview'
    });
    ui.setActiveTab('preview');
    return;
  }

  const refFilePath = String(node.__aml_ref_filePath || '').trim();
  if (refFilePath) {
    postMessage({
      type: 'openFileLocation',
      filePath: refFilePath,
      line: numericLocation(node.__aml_ref_line),
      targetTab: 'drag',
      amlGraphId: String(node.__aml_ref_graphId || '').trim() || undefined
    });
    ui.setActiveTab('drag');
  }
}

const selectedAttributesText = computed(() => {
  const n = selectedNode.value as any;
  if (!n) return '';
  try {
    const raw = n.attributes ?? {};
    return JSON.stringify(raw, null, 2);
  } catch {
    return String(n.attributes ?? '');
  }
});

const rootAttributesText = computed(() => {
  const g = graph.value as any;
  if (!g || !Object.prototype.hasOwnProperty.call(g, AML_ROOT_ATTRIBUTES_XML_KEY)) return '';
  return String(g[AML_ROOT_ATTRIBUTES_XML_KEY] || '');
});

function validateAttributesXml(xml: string): string | null {
  const text = String(xml || '').trim();
  if (!text) return null;
  try {
    const parsed = new DOMParser().parseFromString(text, 'application/xml');
    const parserError = parsed.getElementsByTagName('parsererror')[0];
    if (parserError) return parserError.textContent?.trim() || 'Invalid XML.';
    const root = parsed.documentElement;
    const name = String(root?.localName || root?.nodeName || '');
    if (name !== 'attributes') return 'Root graph attributes must be an <attributes> element.';
    return null;
  } catch (err) {
    return err instanceof Error ? err.message : String(err);
  }
}

function commitRootAttributesXml(rawText: string) {
  if (isStructureReadonly.value || !isAmlDoc.value) return;
  const u = uri.value;
  if (!u) return;
  const text = String(rawText ?? '').trim();
  const err = validateAttributesXml(text);
  if (err) {
    rootAttributesError.value = err;
    return;
  }
  rootAttributesError.value = null;
  vibe.updateRootAttributesXml(u, text);
}

function commitAttributes(rawText: string) {
  if (!selectedNodeEditable.value) return;
  const text = String(rawText ?? '').trim();
  if (!text) {
    attributesError.value = null;
    updateSelectedNode({ attributes: {} });
    return;
  }
  try {
    const parsed = JSON.parse(text);
    attributesError.value = null;
    updateSelectedNode({ attributes: parsed });
  } catch (err) {
    attributesError.value = err instanceof Error ? err.message : String(err);
  }
}

const selectedToolsText = computed(() => {
  const n = selectedNode.value as any;
  if (!n) return '';
  const raw = n.tools;
  if (raw === undefined || raw === null) return '';
  if (Array.isArray(raw)) {
    return raw
      .map((v) => String(v ?? '').trim())
      .filter(Boolean)
      .join('\n');
  }
  if (typeof raw === 'string') return raw;
  try {
    return JSON.stringify(raw, null, 2);
  } catch {
    return String(raw);
  }
});

function commitTools(rawText: string) {
  if (!selectedNodeEditable.value) return;
  const text = String(rawText ?? '').trim();
  if (!text) {
    // Keep the field absent when empty to avoid injecting optional fields.
    updateSelectedNode({ tools: undefined });
    return;
  }

  let list: string[] = [];
  if (text.startsWith('[')) {
    try {
      const parsed = JSON.parse(text);
      if (Array.isArray(parsed)) {
        list = parsed.map((v) => String(v ?? '').trim()).filter(Boolean);
      }
    } catch {
      // fall through to line parsing
    }
  }

  if (list.length === 0) {
    list = text
      .split(/[\n,]+/g)
      .map((s) => String(s ?? '').trim())
      .filter(Boolean);
  }

  const seen = new Set<string>();
  const deduped: string[] = [];
  for (const item of list) {
    if (seen.has(item)) continue;
    seen.add(item);
    deduped.push(item);
  }

  updateSelectedNode({ tools: deduped });
}

function updateSelectedEdge(patch: Partial<VibeEdgeSpec>) {
  if (!selectedEdgeEditable.value) return;
  const u = uri.value;
  const g = graph.value;
  const e = selectedEdge.value as any;
  if (!u || !g || !e) return;
  const idx = e._index as number;
  const edges = Array.isArray(g.Edges) ? g.Edges : [];
  if (!edges[idx]) return;
  vibe.updateEdgeAt(u, idx, { ...(edges[idx] as any), ...patch });
}

function save() {
  if (isStructureReadonly.value) return;
  const u = uri.value;
  if (!u) return;
  vibe.requestSave(u);
}

function reloadFromFile() {
  const u = uri.value;
  if (!u) return;
  selection.value = { kind: 'none' };
  vibe.requestReload(u);
}

function undo() {
  if (isStructureReadonly.value) return;
  const u = uri.value;
  if (!u) return;
  vibe.undo(u);
}

function redo() {
  if (isStructureReadonly.value) return;
  const u = uri.value;
  if (!u) return;
  vibe.redo(u);
}

function isEditableElement(el: unknown): boolean {
  const node = el as HTMLElement | null;
  if (!node) return false;
  const tag = String(node.tagName || '').toUpperCase();
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if ((node as any).isContentEditable) return true;
  return false;
}

function shouldHandleGlobalHotkey(evt: KeyboardEvent): boolean {
  if (ui.activeTab !== 'vibe') return false;
  if (evt.defaultPrevented) return false;
  const t = evt.target as any;
  const active = document.activeElement as any;
  if (isEditableElement(t) || isEditableElement(active)) return false;
  return true;
}

function onKeyDown(evt: KeyboardEvent) {
  if (editorModalOpen.value && evt.key === 'Escape') {
    closeLargeEditor();
    evt.preventDefault();
    evt.stopPropagation();
    return;
  }
  if (editorModalOpen.value && (evt.metaKey || evt.ctrlKey) && evt.key === 'Enter') {
    saveLargeEditor();
    evt.preventDefault();
    evt.stopPropagation();
    return;
  }
  if (!shouldHandleGlobalHotkey(evt)) return;
  const key = String(evt.key || '');
  const lower = key.toLowerCase();
  const mod = evt.metaKey || evt.ctrlKey;

  if (mod && !evt.shiftKey && lower === 'z') {
    if (canUndo.value) undo();
    evt.preventDefault();
    evt.stopPropagation();
    return;
  }

  if (mod && ((evt.shiftKey && lower === 'z') || lower === 'y')) {
    if (canRedo.value) redo();
    evt.preventDefault();
    evt.stopPropagation();
    return;
  }

  if (key === 'Delete' || key === 'Backspace') {
    if (selection.value.kind === 'node') {
      if (!selectedNodeIsInternal.value) deleteCurrentNode();
      evt.preventDefault();
      evt.stopPropagation();
      return;
    }
    if (selection.value.kind === 'edge') {
      deleteCurrentEdge();
      evt.preventDefault();
      evt.stopPropagation();
    }
  }
}

onMounted(() => {
  loadDetailWidth();
  window.addEventListener('keydown', onKeyDown, true);
});

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown, true);
  if (resizeDetailMove) window.removeEventListener('mousemove', resizeDetailMove, true);
  if (resizeDetailUp) window.removeEventListener('mouseup', resizeDetailUp, true);
  resizeDetailMove = null;
  resizeDetailUp = null;
});

watch(
  () => graph.value,
  (g) => {
    if (!g) {
      selection.value = { kind: 'none' };
      return;
    }
    if (selection.value.kind === 'node') {
      const id = selection.value.id;
      if (selectedNodeIsInternal.value) return;
      const found = findNodeSpec(g, id);
      if (!found) selection.value = { kind: 'none' };
      return;
    }
    if (selection.value.kind === 'edge') {
      const edges = Array.isArray(g.Edges) ? g.Edges : [];
      if (selection.value.index < 0 || selection.value.index >= edges.length) {
        selection.value = { kind: 'none' };
      }
    }
  }
);

function renameCurrentNode(nextName: string) {
  if (!selectedNodeEditable.value) return;
  const u = uri.value;
  const n = selectedNode.value;
  if (!u || !n) return;
  const name = String(nextName || '').trim();
  if (!name || name === n.name) return;
  vibe.renameNode(u, n.name, name);
  selection.value = { kind: 'node', id: name };
}

function deleteCurrentNode() {
  if (!selectedNodeEditable.value) return;
  const u = uri.value;
  const n = selectedNode.value;
  if (!u || !n) return;
  vibe.deleteNode(u, n.name);
  selection.value = { kind: 'none' };
}

function deleteCurrentEdge() {
  if (!selectedEdgeEditable.value) return;
  const u = uri.value;
  const e = selectedEdge.value as any;
  if (!u || !e) return;
  vibe.deleteEdge(u, Number(e._index));
  selection.value = { kind: 'none' };
}

const helpText = computed(() => {
  if (!doc.value) return 'Open an AML file or legacy graph design JSON to start.';
  if (isAmlDoc.value && doc.value.parseError) return `Invalid AML: ${doc.value.parseError}`;
  if (isAmlDoc.value && !graph.value) return 'This AML file does not contain a previewable root graph.';
  if (doc.value.parseError) return `Invalid JSON: ${doc.value.parseError}`;
  if (!graph.value) return 'This JSON file is not recognized as a legacy graph design.';
  return '';
});

const edgeSummary = computed(() => {
  const e = selectedEdge.value as any;
  if (!e) return '';
  return `${e.from} → ${e.to}`;
});

function pullKeysDefaultHint(node: VibeNodeSpec): string {
  const t = String(node.type || 'Agent');
  if (t === 'Agent') return 'Default: Agent nodes do not inherit parent graph attributes (equivalent to `{}`).';
  return 'Default: inherits all attributes from the parent graph.';
}

function pullKeysEmptyHint(): string {
  return 'Empty (`{}`): inherit nothing from the parent graph.';
}

function pushKeysDefaultHint(node: VibeNodeSpec): string {
  const t = String(node.type || 'Agent');
  if (t === 'Agent') return 'Default: Agent nodes do not write back attributes (equivalent to `{}`).';
  return 'Default: write-back follows `pull_keys` (inherit → existing keys only; custom → those keys; empty → none).';
}

function pushKeysEmptyHint(): string {
  return 'Empty (`{}`): write back nothing.';
}

function edgeConditionHint(): string {
  return 'Required for Switch outgoing edges. Optional elsewhere (recommended for Loop controller routing).';
}

const validation = computed(() => (graph.value ? validateGraphDesign(graph.value) : null));
const invalidNodes = computed(() => Array.from(validation.value?.invalidNodes || []));
const invalidEdges = computed(() => Array.from(validation.value?.invalidEdges || []));
const issues = computed(() => validation.value?.issues || []);

watch(
  () => uri.value,
  () => {
    warningsCollapsed.value = false;
  }
);
</script>

<template>
  <div class="tab-root">
    <div v-if="editorModalOpen" class="modal" @mousedown.self="closeLargeEditor">
      <div class="modal-card" :class="{ readonly: editorReadonly }" role="dialog" aria-modal="true">
        <div class="modal-head">
          <div class="modal-title mono">
            {{ editorTitle }}
            <span v-if="editorReadonly" class="modal-badge">Read-only</span>
          </div>
          <div class="modal-actions">
            <button class="btn secondary" type="button" @click="closeLargeEditor">
              {{ editorReadonly ? 'Close' : 'Cancel' }}
            </button>
            <button v-if="!editorReadonly" class="btn" type="button" @click="saveLargeEditor">Save</button>
          </div>
        </div>
        <textarea
          ref="editorTextareaRef"
          v-model="editorDraft"
          class="modal-text mono"
          :readonly="editorReadonly"
          spellcheck="false"
        ></textarea>
        <div class="modal-hint mono">
          {{ editorReadonly ? 'Read-only preview' : 'Esc: cancel · Ctrl/Cmd+Enter: save' }}
        </div>
      </div>
    </div>

    <div class="header">
      <div class="title">{{ props.title }}</div>
      <div class="meta">
        <span v-if="doc" class="mono">{{ doc.fileName }}</span>
        <span v-if="isAmlDoc" class="badge">AML</span>
        <span v-if="doc && doc.dirty" class="badge warn">Modified</span>
        <span v-if="doc && !doc.dirty" class="badge ok">Synced</span>
        <span v-if="doc?.saving" class="badge">Saving…</span>
        <span v-if="doc?.saveError" class="badge err">{{ doc.saveError }}</span>
	        <button
	          class="btn secondary"
	          :disabled="!doc || !graph || !canUndo || isStructureReadonly"
          title="Undo (Ctrl/Cmd+Z)"
          @click="undo"
        >
          Undo
        </button>
	        <button
	          class="btn secondary"
	          :disabled="!doc || !graph || !canRedo || isStructureReadonly"
          title="Redo (Ctrl/Cmd+Shift+Z)"
          @click="redo"
        >
          Redo
        </button>
        <button class="btn secondary" :disabled="!doc || doc.saving" @click="reloadFromFile">
          Reload
        </button>
        <button class="btn" :disabled="!doc || !graph || doc.saving || isStructureReadonly" @click="save">Save</button>
      </div>
    </div>

    <div v-if="helpText" class="empty">{{ helpText }}</div>

    <div v-else ref="layoutRef" class="layout" :class="{ readonly: isStructureReadonly }" :style="layoutStyle">
      <aside v-if="!isStructureReadonly" class="palette">
        <div class="palette-title">Components</div>
        <div
          v-for="item in palette"
          :key="item.type"
          class="palette-item"
          draggable="true"
          @dragstart="(e) => onDragStart(e, String(item.type))"
        >
          {{ item.label }}
        </div>
        <div class="palette-hint">
          Drag components into the canvas to add nodes.
        </div>
      </aside>

      <section class="canvas">
        <VibeGraphEditor
          v-if="graph"
          :doc-uri="uri || ''"
          :graph="graph"
          :layout="vibe.activeLayout"
          :layout-meta="vibe.activeLayoutMeta"
          :invalid-nodes="invalidNodes"
          :invalid-edges="invalidEdges"
          :readonly="isStructureReadonly"
          @dropComponent="onDropComponent"
          @selectNode="onSelectNode"
          @selectEdge="onSelectEdge"
          @clearSelection="onClearSelection"
          @nodePosition="onNodePosition"
          @layoutSnapshot="onLayoutSnapshot"
          @nodeParentChanged="onNodeParentChanged"
          @createEdge="onCreateEdge"
          @nodeDoubleClick="onNodeDoubleClick"
        />
      </section>

      <aside class="detail" :class="{ readonly: detailReadonly }">
        <div
          class="detail-resize-handle"
          title="Drag to resize details width (double-click to reset)"
          @mousedown="startResizeDetail"
          @dblclick="resetDetailWidth"
        ></div>
        <div class="detail-title">Details</div>
        <div v-if="issues.length > 0" class="warnings" :class="{ collapsed: warningsCollapsed }">
          <button
            class="warnings-title"
            type="button"
            :aria-expanded="!warningsCollapsed"
            @click="warningsCollapsed = !warningsCollapsed"
          >
            <span>Warnings ({{ issues.length }})</span>
            <span class="warnings-toggle">{{ warningsCollapsed ? 'Show' : 'Hide' }}</span>
          </button>
          <div v-if="!warningsCollapsed" class="warnings-body">
            <div v-for="(it, i) in issues" :key="i" class="warning">
              {{ it.message }}
            </div>
          </div>
        </div>

        <div v-if="selection.kind === 'none'">
          <div class="detail-empty">Select a node or edge.</div>
          <div v-if="isAmlDoc" class="form">
            <label class="field">
              <div class="label">root attributes (XML)</div>
              <textarea
                class="input mono"
                :readonly="!canEditRootAttributes"
                rows="10"
                :value="rootAttributesText"
                @change="(e:any)=>commitRootAttributesXml(e.target.value)"
              ></textarea>
              <div v-if="rootAttributesError" class="hint warn">Invalid XML: {{ rootAttributesError }}</div>
            </label>
          </div>
        </div>

        <div v-else-if="selection.kind === 'node'">
          <div v-if="selectedNodeIsInternal" class="detail-empty">
            This is an internal endpoint node (read-only).
          </div>

          <div v-else-if="selectedNode" class="form">
            <div v-if="selectedNodeIsDerived" class="hint warn">
              This node comes from a Python implementation preview and is read-only.
            </div>
            <div v-else-if="isExternalRefNodeSpec(selectedNode)" class="hint">
              This node belongs to an imported AML subgraph. Edits save back to that AML file.
            </div>
            <label class="field">
              <div class="label">Name</div>
            <input
              class="input mono"
              :readonly="!selectedNodeEditable"
              :value="String(selectedNode.name)"
                @change="
                  (e:any)=>{
                    const next = String(e.target.value || '').trim();
                    renameCurrentNode(next);
                  }
                "
              />
            </label>

            <label class="field">
              <div class="label">Type</div>
              <select
                class="input"
                :disabled="!selectedNodeEditable"
                :value="String(selectedNode.type || 'Agent')"
                @change="(e:any)=>changeCurrentNodeType(String(e.target.value || 'Agent'))"
              >
                <option v-for="item in palette" :key="item.type" :value="String(item.type)">{{ item.label }}</option>
              </select>
            </label>

            <label class="field">
              <div class="label">Parent</div>
              <select
                class="input mono"
                :disabled="!selectedNodeEditable"
                :value="String(selectedNode.parent || 'root')"
                @change="(e:any)=>changeCurrentNodeParent(String(e.target.value || 'root').trim())"
              >
                <option v-for="p in parentOptions" :key="p" :value="p">{{ p }}</option>
              </select>
            </label>

            <label class="field">
              <div class="label">label</div>
              <input
                class="input mono"
                :readonly="!selectedNodeEditable"
                :value="String((selectedNode as any).label || '')"
                @input="(e:any)=>updateSelectedNode({ label: e.target.value })"
              />
            </label>

            <label v-if="selectedNode.type === 'Agent'" class="field">
              <div class="label">agent</div>
              <input
                class="input mono"
                :readonly="!selectedNodeEditable"
                :value="String((selectedNode as any).agent || '')"
                @input="(e:any)=>updateSelectedNode({ agent: e.target.value })"
              />
            </label>

            <label v-if="selectedNode.type === 'Agent'" class="field">
              <div class="label">tools</div>
              <textarea
                class="input mono"
                :readonly="!selectedNodeEditable"
                rows="4"
                :value="selectedToolsText"
                @change="(e:any)=>commitTools(e.target.value)"
              ></textarea>
              <div class="hint">One tool name per line (or a JSON array).</div>
            </label>

            <label class="field">
              <div class="label">attributes (JSON)</div>
              <textarea
                class="input mono"
                :readonly="!selectedNodeEditable"
                rows="4"
                :value="selectedAttributesText"
                @change="(e:any)=>commitAttributes(e.target.value)"
              ></textarea>
              <div v-if="attributesError" class="hint warn">Invalid JSON: {{ attributesError }}</div>
            </label>

            <label v-if="selectedNode.type === 'Loop'" class="field">
              <div class="label">terminate_condition_prompt</div>
              <textarea
                class="input mono"
                :readonly="!selectedNodeEditable"
                rows="3"
                :value="String((selectedNode as any).terminate_condition_prompt || '')"
                @input="(e:any)=>updateSelectedNode({ terminate_condition_prompt: e.target.value })"
              ></textarea>
            </label>

            <label v-if="selectedNode.type === 'Loop'" class="field">
              <div class="label">max_iterations</div>
              <input class="input mono" type="number" min="1" :readonly="!selectedNodeEditable" :value="Number(selectedNode.max_iterations || 1)" @input="(e:any)=>updateSelectedNode({ max_iterations: Number(e.target.value) })" />
            </label>

            <label v-if="selectedNode.type === 'Agent'" class="field">
              <div class="label-row">
                <div class="label">instructions</div>
                <button class="mini-btn mono" type="button" @click="openLargeEditor('instructions')">
                  Open
                </button>
              </div>
              <textarea
                class="input mono"
                :readonly="!selectedNodeEditable"
                rows="8"
                :value="String(selectedNode.instructions || '')"
                @input="(e:any)=>updateSelectedNode({ instructions: e.target.value })"
              ></textarea>
            </label>

            <label v-if="selectedNode.type === 'Agent'" class="field">
              <div class="label-row">
                <div class="label">prompt_template</div>
                <button class="mini-btn mono" type="button" @click="openLargeEditor('prompt_template')">
                  Open
                </button>
              </div>
              <textarea
                class="input mono"
                :readonly="!selectedNodeEditable"
                rows="6"
                :value="String(selectedNode.prompt_template || '')"
                @input="(e:any)=>updateSelectedNode({ prompt_template: e.target.value })"
              ></textarea>
            </label>

            <label v-if="selectedNode.type === 'CustomNode'" class="field">
              <div class="label">{{ customNodeUsesCode ? 'code (Python)' : 'forward_body (Python)' }}</div>
              <textarea
                class="input mono"
                :readonly="!selectedNodeEditable"
                rows="6"
                :value="String(customNodeUsesCode ? (selectedNode as any).code || '' : (selectedNode as any).forward_body || '')"
                @input="
                  (e:any)=>
                    updateSelectedNode(customNodeUsesCode ? { code: e.target.value } : { forward_body: e.target.value })
                "
              ></textarea>
            </label>

            <div v-if="selectedNode.type === 'LogicSwitch' || selectedNode.type === 'AgentSwitch'" class="field">
              <div class="label">Switch routing</div>
              <div class="hint">
                Per the AML flow model, routing conditions live on outgoing
                <span class="mono">Edges[].condition</span>. Select an edge to edit its condition.
              </div>
            </div>

            <div class="field">
              <div class="label">pull_keys</div>
              <KeyValueEditor
                :key="`pull_keys:${selectedNode.name}`"
                :value="selectedNode.pull_keys as any"
                key-label="Key"
                value-label="Description"
                :empty-hint="pullKeysEmptyHint()"
	                :default-hint="pullKeysDefaultHint(selectedNode)"
                :readonly="!selectedNodeEditable"
	                @update:value="(v)=>updateSelectedNode({ pull_keys: v })"
              />
            </div>
            <div class="field">
              <div class="label">push_keys</div>
              <KeyValueEditor
                :key="`push_keys:${selectedNode.name}`"
                :value="selectedNode.push_keys as any"
                key-label="Key"
                value-label="Description"
                :empty-hint="pushKeysEmptyHint()"
	                :default-hint="pushKeysDefaultHint(selectedNode)"
                :readonly="!selectedNodeEditable"
	                @update:value="(v)=>updateSelectedNode({ push_keys: v })"
              />
            </div>

            <button
              v-if="selectedNodeEditable"
              class="btn danger"
              @click="deleteCurrentNode"
            >
              Delete Node
            </button>
          </div>

          <div v-else class="detail-empty">This node is not in Nodes[] (endpoint).</div>
        </div>

	        <div v-else-if="selection.kind === 'edge' && selectedEdge" class="form">
          <div class="kv">
            <div class="k">Edge</div>
            <div class="v mono">{{ edgeSummary }}</div>
          </div>
          <div v-if="graph && !isSameLevelEdge(selectedEdge.from, selectedEdge.to, graph)" class="hint warn">
            Cross-level edge detected (may be invalid in MASFactory).
          </div>
          <div v-if="selectedEdgeIsDerived" class="hint warn">
            This edge comes from a Python implementation preview and is read-only.
          </div>
          <div v-else-if="(selectedEdge as any).__aml_from_ref" class="hint">
            This edge belongs to an imported AML subgraph. Edits save back to that AML file.
          </div>

          <label class="field">
            <div class="label">condition</div>
            <textarea
              class="input mono"
              :readonly="!selectedEdgeEditable"
              rows="3"
              :value="String((selectedEdge as any).condition || '')"
              @input="(e:any)=>updateSelectedEdge({ condition: e.target.value })"
            ></textarea>
            <div class="hint">{{ edgeConditionHint() }}</div>
          </label>

          <button
            v-if="selectedEdgeEditable"
            class="btn danger"
            @click="deleteCurrentEdge"
          >
            Delete Edge
          </button>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.tab-root {
  height: 100%;
  padding: 12px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.modal {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.modal-card {
  width: min(1100px, 96vw);
  height: min(86vh, 980px);
  border-radius: 10px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  background: var(--vscode-editor-background);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-card.readonly {
  border-color: rgba(242, 204, 96, 0.58);
  box-shadow: 0 0 0 1px rgba(242, 204, 96, 0.18);
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--vscode-panel-border, #2d2d2d);
}

.modal-title {
  font-size: 12px;
  font-weight: 600;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.modal-badge {
  display: inline-flex;
  align-items: center;
  margin-left: 8px;
  padding: 2px 6px;
  border-radius: 6px;
  border: 1px solid rgba(242, 204, 96, 0.48);
  color: #f2cc60;
  font-size: 11px;
  font-weight: 600;
}

.modal-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.modal-text {
  flex: 1;
  width: 100%;
  box-sizing: border-box;
  border: none;
  outline: none;
  background: transparent;
  color: var(--vscode-editor-foreground);
  padding: 12px;
  resize: none;
  line-height: 1.45;
}

.modal-card.readonly .modal-text {
  background: rgba(242, 204, 96, 0.05);
}

.modal-hint {
  padding: 8px 12px;
  border-top: 1px solid var(--vscode-panel-border, #2d2d2d);
  opacity: 0.75;
  font-size: 11px;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.title {
  font-size: 14px;
  font-weight: 600;
}

.meta {
  display: flex;
  gap: 8px;
  align-items: center;
  min-width: 0;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
    'Courier New', monospace;
}

.badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  opacity: 0.9;
}

.badge.ok {
  background: rgba(45, 159, 76, 0.15);
  border-color: rgba(45, 159, 76, 0.35);
}

.badge.warn {
  background: rgba(255, 193, 7, 0.12);
  border-color: rgba(255, 193, 7, 0.32);
}

.badge.err {
  background: rgba(244, 135, 113, 0.12);
  border-color: rgba(244, 135, 113, 0.35);
}

.btn {
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--vscode-button-border, transparent);
  background: var(--vscode-button-background, #0e639c);
  color: var(--vscode-button-foreground, #fff);
  cursor: pointer;
}

.btn:disabled {
  opacity: 0.6;
  cursor: default;
}

.btn.secondary {
  background: transparent;
  color: var(--vscode-editor-foreground);
  border-color: var(--vscode-panel-border, #2d2d2d);
}

.btn.secondary:hover:not(:disabled) {
  background: var(--vscode-list-hoverBackground, rgba(255, 255, 255, 0.06));
}

.btn.danger {
  background: rgba(244, 135, 113, 0.18);
  color: var(--vscode-editor-foreground);
  border-color: rgba(244, 135, 113, 0.35);
}

.btn.danger:hover {
  background: rgba(244, 135, 113, 0.26);
}

.empty {
  padding: 12px;
  opacity: 0.8;
}

.layout {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr) 340px;
  gap: 10px;
}

.layout.readonly {
  grid-template-columns: minmax(0, 1fr) 340px;
}

.palette {
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 8px;
  padding: 10px;
  overflow: auto;
  background: var(--vscode-editor-background);
}

.palette-title {
  font-weight: 600;
  margin-bottom: 8px;
}

.palette-item {
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  margin-bottom: 8px;
  cursor: grab;
  user-select: none;
}

.palette-item:active {
  cursor: grabbing;
}

.palette-hint {
  font-size: 12px;
  opacity: 0.75;
  margin-top: 8px;
}

.canvas {
  min-height: 0;
  min-width: 0;
}

.detail {
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 8px;
  padding: 10px 10px 10px 18px;
  overflow: auto;
  background: var(--vscode-editor-background);
  min-width: 0;
  position: relative;
}

.detail.readonly {
  border-color: rgba(242, 204, 96, 0.42);
  background:
    linear-gradient(90deg, rgba(242, 204, 96, 0.08), transparent 32px),
    var(--vscode-editor-background);
}

.detail.readonly .detail-title::after {
  content: 'Read-only';
  display: inline-block;
  margin-left: 8px;
  padding: 1px 6px;
  border-radius: 999px;
  border: 1px solid rgba(242, 204, 96, 0.35);
  color: #f2cc60;
  font-size: 10px;
  font-weight: 500;
  vertical-align: 1px;
}

.detail.readonly .input:read-only,
.detail.readonly select.input:disabled,
.detail.readonly textarea.input:read-only {
  border-color: rgba(242, 204, 96, 0.28);
  background: rgba(242, 204, 96, 0.05);
}

.detail-resize-handle {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 12px;
  cursor: col-resize;
  touch-action: none;
  user-select: none;
  z-index: 20;
}

.detail-resize-handle::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 10px;
  bottom: 10px;
  width: 2px;
  transform: translateX(-50%);
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.06);
}

.detail-resize-handle:hover::after {
  background: rgba(255, 255, 255, 0.16);
}

.detail-title {
  font-weight: 600;
  margin-bottom: 8px;
}

.warnings {
  border: 1px solid rgba(242, 204, 96, 0.35);
  background: rgba(242, 204, 96, 0.06);
  border-radius: 8px;
  padding: 8px;
  margin-bottom: 10px;
}

.warnings-title {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border: 0;
  padding: 0;
  background: transparent;
  font-size: 12px;
  font-weight: 600;
  color: #f2cc60;
  margin-bottom: 6px;
  cursor: pointer;
  text-align: left;
}

.warnings.collapsed .warnings-title {
  margin-bottom: 0;
}

.warnings-toggle {
  flex: 0 0 auto;
  font-size: 11px;
  font-weight: 500;
  color: var(--vscode-editor-foreground);
  opacity: 0.82;
}

.warnings-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.warning {
  font-size: 12px;
  opacity: 0.9;
  line-height: 1.3;
}

.detail-empty {
  opacity: 0.8;
  padding: 6px 0;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.label {
  font-size: 12px;
  opacity: 0.9;
}

.label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.mini-btn {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  background: transparent;
  color: var(--vscode-editor-foreground);
  cursor: pointer;
  flex: 0 0 auto;
}

.mini-btn:hover {
  background: var(--vscode-list-hoverBackground, rgba(255, 255, 255, 0.06));
}

.input {
  width: 100%;
  box-sizing: border-box;
  border-radius: 6px;
  border: 1px solid var(--vscode-input-border, #2d2d2d);
  background: var(--vscode-input-background, rgba(255, 255, 255, 0.06));
  color: var(--vscode-input-foreground, #fff);
  padding: 6px 8px;
}

textarea.input {
  resize: vertical;
}

.kv {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 6px;
  align-items: baseline;
}

.k {
  opacity: 0.8;
}

.v {
  min-width: 0;
}

.hint {
  font-size: 12px;
  opacity: 0.75;
}

.hint.warn {
  opacity: 1;
  color: #f2cc60;
}

.switch-table {
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 8px;
  overflow: hidden;
  margin-top: 6px;
}

.switch-head {
  display: grid;
  grid-template-columns: 120px 1fr 32px;
  background: rgba(255, 255, 255, 0.05);
  border-bottom: 1px solid var(--vscode-panel-border, #2d2d2d);
}

.switch-body {
  display: flex;
  flex-direction: column;
}

.switch-row {
  display: grid;
  grid-template-columns: 120px 1fr 32px;
  gap: 8px;
  padding: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  align-items: start;
}

.switch-row:last-child {
  border-bottom: none;
}

.th {
  font-size: 11px;
  padding: 8px;
  opacity: 0.8;
}

.cell {
  min-width: 0;
}

.btn.secondary {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.12);
}

.btn.secondary:hover {
  background: rgba(255, 255, 255, 0.1);
}
</style>
