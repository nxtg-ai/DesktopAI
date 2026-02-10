"""Browser automation via Playwright CDP connection.

Requires Chrome/Edge launched with --remote-debugging-port=9222.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .action_executor import ActionExecutionResult, TaskActionExecutor
from .schemas import TaskAction


class PlaywrightExecutor(TaskActionExecutor):
    """Browser automation executor using Playwright CDP connection."""

    mode = "playwright-cdp"

    def __init__(self, cdp_endpoint: str = "http://localhost:9222") -> None:
        """Initialize Playwright executor.

        Args:
            cdp_endpoint: Chrome DevTools Protocol endpoint URL
        """
        self._cdp_endpoint = cdp_endpoint
        self._browser: Optional[Any] = None
        self._playwright: Optional[Any] = None
        self._playwright_available = False

        # Lazy import to handle cases where playwright isn't installed
        try:
            import importlib.util
            self._playwright_available = importlib.util.find_spec("playwright") is not None
        except (ImportError, ValueError):
            self._playwright_available = False

    async def _ensure_connected(self) -> None:
        """Ensure Playwright is connected to the browser.

        Raises:
            RuntimeError: If playwright is not available or connection fails
        """
        if self._browser is not None:
            return

        if not self._playwright_available:
            raise RuntimeError("playwright not installed - run: pip install playwright")

        try:
            # Import here to avoid import errors when not installed
            from playwright.async_api import async_playwright

            if self._playwright is None:
                self._playwright = await async_playwright().start()

            self._browser = await self._playwright.chromium.connect_over_cdp(
                self._cdp_endpoint
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to connect to browser at {self._cdp_endpoint}: {exc}"
            ) from exc

    async def execute(self, action: TaskAction, *, objective: str, desktop_context=None) -> ActionExecutionResult:
        """Execute browser action using Playwright.

        Supported actions:
        - navigate: Navigate to URL (parameters: url)
        - click: Click element (parameters: selector)
        - fill: Fill input field (parameters: selector, text)
        - read_text: Read text from element (parameters: selector)
        - screenshot: Take screenshot (parameters: path [optional])
        - evaluate: Execute JavaScript (parameters: script)

        Args:
            action: Action to execute
            objective: Task objective for context

        Returns:
            ActionExecutionResult with ok status, result data, and optional error
        """
        if not self._playwright_available:
            return ActionExecutionResult(
                ok=False,
                error="playwright not installed - run: pip install playwright",
                result={
                    "executor": self.mode,
                    "mode": self.mode,
                    "action": action.action,
                    "ok": False,
                },
            )

        try:
            await self._ensure_connected()
        except Exception as exc:
            return ActionExecutionResult(
                ok=False,
                error=str(exc),
                result={
                    "executor": self.mode,
                    "mode": self.mode,
                    "action": action.action,
                    "ok": False,
                },
            )

        try:
            result = await self._execute_action(action, objective=objective)
            return ActionExecutionResult(
                ok=True,
                result={
                    "executor": self.mode,
                    "mode": self.mode,
                    "action": action.action,
                    "ok": True,
                    **result,
                },
            )
        except Exception as exc:
            return ActionExecutionResult(
                ok=False,
                error=str(exc),
                result={
                    "executor": self.mode,
                    "mode": self.mode,
                    "action": action.action,
                    "ok": False,
                },
            )

    async def _execute_action(self, action: TaskAction, *, objective: str) -> Dict[str, Any]:
        """Execute specific browser action.

        Args:
            action: Action to execute
            objective: Task objective for context

        Returns:
            Dict with action-specific result data

        Raises:
            RuntimeError: If action is unsupported or execution fails
        """
        if self._browser is None:
            raise RuntimeError("Browser not connected")

        # Get the active page from the first context
        contexts = self._browser.contexts
        if not contexts:
            raise RuntimeError("No browser contexts available")

        pages = contexts[0].pages
        if not pages:
            raise RuntimeError("No browser pages available")

        page = pages[0]
        action_name = (action.action or "").strip()
        params = dict(action.parameters or {})

        if action_name == "navigate":
            url = str(params.get("url", "")).strip()
            if not url:
                raise RuntimeError("navigate action requires 'url' parameter")
            await page.goto(url)
            return {"url": url, "title": await page.title()}

        if action_name == "click":
            selector = str(params.get("selector", "")).strip()
            if not selector:
                raise RuntimeError("click action requires 'selector' parameter")
            await page.click(selector)
            return {"selector": selector, "clicked": True}

        if action_name == "fill":
            selector = str(params.get("selector", "")).strip()
            text = str(params.get("text", ""))
            if not selector:
                raise RuntimeError("fill action requires 'selector' parameter")
            await page.fill(selector, text)
            return {"selector": selector, "text": text, "filled": True}

        if action_name == "read_text":
            selector = str(params.get("selector", "")).strip()
            if not selector:
                raise RuntimeError("read_text action requires 'selector' parameter")
            element = await page.query_selector(selector)
            if element is None:
                raise RuntimeError(f"Element not found: {selector}")
            text = await element.text_content()
            return {"selector": selector, "text": text or ""}

        if action_name == "screenshot":
            path = params.get("path")
            screenshot_bytes = await page.screenshot(
                path=path if path else None,
                full_page=params.get("full_page", False),
            )
            result: Dict[str, Any] = {"screenshot_taken": True}
            if path:
                result["path"] = path
            else:
                result["bytes_length"] = len(screenshot_bytes)
            return result

        if action_name == "evaluate":
            script = str(params.get("script", "")).strip()
            if not script:
                raise RuntimeError("evaluate action requires 'script' parameter")
            result_value = await page.evaluate(script)
            return {"script": script, "result": result_value}

        raise RuntimeError(f"unsupported action for playwright executor: {action_name}")

    def status(self) -> Dict[str, Any]:
        """Get executor status.

        Returns:
            Dict with mode, available status, and message
        """
        if not self._playwright_available:
            return {
                "mode": self.mode,
                "available": False,
                "connected": False,
                "cdp_endpoint": self._cdp_endpoint,
                "message": "Playwright not installed - run: pip install playwright",
            }

        connected = self._browser is not None
        return {
            "mode": self.mode,
            "available": True,
            "connected": connected,
            "cdp_endpoint": self._cdp_endpoint,
            "message": (
                "Playwright executor connected."
                if connected
                else "Playwright executor ready (not connected)."
            ),
        }

    async def preflight(self) -> Dict[str, Any]:
        """Run preflight checks for browser connection.

        Returns:
            Dict with mode, ok status, checks list, and message
        """
        checks: list[Dict[str, Any]] = []

        # Check if playwright is installed
        playwright_installed = self._playwright_available
        checks.append(
            {
                "name": "playwright_installed",
                "ok": playwright_installed,
                "detail": (
                    "Playwright library installed."
                    if playwright_installed
                    else "Playwright not installed - run: pip install playwright"
                ),
            }
        )

        if not playwright_installed:
            return {
                "mode": self.mode,
                "ok": False,
                "checks": checks,
                "message": "Playwright preflight failed: library not installed.",
            }

        # Check CDP connection
        try:
            await self._ensure_connected()
            checks.append(
                {
                    "name": "cdp_connection",
                    "ok": True,
                    "detail": f"Connected to browser at {self._cdp_endpoint}",
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "name": "cdp_connection",
                    "ok": False,
                    "detail": str(exc),
                }
            )

        # Check if pages are available
        if self._browser is not None:
            try:
                contexts = self._browser.contexts
                pages = contexts[0].pages if contexts else []
                pages_available = len(pages) > 0
                checks.append(
                    {
                        "name": "browser_pages",
                        "ok": pages_available,
                        "detail": (
                            f"{len(pages)} page(s) available."
                            if pages_available
                            else "No browser pages available."
                        ),
                    }
                )
            except Exception as exc:
                checks.append(
                    {
                        "name": "browser_pages",
                        "ok": False,
                        "detail": str(exc),
                    }
                )

        ok = all(bool(item.get("ok")) for item in checks)
        return {
            "mode": self.mode,
            "ok": ok,
            "checks": checks,
            "message": "Playwright preflight passed." if ok else "Playwright preflight failed.",
        }

    async def disconnect(self) -> None:
        """Disconnect from browser and cleanup resources."""
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
