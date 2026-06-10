import time

from rich.console import Console
from rich.table import Table

from src import config
from src.database import init_db, list_recent, stats, summary
from src.worker import get_state, run_check, start_watcher, stop_watcher

console = Console()


def show_status() -> None:
    init_db()
    counts = stats()
    s = summary()
    table = Table(title="CHIMME Status")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    for status, count in sorted(counts.items()):
        table.add_row(status, str(count))
    console.print(table)
    console.print(f"Total claimed: ${s['total_claimed']:.2f}")

    recent = list_recent()
    if not recent:
        console.print("[dim]No processed emails yet.[/dim]")
        return

    history = Table(title="Recent Activity")
    history.add_column("Time")
    history.add_column("Sender")
    history.add_column("Amount", justify="right")
    history.add_column("Status")
    history.add_column("Subject")

    for row in recent:
        amount = f"${row['amount']:.2f}" if row["amount"] is not None else "-"
        history.add_row(
            row["processed_at"][:19],
            row["sender_name"] or "-",
            amount,
            row["status"],
            row["subject"][:50],
        )
    console.print(history)


def run_daemon() -> None:
    console.print(
        f"[bold green]CHIMME running[/bold green] — checking every "
        f"{config.CHECK_INTERVAL_SECONDS} second(s)"
    )
    start_watcher()
    while True:
        time.sleep(1)


def stop_web() -> None:
    import os
    import signal
    import subprocess

    port = config.WEB_PORT
    killed = []

    for cmd in (
        ["fuser", "-k", f"{port}/tcp"],
        ["bash", "-lc", f"lsof -ti :{port} | xargs -r kill -9"],
    ):
        try:
            subprocess.run(cmd, capture_output=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    try:
        output = subprocess.check_output(
            ["ss", "-tlnp"], text=True, stderr=subprocess.DEVNULL
        )
        for line in output.splitlines():
            if f":{port}" not in line:
                continue
            if "pid=" in line:
                pid_str = line.split("pid=")[1].split(",")[0]
                os.kill(int(pid_str), signal.SIGKILL)
                killed.append(int(pid_str))
    except (subprocess.SubprocessError, ValueError, ProcessLookupError):
        pass

    if killed:
        console.print(f"[yellow]Stopped old server on port {port}[/yellow] (pids: {', '.join(map(str, killed))})")
        time.sleep(1)


def run_web() -> None:
    import uvicorn

    if not config.IS_CLOUD:
        stop_web()

    url = config.PUBLIC_BASE_URL or f"http://{config.WEB_HOST}:{config.WEB_PORT}"
    console.print(f"[bold green]CHIMME Web UI[/bold green] → {url}")

    uvicorn.run(
        "web.app:app",
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        reload=False,
    )


if __name__ == "__main__":
    import sys

    command = sys.argv[1] if len(sys.argv) > 1 else "web"
    if command == "once":
        result = run_check()
        console.print(result["message"])
    elif command == "watch":
        run_daemon()
    elif command == "status":
        show_status()
    elif command == "web":
        run_web()
    elif command == "stop":
        stop_web()
        console.print(f"[green]Port {config.WEB_PORT} cleared[/green]")
    else:
        console.print("Usage: python main.py [web|stop|once|watch|status]")
