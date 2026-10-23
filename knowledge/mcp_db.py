"""Read-only official Neo4j MCP transport for the temporal LangGraph workflow.

One stdio session lives on one async task. A bounded queue bridges Streamlit's
synchronous reruns to the MCP client without restarting a server for every query.
"""

import asyncio
import atexit
import json
import queue
import re
import sys
import threading
from concurrent.futures import Future
from datetime import datetime, timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import Settings


def mcp_parameters(query, params):
    """MCP JSON has no native datetime type: preserve Neo4j datetime comparisons."""
    encoded = {}
    for key, value in params.items():
        if isinstance(value, datetime):
            query = re.sub(r"\$" + re.escape(key) + r"\b", "datetime($" + key + ")", query)
            encoded[key] = value.isoformat()
        else:
            encoded[key] = value
    return query, encoded


def result_rows(result):
    if result.isError:
        raise ConnectionError("Neo4j MCP rejected the read query. Check the local server.")
    value = result.structuredContent
    if value is None:
        texts = [c.text for c in result.content if c.type == "text"]
        value = json.loads("\n".join(texts))
    if isinstance(value, dict):
        for key in ("result", "results", "records", "data"):
            if key in value:
                value = value[key]
                break
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("Unexpected Neo4j MCP result format")
    return value


class Neo4jMCPDatabase:
    transport = "neo4j-mcp/stdio"

    def __init__(self, settings=None):
        self.settings = settings or Settings.from_env()
        if not self.settings.neo4j_password:
            raise ValueError("Set NEO4J_PASSWORD in .env.")
        self._queue = queue.Queue(maxsize=16)
        self._ready = Future()
        self._closed = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="neo4j-mcp-client")
        self._thread.start()
        try:
            self._ready.result(timeout=30)
        except Exception:
            self.close()
            raise ConnectionError("Local read-only Neo4j MCP could not start.") from None
        atexit.register(self.close)

    def _run(self):
        try:
            asyncio.run(self._serve())
        except Exception:
            if not self._ready.done():
                self._ready.set_exception(ConnectionError("MCP initialization failed"))
            while not self._queue.empty():
                item = self._queue.get_nowait()
                if item is not None:
                    item[2].set_exception(ConnectionError("Neo4j MCP connection closed"))

    async def _serve(self):
        s = self.settings
        env = {
            "NEO4J_MCP_URI": s.neo4j_uri.replace("localhost", "127.0.0.1"),
            "NEO4J_MCP_USERNAME": s.neo4j_username,
            "NEO4J_MCP_PASSWORD": s.neo4j_password,
            "NEO4J_MCP_DATABASE": s.neo4j_database,
            "NEO4J_MCP_READ_ONLY": "true",
            "NEO4J_MCP_TELEMETRY": "false",
            "NEO4J_MCP_LOG_LEVEL": "error",
        }
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "neo4j_mcp_server"],
            env=env,
        )
        async with stdio_client(server) as (reader, writer):
            async with ClientSession(
                reader, writer, read_timeout_seconds=timedelta(seconds=20)
            ) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                names = {t.name for t in tools}
                if "read-cypher" not in names or "write-cypher" in names:
                    raise ValueError("Neo4j MCP must expose read-cypher with writes disabled")
                self.tools = sorted(names)
                self._ready.set_result(True)
                while True:
                    item = await asyncio.to_thread(self._queue.get)
                    if item is None:
                        break
                    name, arguments, future = item
                    if future.cancelled():
                        continue
                    try:
                        result = await session.call_tool(name, arguments)
                        future.set_result(result)
                    except Exception:
                        future.set_exception(ConnectionError("Neo4j MCP read call failed"))

    def call(self, tool, arguments):
        if self._closed or not self._thread.is_alive():
            raise ConnectionError("Neo4j MCP session is closed")
        if tool not in {"read-cypher", "get-schema"}:
            raise ValueError("Only read-only Neo4j tools are enabled")
        future = Future()
        self._queue.put((tool, arguments, future), timeout=2)
        return future.result(timeout=25)

    def read(self, cypher, **params):
        query, parameters = mcp_parameters(cypher, params)
        return result_rows(self.call("read-cypher", {"query": query, "params": parameters}))

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
            if self._thread.is_alive():
                self._thread.join(timeout=2)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
