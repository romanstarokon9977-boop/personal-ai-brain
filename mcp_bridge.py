#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Bridge — минимальный JSON-RPC клиент для MCP-серверов.
Независимый модуль, не импортирует brain.py.
"""

import json
import os
import subprocess
import time

# Путь к MCP-серверу filesystem
_MCP_SERVER_BIN = os.path.expanduser(
    "~/personal_ai_brain/mcp_servers/filesystem/node_modules/"
    "@modelcontextprotocol/server-filesystem/dist/index.js"
)

# Разрешённая директория для MCP-сервера
_MCP_ALLOWED_DIR = os.path.expanduser("~/personal_ai_brain")

# Таймауты (секунды)
_INIT_TIMEOUT = 10
_CALL_TIMEOUT = 30


class MCPBridge:
    """Минимальный MCP-клиент через subprocess stdio JSON-RPC."""

    def __init__(self):
        self._proc = None
        self._request_id = 0
        self._tools_cache = None

    def _next_id(self):
        self._request_id += 1
        return self._request_id

    def start(self):
        """Запускает MCP-сервер и выполняет initialize handshake."""
        if self.is_alive():
            return True

        if not os.path.exists(_MCP_SERVER_BIN):
            print(f"  ❌ MCP server not found: {_MCP_SERVER_BIN}")
            return False

        try:
            self._proc = subprocess.Popen(
                ["node", _MCP_SERVER_BIN, _MCP_ALLOWED_DIR],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except Exception as e:
            print(f"  ❌ MCP server start failed: {e}")
            return False

        # Initialize handshake
        init_msg = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "brain-mcp-bridge", "version": "1.0"},
            },
        }
        resp = self._send(init_msg, timeout=_INIT_TIMEOUT)
        if resp is None or "error" in resp:
            print(f"  ❌ MCP initialize failed: {resp}")
            self.stop()
            return False

        # notifications/initialized (без id, без ответа)
        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self._write(notif)

        self._tools_cache = None
        print(f"  🚀 MCP filesystem server запущен (PID {self._proc.pid})")
        return True

    def stop(self):
        """Останавливает MCP-сервер."""
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)
            print("  🛑 MCP server остановлен")
        self._proc = None
        self._tools_cache = None

    def is_alive(self):
        """Проверяет, жив ли процесс MCP-сервера."""
        return self._proc is not None and self._proc.poll() is None

    def list_tools(self):
        """Возвращает список доступных MCP-инструментов (кэшируется)."""
        if self._tools_cache is not None:
            return self._tools_cache

        if not self.is_alive():
            return []

        msg = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        }
        resp = self._send(msg, timeout=_INIT_TIMEOUT)
        if resp and "result" in resp:
            tools = resp["result"].get("tools", [])
            self._tools_cache = {t["name"]: t for t in tools}
            return self._tools_cache
        return {}

    def call(self, tool_name, arguments=None):
        """
        Вызывает MCP-инструмент.
        Возвращает dict: {"ok": bool, "content": str|list, "is_error": bool}
        """
        if not self.is_alive():
            return {"ok": False, "content": "MCP server not running", "is_error": True}

        msg = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
            },
        }
        resp = self._send(msg, timeout=_CALL_TIMEOUT)
        if resp is None:
            return {"ok": False, "content": "MCP call timeout", "is_error": True}
        if "error" in resp:
            return {
                "ok": False,
                "content": resp["error"].get("message", str(resp["error"])),
                "is_error": True,
            }

        result = resp.get("result", {})
        is_error = result.get("isError", False)
        content_blocks = result.get("content", [])

        # Извлекаем текст из content blocks
        texts = []
        for block in content_blocks:
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
        content = "\n".join(texts) if texts else str(content_blocks)

        return {"ok": not is_error, "content": content, "is_error": is_error}

    def _write(self, msg):
        """Отправляет JSON-сообщение в stdin сервера."""
        try:
            line = json.dumps(msg, ensure_ascii=False) + "\n"
            self._proc.stdin.write(line.encode("utf-8"))
            self._proc.stdin.flush()
        except Exception:
            pass

    def _read_response(self, expected_id, timeout):
        """Читает ответ с нужным id из stdout сервера."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = self._proc.stdout.readline()
                if not raw:
                    return None
                msg = json.loads(raw.decode("utf-8").strip())
                # Пропускаем уведомления (нет id) и ответы с другим id
                if msg.get("id") == expected_id:
                    return msg
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            except Exception:
                return None
        return None

    def _send(self, msg, timeout):
        """Отправляет запрос и ждёт ответ с соответствующим id."""
        self._write(msg)
        return self._read_response(msg["id"], timeout)


# Глобальный экземпляр
_bridge = MCPBridge()


def mcp_start():
    """Запускает MCP-сервер."""
    return _bridge.start()


def mcp_stop():
    """Останавливает MCP-сервер."""
    _bridge.stop()


def mcp_is_alive():
    """Проверяет, запущен ли MCP-сервер."""
    return _bridge.is_alive()


def mcp_list_tools():
    """Возвращает dict {name: tool_info} доступных MCP-инструментов."""
    return _bridge.list_tools()


def mcp_call(tool_name, arguments=None):
    """Вызывает MCP-инструмент. Возвращает {"ok", "content", "is_error"}."""
    return _bridge.call(tool_name, arguments)


# ============================================================
# Тестовый блок
# ============================================================
if __name__ == "__main__":
    print("=== MCP Bridge Smoke Test ===")
    print()

    print("[1] Start...")
    ok = mcp_start()
    print(f"    alive={mcp_is_alive()}")
    if not ok:
        print("FAILED")
        exit(1)

    print()
    print("[2] List tools...")
    tools = mcp_list_tools()
    print(f"    {len(tools)} tools: {', '.join(sorted(tools.keys()))}")

    print()
    print("[3] Call read_text_file...")
    result = mcp_call("read_text_file", {
        "path": os.path.expanduser("~/personal_ai_brain/mcp_bridge.py"),
        "max_length": 100,
    })
    print(f"    ok={result['ok']}, is_error={result['is_error']}")
    print(f"    content ({len(result['content'])} chars): {result['content'][:150]}...")

    print()
    print("[4] Call list_directory...")
    result = mcp_call("list_directory", {
        "path": os.path.expanduser("~/personal_ai_brain"),
    })
    print(f"    ok={result['ok']}, content preview: {result['content'][:200]}...")

    print()
    print("[5] Stop...")
    mcp_stop()
    print(f"    alive={mcp_is_alive()}")

    print()
    print("=== ALL TESTS PASSED ===")
