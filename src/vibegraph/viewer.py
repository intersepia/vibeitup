"""HTTP viewer: a tiny Starlette app that streams the graph to Vue + D3 via SSE."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import socket
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import __version__
from .store import GraphError, GraphStore, Mutation

LOG = logging.getLogger("vibegraph.viewer")
STATIC_DIR = Path(__file__).resolve().parent / "static"
# The viewer is a single local page with offline assets. Vue's in-browser
# template compiler needs 'unsafe-eval'; all styles are self-hosted, hence
# 'unsafe-inline' for Vue's style bindings only.
CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "base-uri 'none'; "
    "form-action 'none'"
)


class ViewerError(RuntimeError):
    pass


class EventHub:
    """In-process fan-out of full graph snapshots to SSE clients."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[str | None]] = set()
        self._closed = False

    @property
    def clients(self) -> int:
        return len(self._queues)

    def subscribe(self) -> asyncio.Queue[str | None]:
        queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=8)
        self._queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str | None]) -> None:
        self._queues.discard(queue)

    def publish(self, payload: dict[str, Any]) -> None:
        if self._closed:
            return
        message = _sse_frame(payload)
        for queue in list(self._queues):
            if queue.full():
                # Snapshots are idempotent: keep the newest one.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(message)

    def close(self) -> None:
        self._closed = True
        for queue in list(self._queues):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(None)
        self._queues.clear()


