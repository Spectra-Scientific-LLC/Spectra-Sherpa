"""Connection-scoped, interruptible requests for product WebSocket actions.

The host keeps reading control frames while work runs. Deadlines are absolute;
status updates never extend them. Disconnect and identity changes cancel work.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)
CANCEL_REQUEST = "cancel_request"


@dataclass(frozen=True)
class RequestPolicy:
    timeout_seconds: float = 60.0
    heartbeat_seconds: float = 15.0
    status_event: str = "sherpa_status"


class _RequestSocket:
    def __init__(self, socket, request_id):
        self.socket = socket
        self.request_id = request_id
        self.closed = False
        self.stage = "working"
        self.detail = "Waiting for the model response."

    def __getattr__(self, name):
        return getattr(self.socket, name)

    async def send_json(self, data, *args, **kwargs):
        if self.closed:
            return
        if isinstance(data, dict):
            data = {**data, "request_id": self.request_id}
            if data.get("type") == "sherpa_status" and isinstance(data.get("payload"), dict):
                self.stage = data["payload"].get("stage", self.stage)
                self.detail = data["payload"].get("detail") or self.detail
            elif data.get("type") == "sherpa_tool_start":
                self.stage, self.detail = "tool", f"Running {data.get('tool_name', 'workflow tool')}."
            elif data.get("type") == "sherpa_tool_result":
                self.stage, self.detail = "working", "Preparing the response from the tool result."
        await self.socket.send_json(data, *args, **kwargs)


class WebSocketRequests:
    def __init__(self):
        self.tasks: dict[tuple[int, str], tuple[Any, asyncio.Task]] = {}

    async def start(self, spec, socket, payload, user, limiter):
        from uuid import uuid4

        data = payload.get("payload", payload)
        request_id = data.get("request_id") or str(uuid4())
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            await socket.send_json({"type": spec.error_event, "detail": "Invalid request identity"})
            return
        data["request_id"] = request_id
        key = (id(socket), request_id)
        if key in self.tasks:
            return  # An in-flight request is never dispatched twice.
        if sum(k[0] == id(socket) for k in self.tasks) >= 4:
            await socket.send_json(
                {
                    "type": spec.error_event,
                    "request_id": request_id,
                    "detail": "Finish or stop an active request first.",
                }
            )
            return
        task = asyncio.create_task(self._run(spec, socket, payload, user, limiter, request_id))
        self.tasks[key] = (getattr(user, "id", None), task)
        task.add_done_callback(lambda _: self.tasks.pop(key, None))

    async def _run(self, spec, socket, payload, user, limiter, request_id):
        policy = spec.request_policy
        proxy = _RequestSocket(socket, request_id)
        started = asyncio.get_running_loop().time()

        async def heartbeat():
            while True:
                await asyncio.sleep(policy.heartbeat_seconds)
                await proxy.send_json(
                    {
                        "type": policy.status_event,
                        "payload": {
                            "stage": "working",
                            "detail": proxy.detail,
                            "elapsed_seconds": int(asyncio.get_running_loop().time() - started),
                            "heartbeat": True,
                        },
                    }
                )

        ticker = asyncio.create_task(heartbeat())
        terminal = None
        try:
            async with asyncio.timeout(policy.timeout_seconds):
                await spec.handler(proxy, payload, user, limiter)
        except TimeoutError:
            terminal = (
                "timeout",
                "Analysis timed out after one minute. Check any created workflow or run before retrying.",
            )
        except asyncio.CancelledError:
            terminal = ("interrupted", "Analysis interrupted. Any completed workflow or run has been preserved.")
        except Exception:
            logger.exception("WebSocket request failed: %s", spec.name)
            terminal = ("failed", "Analysis could not be completed.")
        finally:
            proxy.closed = True
            ticker.cancel()
            await asyncio.gather(ticker, return_exceptions=True)
            if terminal:
                try:
                    await socket.send_json(
                        {"type": spec.error_event, "request_id": request_id, "code": terminal[0], "detail": terminal[1]}
                    )
                except Exception:
                    pass  # Disconnect still cancels and cleans up the handler.

    def cancel(self, socket, user, request_id):
        entry = self.tasks.get((id(socket), request_id))
        if entry and entry[0] == getattr(user, "id", None) and not entry[1].cancelling():
            entry[1].cancel()

    async def close(self, socket):
        tasks = [task for (socket_id, _), (_, task) in list(self.tasks.items()) if socket_id == id(socket)]
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
