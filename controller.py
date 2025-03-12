import asyncio
import aiohttp
import websockets
import signal
import logging
import os
import sys
from typing import Optional, Dict, Any, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class ApplicationState:
    """Global application state container"""
    def __init__(self):
        self.browser_id: Optional[str] = None
        self.chromium_process: Optional[asyncio.subprocess.Process] = None
        self.server: Optional[websockets.WebSocketServer] = None
        self.shutdown_event = asyncio.Event()
        self.active_connections: set = set()

# Configuration validation
def validate_port(port: int) -> int:
    if 1 <= port <= 65535:
        return port
    raise ValueError(f"Invalid port number: {port}")

# Environment configuration
CHROME_DEBUG_HOST = os.environ.get("CHROME_DEBUG_HOST", "127.0.0.1")
CHROME_DEBUG_PORT = validate_port(int(os.environ.get("CHROME_DEBUG_PORT", "9223")))
PROXY_LISTEN_HOST = os.environ.get("PROXY_LISTEN_HOST", "0.0.0.0")
PROXY_LISTEN_PORT = validate_port(int(os.environ.get("PROXY_LISTEN_PORT", "9222")))
CHROMIUM_EXECUTABLE = os.environ.get("CHROMIUM_EXECUTABLE", "chromium")
RETRY_ATTEMPTS = int(os.environ.get("RETRY_ATTEMPTS", "10"))
INITIAL_RETRY_DELAY = float(os.environ.get("INITIAL_RETRY_DELAY", "1.0"))
MAX_RETRY_DELAY = float(os.environ.get("MAX_RETRY_DELAY", "30.0"))
CONNECT_TIMEOUT = float(os.environ.get("CONNECT_TIMEOUT", "10.0"))
CLOSE_TIMEOUT = float(os.environ.get("CLOSE_TIMEOUT", "2.0"))

async def forward_websocket(src: websockets.WebSocketClientProtocol, dst: websockets.WebSocketClientProtocol) -> None:
    """Bidirectional WebSocket forwarding with improved error handling"""
    try:
        async for message in src:
            try:
                await dst.send(message)
            except websockets.ConnectionClosed:
                logger.debug("Destination connection closed during send")
                break
    except websockets.ConnectionClosedOK:
        logger.debug("Source connection closed normally")
    except websockets.ConnectionClosedError as e:
        logger.debug(f"Connection closed abruptly: {e}")
    except Exception as e:
        logger.error(f"Unexpected forwarding error: {e}", exc_info=True)
    finally:
        # Graceful close with timeout protection
        try:
            if not dst.closed:
                await dst.close()
        except Exception as e:
            logger.debug(f"Error closing destination: {e}")

        try:
            if not src.closed:
                await src.close()
        except Exception as e:
            logger.debug(f"Error closing source: {e}")

