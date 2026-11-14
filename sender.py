import logging
import re
import time
from typing import Any, Dict, Optional, Tuple
import selectors

logger = logging.getLogger("yt_sender.sender")


def format_template_message(text: str, variables: Optional[Dict[str, Any]] = None) -> str:
    if not variables or not text:
        return text

    formatted = text
    for key, value in variables.items():
        if value is None:
            continue
        val_str = str(value)
        formatted = formatted.replace(f"{{{key}}}", val_str)
        formatted = formatted.replace(f"{{{key.upper()}}}", val_str)
        formatted = formatted.replace(f"{{{key.lower()}}}", val_str)
    return formatted


class ChatSender:
    def __init__(self, chat_target: Any):
        self.target = chat_target
        self._cached_input: Optional[Any] = None

    def find_input(self) -> Optional[Any]:
        if self._cached_input is not None:
            try:
                if self._cached_input.count() > 0:
                    return self._cached_input
            except Exception:
                pass

        for sel in selectors.INPUT_SELECTORS:
            try:
                loc = self.target.locator(sel).first
                if loc.count() > 0:
                    self._cached_input = loc
                    return loc
            except Exception:
                continue
        return None

    def find_send_button(self) -> Optional[Any]:
        for sel in selectors.SEND_BUTTON_SELECTORS:
            try:
                loc = self.target.locator(sel).first
                if loc.count() > 0:
                    return loc
            except Exception:
                continue
        return None

    def check_for_errors(self) -> Tuple[bool, Optional[str], Optional[int]]:
        """Checks for login requirements, slow mode, or error banners."""
        try:
            info = self.target.evaluate("""() => {
                if (document.body && document.body.innerText.includes('Sign in to chat')) {
                    return { type: 'login', text: 'Sign in required' };
                }
                const err = document.querySelector('#error-message, #error-text, yt-live-chat-text-actions-error-message-renderer');
                if (err && err.offsetParent !== null && err.innerText.trim()) {
                    return { type: 'error', text: err.innerText.trim() };
                }
                const cd = document.querySelector('#countdown, [id*="slow-mode"]');
                if (cd && cd.offsetParent !== null && cd.innerText.trim()) {
                    return { type: 'slowmode', text: cd.innerText.trim() };
                }
                const toast = document.querySelector('yt-live-chat-toast-renderer, #toast');
                if (toast && toast.offsetParent !== null && toast.innerText.trim()) {
                    return { type: 'toast', text: toast.innerText.trim() };
                }
                const res = document.querySelector('yt-live-chat-restricted-participation-renderer, #restricted');
                if (res && res.offsetParent !== null && res.innerText.trim()) {
                    return { type: 'restricted', text: res.innerText.trim() };
                }
                return null;
            }""")

            if info:
                t = info.get("type")
                text = info.get("text", "")
                if t == "login":
                    msg = "YouTube login zaroori hai. Khule Chrome window me sign in karein."
                    logger.warning(msg)
                    return True, msg, None

                if t in ["error", "slowmode"]:
                    match_min = re.search(r"(\d+)\s*minute", text, re.IGNORECASE)
                    match_sec = re.search(r"(\d+)\s*second", text, re.IGNORECASE)
                    total_sec = 0
                    if match_min:
                        total_sec += int(match_min.group(1)) * 60
                    if match_sec:
                        total_sec += int(match_sec.group(1))
                    if total_sec == 0 and ("slow mode" in text.lower() or t == "slowmode"):
                        num = re.search(r"(\d+)", text)
                        total_sec = int(num.group(1)) if num else 30
                    if total_sec > 0:
                        logger.warning(f"Slow mode active: {text} ({total_sec}s)")
                        return True, f"Slow mode active: {text}", total_sec
                    return True, text, None

                if t in ["toast", "restricted"]:
                    logger.warning(f"Chat restriction: {text}")
                    return True, text, None
        except Exception:
            pass

        return False, None, None

    def get_input_text(self, input_loc: Any) -> str:
        try:
            text = input_loc.evaluate("el => el.innerText || el.textContent || ''")
        except Exception:
            try:
                text = input_loc.inner_text()
            except Exception:
                text = ""
        return text.replace('\xa0', ' ').replace('\u200b', '').replace('\ufeff', '').strip()

    def clear_input(self, input_loc: Any):
        try:
            input_loc.evaluate("""el => {
                el.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }""")
        except Exception:
            pass

    def send_message(
        self,
        text: str,
        typing_speed_ms: int = 0,
        variables: Optional[Dict[str, Any]] = None,
        max_retries: int = 1
    ) -> Dict[str, Any]:
        result = {
            "success": False,
            "error": None,
            "cooldown": None,
            "retries": 0,
        }

        text = format_template_message(text, variables)

        is_err, err_msg, cooldown = self.check_for_errors()
        if is_err and cooldown:
            result["error"] = err_msg
            result["cooldown"] = cooldown
            return result

        if "\n" in text:
            text = " - ".join(part.strip() for part in text.splitlines() if part.strip())

        input_loc = self.find_input()
        if not input_loc:
            is_err, err_msg, cd = self.check_for_errors()
            if is_err and cd:
                result["error"] = err_msg
                result["cooldown"] = cd
                return result
            result["error"] = "Chat input box nahi mila."
            return result

        for attempt in range(max_retries + 1):
            result["retries"] = attempt
            try:
                if typing_speed_ms <= 0:
                    input_loc.evaluate("""(el, msg) => {
                        el.focus();
                        document.execCommand('selectAll', false, null);
                        document.execCommand('delete', false, null);
                        document.execCommand('insertText', false, msg);
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                    }""", text)
                    time.sleep(0.02)
                else:
                    self.clear_input(input_loc)
                    input_loc.press_sequentially(text, delay=typing_speed_ms)
                    time.sleep(0.03)

                input_loc.press("Enter")
                time.sleep(0.04 if typing_speed_ms <= 2 else 0.10)

                current_text = self.get_input_text(input_loc)
                if not current_text:
                    result["success"] = True
                    return result

                # Fallback to send button click if Enter did not submit
                send_btn = self.find_send_button()
                if send_btn and send_btn.count() > 0:
                    send_btn.click(force=True, timeout=800)
                    time.sleep(0.08)

                current_text = self.get_input_text(input_loc)
                if not current_text:
                    result["success"] = True
                    return result

            except Exception as e:
                logger.warning(f"Send attempt {attempt + 1} exception: {e}")
                if attempt == max_retries:
                    result["error"] = str(e)
                    return result

            time.sleep(0.15)

        remaining = self.get_input_text(input_loc)
        if remaining:
            is_err, err_msg, cd = self.check_for_errors()
            if is_err:
                result["error"] = err_msg
                result["cooldown"] = cd
            else:
                result["error"] = f"Message input clear nahi hua: '{remaining[:30]}...'"
        else:
            result["success"] = True

        return result
