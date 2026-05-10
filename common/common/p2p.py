"""libp2p event mesh for service-to-service job notifications.

Firestore remains the durable state store. This module provides the direct
P2P transport that tells the next service node to read and act on that state.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import queue
import socket
import threading
import uuid
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import settings
from . import db

logger = logging.getLogger("common.p2p")

PROTOCOL_ID = "/ian-km/jobs/1.0.0"
MAX_EVENT_BYTES = 128 * 1024

P2PEventHandler = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class P2PStatus:
    enabled: bool
    running: bool = False
    node_id: str = ""
    peer_id: str = ""
    listen_addrs: list[str] = field(default_factory=list)
    connected_peers: int = 0
    last_error: str = ""


class P2PNode:
    """Runs a libp2p host in a Trio thread and bridges events to asyncio."""

    def __init__(
        self,
        *,
        node_id: str,
        handlers: dict[str, P2PEventHandler],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.node_id = node_id
        self.handlers = handlers
        self.loop = loop
        self.outbox: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.status = P2PStatus(enabled=settings.P2P_ENABLED, node_id=node_id)

    def start(self) -> None:
        if not settings.P2P_ENABLED:
            logger.info("libp2p disabled for node %s", self.node_id)
            return
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(
            target=self._run_thread,
            name=f"p2p-{self.node_id}",
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.outbox.put({"type": "__stop__", "origin": self.node_id})
        if self.thread:
            self.thread.join(timeout=5)

    def publish(self, event_type: str, **payload: Any) -> None:
        if not settings.P2P_ENABLED:
            return
        event = {
            "id": str(uuid.uuid4()),
            "type": event_type,
            "origin": self.node_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        self.outbox.put(event)

    def _run_thread(self) -> None:
        try:
            import trio

            trio.run(self._run_trio)
        except Exception as exc:
            self.status.last_error = str(exc)
            self.status.running = False
            logger.exception("libp2p node crashed")

    async def _run_trio(self) -> None:
        import multiaddr
        import trio
        from libp2p import new_host
        from libp2p.crypto.ed25519 import create_new_key_pair
        from libp2p.custom_types import TProtocol
        from libp2p.peer.peerinfo import info_from_p2p_addr

        key_pair = _deterministic_key_pair(self.node_id, create_new_key_pair)
        listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{settings.P2P_PORT}")
        host = new_host(key_pair=key_pair, listen_addrs=[listen_addr])
        protocol_id = TProtocol(PROTOCOL_ID)
        connected: dict[str, Any] = {}

        async def handle_stream(stream: Any) -> None:
            try:
                raw = await stream.read(MAX_EVENT_BYTES)
                event = json.loads(raw.decode("utf-8"))
                if event.get("origin") == self.node_id:
                    return
                handler = self.handlers.get(event.get("type", ""))
                if handler:
                    future = asyncio.run_coroutine_threadsafe(handler(event), self.loop)
                    future.add_done_callback(_log_handler_exception)
            except Exception:
                logger.exception("Failed to handle libp2p event stream")
            finally:
                try:
                    await stream.close()
                except Exception:
                    pass

        host.set_stream_handler(protocol_id, handle_stream)

        async with host.run([listen_addr]):
            peer_id = str(host.get_id())
            self.status.peer_id = peer_id
            self.status.running = True
            self.status.listen_addrs = _advertised_addrs(peer_id)
            logger.info(
                "libp2p node %s listening as %s at %s",
                self.node_id,
                peer_id,
                self.status.listen_addrs,
            )

            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._registry_loop)
                nursery.start_soon(self._dial_loop, host, connected, info_from_p2p_addr, multiaddr)
                nursery.start_soon(self._publish_loop, host, connected, protocol_id)
                nursery.start_soon(self._stop_loop, nursery)

    async def _registry_loop(self) -> None:
        import trio

        if not settings.P2P_REGISTER_ENABLED:
            await trio.to_thread.run_sync(db.unregister_p2p_node, self.node_id)
            return

        while not self.stop_event.is_set():
            if self.status.peer_id and self.status.listen_addrs:
                await trio.to_thread.run_sync(
                    db.register_p2p_node,
                    self.node_id,
                    self.status.peer_id,
                    self.status.listen_addrs,
                )
            await trio.sleep(settings.P2P_DISCOVERY_INTERVAL_SECONDS)

    async def _dial_loop(self, host: Any, connected: dict[str, Any], info_from_p2p_addr: Any, multiaddr: Any) -> None:
        import trio

        while not self.stop_event.is_set():
            try:
                nodes = await trio.to_thread.run_sync(db.list_p2p_nodes)
                for node in nodes:
                    if node.get("node_id") == self.node_id:
                        continue
                    for addr in node.get("addrs", []):
                        try:
                            peer_info = info_from_p2p_addr(multiaddr.Multiaddr(addr))
                            peer_id = str(peer_info.peer_id)
                            if peer_id in connected:
                                continue
                            with trio.move_on_after(settings.P2P_DIAL_TIMEOUT_SECONDS) as scope:
                                await host.connect(peer_info)
                            if scope.cancelled_caught:
                                logger.debug(
                                    "libp2p dial timed out for %s after %ss",
                                    addr,
                                    settings.P2P_DIAL_TIMEOUT_SECONDS,
                                )
                                continue
                            connected[peer_id] = peer_info.peer_id
                            self.status.connected_peers = len(connected)
                            logger.info("libp2p connected %s -> %s", self.node_id, node.get("node_id"))
                        except Exception as exc:
                            logger.debug("libp2p dial failed for %s: %s", addr, exc)
            except Exception:
                logger.exception("libp2p discovery loop failed")
            await trio.sleep(settings.P2P_DISCOVERY_INTERVAL_SECONDS)

    async def _publish_loop(self, host: Any, connected: dict[str, Any], protocol_id: Any) -> None:
        import trio

        while not self.stop_event.is_set():
            event = await trio.to_thread.run_sync(self.outbox.get)
            if event.get("type") == "__stop__":
                continue
            data = json.dumps(event, default=str).encode("utf-8")
            if not connected:
                attempts = int(event.get("_attempts", 0))
                if attempts < 30:
                    event["_attempts"] = attempts + 1
                    await trio.sleep(1)
                    self.outbox.put(event)
                continue
            stale: set[str] = set()
            for peer_key, peer_id in list(connected.items()):
                try:
                    stream = await host.new_stream(peer_id, [protocol_id])
                    await stream.write(data)
                    await stream.close()
                except Exception as exc:
                    logger.warning("libp2p publish to %s failed: %s", peer_key, exc)
                    stale.add(peer_key)
            for peer_key in stale:
                connected.pop(peer_key, None)
            self.status.connected_peers = len(connected)

    async def _stop_loop(self, nursery: Any) -> None:
        import trio

        while not self.stop_event.is_set():
            await trio.sleep(0.5)
        nursery.cancel_scope.cancel()


def _deterministic_key_pair(node_id: str, factory: Callable[[bytes | None], Any]) -> Any:
    seed_base = f"ian-km-libp2p:{node_id}".encode("utf-8")
    for counter in range(100):
        seed = hashlib.sha256(seed_base + counter.to_bytes(2, "big")).digest()
        try:
            return factory(seed)
        except ValueError:
            continue
    return factory(None)


def _advertised_addrs(peer_id: str) -> list[str]:
    if settings.P2P_ADVERTISE_ADDRS:
        return [
            f"{addr.rstrip('/')}/p2p/{peer_id}" if "/p2p/" not in addr else addr
            for addr in settings.P2P_ADVERTISE_ADDRS.split(",")
            if addr.strip()
        ]
    host = settings.P2P_ADVERTISE_HOST
    if host:
        ip = _resolve_host(host)
        if ip:
            return [f"/ip4/{ip}/tcp/{settings.P2P_PORT}/p2p/{peer_id}"]
        return [f"/dns4/{host}/tcp/{settings.P2P_PORT}/p2p/{peer_id}"]
    if settings.P2P_AUTO_ADVERTISE_PUBLIC_IP:
        public_ip = _public_ip()
        if public_ip:
            return [f"/ip4/{public_ip}/tcp/{settings.P2P_PORT}/p2p/{peer_id}"]
    return [f"/ip4/127.0.0.1/tcp/{settings.P2P_PORT}/p2p/{peer_id}"]


def _resolve_host(host: str) -> str:
    try:
        return socket.gethostbyname(host)
    except OSError:
        return ""


def _public_ip() -> str:
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=2) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        return ""


def _log_handler_exception(future: asyncio.Future) -> None:
    try:
        future.result()
    except Exception:
        logger.exception("libp2p event handler failed")


_node: P2PNode | None = None


def start_node(
    node_id: str,
    handlers: dict[str, P2PEventHandler] | None = None,
) -> P2PNode:
    global _node
    loop = asyncio.get_running_loop()
    node_id = settings.P2P_NODE_ID or node_id
    _node = P2PNode(node_id=node_id, handlers=handlers or {}, loop=loop)
    _node.start()
    return _node


def stop_node() -> None:
    if _node:
        _node.stop()


def publish(event_type: str, **payload: Any) -> None:
    if _node:
        _node.publish(event_type, **payload)


def status() -> dict[str, Any]:
    if not _node:
        return P2PStatus(enabled=settings.P2P_ENABLED).__dict__
    return _node.status.__dict__
