"""Screenshot capture and base64 encoding tool for Lyra.

Uses macOS ``screencapture`` to grab the screen, encodes the image to
base64 for multimodal AI consumption, and cleans up stale captures.
"""

import asyncio
import base64
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("LYRA.Tools.Vision")

SCREENSHOT_DIR: Path = Path.home() / ".lyra" / "screenshots"
MAX_KEPT_SCREENSHOTS: int = 5


def _cleanup_old_screenshots(directory: Path, keep: int = MAX_KEPT_SCREENSHOTS) -> None:
    """Remove oldest screenshots so that at most *keep* remain.

    Args:
        directory: The screenshot directory.
        keep: Number of most-recent screenshots to retain.
    """
    try:
        pngs = sorted(
            directory.glob("lyra_screen_*.png"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in pngs[keep:]:
            try:
                old.unlink()
                logger.debug("Deleted old screenshot: %s", old.name)
            except OSError as exc:
                logger.warning("Could not delete %s: %s", old.name, exc)
    except Exception as exc:
        logger.warning("Screenshot cleanup failed: %s", exc)


async def take_screenshot() -> dict:
    """Capture the current screen and return the image as base64-encoded PNG.

    Returns:
        A dict with ``success``, ``path``, ``base64``, and ``size_bytes``
        on success, or ``success`` and ``error`` on failure.
    """
    logger.info("Taking screenshot")

    try:
        # Ensure the screenshot directory exists
        await asyncio.to_thread(SCREENSHOT_DIR.mkdir, parents=True, exist_ok=True)

        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filepath = SCREENSHOT_DIR / f"lyra_screen_{timestamp}.png"

        process = await asyncio.create_subprocess_exec(
            "screencapture", "-x", str(filepath),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            _, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=10,
            )
        except asyncio.TimeoutError:
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass
            return {"success": False, "error": "Screenshot timed out after 10 seconds"}

        if process.returncode != 0:
            err_msg = stderr_bytes.decode(errors="replace").strip()
            return {
                "success": False,
                "error": f"screencapture failed (exit {process.returncode}): {err_msg}",
            }

        if not filepath.exists():
            return {"success": False, "error": "Screenshot file was not created"}

        image_bytes = await asyncio.to_thread(filepath.read_bytes)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        size = len(image_bytes)

        logger.info("Screenshot saved: %s (%d bytes)", filepath, size)

        # Housekeeping – keep only the most recent screenshots
        await asyncio.to_thread(_cleanup_old_screenshots, SCREENSHOT_DIR)

        return {
            "success": True,
            "path": str(filepath),
            "base64": encoded,
            "size_bytes": size,
        }

    except Exception as exc:
        logger.exception("Failed to take screenshot")
        return {"success": False, "error": str(exc)}
