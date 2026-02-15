import type { Core, Stylesheet } from 'cytoscape';
import type { VisualizationSettings } from '../types/preview';

export type EdgeStyleMode = 'fan' | 'straight';

const EDGE_STYLE_PRESETS: Record<EdgeStyleMode, { curveStyle: 'unbundled-bezier' | 'straight'; stepSize: number; distance: number }> =
  {
    fan: { curveStyle: 'unbundled-bezier', stepSize: 60, distance: 30 },
    straight: { curveStyle: 'straight', stepSize: 0, distance: 0 }
  };

type EdgeStylePack = { base: Record<string, unknown>; hover: Record<string, unknown>; incoming: Record<string, unknown> };

export function isDarkTheme(): boolean {
  try {
    const bgColor = getComputedStyle(document.documentElement)
      .getPropertyValue('--vscode-editor-background')
      .trim();

    if (!bgColor.startsWith('#')) return false;
    const hex = bgColor.replace('#', '');

    const brightnessOf = (r: number, g: number, b: number) => (r * 299 + g * 587 + b * 114) / 1000;

    if (hex.length === 3) {
      const r = Number.parseInt(hex[0] + hex[0], 16);
      const g = Number.parseInt(hex[1] + hex[1], 16);
      const b = Number.parseInt(hex[2] + hex[2], 16);
      return brightnessOf(r, g, b) < 128;
    }

    if (hex.length === 6) {
      const r = Number.parseInt(hex.slice(0, 2), 16);
      const g = Number.parseInt(hex.slice(2, 4), 16);
      const b = Number.parseInt(hex.slice(4, 6), 16);
      return brightnessOf(r, g, b) < 128;
    }

    return false;
  } catch {
    return false;
  }
}

function resolveColor(settings: VisualizationSettings | null | undefined): {
  isDark: boolean;
  nodeBackground: string;
  nodeText: string;
  nodeBorder: string;
  edgeColor: string;
} {
  const isDark = isDarkTheme();
  const useCustom = !!(settings && settings.useCustomColors);
  const nodeBackground =
    useCustom && settings?.nodeBackgroundColor ? settings.nodeBackgroundColor : isDark ? '#2b2b2b' : '#f0f0f0';
  const nodeText = useCustom && settings?.nodeTextColor ? settings.nodeTextColor : isDark ? '#ffffff' : '#333333';
  const nodeBorder = useCustom && settings?.nodeBorderColor ? settings.nodeBorderColor : isDark ? '#8d8d8d' : '#666666';
  const edgeColor = useCustom && settings?.edgeColor ? settings.edgeColor : isDark ? '#cccccc' : '#666666';
  return { isDark, nodeBackground, nodeText, nodeBorder, edgeColor };
}

function deriveEdgeStyles(mode: EdgeStyleMode, isDark: boolean, edgeColor: string): EdgeStylePack {
  const preset = EDGE_STYLE_PRESETS[mode] || EDGE_STYLE_PRESETS.fan;
  const labelColor = isDark ? '#9cdcfe' : '#0066cc';

  const base: Record<string, unknown> = {
    width: 2,
    'line-color': edgeColor,
    'target-arrow-color': edgeColor,
    'target-arrow-shape': 'triangle',
    'curve-style': preset.curveStyle,
    'control-point-step-size': preset.stepSize,
    'control-point-distance': preset.distance,
    opacity: 0.9,
    label: 'data(displayLabel)',
    'font-size': '11px',
    'font-weight': 'normal',
    'font-style': 'italic',
    color: labelColor,
    'text-background-color': isDark ? '#252526' : '#f3f3f3',
    'text-background-opacity': 0.9,
    'text-background-padding': '3px',
    'text-background-shape': 'roundrectangle',
    'text-margin-y': -10,
    'text-wrap': 'wrap',
    'text-max-width': '150px',
    'text-rotation': 'none',
    'edge-text-rotation': 'none'
  };

  const hover: Record<string, unknown> = {
    width: 4,
    'line-color': '#0e639c',
    'target-arrow-color': '#0e639c',
    'curve-style': preset.curveStyle,
    'control-point-step-size': preset.stepSize,
    'control-point-distance': preset.distance,
    opacity: 1,
    label: 'data(displayLabel)',
    'font-size': '12px',
    'font-weight': 'bold',
    'font-style': 'italic',
    color: isDark ? '#4fc3f7' : '#0055aa',
    'text-background-color': isDark ? '#1e1e1e' : '#ffffff',
    'text-background-opacity': 0.95,
    'text-background-padding': '4px',
    'text-background-shape': 'roundrectangle',
    'text-margin-y': -10,
    'text-wrap': 'wrap',
    'text-max-width': '150px',
    'text-rotation': 'none',
    'edge-text-rotation': 'none'
  };

  const incoming: Record<string, unknown> = {
    width: 4,
    'line-color': '#2d9f4c',
    'target-arrow-color': '#2d9f4c',
    'curve-style': preset.curveStyle,
    'control-point-step-size': preset.stepSize,
    'control-point-distance': preset.distance,
    opacity: 1,
    label: 'data(displayLabel)',
    'font-size': '12px',
    'font-weight': 'bold',
    'font-style': 'italic',
    color: isDark ? '#81c784' : '#2e7d32',
    'text-background-color': isDark ? '#1e1e1e' : '#ffffff',
    'text-background-opacity': 0.95,
    'text-background-padding': '4px',
    'text-background-shape': 'roundrectangle',
    'text-margin-y': -10,
    'text-wrap': 'wrap',
    'text-max-width': '150px',
    'text-rotation': 'none',
    'edge-text-rotation': 'none'
  };

  if (preset.curveStyle === 'straight') {
    base['control-point-step-size'] = 0;
    base['control-point-distance'] = 0;
    hover['control-point-step-size'] = 0;
    hover['control-point-distance'] = 0;
    incoming['control-point-step-size'] = 0;
    incoming['control-point-distance'] = 0;
  }

  return { base, hover, incoming };
}

