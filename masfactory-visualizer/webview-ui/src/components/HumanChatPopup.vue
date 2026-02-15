<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRuntimeStore } from '../stores/runtime';
import HumanChatThread from './HumanChatThread.vue';

const props = defineProps<{
  sessionId: string;
}>();

const emit = defineEmits<{
  (e: 'hide'): void;
}>();

const runtime = useRuntimeStore();
const pending = computed(() => runtime.humanPendingCount(props.sessionId));

function hide() {
  emit('hide');
}

type Rect = { x: number; y: number; w: number; h: number };

const popupRef = ref<HTMLDivElement | null>(null);

const rect = reactive<Rect>({
  x: 0,
  y: 0,
  w: 460,
  h: 560
});

const MIN_W = 320;
const MIN_H = 220;
const MARGIN = 14;

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

function getContainerEl(): HTMLElement | null {
  const el = popupRef.value;
  if (!el) return null;
  const parent = el.offsetParent as HTMLElement | null;
  return parent;
}

function getBounds(): { w: number; h: number } {
  const parent = getContainerEl();
  if (!parent) return { w: window.innerWidth, h: window.innerHeight };
  const r = parent.getBoundingClientRect();
  return { w: r.width, h: r.height };
}

function clampRect(next: Rect): Rect {
  const bounds = getBounds();
  const w = clamp(next.w, MIN_W, Math.max(MIN_W, bounds.w - MARGIN * 2));
  const h = clamp(next.h, MIN_H, Math.max(MIN_H, bounds.h - MARGIN * 2));
  const x = clamp(next.x, MARGIN, Math.max(MARGIN, bounds.w - w - MARGIN));
  const y = clamp(next.y, MARGIN, Math.max(MARGIN, bounds.h - h - MARGIN));
  return { x, y, w, h };
}

function loadRect(): void {
  try {
    const raw = window.localStorage.getItem(`masfactoryVisualizer.humanPopup.rect.${props.sessionId}`);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === 'object' &&
      Number.isFinite(parsed.x) &&
      Number.isFinite(parsed.y) &&
      Number.isFinite(parsed.w) &&
      Number.isFinite(parsed.h)
    ) {
      const next = clampRect({
        x: Number(parsed.x),
        y: Number(parsed.y),
        w: Number(parsed.w),
        h: Number(parsed.h)
      });
      rect.x = next.x;
      rect.y = next.y;
      rect.w = next.w;
      rect.h = next.h;
    }
  } catch {
    // ignore
  }
}

function persistRect(): void {
  try {
    window.localStorage.setItem(
      `masfactoryVisualizer.humanPopup.rect.${props.sessionId}`,
      JSON.stringify({ x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.w), h: Math.round(rect.h) })
    );
  } catch {
    // ignore
  }
}

function initDefaultRect(): void {
  const bounds = getBounds();
  const next = clampRect({
    x: bounds.w - rect.w - MARGIN,
    y: bounds.h - rect.h - MARGIN,
    w: rect.w,
    h: rect.h
  });
  rect.x = next.x;
  rect.y = next.y;
  rect.w = next.w;
  rect.h = next.h;
}

const styleObj = computed(() => ({
  left: rect.x + 'px',
  top: rect.y + 'px',
  width: rect.w + 'px',
  height: rect.h + 'px'
}));

type DragState = { pointerId: number; startX: number; startY: number; startRect: Rect };
const drag = ref<DragState | null>(null);
const resize = ref<(DragState & { dir: string }) | null>(null);

function setGlobalDragCursor(cursor: string | null) {
  try {
    document.body.style.userSelect = cursor ? 'none' : '';
    document.body.style.cursor = cursor || '';
  } catch {
    // ignore
  }
}

function onHeaderPointerDown(e: PointerEvent) {
  if (e.button !== 0) return;
  const target = e.target as HTMLElement | null;
  if (target?.closest('button')) return;
  drag.value = {
    pointerId: e.pointerId,
    startX: e.clientX,
    startY: e.clientY,
    startRect: { x: rect.x, y: rect.y, w: rect.w, h: rect.h }
  };
  try {
    (e.currentTarget as HTMLElement | null)?.setPointerCapture(e.pointerId);
  } catch {
    // ignore
  }
  setGlobalDragCursor('grabbing');
  e.preventDefault();
}