def _sse_frame(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: graph\ndata: {data}\n\n"


def _port_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def pick_port(host: str, preferred: int, attempts: int = 20) -> int:
    if not 1 <= preferred <= 65535:
        raise ViewerError("Port must be between 1 and 65535.")
    for candidate in range(preferred, min(preferred + attempts, 65536)):
        if _port_available(host, candidate):
            return candidate
    raise ViewerError(
        f"No free port found in range {preferred}-{preferred + attempts - 1} on {host}."
    )


def _public_host(host: str) -> str:
    if host in ("0.0.0.0", ""):
        return "127.0.0.1"
    if host == "::":
        return "[::1]"
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def create_app(
    store: GraphStore,
    hub: EventHub,
    *,
    meta: dict[str, Any],
) -> Starlette:
    static_dir = STATIC_DIR
    index_file = static_dir / "index.html"
    if not index_file.is_file():
        raise ViewerError(f"Viewer assets are missing: {index_file}")

    def snapshot(change: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = store.snapshot()
        payload["meta"] = dict(meta)
        if change is not None:
            payload["change"] = change
        return payload

    async def index(request: Request) -> FileResponse:
        return FileResponse(
            index_file,
            media_type="text/html; charset=utf-8",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": CSP,
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def graph_api(request: Request) -> JSONResponse:
        return JSONResponse(snapshot(), headers={"Cache-Control": "no-store"})

    async def health(request: Request) -> JSONResponse:
        state = store.snapshot()
        return JSONResponse(
            {
                "ok": True,
                "app": "vibegraph",
                "version": __version__,
                "revision": state["revision"],
                "nodes": state["stats"]["nodes"],
                "edges": state["stats"]["edges"],
                "clients": hub.clients,
                "demo": bool(meta.get("demo")),
            },
            headers={"Cache-Control": "no-store"},
        )

    async def events(request: Request) -> StreamingResponse:
        async def stream() -> AsyncIterator[str]:
            queue = hub.subscribe()
            try:
                yield "retry: 1500\n\n"
                yield _sse_frame(snapshot())
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    if item is None:
                        break
                    yield item
            finally:
                hub.unsubscribe(queue)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    routes = [
        Route("/", index),
        Route("/api/graph", graph_api),
        Route("/api/events", events),
        Route("/api/health", health),
        Mount("/static", StaticFiles(directory=static_dir), name="static"),
    ]
    return Starlette(routes=routes)


class _EmbeddedServer(uvicorn.Server):
    """Uvicorn without signal handlers: stdin owns the lifecycle in MCP mode."""

    @contextlib.contextmanager
    def capture_signals(self):  # type: ignore[override]
        yield


class ViewerServer:
    def __init__(
        self,
        store: GraphStore,
        hub: EventHub,
        *,
        host: str = "127.0.0.1",
        port: int = 8787,
        demo: bool = False,
        demo_interval: float = 0.55,
    ) -> None:
        self.store = store
        self.hub = hub
        self.requested_host = host
        self.requested_port = port
        self.demo = demo
        self.demo_interval = demo_interval
        self.port: int | None = None
        self.url: str | None = None
        self._server: _EmbeddedServer | None = None
        self._task: asyncio.Task[None] | None = None
        self._demo_task: asyncio.Task[None] | None = None
        self._meta = {
            "app": "VibeGraph",
            "version": __version__,
            "demo": demo,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    @property
    def meta(self) -> dict[str, Any]:
        return dict(self._meta)

    async def start(self) -> None:
        self.port = pick_port(self.requested_host, self.requested_port)
        app = create_app(self.store, self.hub, meta=self._meta)
        config = uvicorn.Config(
            app,
            host=self.requested_host,
            port=self.port,
            log_config=None,
            log_level="warning",
            access_log=False,
            lifespan="off",
            server_header=False,
            timeout_graceful_shutdown=2,
        )
        self._server = _EmbeddedServer(config)
        self._task = asyncio.create_task(self._server.serve(), name="vibegraph-viewer")
        deadline = asyncio.get_running_loop().time() + 6.0
        while asyncio.get_running_loop().time() < deadline:
            if self._server.started:
                break
            if self._task.done():
                break
            await asyncio.sleep(0.02)

        if self._server is None or not self._server.started:
            error: BaseException | None = None
            if self._task.done():
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    error = self._task.exception()
            if self._task:
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._task
            raise ViewerError(
                f"Viewer did not start on {self.requested_host}:{self.port}"
                + (f" ({error})" if error else " (timeout).")
            )

        public = _public_host(self.requested_host)
        self.url = f"http://{public}:{self.port}"
        if self.demo:
            self._demo_task = asyncio.create_task(
                run_demo(self.store, self.hub, self._meta, self.demo_interval),
                name="vibegraph-demo",
            )

    async def stop(self) -> None:
        self.hub.close()
        if self._demo_task is not None:
            self._demo_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._demo_task
            self._demo_task = None
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=6.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                if self._server is not None:
                    self._server.force_exit = True
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._task
            except Exception:
                LOG.exception("Viewer stopped with an error")
            self._task = None


async def run_demo(
    store: GraphStore,
    hub: EventHub,
    meta: dict[str, Any],
    interval: float = 0.55,
) -> None:
    """Continuously build, detach and re-attach a small illustrative tree."""

    async def publish(mutation: Mutation | None = None) -> None:
        if mutation is None:
            payload = store.snapshot()
        else:
            payload = mutation.state
            payload["change"] = mutation.change
        payload["meta"] = dict(meta)
        hub.publish(payload)

    steps: list[tuple[str, str | None, str | None, str | None]] = [
        # (id, label, parent, note)
        ("claude", "Claude", "root", "spricht MCP über stdio"),
        ("tools", "Tool Calls", "claude", ""),
        ("add_edge", "add_edge()", "tools", "A geht zu B"),
        ("set_parent", "set_parent()", "tools", "B gehört zu C"),
        ("delete_edge", "delete_edge()", "tools", "löst nur die Kante"),
        ("server", "MCP Server", "root", "Python, stdio"),
        ("store", "Graph Store", "server", "atomar, JSON"),
        ("json", "graph.json", "store", "leicht & lesbar"),
        ("sse", "SSE Hub", "server", "live im Browser"),
        ("viewer", "Browser", "root", "Vue 3 + D3"),
        ("vue", "Vue 3", "viewer", "reaktives UI"),
        ("d3", "D3.js", "viewer", "Tidy Tree"),
        ("layout", "Layout", "d3", "links → rechts"),
    ]

    while True:
        try:
            with contextlib.suppress(GraphError):
                mutation = store.reset(confirm=True)
                if mutation.changed:
                    await publish(mutation)
            await asyncio.sleep(1.2)

            for node_id, label, parent, note in steps:
                mutation = store.add_node(
                    node_id, label=label or "", note=note or "", parent=parent
                )
                if mutation.changed:
                    await publish(mutation)
                await asyncio.sleep(interval)

            await asyncio.sleep(1.0)
            for source, target, label in (
                ("server", "store", "writes"),
                ("server", "sse", "streams"),
                ("viewer", "d3", "renders"),
            ):
                mutation = store.add_edge(source, target, label)
                if mutation.changed:
                    await publish(mutation)
                await asyncio.sleep(interval)

            await asyncio.sleep(3.5)
            mutation = store.delete_edge("viewer", "d3")
            await publish(mutation)
            await asyncio.sleep(5.0)

            mutation = store.set_parent("d3", "viewer", label="renders again")
            await publish(mutation)
            await asyncio.sleep(6.0)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("Demo loop failed; retrying in 3s")
            await asyncio.sleep(3.0)


# ------------------------------------------------------------------ CLI mode
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vibegraph-viewer",
        description="Serve the VibeGraph viewer (read-only) for a graph file or a demo.",
    )
    parser.add_argument(
        "--graph",
        default=os.environ.get("VIBEGRAPH_GRAPH", "graph.json"),
        help="Path to graph.json (default: %(default)s)",
    )
    parser.add_argument("--host", default=os.environ.get("VIBEGRAPH_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("VIBEGRAPH_PORT", "8787"))
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Ignore --graph and loop a temporary demo graph (no files touched in your project).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


async def _run_viewer(args: argparse.Namespace) -> None:
    if args.demo:
        demo_dir = Path(tempfile.mkdtemp(prefix="vibegraph-demo-"))
        store = GraphStore(demo_dir / "graph.json", root_label="VibeGraph")
        LOG.info("Demo graph: %s", store.path)
    else:
        store = GraphStore(args.graph)
        state = store.snapshot()
        LOG.info(
            "Graph: %s (revision %s, %s nodes)",
            store.path,
            state["revision"],
            state["stats"]["nodes"],
        )

    hub = EventHub()
    viewer = ViewerServer(
        store,
        hub,
        host=args.host,
        port=args.port,
        demo=bool(args.demo),
    )
    await viewer.start()
    print(
        f"VibeGraph viewer: {viewer.url}\n"
        f"  graph: {store.path}\n"
        f"  API:   {viewer.url}/api/graph\n"
        f"  SSE:   {viewer.url}/api/events\n"
        "Press Ctrl+C to stop.",
        flush=True,
    )
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await viewer.stop()


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="[vibegraph] %(message)s",
    )
    try:
        asyncio.run(_run_viewer(args))
    except KeyboardInterrupt:
        pass
    except (GraphError, ViewerError) as exc:
        print(f"[vibegraph] {exc}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
