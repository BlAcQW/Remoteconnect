"""Mouse and keyboard injection. pynput is imported lazily so the agent
boots on headless hosts; only command handlers fail when called there."""
import logging

log = logging.getLogger(__name__)


def _mouse_controller():
    from pynput.mouse import Controller, Button  # noqa: F401  re-exported by callers

    return Controller()


def _keyboard_controller():
    from pynput.keyboard import Controller, Key  # noqa: F401

    return Controller()


def move_mouse(x: int, y: int) -> None:
    ctl = _mouse_controller()
    ctl.position = (int(x), int(y))


def click_mouse(x: int, y: int, button: str = "left", count: int = 1) -> None:
    from pynput.mouse import Button

    btn = {
        "left": Button.left,
        "right": Button.right,
        "middle": Button.middle,
    }.get(button.lower(), Button.left)

    ctl = _mouse_controller()
    ctl.position = (int(x), int(y))
    ctl.click(btn, max(1, int(count)))


def scroll_mouse(x: int, y: int, dx: int = 0, dy: int = 0) -> None:
    ctl = _mouse_controller()
    ctl.position = (int(x), int(y))
    ctl.scroll(int(dx), int(dy))


def press_key(key: str) -> None:
    """Press and release a key.

    `key` may be a single character (e.g. "a") or a pynput special key
    name (e.g. "enter", "ctrl", "f1"). Lookup is via ``pynput.keyboard.Key``.
    """
    from pynput.keyboard import Key

    ctl = _keyboard_controller()
    special = getattr(Key, key.lower(), None) if isinstance(key, str) else None
    target = special if special is not None else key
    ctl.press(target)
    ctl.release(target)


def type_text(text: str) -> None:
    ctl = _keyboard_controller()
    ctl.type(text)
