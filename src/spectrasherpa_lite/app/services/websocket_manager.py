from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self._channels: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()

    async def subscribe(self, websocket: WebSocket, channel: str) -> None:
        async with self._lock:
            self._channels.setdefault(channel, set()).add(websocket)

    async def unsubscribe(self, websocket: WebSocket, channel: str) -> None:
        async with self._lock:
            connections = self._channels.get(channel)
            if not connections:
                return
            connections.discard(websocket)
            if not connections:
                self._channels.pop(channel, None)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            for connections in self._channels.values():
                connections.discard(websocket)

    async def broadcast(self, channel: str, message: dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._channels.get(channel, set()))

        stale: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception:
                stale.append(websocket)

        if stale:
            async with self._lock:
                connections = self._channels.get(channel)
                if connections:
                    for websocket in stale:
                        connections.discard(websocket)


ws_manager = WebSocketManager()
