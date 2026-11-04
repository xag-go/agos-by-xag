"""Strict, canonical HTTP/1.1 for agos-sandboxd (engine/sandboxd.py), RFC 9112.

The broker sits between a workspace's gateway and the real Docker daemon. Docker's
Go parser is lenient (a bare LF ends a line, chunk extensions are skipped...), so
any byte sequence the broker reads one way and Docker another is a way past the
checks. The answer is to never forward what the client wrote:

- a request head is accepted only in the one canonical form: CRLF line ends, no
  bare CR/LF, NUL or other control bytes, no obs-fold, token header names with no
  space before the colon, each header once, `HTTP/1.1` only, a Host header;
  Content-Length digits only, never with Transfer-Encoding, and Transfer-Encoding
  only exactly `chunked`; chunk sizes plain hex with no extensions and no trailers;
- the target is decoded once into path segments and query pairs: no `%2F`, `%5C`,
  `..`, `//`, backslash, escaped control or non-ASCII bytes, duplicate query keys;
- upstream, the broker writes a request of its own (`request_bytes`): fixed Host,
  its own Content-Type/Content-Length (or its own chunk framing), Connection close
  (one upstream connection per request) or the Upgrade pair for a hijacked stream.

Stdlib only: the daemon runs as `python3 -I sandboxd.py` and loads this file as its
sibling (no agos_core import here).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import urllib.parse
from collections.abc import AsyncIterator
from dataclasses import dataclass

HEAD_LIMIT = 64 * 1024
LINE_LIMIT = 8 * 1024
MAX_HEADERS = 64
JSON_LIMIT = 4 * 1024 * 1024  # create/exec bodies: a sandbox spec is never megabytes
STREAM_LIMIT = 4 * 1024**3  # an archive upload (files copied into the sandbox)
METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "DELETE"})
# Docker Engine API versions the broker knows (/v1.NN); unversioned = the daemon's own.
API_MINORS = range(24, 61)
_TOKEN = re.compile(rb"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
_CHUNK_SIZE = re.compile(rb"[0-9A-Fa-f]{1,8}")
_CHUNK_PIECE = 64 * 1024
_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")
_QUERY_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_VERSION = re.compile(r"v1\.(0|[1-9][0-9]*)")
# Escapes that never appear in a canonical Docker path: '/', '\', '%', '.', and
# every control or non-ASCII byte.
_PATH_FORBIDDEN = {0x2F, 0x5C, 0x25, 0x2E, 0x7F, *range(0x20), *range(0x80, 0x100)}
_QUERY_FORBIDDEN = {0x7F, *range(0x20), *range(0x80, 0x100)}
_SEGMENT_SAFE = "-._~:@!$&'()*+,;="


class BadRequest(Exception):
    """The request is not canonical HTTP/1.1: answered 400 and the connection is
    closed (its framing can no longer be trusted)."""

    def __init__(self, reason: str, status: int = 400) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


@dataclass(frozen=True)
class Request:
    """One parsed request head; nothing raw survives past this."""

    method: str
    version: str  # "v1.51", or "" for an unversioned path
    segments: tuple[str, ...]  # decoded path segments after the version
    query: tuple[tuple[str, str], ...]  # decoded pairs, each key once
    headers: dict[str, str]  # lowercased name -> value, each name once
    chunked: bool
    length: int  # Content-Length; 0 when absent or chunked

    @property
    def path(self) -> str:
        return "/" + "/".join(self.segments)

    def param(self, name: str, default: str = "") -> str:
        return next((v for k, v in self.query if k == name), default)

    def _connection(self) -> set[str]:
        return {t.strip().lower() for t in self.headers.get("connection", "").split(",")}

    @property
    def wants_upgrade(self) -> bool:
        return "upgrade" in self._connection() and self.headers.get("upgrade", "") == "tcp"

    @property
    def closes(self) -> bool:
        return "close" in self._connection()

    @property
    def has_body(self) -> bool:
        return self.chunked or self.length > 0

    def target(
        self,
        segments: tuple[str, ...] | None = None,
        query: tuple[tuple[str, str], ...] | None = None,
    ) -> str:
        """The canonical upstream target: version, re-quoted segments, re-encoded query."""
        parts = ([self.version] if self.version else []) + [
            urllib.parse.quote(s, safe=_SEGMENT_SAFE)
            for s in (self.segments if segments is None else segments)
        ]
        pairs = self.query if query is None else query
        return "/" + "/".join(parts) + (f"?{urllib.parse.urlencode(pairs)}" if pairs else "")


def _decode(text: str, forbidden: set[int], what: str, plus: bool = False) -> str:
    for match in _ESCAPE.finditer(text):
        if int(match.group(1), 16) in forbidden:
            raise BadRequest(f"{what} has a refused escape %{match.group(1)}")
    if text.count("%") != len(_ESCAPE.findall(text)):
        raise BadRequest(f"{what} has a broken %-escape")
    return urllib.parse.unquote_plus(text) if plus else urllib.parse.unquote(text)


def parse_target(target: str) -> tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]]:
    """(version, path segments, query pairs) of an origin-form target."""
    if any(c in target for c in "#\\") or not target.isascii():
        raise BadRequest("the target has a refused character")
    path, mark, query = target.partition("?")
    if not path.startswith("/") or "?" in query or (mark and not query):
        raise BadRequest("the target is not a canonical origin-form path")
    if "//" in path:
        raise BadRequest("the path has an empty segment ('//')")
    raw = path[1:].split("/") if path != "/" else []
    segments = [_decode(s, _PATH_FORBIDDEN, "the path") for s in raw]
    if any(s in ("", ".", "..") for s in segments):
        raise BadRequest("the path has an empty, '.' or '..' segment")
    version = ""
    if segments and re.fullmatch(r"v[0-9].*", segments[0]):
        if not (m := _VERSION.fullmatch(raw[0])) or int(m.group(1)) not in API_MINORS:
            raise BadRequest(f"unknown Docker API version {raw[0]!r}")
        version = segments.pop(0)
    pairs: list[tuple[str, str]] = []
    for part in query.split("&") if query else []:
        key, _, value = part.partition("=")
        key = _decode(key, _QUERY_FORBIDDEN, "a query key", plus=True)
        if not _QUERY_KEY.fullmatch(key):
            raise BadRequest(f"query key {key!r} is not a parameter name")
        if any(k == key for k, _ in pairs):
            raise BadRequest(f"query key {key!r} is given twice")
        pairs.append((key, _decode(value, _QUERY_FORBIDDEN, "a query value", plus=True)))
    return version, tuple(segments), tuple(pairs)


def parse_head(raw: bytes) -> Request:
    """The request head (up to and including the blank line) in its canonical form."""
    if len(raw) > HEAD_LIMIT:
        raise BadRequest("the request head is too large", 431)
    if not raw.endswith(b"\r\n\r\n"):
        raise BadRequest("the request head does not end with CRLF CRLF")
    lines = raw[:-4].split(b"\r\n")
    if len(lines) - 1 > MAX_HEADERS:
        raise BadRequest("too many header fields", 431)
    for line in lines:
        if b"\r" in line or b"\n" in line:
            raise BadRequest("a bare CR or LF inside a line")
        if len(line) > LINE_LIMIT:
            raise BadRequest("a header line is too long", 431)
    parts = lines[0].split(b" ")
    if len(parts) != 3 or not all(parts):
        raise BadRequest("the request line is not METHOD SP target SP HTTP/1.1")
    method_b, target_b, proto = parts
    if proto != b"HTTP/1.1":
        raise BadRequest("only HTTP/1.1 is spoken here")
    if not _TOKEN.fullmatch(method_b) or method_b.decode() not in METHODS:
        raise BadRequest("unknown method", 501)
    if any(b < 0x21 or b > 0x7E for b in target_b):
        raise BadRequest("the target has a control, space or non-ASCII byte")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if line[:1] in (b" ", b"\t"):
            raise BadRequest("obs-fold (a line starting with space or tab) is refused")
        name_b, colon, value_b = line.partition(b":")
        if not colon or not _TOKEN.fullmatch(name_b):
            raise BadRequest("a header field name is not a token followed by ':'")
        value_b = value_b.strip(b" \t")
        if any((b < 0x20 and b != 0x09) or b >= 0x7F for b in value_b):
            raise BadRequest("a header value has a control or non-ASCII byte")
        name = name_b.decode().lower()
        if name in headers:
            raise BadRequest(f"header {name!r} is given twice")
        headers[name] = value_b.decode()
    if "host" not in headers:
        raise BadRequest("HTTP/1.1 needs a Host header")
    te, cl = headers.get("transfer-encoding"), headers.get("content-length")
    if te is not None and cl is not None:
        raise BadRequest("Content-Length together with Transfer-Encoding is refused")
    if te is not None and te != "chunked":
        raise BadRequest("Transfer-Encoding other than exactly 'chunked' is refused")
    if cl is not None and not re.fullmatch(r"[0-9]{1,15}", cl):
        raise BadRequest("Content-Length is not a plain number")
    version, segments, query = parse_target(target_b.decode())
    return Request(
        method=method_b.decode(),
        version=version,
        segments=segments,
        query=query,
        headers=headers,
        chunked=te is not None,
        length=int(cl) if cl is not None else 0,
    )


async def read_head(reader: asyncio.StreamReader) -> Request | None:
    """The next request on a connection, or None at a clean EOF."""
    try:
        raw = await reader.readuntil(b"\r\n\r\n")
    except asyncio.IncompleteReadError as error:
        if not error.partial:
            return None
        raise BadRequest("the connection ended inside a request head") from None
    except asyncio.LimitOverrunError:
        raise BadRequest("the request head is too large", 431) from None
    return parse_head(raw)


async def _chunks(reader: asyncio.StreamReader, limit: int) -> AsyncIterator[bytes]:
    total = 0
    while True:
        try:
            line = await reader.readuntil(b"\r\n")
        except asyncio.LimitOverrunError:
            raise BadRequest("a chunk size line is too long") from None
        if not _CHUNK_SIZE.fullmatch(line[:-2]):
            raise BadRequest("a chunk size is not plain hex (no extensions, no spaces)")
        size = int(line[:-2], 16)
        if size == 0:
            if await reader.readexactly(2) != b"\r\n":
                raise BadRequest("chunked trailers are refused")
            return
        total += size
        if total > limit:
            raise BadRequest("the request body is too large", 413)
        while size:
            piece = await reader.readexactly(min(size, _CHUNK_PIECE))
            size -= len(piece)
            yield piece
        if await reader.readexactly(2) != b"\r\n":
            raise BadRequest("chunk data is not followed by CRLF")


async def iter_body(
    reader: asyncio.StreamReader, request: Request, limit: int
) -> AsyncIterator[bytes]:
    """The request body's bytes (framing removed), refusing more than `limit`."""
    if request.chunked:
        async for piece in _chunks(reader, limit):
            yield piece
        return
    if request.length > limit:
        raise BadRequest("the request body is too large", 413)
    left = request.length
    while left:
        piece = await reader.readexactly(min(left, _CHUNK_PIECE))
        left -= len(piece)
        yield piece


