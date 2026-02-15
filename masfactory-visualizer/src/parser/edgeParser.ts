/**
 * Edge parsing logic for MASFactory graphs
 */
import type { Node as TSNode } from 'web-tree-sitter';
import { GraphEdge } from './types';
import { getNodeText, parseDictArgument, extractMethodCall } from './astUtils';
import type { ParserFeatures } from './features';

export interface EdgeParseContext {
    edges: GraphEdge[];
    variableToNodeName: { [variable: string]: string };
    nodes: string[];
    subgraphParents?: { [key: string]: string };
    // Line offset for reparsed code (used in builder function parsing)
    lineOffset?: number;
    /**
     * Parser feature flags (optional) for forward compatibility.
     * New parsing behaviors should be guarded behind flags with safe defaults.
     */
    features?: ParserFeatures;
}

type ParsedEdgeInfo = {
    sender: string;
    receiver: string;
    keys: string[];
    keysDetails?: { [key: string]: string };
};

type EdgeParseRule = {
    name: string;
    suffix: string;
    parse: (args: TSNode[], code: string, ctx: EdgeParseContext, functionText: string) => ParsedEdgeInfo;
};

function parseCreateEdge(args: TSNode[], code: string, ctx: EdgeParseContext): ParsedEdgeInfo {
    let sender = '';
    let receiver = '';
    let keys: string[] = [];
    let keysDetails: { [key: string]: string } | undefined;

    // create_edge(sender, receiver, keys={...})
    let positionalIndex = 0;
    for (const arg of args) {
        if (arg.type === 'keyword_argument') {
            const argName = getNodeText(arg.childForFieldName('name'), code);
            const argValue = arg.childForFieldName('value');
            if (argName === 'sender' && argValue && !sender) {
                sender = resolveNodeReference(getNodeText(argValue, code), ctx.variableToNodeName);
            } else if (argName === 'receiver' && argValue && !receiver) {
                receiver = resolveNodeReference(getNodeText(argValue, code), ctx.variableToNodeName);
            } else if (argName === 'keys' && argValue) {
                const keysDict = parseDictArgument(argValue, code);
                if (keysDict) {
                    keys = Object.keys(keysDict);
                    keysDetails = keysDict;
                }
            }
        } else {
            if (positionalIndex === 0 && !sender) {
                sender = resolveNodeReference(getNodeText(arg, code), ctx.variableToNodeName);
            } else if (positionalIndex === 1 && !receiver) {
                receiver = resolveNodeReference(getNodeText(arg, code), ctx.variableToNodeName);
            } else if (positionalIndex === 2 && arg.type === 'dictionary') {
                const keysDict = parseDictArgument(arg, code);
                if (keysDict) {
                    keys = Object.keys(keysDict);
                    keysDetails = keysDict;
                }
            }
            positionalIndex++;
        }
    }

    return { sender, receiver, keys, keysDetails };
}

function parseEdgeFromEntry(args: TSNode[], code: string, ctx: EdgeParseContext, functionText: string): ParsedEdgeInfo {
    let sender = '';
    let receiver = '';
    let keys: string[] = [];
    let keysDetails: { [key: string]: string } | undefined;

    const methodCall = extractMethodCall(functionText);
    const graphVar = methodCall ? methodCall.caller : '';

    if (graphVar === 'self' || graphVar === 'graph' || !ctx.variableToNodeName[graphVar]) {
        sender = 'entry';
    } else {
        const subgraphName = ctx.variableToNodeName[graphVar];
        sender = `${subgraphName}_entry`;
    }

    for (const arg of args) {
        if (arg.type === 'keyword_argument') {
            const argName = getNodeText(arg.childForFieldName('name'), code);
            const argValue = arg.childForFieldName('value');
            if (argName === 'receiver' && argValue && !receiver) {
                receiver = resolveNodeReference(getNodeText(argValue, code), ctx.variableToNodeName);
            } else if (argName === 'keys' && argValue) {
                const keysDict = parseDictArgument(argValue, code);
                if (keysDict) {
                    keys = Object.keys(keysDict);
                    keysDetails = keysDict;
                }
            }
        } else if (!receiver) {
            receiver = resolveNodeReference(getNodeText(arg, code), ctx.variableToNodeName);
        } else if (arg.type === 'dictionary') {
            const keysDict = parseDictArgument(arg, code);
            if (keysDict) {
                keys = Object.keys(keysDict);
                keysDetails = keysDict;
            }
        }
    }

    return { sender, receiver, keys, keysDetails };
}

