/**
 * Map a browser KeyboardEvent.key to a name pynput's Key enum understands.
 *
 * Single printable characters pass through (e.g. "a" -> "a"). Named keys are
 * lowered so the agent can look them up via `getattr(Key, key.lower())`.
 */
const SPECIAL_MAP: Record<string, string> = {
  Enter: "enter",
  Escape: "esc",
  Backspace: "backspace",
  Tab: "tab",
  " ": "space",
  ArrowUp: "up",
  ArrowDown: "down",
  ArrowLeft: "left",
  ArrowRight: "right",
  Shift: "shift",
  Control: "ctrl",
  Alt: "alt",
  Meta: "cmd",
  CapsLock: "caps_lock",
  Delete: "delete",
  Home: "home",
  End: "end",
  PageUp: "page_up",
  PageDown: "page_down",
  Insert: "insert",
  F1: "f1",
  F2: "f2",
  F3: "f3",
  F4: "f4",
  F5: "f5",
  F6: "f6",
  F7: "f7",
  F8: "f8",
  F9: "f9",
  F10: "f10",
  F11: "f11",
  F12: "f12",
};

export function mapKey(eventKey: string): string | null {
  if (!eventKey) return null;
  if (SPECIAL_MAP[eventKey]) return SPECIAL_MAP[eventKey];
  // Pass single printable characters through as-is.
  if (eventKey.length === 1) return eventKey;
  return null;
}

export function mouseButton(button: number): "left" | "middle" | "right" {
  if (button === 1) return "middle";
  if (button === 2) return "right";
  return "left";
}
