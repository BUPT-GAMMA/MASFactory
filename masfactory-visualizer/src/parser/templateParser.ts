/**
 * NodeTemplate Parser
 *
 * Best-effort parsing for module/function-scope assignments like:
 *   t = NodeTemplate(Graph, nodes=[...], edges=[...], build_func=..., pull_keys=..., push_keys=..., attributes=...)
 *
 * This is used to:
 * - infer whether an identifier refers to a Graph/Loop template (so we can render entry/exit/controller/terminate)
 * - optionally capture declarative nodes/edges from the template for later expansion (handled in parser.ts)
 */
import type { Node as TSNode } from 'web-tree-sitter';

import { getNodeText, isNonNullNode, parseDictArgument, parseKeysArgument } from './astUtils';

export type TemplateBaseKind = 'Graph' | 'Loop' | 'Node';

export interface ParsedBuildFuncInfo {
    functionName: string;
    modulePath: string;
    type: 'partial' | 'lambda' | 'closure' | 'direct';
}

export interface ParsedNodeTemplate {
    templateName: string;
    nodeClass: string;
    baseKind: TemplateBaseKind;
    buildFunc?: ParsedBuildFuncInfo;
    nodesArg?: TSNode;
    edgesArg?: TSNode;
    pullKeys?: { [key: string]: string } | null | 'empty';
    pushKeys?: { [key: string]: string } | null | 'empty';
    attributes?: { [key: string]: any } | null;
}

function getCallArgs(callNode: TSNode): TSNode[] {
    const argsNode = callNode.childForFieldName('arguments');
    if (!argsNode) return [];
    return argsNode.namedChildren.filter(isNonNullNode).filter(n => n.type !== 'comment');
}

function getPositionalArgs(args: TSNode[]): TSNode[] {
    return args.filter(arg => arg.type !== 'keyword_argument' && arg.type !== 'comment');
}

function getKeywordArgMap(args: TSNode[], code: string): Map<string, TSNode> {
    const map = new Map<string, TSNode>();
    for (const arg of args) {
        if (arg.type !== 'keyword_argument') continue;
        const nameNode = arg.childForFieldName('name');
        const valueNode = arg.childForFieldName('value');
        if (!nameNode || !valueNode) continue;
        const key = getNodeText(nameNode, code).trim();
        map.set(key, valueNode);
    }
    return map;
}

function stripStringQuotes(raw: string): string {
    return raw.replace(/^f?["']|["']$/g, '');
}

function inferBaseKindFromNodeClass(nodeClassText: string): TemplateBaseKind {
    const normalized = nodeClassText.includes('.') ? nodeClassText.split('.').pop()! : nodeClassText;
    if (normalized.includes('Loop') || normalized.endsWith('Loop')) return 'Loop';
    if (normalized.includes('Graph') || normalized.endsWith('Graph') || normalized.endsWith('Workflow') || normalized === 'RootGraph') {
        return 'Graph';
    }
    return 'Node';
}

function parseBuildFuncArgument(argValue: TSNode, code: string): ParsedBuildFuncInfo | undefined {
    const valueText = getNodeText(argValue, code).trim();

    // partial(func, ...)
    if (argValue.type === 'call') {
        const funcNode = argValue.childForFieldName('function');
        const funcName = funcNode ? getNodeText(funcNode, code).trim() : '';
        if (funcName === 'partial' || funcName.endsWith('.partial')) {
            const argsNode = argValue.childForFieldName('arguments');
            const firstArg = argsNode?.namedChildren
                ?.filter(isNonNullNode)
                ?.find(n => n.type !== 'comment' && n.type !== 'keyword_argument');
            if (firstArg) {
                return { functionName: getNodeText(firstArg, code).trim(), modulePath: '', type: 'partial' };
            }
        }
    }

    // lambda xxx: func(xxx, ...)
    if (argValue.type === 'lambda') {
        const body = argValue.childForFieldName('body');
        if (body && body.type === 'call') {
            const fn = body.childForFieldName('function');
            if (fn) {
                return { functionName: getNodeText(fn, code).trim(), modulePath: '', type: 'lambda' };
            }
        }
    }

    // direct identifier / attribute (closure or imported function)
    if (argValue.type === 'identifier' || argValue.type === 'attribute') {
        return { functionName: valueText, modulePath: '', type: 'direct' };
    }

    return undefined;
}

function isNodeTemplateCallee(functionText: string): boolean {
    return functionText === 'NodeTemplate' || functionText.endsWith('.NodeTemplate');
}

export function tryParseNodeTemplateAssignment(
    leftVarText: string,
    callNode: TSNode,
    code: string
): ParsedNodeTemplate | null {
    if (!leftVarText) return null;
    if (callNode.type !== 'call') return null;
    const funcNode = callNode.childForFieldName('function');
    if (!funcNode) return null;
    const funcText = getNodeText(funcNode, code).trim();
    if (!isNodeTemplateCallee(funcText)) return null;

    const args = getCallArgs(callNode);
    const positional = getPositionalArgs(args);
    if (positional.length === 0) return null;

    const nodeClass = getNodeText(positional[0], code).trim();
    const baseKind = inferBaseKindFromNodeClass(nodeClass);

    const kw = getKeywordArgMap(args, code);
    const nodesArg = kw.get('nodes');
    const edgesArg = kw.get('edges');
    const pullKeysNode = kw.get('pull_keys');
    const pushKeysNode = kw.get('push_keys');
    const attributesNode = kw.get('attributes');
    const buildFuncNode = kw.get('build_func');

    const out: ParsedNodeTemplate = {
        templateName: leftVarText,
        nodeClass,
        baseKind
    };

    if (nodesArg) out.nodesArg = nodesArg;
    if (edgesArg) out.edgesArg = edgesArg;
    if (pullKeysNode) out.pullKeys = parseKeysArgument(pullKeysNode, code);
    if (pushKeysNode) out.pushKeys = parseKeysArgument(pushKeysNode, code);
    if (attributesNode) out.attributes = parseDictArgument(attributesNode, code);
    if (buildFuncNode) out.buildFunc = parseBuildFuncArgument(buildFuncNode, code);

    // Normalize leftVarText: for assignments like "self.foo = NodeTemplate(...)" keep raw key as-is,
    // but also support deref by the final segment in lookups elsewhere.
    out.templateName = leftVarText.trim();

    // If left side is a string literal (unlikely), strip quotes
    if (out.templateName.startsWith('"') || out.templateName.startsWith("'") || out.templateName.startsWith('f"') || out.templateName.startsWith("f'")) {
        out.templateName = stripStringQuotes(out.templateName);
    }

    return out;
}