function parseEdgeToExit(args: TSNode[], code: string, ctx: EdgeParseContext, functionText: string): ParsedEdgeInfo {
    let sender = '';
    let receiver = '';
    let keys: string[] = [];
    let keysDetails: { [key: string]: string } | undefined;

    const methodCall = extractMethodCall(functionText);
    const graphVar = methodCall ? methodCall.caller : '';

    if (graphVar === 'self' || graphVar === 'graph' || !ctx.variableToNodeName[graphVar]) {
        receiver = 'exit';
    } else {
        const subgraphName = ctx.variableToNodeName[graphVar];
        receiver = `${subgraphName}_exit`;
    }

    for (const arg of args) {
        if (arg.type === 'keyword_argument') {
            const argName = getNodeText(arg.childForFieldName('name'), code);
            const argValue = arg.childForFieldName('value');
            if (argName === 'sender' && argValue && !sender) {
                sender = resolveNodeReference(getNodeText(argValue, code), ctx.variableToNodeName);
            } else if (argName === 'keys' && argValue) {
                const keysDict = parseDictArgument(argValue, code);
                if (keysDict) {
                    keys = Object.keys(keysDict);
                    keysDetails = keysDict;
                }
            }
        } else if (!sender) {
            sender = resolveNodeReference(getNodeText(arg, code), ctx.variableToNodeName);
        } else if (arg.type === 'dictionary') {
            const keysDict = parseDictArgument(arg, code);
            if (keysDict) {
                keys = Object.keys(keysDict);
                keysDetails = keysDict;
            }
        }
    }

    return { sender, receiver, keys, keysDetails };
}

function parseEdgeFromController(args: TSNode[], code: string, ctx: EdgeParseContext, functionText: string): ParsedEdgeInfo {
    let sender = '';
    let receiver = '';
    let keys: string[] = [];
    let keysDetails: { [key: string]: string } | undefined;

    const methodCall = extractMethodCall(functionText);
    const loopVar = methodCall ? methodCall.caller : '';

    if (loopVar === 'self') {
        sender = 'controller';
    } else {
        const resolvedLoop = resolveNodeReference(loopVar, ctx.variableToNodeName);
        sender = `${resolvedLoop}_controller`;
    }

    for (const arg of args) {
        if (arg.type === 'keyword_argument') {
            const argName = getNodeText(arg.childForFieldName('name'), code);
            const argValue = arg.childForFieldName('value');
            if (argName === 'receiver' && argValue && !receiver) {
                receiver = resolveNodeReference(getNodeText(argValue, code), ctx.variableToNodeName);
            } else if (argName === 'keys' && argValue) {
                const keysDict = parseDictArgument(argValue, code);
                if (keysDict) {
                    keys = Object.keys(keysDict);
                    keysDetails = keysDict;
                }
            }
        } else if (!receiver) {
            receiver = resolveNodeReference(getNodeText(arg, code), ctx.variableToNodeName);
        } else if (arg.type === 'dictionary') {
            const keysDict = parseDictArgument(arg, code);
            if (keysDict) {
                keys = Object.keys(keysDict);
                keysDetails = keysDict;
            }
        }
    }

    return { sender, receiver, keys, keysDetails };
}

function parseEdgeToController(args: TSNode[], code: string, ctx: EdgeParseContext, functionText: string): ParsedEdgeInfo {
    let sender = '';
    let receiver = '';
    let keys: string[] = [];
    let keysDetails: { [key: string]: string } | undefined;

    const methodCall = extractMethodCall(functionText);
    const loopVar = methodCall ? methodCall.caller : '';

    if (loopVar === 'self') {
        receiver = 'controller';
    } else {
        const resolvedLoop = resolveNodeReference(loopVar, ctx.variableToNodeName);
        receiver = `${resolvedLoop}_controller`;
    }

    for (const arg of args) {
        if (arg.type === 'keyword_argument') {
            const argName = getNodeText(arg.childForFieldName('name'), code);
            const argValue = arg.childForFieldName('value');
            if (argName === 'sender' && argValue && !sender) {
                sender = resolveNodeReference(getNodeText(argValue, code), ctx.variableToNodeName);
            } else if (argName === 'keys' && argValue) {
                const keysDict = parseDictArgument(argValue, code);
                if (keysDict) {
                    keys = Object.keys(keysDict);
                    keysDetails = keysDict;
                }
            }
        } else if (!sender) {
            sender = resolveNodeReference(getNodeText(arg, code), ctx.variableToNodeName);
        } else if (arg.type === 'dictionary') {
            const keysDict = parseDictArgument(arg, code);
            if (keysDict) {
                keys = Object.keys(keysDict);
                keysDetails = keysDict;
            }
        }
    }

    return { sender, receiver, keys, keysDetails };
}

