"""
Centralized CSS and XPath selectors for YouTube Live Chat automation.
If YouTube updates their layout or element IDs, update them here.
"""

# Chat Iframe
CHAT_IFRAME = "iframe#chatframe"

# Popout / standalone live chat container
STANDALONE_CHAT = "yt-live-chat-renderer, yt-live-chat-app"

# Text input field inside chat
INPUT_SELECTORS = [
    'div#input[contenteditable="true"]',
    '#input.yt-live-chat-text-input-field-renderer',
    'yt-live-chat-text-input-field-renderer #input',
    'div[id="input"][role="textbox"]',
]

# Send button
SEND_BUTTON_SELECTORS = [
    "#send-button button",
    "yt-button-shape#send-button button",
    "#send-button yt-icon-button button",
    'button[aria-label="Send"]',
    'button[aria-label="Send message"]',
    'yt-icon-button#send-button',
]

# Error and slow-mode indicators
ERROR_TOAST = "#error-message, #error-text, yt-live-chat-text-actions-error-message-renderer, yt-live-chat-toast-renderer #message"
SLOW_MODE_COUNTDOWN = "#countdown, yt-live-chat-message-input-renderer #countdown, #error-text, #error-message"
RESTRICTED_CHAT = "yt-live-chat-restricted-participation-renderer"

# Any dismissible tooltip or banner
TOOLTIP = "tp-yt-paper-tooltip, yt-tooltip-renderer"
