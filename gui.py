import os
import sys
import json
import time
import random
import logging
from logging.handlers import RotatingFileHandler
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

import customtkinter as ctk
from browser import ChromeAttacher
from sender import ChatSender, format_template_message

# Modern Appearance Setup
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOGS_DIR, "run.log")

gui_logger = logging.getLogger("yt_sender.gui")
gui_logger.setLevel(logging.INFO)
fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
fh.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
gui_logger.addHandler(fh)


class MultiTabYTChatApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("YouTube Live Chat Sender")
        self.geometry("980, 780")
        self.minsize(880, 700)

        # State
        self.config: Dict[str, Any] = self.load_config()
        self.attacher: Optional[ChromeAttacher] = None
        self.open_tabs_list: List[Dict[str, Any]] = []

        self.tab_ui_map: Dict[str, Dict[str, Any]] = {}
        self.is_running = False
        self.is_paused = False
        self.stop_requested = False
        self.worker_thread: Optional[threading.Thread] = None

        self.total_sent = 0

        self.build_ui()
        self.after(300, self.refresh_tabs_async)

    def load_config(self) -> Dict[str, Any]:
        """Load and normalize config with full ms and multi-tab support."""
        default_cfg = {
            "cdp_url": "http://127.0.0.1:9222",
            "delay_ms": 3500,
            "typing_speed_ms": 0,
            "jitter_ms": 200,
            "variables": {},
            "tabs": [
                {
                    "name": "Tab 1 (Stream)",
                    "tab_url_contains": "https://www.youtube.com/",
                    "enabled": True,
                    "messages": [
                        "Hello everyone! Loving the live stream!",
                        "Great gameplay bro! Keep it up!",
                        "Full support from viewer!"
                    ]
                }
            ]
        }
        if not os.path.exists(CONFIG_PATH):
            return default_cfg
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            # Delay normalization
            if "delay_ms" in cfg:
                cfg["delay_ms"] = int(cfg["delay_ms"])
            elif "delay_between_messages_sec" in cfg:
                cfg["delay_ms"] = int(float(cfg["delay_between_messages_sec"]) * 1000)
            else:
                cfg["delay_ms"] = 3500

            cfg.setdefault("typing_speed_ms", 0)
            cfg.setdefault("jitter_ms", 200)
            cfg.setdefault("variables", {})

            # Convert legacy single-tab config to multi-tab if needed
            if "tabs" not in cfg or not cfg["tabs"]:
                old_msgs = [m.get("text", "") for m in cfg.get("messages", []) if isinstance(m, dict)]
                if not old_msgs and isinstance(cfg.get("messages", []), list):
                    old_msgs = [m for m in cfg.get("messages", []) if isinstance(m, str)]

                cfg["tabs"] = [
                    {
                        "name": "Tab 1",
                        "tab_url_contains": cfg.get("tab_url_contains", "youtube.com"),
                        "enabled": True,
                        "messages": old_msgs or default_cfg["tabs"][0]["messages"]
                    }
                ]
            return cfg
        except Exception:
            return default_cfg

    def save_config(self):
        """Save UI state back into config.json."""
        try:
            delay_ms_val = int(self.delay_entry.get().strip() or "3500")
            jitter_ms_val = int(self.jitter_entry.get().strip() or "200")
            typing_speed_val = int(self.typing_entry.get().strip() or "0")

            self.config["delay_ms"] = delay_ms_val
            self.config["typing_speed_ms"] = typing_speed_val
            self.config["jitter_ms"] = jitter_ms_val
            # Backward compatibility keys
            self.config["delay_between_messages_sec"] = max(1, delay_ms_val // 1000)
            self.config["random_jitter_sec"] = max(0, jitter_ms_val // 1000)

            updated_tabs = []
            for tab_id, data in self.tab_ui_map.items():
                name = data["name_entry"].get().strip() or tab_id
                target_choice = data["dropdown"].get()
                matching_url = ""
                for t in self.open_tabs_list:
                    if t["title"][:30] in target_choice or t["url"][:30] in target_choice:
                        matching_url = t["url"]
                        break
                if not matching_url:
                    matching_url = data.get("original_url", "")

                enabled = data["enabled_switch"].get() == 1
                raw_text = data["msg_textbox"].get("1.0", "end-1c")
                msgs = [line.strip() for line in raw_text.splitlines() if line.strip()]

                updated_tabs.append({
                    "name": name,
                    "tab_url_contains": matching_url,
                    "enabled": enabled,
                    "messages": msgs
                })

            if updated_tabs:
                self.config["tabs"] = updated_tabs

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)

            self.update_safety_label(delay_ms_val)
            self.log("✓ Settings saved to config.json!", "SUCCESS")
        except Exception as e:
            self.log(f"Save error: {e}", "ERROR")

    def update_safety_label(self, delay_ms: int):
        if delay_ms < 2000:
            self.safety_lbl.configure(
                text="⚠️ Warning: Delay < 2000ms may trigger YouTube shadow-drop! Recommended: 3000ms - 6000ms",
                text_color="#f59e0b"
            )
        else:
            self.safety_lbl.configure(
                text="🟢 Safe Speed Mode: Message gap is within YouTube's public delivery safety zone.",
                text_color="#10b981"
            )

    def build_ui(self):
        # 1. Header & Status
        header = ctk.CTkFrame(self, corner_radius=10, fg_color="#18181b")
        header.pack(fill="x", padx=16, pady=(12, 6))

        h_left = ctk.CTkFrame(header, fg_color="transparent")
        h_left.pack(side="left", padx=14, pady=10)

        title_lbl = ctk.CTkLabel(
            h_left,
            text="YouTube Live Chat Sender",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color="#38bdf8"
        )
        title_lbl.pack(anchor="w")

        sub_lbl = ctk.CTkLabel(
            h_left,
            text="Multi-tab background live chat automation",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#94a3b8"
        )
        sub_lbl.pack(anchor="w")

        self.status_badge = ctk.CTkLabel(
            header,
            text="● Chrome Disconnected",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#f87171"
        )
        self.status_badge.pack(side="right", padx=14, pady=10)

        # 2. Global Delay & Control Bar
        ctrl_bar = ctk.CTkFrame(self, corner_radius=10, fg_color="#27272a")
        ctrl_bar.pack(fill="x", padx=16, pady=4)

        # Left controls: Delay setting (ms), Typing speed, Jitter
        delay_sub = ctk.CTkFrame(ctrl_bar, fg_color="transparent")
        delay_sub.pack(side="left", padx=14, pady=8)

        ctk.CTkLabel(delay_sub, text="Delay:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 4))

        self.delay_entry = ctk.CTkEntry(delay_sub, width=65, height=30, justify="center")
        self.delay_entry.insert(0, str(self.config.get("delay_ms", 3500)))
        self.delay_entry.pack(side="left", padx=(0, 2))

        ctk.CTkLabel(delay_sub, text="ms", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 10))

        ctk.CTkLabel(delay_sub, text="Typing:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))
        self.typing_entry = ctk.CTkEntry(delay_sub, width=45, height=30, justify="center")
        self.typing_entry.insert(0, str(self.config.get("typing_speed_ms", 0)))
        self.typing_entry.pack(side="left", padx=(0, 2))
        ctk.CTkLabel(delay_sub, text="ms (0=instant)", font=ctk.CTkFont(size=10)).pack(side="left", padx=(0, 10))

        ctk.CTkLabel(delay_sub, text="Jitter: ±", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))
        self.jitter_entry = ctk.CTkEntry(delay_sub, width=45, height=30, justify="center")
        self.jitter_entry.insert(0, str(self.config.get("jitter_ms", 200)))
        self.jitter_entry.pack(side="left", padx=(0, 2))
        ctk.CTkLabel(delay_sub, text="ms", font=ctk.CTkFont(size=11)).pack(side="left")

        # Right controls: Start, Pause, Stop
        btn_sub = ctk.CTkFrame(ctrl_bar, fg_color="transparent")
        btn_sub.pack(side="right", padx=14, pady=8)

        self.start_btn = ctk.CTkButton(
            btn_sub,
            text="START",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=34,
            width=120,
            fg_color="#10b981",
            hover_color="#059669",
            command=self.start_automation
        )
        self.start_btn.pack(side="left", padx=4)

        self.pause_btn = ctk.CTkButton(
            btn_sub,
            text="PAUSE",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
            width=80,
            fg_color="#f59e0b",
            hover_color="#d97706",
            state="disabled",
            command=self.toggle_pause
        )
        self.pause_btn.pack(side="left", padx=4)

        self.stop_btn = ctk.CTkButton(
            btn_sub,
            text="STOP",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
            width=80,
            fg_color="#ef4444",
            hover_color="#dc2626",
            state="disabled",
            command=self.stop_automation
        )
        self.stop_btn.pack(side="left", padx=4)

        # Safety banner
        safety_bar = ctk.CTkFrame(self, fg_color="transparent")
        safety_bar.pack(fill="x", padx=20, pady=(0, 2))
        self.safety_lbl = ctk.CTkLabel(
            safety_bar,
            text="",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.safety_lbl.pack(side="left")
        self.update_safety_label(self.config.get("delay_ms", 3500))

        # 3. Tab Management Section (Tabview)
        tabs_header = ctk.CTkFrame(self, fg_color="transparent")
        tabs_header.pack(fill="x", padx=16, pady=(4, 2))

        ctk.CTkLabel(
            tabs_header,
            text="📂 Chrome Tabs & Per-Tab Messages:",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(side="left")

        add_tab_btn = ctk.CTkButton(
            tabs_header,
            text="+ Add Another Tab",
            height=28,
            width=140,
            fg_color="#0284c7",
            hover_color="#0369a1",
            command=self.add_new_tab_dialog
        )
        add_tab_btn.pack(side="right")

        refresh_all_btn = ctk.CTkButton(
            tabs_header,
            text="🔄 Refresh Chrome Tabs",
            height=28,
            width=150,
            fg_color="#334155",
            hover_color="#475569",
            command=self.refresh_tabs_async
        )
        refresh_all_btn.pack(side="right", padx=8)

        # TabView
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.pack(fill="both", expand=True, padx=16, pady=4)

        # Load tabs from config
        tabs_cfg = self.config.get("tabs", [])
        for i, tcfg in enumerate(tabs_cfg):
            tab_id = f"Tab {i + 1}"
            self.create_tab_page(tab_id, tcfg)

        # 4. Activity Log and Live Countdown
        bottom_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#18181b")
        bottom_frame.pack(fill="x", padx=16, pady=(4, 12))

        b_hdr = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        b_hdr.pack(fill="x", padx=12, pady=(6, 2))

        ctk.CTkLabel(b_hdr, text="📜 Live Activity & Status:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")

        self.countdown_label = ctk.CTkLabel(
            b_hdr,
            text="Idle • Ready to start",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94a3b8"
        )
        self.countdown_label.pack(side="right")

        self.log_box = ctk.CTkTextbox(
            bottom_frame,
            height=120,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#09090b",
            text_color="#e2e8f0"
        )
        self.log_box.pack(fill="x", padx=12, pady=(2, 8))

    def create_tab_page(self, tab_id: str, tab_cfg: Dict[str, Any]):
        """Create a dedicated page inside CTkTabview for this tab."""
        tab_name = tab_cfg.get("name", tab_id)
        page = self.tabview.add(tab_name)

        # Top row: Tab Name + Chrome dropdown + Enable Toggle
        top_row = ctk.CTkFrame(page, fg_color="transparent")
        top_row.pack(fill="x", padx=10, pady=(6, 4))

        ctk.CTkLabel(top_row, text="Label:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 4))
        name_entry = ctk.CTkEntry(top_row, width=130, height=28)
        name_entry.insert(0, tab_name)
        name_entry.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(top_row, text="Target Tab:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 4))

        dropdown_values = ["Searching open Chrome tabs..."]
        dropdown = ctk.CTkComboBox(top_row, values=dropdown_values, width=320, height=28)
        dropdown.pack(side="left", padx=(0, 12))

        enabled_var = ctk.IntVar(value=1 if tab_cfg.get("enabled", True) else 0)
        enabled_switch = ctk.CTkSwitch(top_row, text="Enabled", variable=enabled_var)
        enabled_switch.pack(side="left", padx=(0, 12))

        save_btn = ctk.CTkButton(
            top_row,
            text="💾 Save",
            width=70,
            height=28,
            fg_color="#3b82f6",
            hover_color="#2563eb",
            command=self.save_config
        )
        save_btn.pack(side="right")

        # Middle: Multiline Message Box
        msg_header = ctk.CTkFrame(page, fg_color="transparent")
        msg_header.pack(fill="x", padx=10, pady=(4, 2))

        ctk.CTkLabel(
            msg_header,
            text="Chat Messages for this Tab (One message per line • Cycles continuously • Supports {uid}):",
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color="#94a3b8"
        ).pack(side="left")

        msg_textbox = ctk.CTkTextbox(page, height=130, font=ctk.CTkFont(family="Consolas", size=12))
        msg_textbox.pack(fill="both", expand=True, padx=10, pady=(2, 6))

        # Populate existing messages
        existing_msgs = tab_cfg.get("messages", [])
        if existing_msgs:
            msg_textbox.insert("1.0", "\n".join(existing_msgs))

        # Store widget references
        self.tab_ui_map[tab_name] = {
            "name_entry": name_entry,
            "dropdown": dropdown,
            "enabled_switch": enabled_switch,
            "msg_textbox": msg_textbox,
            "original_url": tab_cfg.get("tab_url_contains", "")
        }

    def add_new_tab_dialog(self):
        new_idx = len(self.tab_ui_map) + 1
        new_name = f"Tab {new_idx}"
        new_cfg = {
            "name": new_name,
            "tab_url_contains": "https://www.youtube.com/",
            "enabled": True,
            "messages": ["Giveaway entry! Support streamer!"]
        }
        self.create_tab_page(new_name, new_cfg)
        self.tabview.set(new_name)
        self.refresh_tabs_async()
        self.log(f"Added new tab: '{new_name}'", "INFO")

    def log(self, text: str, level: str = "INFO"):
        time_str = datetime.now().strftime("%H:%M:%S")
        color_map = {
            "INFO": "#94a3b8",
            "SUCCESS": "#10b981",
            "WARNING": "#f59e0b",
            "ERROR": "#ef4444"
        }
        color = color_map.get(level, "#e2e8f0")
        line = f"[{time_str}] {text}\n"

        def _append():
            self.log_box.insert("end", line)
            self.log_box.see("end")

        self.after(0, _append)
        if level == "ERROR":
            gui_logger.error(text)
        elif level == "WARNING":
            gui_logger.warning(text)
        else:
            gui_logger.info(text)

    def refresh_tabs_async(self):
        threading.Thread(target=self._refresh_tabs_worker, daemon=True).start()

    def _refresh_tabs_worker(self):
        try:
            if not self.attacher:
                self.attacher = ChromeAttacher(cdp_url=self.config.get("cdp_url", "http://127.0.0.1:9222"))
            self.attacher.connect(auto_launch=False)

            tabs = self.attacher.get_open_tabs()
            self.open_tabs_list = tabs

            formatted_choices = []
            for t in tabs:
                active_flag = "[ACTIVE] " if t.get("is_active") else ""
                short_title = t["title"][:40] if t.get("title") else "Untitled"
                formatted_choices.append(f"{active_flag}{short_title} - {t['url'][:45]}")

            if not formatted_choices:
                formatted_choices = ["No tabs found in Chrome."]

            def _update_ui():
                self.status_badge.configure(text="● Chrome Connected (9222)", text_color="#10b981")
                for tab_name, data in self.tab_ui_map.items():
                    data["dropdown"].configure(values=formatted_choices)
                    orig_url = data.get("original_url", "").lower()
                    matched_choice = None
                    if orig_url:
                        for c in formatted_choices:
                            if orig_url in c.lower():
                                matched_choice = c
                                break
                    if matched_choice:
                        data["dropdown"].set(matched_choice)
                    elif formatted_choices:
                        data["dropdown"].set(formatted_choices[0])

            self.after(0, _update_ui)
            self.log(f"Detected {len(tabs)} open tab(s) in Chrome.", "INFO")

        except Exception as e:
            def _update_err():
                self.status_badge.configure(text="● Chrome Not Detected", text_color="#f87171")

            self.after(0, _update_err)
            self.log("Chrome se connect nahi ho paya. Kripya 'start_chrome.bat' run karein.", "WARNING")

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.pause_btn.configure(text="▶️ RESUME", fg_color="#10b981", hover_color="#059669")
            self.countdown_label.configure(text="PAUSED", text_color="#f59e0b")
            self.log("Automation PAUSED by user.", "WARNING")
        else:
            self.pause_btn.configure(text="⏸️ PAUSE", fg_color="#f59e0b", hover_color="#d97706")
            self.countdown_label.configure(text="Resuming...", text_color="#38bdf8")
            self.log("Automation RESUMED by user.", "INFO")

    def start_automation(self):
        if self.is_running:
            return
        self.save_config()
        self.is_running = True
        self.is_paused = False
        self.stop_requested = False

        self.start_btn.configure(state="disabled")
        self.pause_btn.configure(state="normal", text="⏸️ PAUSE")
        self.stop_btn.configure(state="normal")
        self.countdown_label.configure(text="Initializing...", text_color="#38bdf8")

        self.worker_thread = threading.Thread(target=self._multi_tab_worker, daemon=True)
        self.worker_thread.start()

    def stop_automation(self):
        if not self.is_running:
            return
        self.stop_requested = True
        self.is_paused = False
        self.countdown_label.configure(text="Stopping safely...", text_color="#ef4444")
        self.log("Stopping auto-sender across all tabs...", "WARNING")

    def _multi_tab_worker(self):
        """Dedicated worker thread for safe Playwright CDP operations."""
        worker_attacher = None
        try:
            worker_attacher = ChromeAttacher(cdp_url=self.config.get("cdp_url", "http://127.0.0.1:9222"))
            worker_attacher.connect(auto_launch=True)

            active_tabs = [t for t in self.config.get("tabs", []) if t.get("enabled", True)]
            if not active_tabs:
                self.log("Koi active tab enabled nahi hai! Tab switch on karein.", "ERROR")
                return

            tab_workers = []
            for t_cfg in active_tabs:
                t_name = t_cfg.get("name", "Unnamed")
                self.log(f"Attaching to tab: '{t_name}'...", "INFO")

                page = worker_attacher.find_tab_for_config(t_cfg)
                if not page:
                    self.log(f"Tab '{t_name}' match nahi hua. Chrome me stream open hai?", "WARNING")
                    continue

                try:
                    chat_target, _ = worker_attacher.get_chat_target(page, timeout_sec=15)
                    sender = ChatSender(chat_target)
                    tab_workers.append({
                        "name": t_name,
                        "page": page,
                        "sender": sender,
                        "messages": t_cfg.get("messages", []),
                        "msg_index": 0
                    })
                    self.log(f"✓ '{t_name}' connected to live chat!", "SUCCESS")
                except Exception as e:
                    self.log(f"✗ Failed to connect '{t_name}': {e}", "ERROR")

            if not tab_workers:
                self.log("Kisi bhi tab ke chat frame se connect nahi ho paya. Kripya check karein stream open hai.", "ERROR")
                return

            delay_ms = int(self.config.get("delay_ms", 3500))
            typing_speed = int(self.config.get("typing_speed_ms", 0))
            jitter_ms = int(self.config.get("jitter_ms", 200))
            variables = self.config.get("variables", {})
            self.total_sent = 0

            self.log(f"Ready! Running across {len(tab_workers)} tab(s) with {delay_ms}ms gap (Unlimited Loop).", "SUCCESS")

            worker_idx = 0
            while not self.stop_requested:
                while self.is_paused and not self.stop_requested:
                    time.sleep(0.1)
                if self.stop_requested:
                    break

                current_tab = tab_workers[worker_idx]
                msgs = current_tab["messages"]
                if not msgs:
                    worker_idx = (worker_idx + 1) % len(tab_workers)
                    time.sleep(0.05)
                    continue

                raw_msg = msgs[current_tab["msg_index"]]
                msg_text = format_template_message(raw_msg, variables)
                t_name = current_tab["name"]

                # Calculate delay with jitter
                eff_jitter = min(jitter_ms, max(0, delay_ms // 2))
                j = random.randint(-eff_jitter, eff_jitter) if eff_jitter > 0 else 0
                actual_delay_ms = max(5, delay_ms + j)

                self.countdown_label.configure(
                    text=f"Sending into {t_name}...",
                    text_color="#38bdf8"
                )
                self.log(f"[{t_name}] Sending #{self.total_sent + 1}: \"{msg_text[:40]}...\"", "INFO")

                send_result = current_tab["sender"].send_message(
                    msg_text,
                    typing_speed_ms=typing_speed
                )

                if send_result["success"]:
                    self.total_sent += 1
                    self.log(f"✓ [{t_name}] Sent! (Next gap: {actual_delay_ms}ms)", "SUCCESS")
                else:
                    err = send_result.get("error") or "Failed"
                    self.log(f"✗ [{t_name}] Failed: {err}", "ERROR")
                    cooldown = send_result.get("cooldown")
                    if cooldown:
                        self.log(f"⏳ [{t_name}] Slow mode active: cooldown {cooldown}s", "WARNING")
                        actual_delay_ms = max(actual_delay_ms, (cooldown + 2) * 1000)

                # Advance index
                current_tab["msg_index"] = (current_tab["msg_index"] + 1) % len(msgs)
                worker_idx = (worker_idx + 1) % len(tab_workers)
                next_tab = tab_workers[worker_idx]

                # Wait delay with live millisecond countdown
                start_sleep = time.time()
                total_wait_sec = float(actual_delay_ms) / 1000.0

                while time.time() - start_sleep < total_wait_sec:
                    if self.stop_requested:
                        break
                    while self.is_paused and not self.stop_requested:
                        time.sleep(0.1)

                    rem_ms = max(0, int((total_wait_sec - (time.time() - start_sleep)) * 1000))
                    self.countdown_label.configure(
                        text=f"⏳ Next in {rem_ms}ms | Next Tab: {next_tab['name']} | Sent: {self.total_sent}"
                    )
                    time.sleep(0.04)

        except Exception as e:
            self.log(f"Execution Error: {e}", "ERROR")
        finally:
            if worker_attacher:
                worker_attacher.close()
            self.is_running = False
            self.is_paused = False
            self.after(0, self._on_automation_ended)

    def _on_automation_ended(self):
        self.start_btn.configure(state="normal")
        self.pause_btn.configure(state="disabled", text="⏸️ PAUSE")
        self.stop_btn.configure(state="disabled")
        self.countdown_label.configure(text=f"Stopped (Total Sent: {self.total_sent})", text_color="#94a3b8")
        self.log(f"Session finished. Total messages sent: {self.total_sent}", "INFO")


if __name__ == "__main__":
    app = MultiTabYTChatApp()
    app.mainloop()
