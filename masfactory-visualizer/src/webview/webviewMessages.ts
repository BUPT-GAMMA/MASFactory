import type { WebviewOutboundMessage } from '../shared/webviewProtocol';
import { parseWebviewOutboundMessage } from '../shared/webviewProtocol';

export type WebviewMessage = WebviewOutboundMessage;

export function parseWebviewMessage(raw: unknown): WebviewMessage | null {
  return parseWebviewOutboundMessage(raw);
}
