/** Keyboard shortcuts for the DesktopAI UI. */

import { chatInputEl } from "./state.js";
import { sendChatMessage, startNewChat } from "./chat.js";

function isInputFocused() {
  const tag = document.activeElement?.tagName?.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select";
}

export function initShortcuts() {
  document.addEventListener("keydown", (e) => {
    // "/" — focus chat input (when not already in an input)
    if (e.key === "/" && !isInputFocused()) {
      e.preventDefault();
      if (chatInputEl) chatInputEl.focus();
    }

    // Escape — blur and clear chat input
    if (e.key === "Escape" && chatInputEl) {
      chatInputEl.blur();
      chatInputEl.value = "";
    }

    // Ctrl+Enter — send chat message from anywhere
    if (e.key === "Enter" && e.ctrlKey && chatInputEl) {
      e.preventDefault();
      sendChatMessage(chatInputEl.value);
    }

    // Ctrl+Shift+N — new chat
    if (e.key === "N" && e.ctrlKey && e.shiftKey) {
      e.preventDefault();
      startNewChat();
    }
  });
}
