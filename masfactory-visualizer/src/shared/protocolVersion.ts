export const PROTOCOL_VERSION = 1;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/**
 * Throws when the inbound message protocol is newer than this client understands.
 *
 * Backward compatibility:
 * - missing `protocolVersion` is accepted
 * - `protocolVersion` <= `PROTOCOL_VERSION` is accepted
 */
export function assertSupportedInboundProtocol(raw: unknown): void {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return;
  const v = (raw as any).protocolVersion;
  if (!isFiniteNumber(v)) return;
  if (v > PROTOCOL_VERSION) {
    throw new Error(
      `Unsupported protocolVersion ${v} (supported <= ${PROTOCOL_VERSION}). Please update masfactory-visualizer.`
    );
  }
}