async def proxy_handler(ws: websockets.WebSocketServerProtocol, path: str, state: ApplicationState) -> None:
    """Handle WebSocket connections with enhanced error handling"""
    state.active_connections.add(ws)
    try:
        if path != "/devtools/browser":
            logger.warning(f"Invalid path requested: {path}")
            await ws.close(code=1003, reason="Invalid request path")
            return

        if not state.browser_id:
            logger.error("Browser ID not available")
            await ws.close(code=1001, reason="Browser not ready")
            return

        real_url = f"ws://{CHROME_DEBUG_HOST}:{CHROME_DEBUG_PORT}/devtools/browser/{state.browser_id}"
        try:
            async with websockets.connect(
                real_url,
                open_timeout=CONNECT_TIMEOUT,
                close_timeout=CLOSE_TIMEOUT
            ) as chrome_ws:
                logger.info(f"Proxy connection established for {ws.remote_address}")
                fwd_task = asyncio.create_task(forward_websocket(ws, chrome_ws))
                rev_task = asyncio.create_task(forward_websocket(chrome_ws, ws))
                
                # Wait for either connection to close
                done, pending = await asyncio.wait(
                    [fwd_task, rev_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # Cancel remaining tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        except websockets.InvalidURI:
            logger.error(f"Invalid Chromium debug URL: {real_url}")
        except websockets.InvalidHandshake:
            logger.error("Handshake failed with Chromium debugger")
        except asyncio.TimeoutError:
            logger.warning("Connection timeout with Chromium debugger")

    except Exception as e:
        logger.error(f"Proxy error: {e}", exc_info=True)
    finally:
        try:
            await ws.close()
        except Exception as e:
            logger.debug(f"Error closing client connection: {e}")
        state.active_connections.discard(ws)

async def fetch_browser_id(state: ApplicationState) -> str:
    """Fetch browser ID with configurable retry logic"""
    delay = INITIAL_RETRY_DELAY
    for attempt in range(RETRY_ATTEMPTS):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://{CHROME_DEBUG_HOST}:{CHROME_DEBUG_PORT}/json/version",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    info = await resp.json()
                    debugger_url = info["webSocketDebuggerUrl"]
                    return debugger_url.split("/devtools/browser/")[1]
        except (aiohttp.ClientError, KeyError, IndexError) as e:
            if attempt < RETRY_ATTEMPTS - 1:
                logger.warning(f"Browser ID fetch failed (attempt {attempt+1}): {e}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAX_RETRY_DELAY)
            else:
                raise RuntimeError(f"Failed to fetch browser ID after {RETRY_ATTEMPTS} attempts") from e

async def log_stream(stream: Optional[asyncio.StreamReader], level: Any) -> None:
    """Log subprocess output with specified log level"""
    if not stream:
        return
    while True:
        line = await stream.readline()
        if not line:
            break
        level(line.decode().strip())

async def monitor_chromium_process(state: ApplicationState) -> None:
    """Monitor Chromium process lifecycle"""
    if not state.chromium_process:
        return
    
    returncode = await state.chromium_process.wait()
    logger.error(f"Chromium exited unexpectedly (code: {returncode})")
    state.shutdown_event.set()

async def start_chromium(state: ApplicationState) -> None:
    """Start Chromium process with configurable parameters"""
    chromium_args = [
        CHROMIUM_EXECUTABLE,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        f"--remote-debugging-address={CHROME_DEBUG_HOST}",
        f"--remote-debugging-port={CHROME_DEBUG_PORT}",
        *os.environ.get("CHROMIUM_EXTRA_ARGS", "").split()
    ]

    try:
        state.chromium_process = await asyncio.create_subprocess_exec(
            *chromium_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info(f"Started Chromium (PID: {state.chromium_process.pid})")
    except Exception as e:
        logger.critical(f"Failed to start Chromium: {e}")
        state.shutdown_event.set()
        return

    asyncio.create_task(log_stream(state.chromium_process.stdout, logger.info))
    asyncio.create_task(log_stream(state.chromium_process.stderr, logger.error))
    asyncio.create_task(monitor_chromium_process(state))

async def start_websocket_server(state: ApplicationState) -> None:
    """Initialize WebSocket proxy server"""
    try:
        state.server = await websockets.serve(
            lambda ws, path: proxy_handler(ws, path, state),
            PROXY_LISTEN_HOST,
            PROXY_LISTEN_PORT,
            ping_interval=20,
            ping_timeout=30,
            close_timeout=10
        )
        logger.info(f"WebSocket proxy listening on {PROXY_LISTEN_HOST}:{PROXY_LISTEN_PORT}")
    except Exception as e:
        logger.critical(f"Failed to start WebSocket server: {e}")
        state.shutdown_event.set()

async def handle_shutdown(state: ApplicationState) -> None:
    """Handle graceful shutdown sequence"""
    await state.shutdown_event.wait()
    logger.info("Initiating shutdown sequence...")

    # Close WebSocket server
    if state.server:
        state.server.close()
        await state.server.wait_closed()
        logger.info("WebSocket server stopped")

    # Close active connections
    if state.active_connections:
        logger.info(f"Closing {len(state.active_connections)} active connections")
        await asyncio.gather(*[conn.close() for conn in state.active_connections])

    # Terminate Chromium process
    if state.chromium_process and state.chromium_process.returncode is None:
        logger.info("Terminating Chromium process...")
        state.chromium_process.terminate()
        try:
            await asyncio.wait_for(state.chromium_process.wait(), timeout=10)
        except asyncio.TimeoutError:
            logger.warning("Force killing Chromium process")
            state.chromium_process.kill()
            await state.chromium_process.wait()
        logger.info("Chromium process terminated")

def register_signal_handlers(state: ApplicationState) -> None:
    """Register OS signal handlers"""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, state.shutdown_event.set)

async def main() -> None:
    """Main application entry point"""
    state = ApplicationState()

    try:
        await start_chromium(state)
        """Wait 2sec for chrome to start, so it won't error"""
        await asyncio.sleep(2)

        await start_websocket_server(state)
        register_signal_handlers(state)
        
        if not state.shutdown_event.is_set():
            try:
                state.browser_id = await fetch_browser_id(state)
                logger.info(f"Browser ID obtained: {state.browser_id}")
            except RuntimeError as e:
                logger.critical(str(e))
                state.shutdown_event.set()

        await handle_shutdown(state)
    except Exception as e:
        logger.critical(f"Critical failure: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("Shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown initiated by user")
        sys.exit(0)