function parseEdgeToTerminateNode(args: TSNode[], code: string, ctx: EdgeParseContext, functionText: string): ParsedEdgeInfo {
    let sender = '';
    let receiver = '';
    let keys: string[] = [];
    let keysDetails: { [key: string]: string } | undefined;

    const methodCall = extractMethodCall(functionText);
    const loopVar = methodCall ? methodCall.caller : '';

    if (loopVar === 'self') {
        receiver = 'terminate';
    } else {
        const resolvedLoop = resolveNodeReference(loopVar, ctx.variableToNodeName);
        receiver = `${resolvedLoop}_terminate`;
    }

    for (const arg of args) {
        if (arg.type === 'keyword_argument') {
            const argName = getNodeText(arg.childForFieldName('name'), code);
            const argValue = arg.childForFieldName('value');
            if (argName === 'sender' && argValue && !sender) {
                sender = resolveNodeReference(getNodeText(argValue, code), ctx.variableToNodeName);
            } else if (argName === 'keys' && argValue) {
                const keysDict = parseDictArgument(argValue, code);
                if (keysDict) {
                    keys = Object.keys(keysDict);
                    keysDetails = keysDict;
                }
            }
        } else if (!sender) {
            sender = resolveNodeReference(getNodeText(arg, code), ctx.variableToNodeName);
        } else if (arg.type === 'dictionary') {
            const keysDict = parseDictArgument(arg, code);
            if (keysDict) {
                keys = Object.keys(keysDict);
                keysDetails = keysDict;
            }
        }
    }

    return { sender, receiver, keys, keysDetails };
}

const EDGE_PARSE_RULES: EdgeParseRule[] = [
    { name: 'create_edge', suffix: '.create_edge', parse: (args, code, ctx) => parseCreateEdge(args, code, ctx) },
    { name: 'edge_from_entry', suffix: '.edge_from_entry', parse: (args, code, ctx, fn) => parseEdgeFromEntry(args, code, ctx, fn) },
    { name: 'edge_to_exit', suffix: '.edge_to_exit', parse: (args, code, ctx, fn) => parseEdgeToExit(args, code, ctx, fn) },
    { name: 'edge_from_controller', suffix: '.edge_from_controller', parse: (args, code, ctx, fn) => parseEdgeFromController(args, code, ctx, fn) },
    { name: 'edge_to_controller', suffix: '.edge_to_controller', parse: (args, code, ctx, fn) => parseEdgeToController(args, code, ctx, fn) },
    { name: 'edge_to_terminate_node', suffix: '.edge_to_terminate_node', parse: (args, code, ctx, fn) => parseEdgeToTerminateNode(args, code, ctx, fn) }
];

/**
 * Parse edge creation call (create_edge, edge_from_entry, edge_to_exit, etc.)
 */
export function parseEdgeCreation(
    callNode: TSNode,
    code: string,
    ctx: EdgeParseContext,
    functionText: string
): void {
    const argsNode = callNode.childForFieldName('arguments');
    if (!argsNode) return;

    const args = argsNode.namedChildren.filter((n): n is TSNode => !!n && n.type !== 'comment');
    const lineOffset = ctx.lineOffset || 0;
    const lineNumber = callNode.startPosition.row + 1 + lineOffset;

    let parsed: ParsedEdgeInfo | null = null;
    for (const rule of EDGE_PARSE_RULES) {
        if (functionText.endsWith(rule.suffix)) {
            parsed = rule.parse(args, code, ctx, functionText);
            break;
        }
    }

    const sender = parsed?.sender || '';
    const receiver = parsed?.receiver || '';
    const keys = parsed?.keys || [];
    const keysDetails = parsed?.keysDetails;

    // Add edge if both sender and receiver are valid
    if (sender && receiver) {
        ctx.edges.push({
            from: sender,
            to: receiver,
            keys: keys,
            keysDetails: keysDetails,
            lineNumber: lineNumber
        });
        console.log(`[Parser] Found edge: ${sender} -> ${receiver}`);
    } else {
        console.log(`[Parser] Warning: Incomplete edge at line ${lineNumber}: sender=${sender}, receiver=${receiver}`);
    }
}

/**
 * Resolve node reference (variable name to node name)
 */
function resolveNodeReference(ref: string, variableToNodeName: { [variable: string]: string }): string {
    // Handle self._ prefix
    if (ref.startsWith('self._')) {
        const varName = ref;
        if (variableToNodeName[varName]) {
            return variableToNodeName[varName];
        }
        return ref.replace('self._', '');
    }
    
    // Handle self. prefix
    if (ref.startsWith('self.')) {
        const varName = ref;
        if (variableToNodeName[varName]) {
            return variableToNodeName[varName];
        }
        return ref.replace('self.', '');
    }
    
    // Check variable mapping
    if (variableToNodeName[ref]) {
        return variableToNodeName[ref];
    }
    
    return ref;
}

/**
 * Extract argument value, handling both positional and keyword arguments
 */
function extractArgValue(arg: TSNode, code: string, expectedName?: string): string | null {
    if (arg.type === 'keyword_argument') {
        // keyword argument: name=value
        const argName = getNodeText(arg.childForFieldName('name'), code);
        const argValue = arg.childForFieldName('value');
        if (expectedName && argName !== expectedName) {
            return null;
        }
        return argValue ? getNodeText(argValue, code) : null;
    }
    // positional argument
    return getNodeText(arg, code);
}

/**
 * Check if function text represents an edge creation method
 */
export function isEdgeCreationMethod(functionText: string): boolean {
    return EDGE_PARSE_RULES.some(rule => functionText.endsWith(rule.suffix));
}