function onHeaderPointerMove(e: PointerEvent) {
  if (!drag.value) return;
  const dx = e.clientX - drag.value.startX;
  const dy = e.clientY - drag.value.startY;
  const next = clampRect({
    ...drag.value.startRect,
    x: drag.value.startRect.x + dx,
    y: drag.value.startRect.y + dy
  });
  rect.x = next.x;
  rect.y = next.y;
}

function onHeaderPointerUp(e: PointerEvent) {
  if (!drag.value) return;
  try {
    (e.currentTarget as HTMLElement | null)?.releasePointerCapture(e.pointerId);
  } catch {
    // ignore
  }
  drag.value = null;
  setGlobalDragCursor(null);
  persistRect();
}

function onHeaderPointerCancel() {
  if (!drag.value) return;
  drag.value = null;
  setGlobalDragCursor(null);
  persistRect();
}

function cursorForDir(dir: string): string {
  switch (dir) {
    case 'n':
    case 's':
      return 'ns-resize';
    case 'e':
    case 'w':
      return 'ew-resize';
    case 'ne':
    case 'sw':
      return 'nesw-resize';
    case 'nw':
    case 'se':
      return 'nwse-resize';
    default:
      return 'default';
  }
}

function onResizeDown(dir: string, e: PointerEvent) {
  if (e.button !== 0) return;
  resize.value = {
    dir,
    pointerId: e.pointerId,
    startX: e.clientX,
    startY: e.clientY,
    startRect: { x: rect.x, y: rect.y, w: rect.w, h: rect.h }
  };
  try {
    (e.currentTarget as HTMLElement | null)?.setPointerCapture(e.pointerId);
  } catch {
    // ignore
  }
  setGlobalDragCursor(cursorForDir(dir));
  e.preventDefault();
}

function onResizeMove(e: PointerEvent) {
  if (!resize.value) return;
  const dx = e.clientX - resize.value.startX;
  const dy = e.clientY - resize.value.startY;
  const start = resize.value.startRect;
  const dir = resize.value.dir;

  let x = start.x;
  let y = start.y;
  let w = start.w;
  let h = start.h;

  if (dir.includes('e')) w = start.w + dx;
  if (dir.includes('s')) h = start.h + dy;
  if (dir.includes('w')) {
    w = start.w - dx;
    x = start.x + dx;
  }
  if (dir.includes('n')) {
    h = start.h - dy;
    y = start.y + dy;
  }

  const next = clampRect({ x, y, w, h });
  rect.x = next.x;
  rect.y = next.y;
  rect.w = next.w;
  rect.h = next.h;
}

function onResizeUp(e: PointerEvent) {
  if (!resize.value) return;
  try {
    (e.currentTarget as HTMLElement | null)?.releasePointerCapture(e.pointerId);
  } catch {
    // ignore
  }
  resize.value = null;
  setGlobalDragCursor(null);
  persistRect();
}

function onResizeCancel() {
  if (!resize.value) return;
  resize.value = null;
  setGlobalDragCursor(null);
  persistRect();
}

function onWindowResize() {
  const next = clampRect({ x: rect.x, y: rect.y, w: rect.w, h: rect.h });
  rect.x = next.x;
  rect.y = next.y;
  rect.w = next.w;
  rect.h = next.h;
}

onMounted(() => {
  initDefaultRect();
  loadRect();
  window.addEventListener('resize', onWindowResize);
});

onBeforeUnmount(() => {
  window.removeEventListener('resize', onWindowResize);
});

watch(
  () => props.sessionId,
  () => {
    // New session: reset to bottom-right default and load persisted rect for that session.
    initDefaultRect();
    loadRect();
  }
);
</script>

