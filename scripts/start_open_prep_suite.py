from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


def _find_free_port(start_port: int, max_tries: int = 30) -> int:
    port = start_port
    for _ in range(max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1
    raise RuntimeError(f"No free port found in range {start_port}..{start_port + max_tries - 1}")


def _run_open_prep(repo_root: Path, python_exe: str) -> None:
    out_file = repo_root / "artifacts" / "open_prep" / "latest" / "latest_open_prep_run.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # generate_open_prep_result() already writes latest_open_prep_run.json
    # atomically (mkstemp + os.replace). The previous stdout redirect straight
    # into the target file truncated it at process start (crash -> empty file
    # for monitor/CLI dashboards) and wrote the final JSON into an inode
    # already orphaned by os.replace. stdout therefore goes to a tmp file;
    # the target is only replaced after a successful run.
    # PID suffix avoids clobbering when two suite runs overlap accidentally.
    tmp_file = out_file.with_name(f"{out_file.stem}.stdout.{os.getpid()}.tmp")
    try:
        with tmp_file.open("w", encoding="utf-8") as fh:
            subprocess.run(
                [python_exe, "-m", "open_prep.run_open_prep", "--pre-open-only"],
                cwd=str(repo_root),
                stdout=fh,
                check=True,
            )
        tmp_file.replace(out_file)
    except BaseException:
        tmp_file.unlink(missing_ok=True)
        raise


def _stop_existing_monitor() -> None:
    pkill_exe = shutil.which("pkill") or "pkill"
    subprocess.run([pkill_exe, "-f", "streamlit.*streamlit_monitor.py"], check=False)


def _start_streamlit(repo_root: Path, python_exe: str, port: int) -> int:
    log_file = repo_root / "open_prep" / "streamlit_monitor.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)

    streamlit_cmd = [
        str(Path(python_exe).with_name("streamlit")),
        "run",
        str(repo_root / "open_prep" / "streamlit_monitor.py"),
        "--server.headless",
        "true",
        "--server.port",
        str(port),
    ]

    with log_file.open("w", encoding="utf-8") as fh:
        proc = subprocess.Popen(
            streamlit_cmd,
            cwd=str(repo_root),
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    time.sleep(1.0)
    if proc.poll() is not None:
        raise RuntimeError(
            f"Streamlit exited early with code {proc.returncode}. Check {log_file}"
        )
    return proc.pid


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Open Prep once and start Streamlit monitor on a free port."
    )
    parser.add_argument("--start-port", type=int, default=8501, help="First port to try for Streamlit")
    parser.add_argument("--max-port-tries", type=int, default=30, help="How many ports to probe")
    parser.add_argument(
        "--python-exe",
        type=str,
        default=sys.executable,
        help="Python executable to use (defaults to current interpreter)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    _run_open_prep(repo_root, args.python_exe)
    _stop_existing_monitor()

    port = _find_free_port(args.start_port, max_tries=args.max_port_tries)
    pid = _start_streamlit(repo_root, args.python_exe, port)

    print("Open Prep suite started successfully.")
    print(f"Streamlit PID: {pid}")
    print(f"Monitor URL: http://localhost:{port}")
    print(f"Log file: {repo_root / 'open_prep' / 'streamlit_monitor.log'}")


if __name__ == "__main__":
    main()
