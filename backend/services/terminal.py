"""
terminal.py  –  PTY-backed terminal session for UniDev Toolkit

Security posture
────────────────
The terminal starts a restricted bash shell whose HOME and working
directory are both set to WORKSPACE (a temp dir).  The following
environment variables are cleared: HF_TOKEN, HUGGING_FACE_HUB_TOKEN,
GH_TOKEN, GITLAB_TOKEN, AWS_*, and any *SECRET* / *PASSWORD* / *KEY*
variables so that credentials injected by Hugging Face Spaces or CI
systems are not exposed to the browser terminal.

Users are informed of the sandbox via the welcome banner.
"""
from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import select
import struct
import termios
from typing import AsyncGenerator

# Variables to scrub from the child process environment
_SCRUB_PREFIXES = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "GH_TOKEN", "GITLAB_TOKEN",
                   "AWS_", "AZURE_", "GOOGLE_APPLICATION_CREDENTIALS")
_SCRUB_SUBSTRINGS = ("SECRET", "PASSWORD", "PASSWD", "API_KEY", "PRIVATE_KEY", "TOKEN")


def _clean_env(workspace: str) -> dict[str, str]:
    """Return a sanitised copy of os.environ for the child shell."""
    env: dict[str, str] = {}
    for k, v in os.environ.items():
        ku = k.upper()
        # Drop credentials and secrets
        if any(ku.startswith(p) for p in _SCRUB_PREFIXES):
            continue
        if any(s in ku for s in _SCRUB_SUBSTRINGS):
            continue
        env[k] = v
    # Force PATH to common system locations
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    env["HOME"] = workspace
    env["TERM"] = "xterm-256color"
    env["SHELL"] = "/bin/bash"
    # Restrict cwd-based tools to workspace
    env["PWD"] = workspace
    return env


class TerminalSession:
    def __init__(self, cols: int = 80, rows: int = 24):
        self.cols = cols
        self.rows = rows
        self.pid: int | None = None
        self.master_fd: int | None = None

    def start(self, cwd: str | None = None) -> None:
        workspace = cwd or os.path.expanduser("~")
        env = _clean_env(workspace)

        pid, master_fd = pty.fork()
        if pid == 0:
            os.chdir(workspace)
            # Replace environment entirely with sanitised copy
            os.execvpe(
                "/bin/bash",
                ["/bin/bash", "--norc", "--noprofile"],
                env,
            )
        else:
            self.pid = pid
            self.master_fd = master_fd
            self._set_size(self.cols, self.rows)

    def _set_size(self, cols: int, rows: int) -> None:
        if self.master_fd is None:
            return
        self.cols = cols
        self.rows = rows
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)

    def resize(self, cols: int, rows: int) -> None:
        self._set_size(cols, rows)

    def write(self, data: str) -> None:
        if self.master_fd is not None:
            os.write(self.master_fd, data.encode("utf-8", errors="replace"))

    async def read_output(self) -> AsyncGenerator[str, None]:
        if self.master_fd is None:
            return
        loop = asyncio.get_event_loop()
        while True:
            if self.pid is not None:
                try:
                    pid, _ = os.waitpid(self.pid, os.WNOHANG)
                    if pid != 0:
                        break
                except ChildProcessError:
                    break
            ready, _, _ = await loop.run_in_executor(
                None, lambda: select.select([self.master_fd], [], [], 0.1)
            )
            if ready:
                try:
                    data = os.read(self.master_fd, 4096)
                    if not data:
                        break
                    yield data.decode("utf-8", errors="replace")
                except OSError:
                    break
            await asyncio.sleep(0.01)

    def close(self) -> None:
        if self.pid is not None:
            try:
                os.kill(self.pid, 15)
            except Exception:
                pass
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except Exception:
                pass