async def read_body(reader: asyncio.StreamReader, request: Request, limit: int) -> bytes:
    return b"".join([piece async for piece in iter_body(reader, request, limit)])


def json_body(raw: bytes) -> object:
    """A JSON request body, parsed (None for an empty body)."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        raise BadRequest("the body is not JSON") from None


def request_bytes(
    method: str,
    target: str,
    *,
    content_type: str = "",
    length: int | None = None,
    chunked: bool = False,
    upgrade: bool = False,
) -> bytes:
    """The broker's own request head for the real daemon: nothing the client sent
    but the checked method and the canonical target."""
    lines = [f"{method} {target} HTTP/1.1", "Host: docker", "User-Agent: agos-sandboxd"]
    lines += ["Connection: Upgrade", "Upgrade: tcp"] if upgrade else ["Connection: close"]
    if content_type:
        lines.append(f"Content-Type: {content_type}")
    if chunked:
        lines.append("Transfer-Encoding: chunked")
    elif length is not None:
        lines.append(f"Content-Length: {length}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")


# ---- responses (from the real daemon: trusted, but re-framed for the client) ---------
async def read_to_eof(reader: asyncio.StreamReader, limit: int = JSON_LIMIT) -> bytes:
    """An inspect answer (Connection: close), capped: an inspect is never megabytes."""
    out = b""
    while piece := await reader.read(65536):
        out += piece
        if len(out) > limit:
            raise ConnectionError("inspect answer too large")
    return out


def unchunk(raw: bytes) -> bytes:
    out, view = b"", raw
    while view:
        line, _, view = view.partition(b"\r\n")
        try:
            size = int(line.strip().split(b";")[0], 16)
        except ValueError:
            return out
        if size == 0:
            return out
        out += view[:size]
        view = view[size + 2 :]
    return out


async def copy_exact(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, n: int) -> None:
    left = n
    while left:
        piece = await reader.read(min(left, 65536))
        if not piece:
            raise ConnectionError("body ended early")
        writer.write(piece)
        await writer.drain()
        left -= len(piece)


async def _copy_chunked(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    while True:
        size_line = await reader.readuntil(b"\r\n")
        try:
            size = int(size_line.strip().split(b";")[0], 16)
        except ValueError:
            raise ConnectionError("bad chunk size") from None
        writer.write(f"{size:x}\r\n".encode())
        if size == 0:
            while await reader.readuntil(b"\r\n") != b"\r\n":
                pass  # the daemon's trailers are dropped
            writer.write(b"\r\n")
            await writer.drain()
            return
        writer.write(await reader.readexactly(size + 2))
        await writer.drain()


async def splice(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    with contextlib.suppress(ConnectionError, asyncio.IncompleteReadError):
        while piece := await reader.read(65536):
            writer.write(piece)
            await writer.drain()
    with contextlib.suppress(OSError):
        if writer.can_write_eof():
            writer.write_eof()


_HOP_BY_HOP = {"connection", "keep-alive", "proxy-connection"}


async def relay_response(
    method: str,
    up_r: asyncio.StreamReader,
    up_w: asyncio.StreamWriter,
    client_r: asyncio.StreamReader,
    client_w: asyncio.StreamWriter,
    *,
    hijack: bool,
) -> bool:
    """Forwards one upstream response; True when the client connection survives.
    A 101 is honoured only on a hijack route the client asked to upgrade: then
    this one client connection and this one upstream connection are spliced."""
    raw = await up_r.readuntil(b"\r\n\r\n")
    lines = raw.decode("latin-1").split("\r\n")
    status_line = lines[0].split(" ", 2)
    status = int(status_line[1]) if len(status_line) > 1 and status_line[1].isdigit() else 502
    if status == 101:
        if not hijack:
            raise ConnectionError("the daemon upgraded a call that is not a stream")
        client_w.write(raw)
        await client_w.drain()
        await asyncio.gather(splice(up_r, client_w), splice(client_r, up_w))
        return False
    headers = {
        ln.partition(":")[0].strip().lower(): ln.partition(":")[2].strip()
        for ln in lines[1:]
        if ":" in ln
    }
    kept = [
        ln for ln in lines[1:] if ln and ln.partition(":")[0].strip().lower() not in _HOP_BY_HOP
    ]
    client_w.write(("\r\n".join([lines[0], *kept]) + "\r\n\r\n").encode("latin-1"))
    await client_w.drain()
    if method == "HEAD" or status in (204, 304) or 100 <= status < 200:
        return True
    if headers.get("transfer-encoding", "").lower() == "chunked":
        await _copy_chunked(up_r, client_w)
        return True
    length = headers.get("content-length")
    if length is not None and length.isdigit():
        await copy_exact(up_r, client_w, int(length))
        return True
    await splice(up_r, client_w)  # unframed: streams until the daemon hangs up (logs -f)
    return False


async def respond(
    writer: asyncio.StreamWriter, status: int, message: str, *, close: bool = False
) -> None:
    label = {
        400: "Bad Request",
        403: "Forbidden",
        413: "Content Too Large",
        431: "Request Header Fields Too Large",
        501: "Not Implemented",
        502: "Bad Gateway",
    }.get(status, "Error")
    body = json.dumps({"message": f"agos-sandboxd: {message}"}).encode()
    head = f"HTTP/1.1 {status} {label}\r\nContent-Type: application/json\r\n"
    if close:
        head += "Connection: close\r\n"
    writer.write(head.encode() + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    with contextlib.suppress(ConnectionError):
        await writer.drain()
