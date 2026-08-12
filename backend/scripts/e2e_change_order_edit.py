from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from urllib.request import urlopen

import websockets


CHROME_DEBUG_PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9223"))


class Chrome:
    def __init__(self, websocket_url: str) -> None:
        self.websocket_url = websocket_url
        self._next_id = 0
        self._socket: Any = None

    async def __aenter__(self) -> "Chrome":
        self._socket = await websockets.connect(
            self.websocket_url,
            origin=f"http://127.0.0.1:{CHROME_DEBUG_PORT}",
        )
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self._socket.close()

    async def command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        command_id = self._next_id
        await self._socket.send(
            json.dumps({"id": command_id, "method": method, "params": params or {}})
        )
        while True:
            response = json.loads(await self._socket.recv())
            if response.get("id") == command_id:
                if "error" in response:
                    raise RuntimeError(response["error"])
                return response.get("result", {})

    async def evaluate(self, expression: str) -> Any:
        result = await self.command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        return result["result"].get("value")

    async def wait_for(self, expression: str, *, timeout: float = 15) -> Any:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            value = await self.evaluate(expression)
            if value:
                return value
            await asyncio.sleep(0.2)
        raise TimeoutError(f"Timed out waiting for: {expression}")


async def main() -> None:
    with urlopen(f"http://127.0.0.1:{CHROME_DEBUG_PORT}/json", timeout=5) as response:
        targets = json.load(response)
    page = next(target for target in targets if target["type"] == "page")

    async with Chrome(page["webSocketDebuggerUrl"]) as chrome:
        await chrome.command("Page.enable")
        await chrome.command(
            "Page.navigate",
            {"url": "http://127.0.0.1:3000/projects/change-orders"},
        )
        await chrome.wait_for(
            "document.readyState === 'complete' && "
            "document.body.innerText.includes('Change Orders')"
        )
        page_text = await chrome.evaluate("document.body.innerText")
        if "Send for Signature" not in page_text:
            raise RuntimeError(f"No editable draft rendered. Page text: {page_text[:1000]}")

        opened = await chrome.evaluate(
            """(() => {
              const draftArticle = [...document.querySelectorAll('article')].find(article =>
                [...article.querySelectorAll('button')].some(button =>
                  button.textContent.includes('Send for Signature')));
              const menu = draftArticle?.querySelector('button[aria-label^="Actions for"]');
              menu?.click();
              return Boolean(menu);
            })()"""
        )
        if not opened:
            raise RuntimeError("Could not find a draft change order action menu")

        edit_href = await chrome.wait_for(
            """(() => {
              const link = [...document.querySelectorAll('a')].find(a =>
                a.textContent.trim() === 'Edit' && a.getAttribute('href')?.endsWith('/edit'));
              if (!link) return '';
              link.click();
              return link.getAttribute('href');
            })()"""
        )
        await chrome.wait_for("location.pathname.endsWith('/edit')")
        loaded_address = await chrome.wait_for(
            """(() => {
              const heading = [...document.querySelectorAll('h1')].find(h =>
                h.textContent.trim() === 'Edit Change Order');
              const address = document.querySelector('input[list="change-order-lot-options"]');
              return heading && address?.value;
            })()"""
        )

        save_clicked = await chrome.evaluate(
            """(() => {
              const button = [...document.querySelectorAll('button')].find(b =>
                b.textContent.trim() === 'Save Changes');
              button?.click();
              return Boolean(button);
            })()"""
        )
        if not save_clicked:
            raise RuntimeError("Edit form loaded but Save Changes was not available")
        await chrome.wait_for("location.pathname === '/projects/change-orders'", timeout=20)

        print(
            json.dumps(
                {
                    "menu_opened": opened,
                    "edit_href": edit_href,
                    "form_loaded": True,
                    "address": loaded_address,
                    "save_completed": True,
                    "final_path": await chrome.evaluate("location.pathname"),
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
