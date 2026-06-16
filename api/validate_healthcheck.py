import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request


def main() -> int:
    bind_host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8000"))
    connect_host = "127.0.0.1" if bind_host in ("0.0.0.0", "") else bind_host
    url = f"http://{connect_host}:{port}/health"

    api_dir = os.path.dirname(os.path.abspath(__file__))
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "main:app",
            "--host", bind_host,
            "--port", str(port),
            "--no-access-log",
        ],
        cwd=api_dir,
    )

    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    status = response.status
                    body = response.read().decode()
                    print(f"OK — GET {url} -> HTTP {status}: {body}")
                    return 0
            except (urllib.error.URLError, OSError):
                time.sleep(0.3)

        print(f"FAIL — {url} did not respond within 10 seconds", file=sys.stderr)
        return 1
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
