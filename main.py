import os
import sys
import json
import time
import random
import logging
from logging.handlers import RotatingFileHandler
import ctypes
import msvcrt
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from browser import ChromeAttacher
from sender import ChatSender, format_template_message

console = Console()

LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOGS_DIR, "run.log")

# Rotating log handler (max 5 MB, 3 backups)
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8"
)
file_handler.setFormatter(
    logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
)
logger = logging.getLogger("yt_sender")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
last_config_mtime = 0.0


def disable_quick_edit():
    """Prevents Windows terminal from freezing on click and enables ANSI escape sequences."""
    try:
        kernel32 = ctypes.windll.kernel32
        h_stdin = kernel32.GetStdHandle(-10)
        in_mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(h_stdin, ctypes.byref(in_mode)):
            ENABLE_QUICK_EDIT_MODE = 0x0040
            ENABLE_EXTENDED_FLAGS = 0x0080
            new_in_mode = (in_mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS
            kernel32.SetConsoleMode(h_stdin, new_in_mode)

        h_stdout = kernel32.GetStdHandle(-11)
        out_mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(h_stdout, ctypes.byref(out_mode)):
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(h_stdout, out_mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass


def load_config(config_path: str = CONFIG_PATH) -> Dict[str, Any]:
    global last_config_mtime
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file '{config_path}' nahi mila.")
    try:
        last_config_mtime = os.path.getmtime(config_path)
    except Exception:
        pass

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    config.setdefault("cdp_url", "http://127.0.0.1:9222")

    # Support delay_ms (priority) or legacy delay_between_messages_sec
    if "delay_ms" in config:
        config["delay_ms"] = int(config["delay_ms"])
    elif "delay_between_messages_sec" in config:
        config["delay_ms"] = int(float(config["delay_between_messages_sec"]) * 1000)
    else:
        config["delay_ms"] = 3500

    config.setdefault("typing_speed_ms", 0)
    config.setdefault("jitter_ms", 200)
    config.setdefault("variables", {})

    # Normalize tabs
    if "tabs" not in config or not config["tabs"]:
        old_msgs = [m.get("text", "") for m in config.get("messages", []) if isinstance(m, dict)]
        if not old_msgs and isinstance(config.get("messages", []), list):
            old_msgs = [m for m in config.get("messages", []) if isinstance(m, str)]
        config["tabs"] = [
            {
                "name": "Tab 1",
                "tab_url_contains": config.get("tab_url_contains", "youtube.com"),
                "enabled": True,
                "messages": old_msgs or ["Giveaway entry!"]
            }
        ]

    return config


def check_and_reload_config_file(
    current_delay: int,
    current_typing: int,
    current_jitter: int,
    current_variables: Dict[str, Any],
    workers: List[Dict[str, Any]]
) -> Tuple[bool, int, int, int, Dict[str, Any]]:
    """
    Checks if config.json was modified on disk and hot-reloads settings in realtime.
    Returns (did_change, new_delay, new_typing, new_jitter, new_variables).
    """
    global last_config_mtime
    if not os.path.exists(CONFIG_PATH):
        return False, current_delay, current_typing, current_jitter, current_variables

    try:
        mtime = os.path.getmtime(CONFIG_PATH)
    except Exception:
        return False, current_delay, current_typing, current_jitter, current_variables

    if mtime <= last_config_mtime:
        return False, current_delay, current_typing, current_jitter, current_variables

    time.sleep(0.02)  # Tiny pause for file writer to finish
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return False, current_delay, current_typing, current_jitter, current_variables

    last_config_mtime = mtime
    changed = False

    # 1. Delay
    new_delay = int(cfg.get("delay_ms", current_delay))
    if new_delay != current_delay:
        console.print(f"\n[bold cyan]🔄 [Config Hot-Reload][/bold cyan] delay_ms: [bold yellow]{current_delay}ms -> {new_delay}ms[/bold yellow]")
        changed = True
        current_delay = new_delay

    # 2. Typing speed
    new_typing = int(cfg.get("typing_speed_ms", current_typing))
    if new_typing != current_typing:
        type_str = f"{new_typing}ms" if new_typing > 0 else "0ms (Instant)"
        console.print(f"\n[bold cyan]🔄 [Config Hot-Reload][/bold cyan] typing_speed_ms: [bold yellow]{type_str}[/bold yellow]")
        changed = True
        current_typing = new_typing

    # 3. Jitter
    new_jitter = int(cfg.get("jitter_ms", current_jitter))
    if new_jitter != current_jitter:
        console.print(f"\n[bold cyan]🔄 [Config Hot-Reload][/bold cyan] jitter_ms: [bold yellow]{current_jitter}ms -> {new_jitter}ms[/bold yellow]")
        changed = True
        current_jitter = new_jitter

    # 4. Variables
    new_vars = cfg.get("variables", current_variables)
    if new_vars != current_variables:
        console.print(f"\n[bold cyan]🔄 [Config Hot-Reload][/bold cyan] Template variables updated: {new_vars}")
        changed = True
        current_variables = new_vars

    # 5. Messages in tabs
    cfg_tabs = cfg.get("tabs", [])
    for w in workers:
        for t in cfg_tabs:
            if t.get("name") == w["name"] or t.get("tab_url_contains") in w.get("url", ""):
                fresh_msgs = t.get("messages", [])
                if fresh_msgs and fresh_msgs != w["messages"]:
                    w["messages"] = fresh_msgs
                    w["msg_idx"] = min(w["msg_idx"], len(fresh_msgs) - 1)
                    console.print(f"\n[bold cyan]🔄 [Config Hot-Reload][/bold cyan] Tab '{w['name']}' messages updated ({len(fresh_msgs)} messages)!")
                    changed = True

    return changed, current_delay, current_typing, current_jitter, current_variables


def check_terminal_key() -> str:
    """Non-blocking check for keypress in Windows terminal."""
    if msvcrt.kbhit():
        try:
            ch = msvcrt.getch()
            return ch.decode("utf-8", errors="ignore").lower()
        except Exception:
            return ""
    return ""


def countdown_sleep_ms(
    ms: int,
    current_delay_ms: int,
    typing_speed_ms: int,
    jitter_ms: int,
    variables: Dict[str, Any],
    workers: List[Dict[str, Any]],
    status_prefix: str = ""
) -> Tuple[str, int, int, int, Dict[str, Any]]:
    """
    Sleeps for the given milliseconds while updating status every 25ms.
    Continuously monitors config.json for disk changes and listens to hotkeys:
    '+' / '=' : Speed up delay (-100ms)
    '-' / '_' : Slow down delay (+100ms)
    '[' : Speed up typing (-1ms)
    ']' : Slow down typing (+1ms)
    'p' : Pause / Resume
    'q' : Quit
    """
    start_time = time.time()
    total_sec = max(0.001, float(ms) / 1000.0)
    delay_ms = current_delay_ms
    typing_ms = typing_speed_ms
    j_ms = jitter_ms
    vars_dict = variables

    while True:
        elapsed = time.time() - start_time
        remaining_ms = max(0, int((total_sec - elapsed) * 1000))

        # Check hotkeys
        key = check_terminal_key()
        if key == "q":
            return "quit", delay_ms, typing_ms, j_ms, vars_dict
        elif key == "p":
            return "pause", delay_ms, typing_ms, j_ms, vars_dict
        elif key in ["+", "="]:
            delay_ms = max(10, delay_ms - 100)
            console.print(f"\n[bold green]⚡ Delay Adjusted:[/bold green] [bold yellow]{delay_ms}ms[/bold yellow]")
            total_sec = max(0.001, float(delay_ms) / 1000.0)
        elif key in ["-", "_"]:
            delay_ms = delay_ms + 100
            console.print(f"\n[bold yellow]🐢 Delay Adjusted:[/bold yellow] [bold yellow]{delay_ms}ms[/bold yellow]")
            total_sec = max(0.001, float(delay_ms) / 1000.0)
        elif key == "[":
            typing_ms = max(0, typing_ms - 1)
            t_str = "0ms (Instant)" if typing_ms == 0 else f"{typing_ms}ms"
            console.print(f"\n[bold green]⚡ Typing Speed:[/bold green] [bold yellow]{t_str}[/bold yellow]")
        elif key == "]":
            typing_ms = typing_ms + 1
            console.print(f"\n[bold yellow]🐢 Typing Speed:[/bold yellow] [bold yellow]{typing_ms}ms[/bold yellow]")

        # Check config.json on disk in real time
        changed, delay_ms, typing_ms, j_ms, vars_dict = check_and_reload_config_file(
            delay_ms, typing_ms, j_ms, vars_dict, workers
        )
        if changed:
            total_sec = max(0.001, float(delay_ms) / 1000.0)

        if elapsed >= total_sec:
            break

        type_label = "Instant" if typing_ms == 0 else f"{typing_ms}ms"
        sys.stdout.write(
            f"\r\033[K[Next: {remaining_ms:>4}ms] {status_prefix} | Delay: {delay_ms}ms | Type: {type_label} | [+] Faster [-] Slower"
        )
        sys.stdout.flush()
        time.sleep(0.025)

    sys.stdout.write("\r\033[K")
    sys.stdout.flush()
    return "done", delay_ms, typing_ms, j_ms, vars_dict


def handle_paused_state(
    current_delay_ms: int,
    typing_speed_ms: int,
    jitter_ms: int,
    variables: Dict[str, Any],
    workers: List[Dict[str, Any]]
) -> Tuple[str, int, int, int, Dict[str, Any]]:
    console.print("\n[bold yellow]⏸️  PAUSED: [p] dabayein resume ke liye, [q] dabayein quit ke liye.[/bold yellow]")
    logger.info("Automation PAUSED by user.")
    delay_ms = current_delay_ms
    typing_ms = typing_speed_ms
    j_ms = jitter_ms
    vars_dict = variables

    while True:
        key = check_terminal_key()
        if key == "p":
            console.print("[bold green]▶️  RESUMING: Wapas shuru ho raha hai...[/bold green]\n")
            logger.info("Automation RESUMED by user.")
            return "resume", delay_ms, typing_ms, j_ms, vars_dict
        elif key == "q":
            return "quit", delay_ms, typing_ms, j_ms, vars_dict
        elif key in ["+", "="]:
            delay_ms = max(10, delay_ms - 100)
            console.print(f"[bold green]⚡ Delay set to {delay_ms}ms[/bold green]")
        elif key in ["-", "_"]:
            delay_ms = delay_ms + 100
            console.print(f"[bold yellow]🐢 Delay set to {delay_ms}ms[/bold yellow]")

        # Allow disk reload while paused
        _, delay_ms, typing_ms, j_ms, vars_dict = check_and_reload_config_file(
            delay_ms, typing_ms, j_ms, vars_dict, workers
        )
        time.sleep(0.05)


def main():
    disable_quick_edit()

    try:
        config = load_config()
    except Exception as e:
        console.print(f"[bold red]Configuration Error:[/bold red] {e}")
        return

    # Banner
    grid = Table.grid(expand=True)
    grid.add_column(justify="center", ratio=1)
    grid.add_row("[bold cyan]YouTube Live Chat Sender[/bold cyan]")
    console.print(Panel(grid, border_style="cyan"))

    current_delay_ms = config.get("delay_ms", 3500)
    current_typing_speed_ms = config.get("typing_speed_ms", 0)
    current_jitter_ms = config.get("jitter_ms", 200)
    current_variables = config.get("variables", {})
    tabs_cfg = [t for t in config.get("tabs", []) if t.get("enabled", True)]

    type_str = "Instant (0ms)" if current_typing_speed_ms == 0 else f"{current_typing_speed_ms} ms/char"

    if current_delay_ms < 2000:
        safety_status = "[bold yellow]Warning: Delay < 2000ms may trigger YouTube spam filters. Recommended: 3000ms+[/bold yellow]"
    else:
        safety_status = "[bold green]Normal (>= 2000ms)[/bold green]"

    info_table = Table(show_header=False, box=None, padding=(0, 2))
    info_table.add_column("Key", style="bold white")
    info_table.add_column("Value", style="yellow")
    info_table.add_row("Delay", f"{current_delay_ms} ms (±{current_jitter_ms} ms)")
    info_table.add_row("Typing Speed", type_str)
    info_table.add_row("Rate Limit Status", safety_status)
    if current_variables:
        info_table.add_row("Variables", str(current_variables))
    info_table.add_row("Speed Hotkeys", r"[+] -100ms | [-] +100ms | [[] -1ms type | []] +1ms type")
    info_table.add_row("Controls", r"\[p] Pause/Resume | \[q] Quit | [Ctrl+C] Exit")
    console.print(Panel(info_table, title="[bold green]Configuration[/bold green]", border_style="green"))

    if not tabs_cfg:
        console.print("[bold red]Koi active tab config.json me nahi mila![/bold red]")
        return

    # Connect Chrome
    attacher = ChromeAttacher(cdp_url=config.get("cdp_url", "http://127.0.0.1:9222"))
    console.print("\n[bold cyan][*] Chrome se connect ho raha hai...[/bold cyan]")
    try:
        attacher.connect(auto_launch=True)
    except Exception as e:
        console.print(f"[bold red]{e}[/bold red]")
        return

    # Attach tabs
    workers = []
    for t in tabs_cfg:
        name = t.get("name", "Unnamed Tab")
        console.print(f"[*] Attaching to: [bold white]{name}[/bold white]...")
        page = attacher.find_tab_for_config(t)
        if not page:
            console.print(f"[bold yellow]⚠️ Tab '{name}' Chrome me nahi mila.[/bold yellow]")
            continue

        try:
            chat_target, _ = attacher.get_chat_target(page, timeout_sec=15)
            sender = ChatSender(chat_target)
            workers.append({
                "name": name,
                "page": page,
                "url": page.url,
                "sender": sender,
                "messages": t.get("messages", []),
                "msg_idx": 0
            })
            console.print(f"[bold green]✓ '{name}' live chat ready![/bold green]")
        except Exception as e:
            console.print(f"[bold red]✗ '{name}' chat connect fail: {e}[/bold red]")

    if not workers:
        console.print("[bold red]Koi bhi stream tab ready nahi hua. Stream khol kar dubara run karein.[/bold red]")
        attacher.close()
        return

    console.print("\n[bold green]Running. Edit config.json or use hotkeys (+/-) to change speed.[/bold green]\n")

    total_sent = 0
    worker_idx = 0

    try:
        while True:
            # Check config.json modifications before send
            _, current_delay_ms, current_typing_speed_ms, current_jitter_ms, current_variables = check_and_reload_config_file(
                current_delay_ms, current_typing_speed_ms, current_jitter_ms, current_variables, workers
            )

            current_worker = workers[worker_idx]
            msgs = current_worker["messages"]
            if not msgs:
                worker_idx = (worker_idx + 1) % len(workers)
                time.sleep(0.05)
                continue

            raw_text = msgs[current_worker["msg_idx"]]
            t_name = current_worker["name"]

            # Calculate actual delay with safe jitter
            effective_jitter = min(current_jitter_ms, max(0, current_delay_ms // 2))
            j_ms = random.randint(-effective_jitter, effective_jitter) if effective_jitter > 0 else 0
            actual_delay_ms = max(5, current_delay_ms + j_ms)

            # Format template variables
            formatted_text = format_template_message(raw_text, current_variables)

            time_str = datetime.now().strftime("%H:%M:%S")
            console.print(f"[{time_str}] [bold cyan][{t_name}][/bold cyan] [bold blue]Sending #{total_sent + 1}:[/bold blue] \"{formatted_text[:45]}...\"")

            # Send message with configured typing speed and template substitution
            send_result = current_worker["sender"].send_message(
                formatted_text,
                typing_speed_ms=current_typing_speed_ms
            )

            if send_result["success"]:
                total_sent += 1
                type_info = "instant" if current_typing_speed_ms == 0 else f"{current_typing_speed_ms}ms"
                log_line = f"SUCCESS | [{t_name}] Sent #{total_sent}: \"{formatted_text}\" | Delay: {actual_delay_ms}ms | Type: {type_info}"
                logger.info(log_line)
                console.print(f"[{time_str}] [bold green]✓ Sent successfully![/bold green] (Next gap: {actual_delay_ms}ms)")
            else:
                err = send_result.get("error") or "Unknown error"
                log_line = f"FAIL | [{t_name}] Failed: \"{formatted_text}\" | Reason: {err}"
                logger.error(log_line)
                console.print(f"[{time_str}] [bold red]✗ [{t_name}] Send Failed:[/bold red] {err}")
                cooldown = send_result.get("cooldown")
                if cooldown:
                    console.print(f"[yellow]⏳ Slow mode active: waiting {cooldown}s cooldown...[/yellow]")
                    actual_delay_ms = (cooldown + 2) * 1000

            # Advance message index for this tab
            current_worker["msg_idx"] = (current_worker["msg_idx"] + 1) % len(msgs)

            # Advance to next tab
            worker_idx = (worker_idx + 1) % len(workers)
            next_worker = workers[worker_idx]

            # Millisecond countdown sleep with runtime speed controls + disk file monitoring
            status_pfx = f"Sent: {total_sent} | Next: [{next_worker['name']}]"
            action, current_delay_ms, current_typing_speed_ms, current_jitter_ms, current_variables = countdown_sleep_ms(
                actual_delay_ms,
                current_delay_ms,
                current_typing_speed_ms,
                current_jitter_ms,
                current_variables,
                workers,
                status_prefix=status_pfx
            )

            if action == "quit":
                console.print("\n[bold yellow]Quit command mila. Safe exit...[/bold yellow]")
                break
            elif action == "pause":
                res, current_delay_ms, current_typing_speed_ms, current_jitter_ms, current_variables = handle_paused_state(
                    current_delay_ms, current_typing_speed_ms, current_jitter_ms, current_variables, workers
                )
                if res == "quit":
                    break

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Ctrl+C detected. Safe exit...[/bold yellow]")
    finally:
        attacher.close()
        console.print(f"[bold cyan]Done! Total messages sent: {total_sent}[/bold cyan]")


if __name__ == "__main__":
    main()