export function createPreviewStyle(settings?: VisualizationSettings, edgeStyle: EdgeStyleMode = 'fan'): Stylesheet[] {
  const { isDark, nodeBackground, nodeText, nodeBorder, edgeColor } = resolveColor(settings);
  const { base: baseEdgeStyle, hover: hoverEdgeStyle } = deriveEdgeStyles(edgeStyle, isDark, edgeColor);

  return [
    {
      selector: 'node[!parent]',
      style: {
        label: 'data(label)',
        'text-valign': 'center',
        'text-halign': 'center',
        'background-color': nodeBackground,
        'border-width': 2,
        'border-color': nodeBorder,
        color: nodeText,
        'font-size': '12px',
        width: 'label',
        height: 'label',
        padding: '10px',
        shape: 'roundrectangle',
        'text-wrap': 'wrap',
        'text-max-width': '120px'
      }
    },
    {
      selector: 'node[parent]',
      style: {
        label: 'data(label)',
        'text-valign': 'center',
        'text-halign': 'center',
        'background-color': nodeBackground,
        'border-width': 2,
        'border-color': nodeBorder,
        color: nodeText,
        'font-size': '12px',
        width: 'label',
        height: 'label',
        padding: '10px',
        shape: 'roundrectangle',
        'text-wrap': 'wrap',
        'text-max-width': '120px'
      }
    },
    {
      selector: 'node[id="entry"], node[id="exit"], node[type="entry"], node[type="exit"]',
      style: {
        shape: 'ellipse',
        'background-color': isDark ? '#1e5631' : '#90ee90',
        'border-color': isDark ? '#2d8659' : '#228b22'
      }
    },
    {
      selector: 'node[type="Controller"]',
      style: {
        shape: 'ellipse',
        'background-color': isDark ? '#1e4a5c' : '#87ceeb',
        'border-color': isDark ? '#2d7a9c' : '#4682b4',
        width: '70px',
        height: '35px',
        'font-size': '11px',
        padding: '5px'
      }
    },
    {
      selector: 'node[type="TerminateNode"]',
      style: {
        shape: 'ellipse',
        'background-color': isDark ? '#5c1e1e' : '#ffb6c1',
        'border-color': isDark ? '#8b2d2d' : '#dc143c',
        width: '70px',
        height: '35px',
        'font-size': '11px',
        padding: '5px'
      }
    },
    {
      selector: 'node:parent',
      style: {
        label: '',
        'background-color': isDark ? 'rgba(50, 50, 50, 0.3)' : 'rgba(200, 200, 200, 0.3)',
        'background-opacity': 0.3,
        'border-width': 2,
        'border-color': nodeBorder,
        'border-style': 'dashed',
        'padding-top': '15px',
        'padding-bottom': '15px',
        'padding-left': '15px',
        'padding-right': '15px'
      }
    },
    {
      selector: 'node:parent.collapsed',
      style: {
        label: 'data(label)',
        'text-valign': 'center',
        'text-halign': 'center',
        'background-color': isDark ? 'rgba(70, 70, 70, 0.8)' : 'rgba(180, 180, 180, 0.8)',
        'border-style': 'solid',
        'border-width': 2,
        padding: '20px',
        width: '120px',
        height: '60px',
        color: nodeText,
        'font-size': '14px',
        'font-weight': 'bold'
      }
    },
    { selector: 'edge', style: baseEdgeStyle as any },
    { selector: 'edge.hovered-edge', style: hoverEdgeStyle as any },
    { selector: 'edge.source-highlighted', style: hoverEdgeStyle as any },
    {
      selector: 'node:selected',
      style: {
        'border-width': 3,
        'border-color': isDark ? '#0e639c' : '#007acc'
      }
    },
    {
      selector: 'node.hovered-node',
      style: {
        'border-width': 3,
        'border-color': isDark ? '#0e639c' : '#007acc',
        'shadow-blur': 12,
        'shadow-color': isDark ? '#000000' : '#666666',
        'shadow-opacity': 0.4
      }
    }
  ];
}

export function applyPreviewEdgeStyle(
  cy: Core,
  mode: EdgeStyleMode,
  settings?: VisualizationSettings
): { mode: EdgeStyleMode; edgeColor: string; isDark: boolean } {
  const { isDark, edgeColor } = resolveColor(settings);
  const { base, hover, incoming } = deriveEdgeStyles(mode, isDark, edgeColor);

  cy.style()
    .selector('edge')
    .style(base as any)
    .selector('edge.hovered-edge')
    .style(hover as any)
    .selector('edge.incoming-edge')
    .style(incoming as any)
    .update();

  return { mode, edgeColor, isDark };
}
