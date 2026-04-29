"""Screen capture helpers. mss + Pillow are imported lazily so the agent
process can boot on a headless host (no DISPLAY) without crashing — capture
will only be attempted when the technician actually starts a session."""
from io import BytesIO
from typing import List, Tuple, TypedDict


class MonitorInfo(TypedDict):
    index: int
    width: int
    height: int
    left: int
    top: int


def capture_frame(quality: int = 60, monitor_index: int = 1) -> bytes:
    """Capture the requested monitor and return JPEG-encoded bytes."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        mon = sct.monitors[monitor_index]
        raw = sct.grab(mon)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def screen_size(monitor_index: int = 1) -> Tuple[int, int]:
    import mss
    with mss.mss() as sct:
        mon = sct.monitors[monitor_index]
        return mon["width"], mon["height"]


def list_monitors() -> List[MonitorInfo]:
    """Enumerate monitors. mss.monitors[0] is the virtual "all monitors"
    rectangle; we expose only the per-monitor entries (1..N)."""
    import mss
    with mss.mss() as sct:
        out: List[MonitorInfo] = []
        for i, m in enumerate(sct.monitors):
            if i == 0:
                continue  # skip the all-monitors aggregate
            out.append(
                MonitorInfo(
                    index=i,
                    width=int(m["width"]),
                    height=int(m["height"]),
                    left=int(m["left"]),
                    top=int(m["top"]),
                )
            )
        return out
