from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct
from dataclasses import dataclass


class WebSocketError(RuntimeError):
    """Raised when the minimal WebSocket client encounters a protocol error."""
    pass


@dataclass
class WsFrame:
    """Decoded WebSocket frame."""

    opcode: int
    payload: bytes


def ws_handshake(sock: socket.socket, host: str, port: int, path: str = "/") -> None:
    """Perform a WebSocket HTTP upgrade handshake on an existing TCP socket.

    Args:
        sock: Connected TCP socket.
        host: Host used in the HTTP Host header.
        port: Port used in the HTTP Host header.
        path: WebSocket path (default: "/").

    Raises:
        WebSocketError: If the server rejects the upgrade or closes the connection.
    """
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(req.encode("ascii"))

    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise WebSocketError("handshake failed: connection closed")
        buf += chunk

    header_blob = buf.split(b"\r\n\r\n", 1)[0].decode("latin1")
    status = header_blob.split("\r\n", 1)[0]
    if "101" not in status:
        raise WebSocketError(f"handshake failed: {status}")

    accept = None
    for line in header_blob.split("\r\n")[1:]:
        if line.lower().startswith("sec-websocket-accept:"):
            accept = line.split(":", 1)[1].strip()
            break

    expected = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    ).decode("ascii")

    if accept and accept != expected:
        raise WebSocketError("handshake failed: invalid Sec-WebSocket-Accept")


def ws_send_frame(sock: socket.socket, opcode: int, payload: bytes) -> None:
    fin_and_opcode = 0x80 | (opcode & 0x0F)
    mask_bit = 0x80
    length = len(payload)

    header = bytearray()
    header.append(fin_and_opcode)

    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))

    mask = os.urandom(4)
    header.extend(mask)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(bytes(header) + masked)


def ws_send_text(sock: socket.socket, text: str) -> None:
    ws_send_frame(sock, 0x1, text.encode("utf-8"))


def ws_send_pong(sock: socket.socket, payload: bytes = b"") -> None:
    ws_send_frame(sock, 0xA, payload)


def ws_send_close(sock: socket.socket, code: int = 1000, reason: str = "") -> None:
    payload = struct.pack("!H", code) + reason.encode("utf-8")
    ws_send_frame(sock, 0x8, payload)


def ws_try_decode_frame(buf: bytes) -> tuple[WsFrame, bytes] | None:
    """Try to decode one complete WebSocket frame from `buf`.

    Args:
        buf: Raw bytes buffer.

    Returns:
        `(frame, rest)` if a complete frame is available, otherwise `None`.

    Notes:
        This supports server frames (unmasked) and client frames (masked). Fragmented messages
        are not supported.
    """
    # Supports server frames (unmasked) and client frames (masked).
    if len(buf) < 2:
        return None
    b0 = buf[0]
    b1 = buf[1]
    fin = (b0 & 0x80) != 0
    opcode = b0 & 0x0F
    masked = (b1 & 0x80) != 0
    length = b1 & 0x7F
    offset = 2

    if length == 126:
        if len(buf) < 4:
            return None
        length = struct.unpack("!H", buf[2:4])[0]
        offset = 4
    elif length == 127:
        if len(buf) < 10:
            return None
        length = struct.unpack("!Q", buf[2:10])[0]
        offset = 10

    mask = None
    if masked:
        if len(buf) < offset + 4:
            return None
        mask = buf[offset : offset + 4]
        offset += 4

    if len(buf) < offset + length:
        return None

    payload = buf[offset : offset + length]
    rest = buf[offset + length :]

    if masked and mask is not None:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

    if not fin:
        # We don't support fragmented messages yet.
        return None

    return WsFrame(opcode=opcode, payload=payload), rest
