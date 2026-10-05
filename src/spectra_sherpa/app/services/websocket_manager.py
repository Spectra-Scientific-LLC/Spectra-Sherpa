from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self._channels: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._authorizers: dict[tuple[WebSocket, str], Callable[[], Awaitable[bool]]] = {}

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()

    async def subscribe(self, websocket: WebSocket, channel: str, authorize=None) -> None:
        async with self._lock:
            self._channels.setdefault(channel, set()).add(websocket)
            if authorize is not None:
                self._authorizers[websocket, channel] = authorize

    async def unsubscribe(self, websocket: WebSocket, channel: str) -> None:
        async with self._lock:
            connections = self._channels.get(channel)
            if not connections:
                return
            connections.discard(websocket)
            self._authorizers.pop((websocket, channel), None)
            if not connections:
                self._channels.pop(channel, None)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            for channel, connections in self._channels.items():
                connections.discard(websocket)
                self._authorizers.pop((websocket, channel), None)

    async def broadcast(self, channel: str, message: dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._channels.get(channel, set()))

        stale: list[WebSocket] = []
        for websocket in connections:
            try:
                authorize = self._authorizers.get((websocket, channel))
                if authorize is not None and not await authorize():
                    stale.append(websocket)
                    continue
                await websocket.send_json(message)
            except Exception:
                stale.append(websocket)

        if stale:
            async with self._lock:
                connections = self._channels.get(channel)
                if connections:
                    for websocket in stale:
                        connections.discard(websocket)
                        self._authorizers.pop((websocket, channel), None)


ws_manager = WebSocketManager()
