import * as crypto from 'node:crypto';
import { EventEmitter } from 'node:events';
import * as http from 'node:http';
import type * as net from 'node:net';

type Opcode = 0x0 | 0x1 | 0x2 | 0x8 | 0x9 | 0xa;

function makeAcceptValue(secWebSocketKey: string): string {
  return crypto
    .createHash('sha1')
    .update(secWebSocketKey + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11', 'binary')
    .digest('base64');
}

function encodeFrame(opcode: Opcode, payload: Buffer): Buffer {
  const finAndOpcode = 0x80 | opcode;
  const payloadLen = payload.length;

  if (payloadLen < 126) {
    const header = Buffer.allocUnsafe(2);
    header[0] = finAndOpcode;
    header[1] = payloadLen;
    return Buffer.concat([header, payload]);
  }

  if (payloadLen < 65536) {
    const header = Buffer.allocUnsafe(4);
    header[0] = finAndOpcode;
    header[1] = 126;
    header.writeUInt16BE(payloadLen, 2);
    return Buffer.concat([header, payload]);
  }

  const header = Buffer.allocUnsafe(10);
  header[0] = finAndOpcode;
  header[1] = 127;
  header.writeBigUInt64BE(BigInt(payloadLen), 2);
  return Buffer.concat([header, payload]);
}

function tryDecodeFrame(
  buffer: Buffer
): { frame: { fin: boolean; opcode: Opcode; payload: Buffer; masked: boolean }; rest: Buffer } | null {
  if (buffer.length < 2) return null;

  const b0 = buffer[0];
  const b1 = buffer[1];
  const fin = (b0 & 0x80) !== 0;
  const opcode = (b0 & 0x0f) as Opcode;
  const masked = (b1 & 0x80) !== 0;

  let len = b1 & 0x7f;
  let offset = 2;

  if (len === 126) {
    if (buffer.length < 4) return null;
    len = buffer.readUInt16BE(2);
    offset = 4;
  } else if (len === 127) {
    if (buffer.length < 10) return null;
    const big = buffer.readBigUInt64BE(2);
    if (big > BigInt(Number.MAX_SAFE_INTEGER)) {
      throw new Error('WebSocket frame too large');
    }
    len = Number(big);
    offset = 10;
  }

  let mask: Buffer | null = null;
  if (masked) {
    if (buffer.length < offset + 4) return null;
    mask = buffer.subarray(offset, offset + 4);
    offset += 4;
  }

  if (buffer.length < offset + len) return null;

  let payload = buffer.subarray(offset, offset + len);
  if (masked && mask) {
    const out = Buffer.allocUnsafe(payload.length);
    for (let i = 0; i < payload.length; i++) {
      out[i] = payload[i] ^ mask[i % 4];
    }
    payload = out;
  }

  const rest = buffer.subarray(offset + len);
  return { frame: { fin, opcode, payload, masked }, rest };
}

export class WsConnection extends EventEmitter {
  public readonly id: string;
  private readonly socket: net.Socket;
  private buffer: Buffer = Buffer.alloc(0);
  private closed = false;
  private closeEmitted = false;

  constructor(id: string, socket: net.Socket) {
    super();
    this.id = id;
    this.socket = socket;
    // Prevent unhandled 'error' events from crashing the host when callers
    // don't explicitly subscribe to connection errors.
    this.on('error', () => undefined);

    socket.on('data', (chunk) => this.onData(chunk));
    socket.on('close', () => this.onSocketClosed());
    socket.on('end', () => this.onSocketEnded());
    socket.on('error', (err) => this.emit('error', err));
  }

  public get remoteAddress(): string {
    return this.socket.remoteAddress || '';
  }

  public sendText(text: string): void {
    if (this.closed) return;
    const payload = Buffer.from(text, 'utf8');
    this.socket.write(encodeFrame(0x1, payload));
  }

  public sendJson(value: unknown): void {
    this.sendText(JSON.stringify(value));
  }

  public close(code = 1000, reason = ''): void {
    if (this.closed) return;
    this.closed = true;
    try {
      const reasonBuf = Buffer.from(reason, 'utf8');
      const payload = Buffer.allocUnsafe(2 + reasonBuf.length);
      payload.writeUInt16BE(code, 0);
      reasonBuf.copy(payload, 2);
      this.socket.write(encodeFrame(0x8, payload));
    } catch {
      // ignore
    } finally {
      this.emitCloseOnce();
      this.socket.end();
    }
  }

  private emitCloseOnce(): void {
    if (this.closeEmitted) return;
    this.closeEmitted = true;
    this.emit('close');
  }

  private onSocketEnded(): void {
    // Remote half-closed the TCP stream. Close our side to ensure the server can shut down.
    this.closed = true;
    try {
      this.socket.end();
    } catch {
      // ignore
    }
    this.emitCloseOnce();
  }

  private onSocketClosed(): void {
    this.closed = true;
    this.emitCloseOnce();
  }

  private onData(chunk: Buffer): void {
    if (this.closed) return;
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (true) {
      const decoded = tryDecodeFrame(this.buffer);
      if (!decoded) break;
      this.buffer = decoded.rest;

      const { fin, opcode, payload } = decoded.frame;
      if (!fin && opcode !== 0x0) {
        // Fragmentation not supported yet; drop.
        continue;
      }

      if (opcode === 0x8) {
        // Close: best-effort echo close then end.
        this.close();
        return;
      }
      if (opcode === 0x9) {
        // Ping -> Pong
        if (!this.closed) {
          this.socket.write(encodeFrame(0xa, payload));
        }
        continue;
      }
      if (opcode === 0xa) {
        continue;
      }
      if (opcode === 0x1) {
        this.emit('text', payload.toString('utf8'));
      }
    }
  }
}

export interface WsServerOptions {
  host?: string;
  port?: number;
}

export class SimpleWebSocketServer extends EventEmitter {
  private readonly options: Required<WsServerOptions>;
  private readonly server: http.Server;
  private readonly sockets: Set<net.Socket> = new Set();
  private nextId = 1;
  private port: number | null = null;

  constructor(options: WsServerOptions = {}) {
    super();
    // Prevent unhandled 'error' events from crashing the host when callers
    // don't explicitly subscribe to server errors.
    this.on('error', () => undefined);
    this.options = {
      host: options.host ?? '127.0.0.1',
      port: options.port ?? 0
    };

    this.server = http.createServer((_req, res) => {
      res.writeHead(426, { 'Content-Type': 'text/plain' });
      res.end('Upgrade Required');
    });

    this.server.on('upgrade', (req, socket, head) => {
      try {
        this.handleUpgrade(req, socket, head);
      } catch (err) {
        try {
          socket.destroy();
        } catch {
          // ignore
        }
        this.emit('error', err);
      }
    });

    this.server.on('error', (err) => this.emit('error', err));
  }

  public async listen(): Promise<number> {
    if (this.port !== null) return this.port;
    await new Promise<void>((resolve, reject) => {
      const onError = (err: unknown) => {
        cleanup();
        reject(err);
      };
      const onListening = () => {
        cleanup();
        resolve();
      };
      const cleanup = () => {
        this.server.off('error', onError);
        this.server.off('listening', onListening);
      };

      this.server.once('error', onError);
      this.server.once('listening', onListening);
      this.server.listen(this.options.port, this.options.host);
    });
    const address = this.server.address();
    if (!address || typeof address === 'string') {
      throw new Error('Failed to determine WebSocket server port');
    }
    this.port = address.port;
    return this.port;
  }

  public getPort(): number | null {
    return this.port;
  }

  public async close(): Promise<void> {
    // Ensure no active sockets keep the server alive.
    for (const socket of Array.from(this.sockets)) {
      try {
        socket.destroy();
      } catch {
        // ignore
      }
    }
    await new Promise<void>((resolve) => {
      this.server.close(() => resolve());
    });
  }

  private handleUpgrade(req: http.IncomingMessage, socket: any, head: Buffer): void {
    const netSocket = socket as net.Socket;
    const upgrade = String(req.headers.upgrade || '').toLowerCase();
    if (upgrade !== 'websocket') {
      netSocket.end('HTTP/1.1 400 Bad Request\r\n\r\n');
      return;
    }

    const keyHeader = req.headers['sec-websocket-key'];
    if (!keyHeader || typeof keyHeader !== 'string') {
      netSocket.end('HTTP/1.1 400 Bad Request\r\n\r\n');
      return;
    }

    const accept = makeAcceptValue(keyHeader);

    const responseHeaders = [
      'HTTP/1.1 101 Switching Protocols',
      'Upgrade: websocket',
      'Connection: Upgrade',
      `Sec-WebSocket-Accept: ${accept}`,
      '\r\n'
    ];
    socket.write(responseHeaders.join('\r\n'));

    this.sockets.add(netSocket);
    netSocket.on('close', () => {
      this.sockets.delete(netSocket);
    });

    const id = String(this.nextId++);
    const conn = new WsConnection(id, netSocket);

    if (head && head.length > 0) {
      // Put back any buffered bytes so the connection frame parser can consume them.
      netSocket.unshift(head);
    }

    this.emit('connection', conn);
  }
}
