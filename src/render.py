"""Headless-Chrome page fetcher for hosts that require JavaScript (opt-in).

Some sites front every URL with a JS bot-challenge, and some render their
content client-side. The vendored crawler uses plain HTTP, so it sees only
the interstitial. With ``SEO_AGENT_RENDER=1`` the adapter swaps the crawler's
fetch primitive for this module: one Chrome process per audit, every page
loaded in a real browser and returned as rendered HTML.

Only the stdlib is used. Chrome/Chromium must be installed locally.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from src import config

CHROME_CANDIDATES = (
    "google-chrome-stable",
    "google-chrome",
    "chromium",
    "chromium-browser",
)

# Titles used by common bot-protection interstitials (Cloudflare, LiteSpeed,
# Hostinger/GoDaddy, Sucuri, Imperva). Matched case-insensitively.
CHALLENGE_TITLE_MARKERS: tuple[str, ...] = (
    "one moment, please",
    "just a moment",
    "attention required",
    "checking your browser",
    "enable javascript and cookies",
    "verify you are human",
    "please verify you are a human",
    "access denied",
)

# Page property checks the challenge script performs; headless Chrome fails
# them by default and then the host flags the client instead of solving.
_INIT_SCRIPT = (
    "Object.defineProperty(navigator,'webdriver',{get:()=>false});"
    "Object.defineProperty(navigator,'languages',{get:()=>['en-GB','en']});"
    "Object.defineProperty(window,'outerWidth',{get:()=>1920});"
    "Object.defineProperty(window,'outerHeight',{get:()=>1080});"
)


class RenderError(RuntimeError):
    """Chrome died, refused a DevTools command, or no browser is installed."""


def is_challenge_title(title: str) -> bool:
    folded = (title or "").casefold()
    return any(marker in folded for marker in CHALLENGE_TITLE_MARKERS)


def _same_page(left: str, right: str) -> bool:
    """True when two URLs address the same page (host, scheme, slash tolerant)."""

    def normalise(value: str) -> tuple[str, str]:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host, (parsed.path or "/").rstrip("/") or "/"

    if not left:
        return False
    return normalise(left) == normalise(right)


def _find_chrome() -> str:
    override = os.environ.get("CHROME_BIN")
    if override:
        return override
    for name in CHROME_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    raise RenderError("Chrome/Chromium not found; set CHROME_BIN or install one.")


class _WebSocket:
    """Minimal client for text frames (masked writes, unmasked reads)."""

    def __init__(self, url: str, timeout: float = 20.0) -> None:
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        self._sock.sendall(
            (
                f"GET {parsed.path or '/'} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii")
        )
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise RenderError("Chrome closed the socket during handshake")
            response += chunk
        status = response.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise RenderError(f"websocket handshake failed: {status.decode(errors='replace')}")

    def send(self, payload: str) -> None:
        data = payload.encode("utf-8")
        header = bytearray([0x81])
        if len(data) < 126:
            header.append(0x80 | len(data))
        elif len(data) < 1 << 16:
            header.append(0x80 | 126)
            header += struct.pack("!H", len(data))
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", len(data))
        mask = secrets.token_bytes(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
        self._sock.sendall(bytes(header) + mask + masked)

    def _read(self, count: int) -> bytes:
        buffer = b""
        while len(buffer) < count:
            chunk = self._sock.recv(count - len(buffer))
            if not chunk:
                raise RenderError("Chrome closed the socket")
            buffer += chunk
        return buffer

    def recv(self) -> str | None:
        fragments: list[bytes] = []
        while True:
            first, second = self._read(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read(8))[0]
            mask = self._read(4) if second & 0x80 else b""
            payload = self._read(length)
            if mask:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
            if opcode == 0x8:
                return None
            if opcode == 0x9:  # ping
                self._sock.sendall(b"\x8a\x80" + secrets.token_bytes(4))
                continue
            if opcode == 0xA:  # pong
                continue
            fragments.append(payload)
            if first & 0x80:
                return b"".join(fragments).decode("utf-8")

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class _CDP:
    def __init__(self, ws_url: str) -> None:
        self._ws = _WebSocket(ws_url)
        self._next_id = 0

    def call(self, method: str, params: dict | None = None, session_id: str | None = None) -> dict:
        self._next_id += 1
        message: dict = {"id": self._next_id, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        self._ws.send(json.dumps(message))
        while True:
            raw = self._ws.recv()
            if raw is None:
                raise RenderError(f"Chrome closed the socket during {method}")
            try:
                reply = json.loads(raw)
            except ValueError:
                continue
            if reply.get("id") != message["id"]:
                continue
            if "error" in reply:
                raise RenderError(f"{method}: {reply['error']}")
            return reply.get("result", {})

    def close(self) -> None:
        self._ws.close()


class ChromeBrowser:
    """One headless Chrome tab reused for every page in a run."""

    def __init__(self, *, solve_timeout: float = 15.0) -> None:
        self.solve_timeout = solve_timeout
        self._profile = Path(tempfile.mkdtemp(prefix="seo-agent-render-"))
        self._process = subprocess.Popen(
            [
                _find_chrome(),
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1920,1080",
                "--remote-debugging-port=0",
                f"--user-data-dir={self._profile}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        port, path = self._wait_for_port()
        self._cdp = _CDP(f"ws://127.0.0.1:{port}{path}")
        target = self._cdp.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self._session = self._cdp.call(
            "Target.attachToTarget", {"targetId": target, "flatten": True}
        )["sessionId"]
        self._cdp.call("Page.enable", session_id=self._session)
        self._cdp.call(
            "Emulation.setUserAgentOverride",
            {"userAgent": config.USER_AGENT, "acceptLanguage": "en-GB,en;q=0.9"},
            session_id=self._session,
        )
        self._cdp.call(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": _INIT_SCRIPT},
            session_id=self._session,
        )

    def _wait_for_port(self, timeout: float = 20.0) -> tuple[int, str]:
        port_file = self._profile / "DevToolsActivePort"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if port_file.exists():
                lines = port_file.read_text(encoding="utf-8").splitlines()
                if len(lines) >= 2 and lines[0].strip():
                    return int(lines[0]), lines[1].strip()
            time.sleep(0.1)
        raise RenderError("Chrome did not expose a DevTools port")

    def _evaluate(self, expression: str) -> str:
        result = self._cdp.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
            session_id=self._session,
        )
        return str(result.get("result", {}).get("value") or "")

    def _navigate(self, url: str) -> None:
        self._cdp.call("Page.navigate", {"url": url}, session_id=self._session)
        deadline = time.monotonic() + self.solve_timeout
        while time.monotonic() < deadline:
            state = self._evaluate(
                "JSON.stringify({ready:document.readyState,title:document.title,href:location.href})"
            )
            try:
                info = json.loads(state) if state else {}
            except ValueError:
                info = {}
            # Do not read the previous page while the new navigation commits.
            if not _same_page(str(info.get("href", "")), url):
                time.sleep(0.4)
                continue
            title = info.get("title", "")
            if info.get("ready") == "complete" and title and not is_challenge_title(title):
                return
            time.sleep(0.4)

    def fetch(self, url: str, _session: object | None = None) -> dict:
        """Fetch ``url`` and return a dict shaped like seoextract's fetch_page."""

        started = time.monotonic()
        try:
            self._navigate(url)
            html = self._evaluate("document.documentElement.outerHTML")
            final_url = self._evaluate("location.href") or url
        except RenderError:
            return {
                "url": url,
                "final_url": url,
                "status_code": 0,
                "html": "",
                "response_time_ms": 0.0,
                "error": "render failure",
            }
        return {
            "url": url,
            "final_url": final_url,
            "status_code": 200,
            "html": html,
            "response_time_ms": round((time.monotonic() - started) * 1000, 2),
        }

    def fetch_text(self, url: str) -> str:
        """Return the rendered page's visible text (used for robots.txt)."""

        self._navigate(url)
        return self._evaluate("document.body ? document.body.innerText : ''")

    def close(self) -> None:
        try:
            self._cdp.call("Browser.close")
        except RenderError:
            pass
        self._cdp.close()
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()
        shutil.rmtree(self._profile, ignore_errors=True)


__all__ = [
    "CHALLENGE_TITLE_MARKERS",
    "ChromeBrowser",
    "RenderError",
    "is_challenge_title",
]