<template>
  <div ref="popupRef" class="popup" role="dialog" aria-label="Human chat" :style="styleObj">
    <div
      class="header"
      title="Drag to move"
      @pointerdown="onHeaderPointerDown"
      @pointermove="onHeaderPointerMove"
      @pointerup="onHeaderPointerUp"
      @pointercancel="onHeaderPointerCancel"
    >
      <div class="title">
        <span class="label">Human</span>
        <span v-if="pending > 0" class="badge">{{ pending }}</span>
      </div>
      <div class="actions">
        <button class="btn secondary small" @click="hide" @pointerdown.stop>Hide</button>
      </div>
    </div>

    <div class="body">
      <HumanChatThread :session-id="sessionId" />
    </div>

    <!-- Resize handles (8 directions). -->
    <div class="rh n" @pointerdown="(e) => onResizeDown('n', e)" @pointermove="onResizeMove" @pointerup="onResizeUp" @pointercancel="onResizeCancel" />
    <div class="rh s" @pointerdown="(e) => onResizeDown('s', e)" @pointermove="onResizeMove" @pointerup="onResizeUp" @pointercancel="onResizeCancel" />
    <div class="rh e" @pointerdown="(e) => onResizeDown('e', e)" @pointermove="onResizeMove" @pointerup="onResizeUp" @pointercancel="onResizeCancel" />
    <div class="rh w" @pointerdown="(e) => onResizeDown('w', e)" @pointermove="onResizeMove" @pointerup="onResizeUp" @pointercancel="onResizeCancel" />
    <div class="rh ne" @pointerdown="(e) => onResizeDown('ne', e)" @pointermove="onResizeMove" @pointerup="onResizeUp" @pointercancel="onResizeCancel" />
    <div class="rh nw" @pointerdown="(e) => onResizeDown('nw', e)" @pointermove="onResizeMove" @pointerup="onResizeUp" @pointercancel="onResizeCancel" />
    <div class="rh se" @pointerdown="(e) => onResizeDown('se', e)" @pointermove="onResizeMove" @pointerup="onResizeUp" @pointercancel="onResizeCancel" />
    <div class="rh sw" @pointerdown="(e) => onResizeDown('sw', e)" @pointermove="onResizeMove" @pointerup="onResizeUp" @pointercancel="onResizeCancel" />
  </div>
</template>

<style scoped>
.popup {
  position: absolute;
  left: 14px;
  top: 14px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid var(--vscode-panel-border, #2d2d2d);
  border-radius: 12px;
  background: var(--vscode-editor-background);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
  z-index: 50;
  overflow: hidden;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 10px 8px 12px;
  border-bottom: 1px solid var(--vscode-panel-border, #2d2d2d);
  user-select: none;
  cursor: grab;
  touch-action: none;
}

.title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.label {
  font-weight: 800;
  font-size: 12px;
}

.badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid rgba(215, 186, 125, 0.55);
  background: rgba(215, 186, 125, 0.16);
  color: var(--vscode-editor-foreground);
}

.actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}

.btn {
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid var(--vscode-button-border, transparent);
  background: var(--vscode-button-background, #0e639c);
  color: var(--vscode-button-foreground, #fff);
  cursor: pointer;
}

.btn.secondary {
  background: transparent;
  color: var(--vscode-editor-foreground);
  border-color: var(--vscode-panel-border, #2d2d2d);
}

.btn.secondary:hover {
  background: var(--vscode-list-hoverBackground, rgba(255, 255, 255, 0.06));
}

.btn.small {
  padding: 4px 8px;
  font-size: 11px;
}

.body {
  flex: 1;
  min-height: 0;
  padding: 10px;
}

.rh {
  position: absolute;
  z-index: 60;
  touch-action: none;
}

.rh.n,
.rh.s {
  left: 8px;
  right: 8px;
  height: 8px;
}

.rh.n {
  top: 0;
  cursor: ns-resize;
}

.rh.s {
  bottom: 0;
  cursor: ns-resize;
}

.rh.e,
.rh.w {
  top: 8px;
  bottom: 8px;
  width: 8px;
}

.rh.e {
  right: 0;
  cursor: ew-resize;
}

.rh.w {
  left: 0;
  cursor: ew-resize;
}

.rh.ne,
.rh.nw,
.rh.se,
.rh.sw {
  width: 12px;
  height: 12px;
}

.rh.ne {
  right: 0;
  top: 0;
  cursor: nesw-resize;
}

.rh.nw {
  left: 0;
  top: 0;
  cursor: nwse-resize;
}

.rh.se {
  right: 0;
  bottom: 0;
  cursor: nwse-resize;
}

.rh.sw {
  left: 0;
  bottom: 0;
  cursor: nesw-resize;
}
</style>
