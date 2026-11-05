import ctypes
import math
import os
import queue
import sys
import threading
import time
from ctypes import wintypes

import cv2
import mss
import numpy as np
from pynput import mouse, keyboard
import tkinter as tk
import webview

# ---------------------------------------------------------------
#  Windows-Eingaben
# ---------------------------------------------------------------
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040

BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

# Tastatur per SendInput + Scancode (funktioniert zuverlaessig in Minecraft)
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
SC_S = 0x1F
SC_LSHIFT = 0x2A
SC_LCTRL = 0x1D
SNEAK_KEYS = {"shift": SC_LSHIFT, "ctrl": SC_LCTRL}
SIDE_KEYS = {"a": 0x1E, "d": 0x20}
WARDOGS_TEAMS = {
    "manticore": ("Manticore", "Manticore.png"),
    "valkyr": ("Valkyra", "Valkyra.png"),
    "lonesta": ("Lonestar", "Lonestar.png"),
}
WARDOGS_MATCH_SCALES = (0.65, 0.8, 0.9, 1.0, 1.1, 1.25, 1.45, 1.7)
WARDOGS_MATCH_THRESHOLD = 0.92
WARDOGS_COUNTDOWN_SECONDS = 3


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def send_scancode(scan: int, down: bool):
    flags = KEYEVENTF_SCANCODE | (0 if down else KEYEVENTF_KEYUP)
    inp = INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(0, scan, flags, 0, 0)))
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def resource_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


class CountdownOverlay:
    TRANSPARENT_COLOR = "#010203"

    def __init__(self):
        self._commands = queue.Queue()
        self._ready = threading.Event()
        self._error = None
        threading.Thread(target=self._run, daemon=True).start()
        if not self._ready.wait(5):
            raise RuntimeError("Der Countdown-Rahmen konnte nicht gestartet werden.")
        if self._error:
            raise RuntimeError("Der Countdown-Rahmen konnte nicht gestartet werden: %s" % self._error)

    def show(self, seconds: int):
        self._commands.put(seconds)

    def hide(self):
        self._commands.put(None)

    def _run(self):
        try:
            root = tk.Tk()
            root.withdraw()
            root.overrideredirect(True)
            root.configure(background=self.TRANSPARENT_COLOR)
            root.wm_attributes("-transparentcolor", self.TRANSPARENT_COLOR)
            root.wm_attributes("-topmost", True)

            user32 = ctypes.windll.user32
            left = user32.GetSystemMetrics(76)
            top = user32.GetSystemMetrics(77)
            width = user32.GetSystemMetrics(78)
            height = user32.GetSystemMetrics(79)
            user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
            user32.GetWindowLongW.restype = wintypes.LONG
            user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.LONG)
            user32.SetWindowLongW.restype = wintypes.LONG
            user32.GetParent.argtypes = (wintypes.HWND,)
            user32.GetParent.restype = wintypes.HWND
            user32.SetWindowPos.argtypes = (
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            )
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
            user32.ShowWindow.restype = wintypes.BOOL
            root.geometry("%dx%d+%d+%d" % (width, height, left, top))
            canvas = tk.Canvas(
                root,
                width=width,
                height=height,
                background=self.TRANSPARENT_COLOR,
                highlightthickness=0,
                borderwidth=0,
            )
            canvas.pack(fill="both", expand=True)
            root.update_idletasks()
            hwnd = user32.GetParent(wintypes.HWND(root.winfo_id()))
            if not hwnd:
                hwnd = wintypes.HWND(root.winfo_id())
            style = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, style | 0x00000020 | 0x00000080 | 0x08000000)

            deadline = None
            phase = 0

            def tick():
                nonlocal deadline, phase
                try:
                    while True:
                        command = self._commands.get_nowait()
                        if command is None:
                            deadline = None
                            user32.ShowWindow(hwnd, 0)
                        else:
                            deadline = time.perf_counter() + command
                            user32.ShowWindow(hwnd, 4)
                            user32.SetWindowPos(
                                hwnd, wintypes.HWND(-1), left, top, width, height, 0x0010 | 0x0040
                            )
                except queue.Empty:
                    pass

                if deadline is not None:
                    phase = (phase + 1) % 40
                    canvas.delete("overlay")
                    inset = 12
                    thickness = 6
                    perimeter = 2 * (width + height - 4 * inset)
                    for index in range(64):
                        position = (index * perimeter / 64 + phase * perimeter / 40) % perimeter
                        color = "#a855f7" if index % 2 == 0 else "#fb923c"
                        if position < width - 2 * inset:
                            x, y = inset + position, inset
                        elif position < width - 2 * inset + height - 2 * inset:
                            x, y = width - inset, inset + position - (width - 2 * inset)
                        elif position < 2 * (width - 2 * inset) + height - 2 * inset:
                            x = width - inset - (position - (width - 2 * inset + height - 2 * inset))
                            y = height - inset
                        else:
                            x = inset
                            y = height - inset - (position - (2 * (width - 2 * inset) + height - 2 * inset))
                        canvas.create_oval(
                            x - thickness,
                            y - thickness,
                            x + thickness,
                            y + thickness,
                            fill=color,
                            outline=color,
                            tags="overlay",
                        )

                    remaining = max(1, math.ceil(deadline - time.perf_counter()))
                    center_x, center_y = width // 2, height // 2
                    canvas.create_text(
                        center_x,
                        center_y - 20,
                        text=str(remaining),
                        fill="#ffffff",
                        font=("Segoe UI", 72, "bold"),
                        tags="overlay",
                    )
                    canvas.create_text(
                        center_x,
                        center_y + 54,
                        text="NICHT BEWEGEN",
                        fill="#fb923c",
                        font=("Segoe UI", 20, "bold"),
                        tags="overlay",
                    )
                    if time.perf_counter() >= deadline:
                        deadline = None
                        user32.ShowWindow(hwnd, 0)

                root.after(40, tick)

            self._ready.set()
            root.after(40, tick)
            root.mainloop()
        except (tk.TclError, OSError, RuntimeError) as error:
            self._error = error
            self._ready.set()


# ---------------------------------------------------------------
#  Hotkey-Hilfen
# ---------------------------------------------------------------
def key_id(key) -> str:
    """Macht aus Tasten/Maustasten eine eindeutige Zeichenkette."""
    if isinstance(key, keyboard.KeyCode):
        if key.char:
            return "char:" + key.char.lower()
        return "vk:%s" % key.vk
    return str(key)  # z.B. "Key.f6" oder "Button.x1"


def key_display(kid: str) -> str:
    if kid.startswith("Button."):
        name = kid.split(".", 1)[1]
        return {"x1": "Maustaste 4", "x2": "Maustaste 5"}.get(name, "Maus " + name.upper())
    if kid.startswith("Key."):
        return kid[4:].upper().replace("_", " ")
    if kid.startswith("char:"):
        return kid[5:].upper()
    if kid.startswith("vk:"):
        return "Taste " + kid[3:]
    return kid.upper()


class Api:
    def __init__(self):
        self.hotkeys = {"wardogs": "Key.f8", "clicker": "Key.f6", "bridge": "Key.f7"}
        self.interval_ms = 100
        self.button = "left"
        self.team = "manticore"
        self.wardogs_clicks = 0
        self.wardogs_status = "Bereit"
        self._wardogs_templates = {}
        self._wardogs_deadline = None
        self._countdown_overlay = None
        self._overlay_lock = threading.Lock()
        self.mode = "toggle"      # "toggle" oder "hold"
        self.sneak_ms = 150       # Fast Bridge: Zeit mit gedrueckter Sneak-Taste
        self.sneak_key = "ctrl"   # Sneak-Taste in Minecraft: "ctrl" oder "shift"
        self.side = "none"        # Fast Bridge: Seitentaste fuer Diagonal ("none"/"a"/"d")
        self.walk_ms = 150        # Fast Bridge: Zeit ohne Sneak (rueckwaerts laufen)

        self.active = None        # None | "wardogs" | "clicker" | "bridge"
        self._wake = threading.Event()
        self.clicks = 0
        self.blocks = 0
        self._capturing = False
        self._pressed = set()     # gegen Tasten-Wiederholung
        self._s_down = False
        self._shift_down = False
        self._side_down = None
        self._sneak_used = SC_LSHIFT

        self.keyboard_listener = keyboard.Listener(
            on_press=lambda k: self._on_input(key_id(k), True),
            on_release=lambda k: self._on_input(key_id(k), False),
        )
        self.mouse_listener = mouse.Listener(
            on_click=lambda x, y, b, p: self._on_input(key_id(b), p)
        )
        self.keyboard_listener.start()
        self.mouse_listener.start()
        threading.Thread(target=self._loop, daemon=True).start()

    # ---------- Eingabe-Events ----------
    def _on_input(self, kid: str, pressed: bool):
        if self._capturing:
            return
        if pressed:
            if kid in self._pressed:
                return  # Tasten-Wiederholung ignorieren
            self._pressed.add(kid)
        else:
            self._pressed.discard(kid)

        for feat, hk in self.hotkeys.items():
            if kid != hk:
                continue
            if self.mode == "toggle" and pressed:
                self.toggle(feat)
            elif self.mode == "hold":
                if pressed:
                    if feat == "wardogs":
                        self._start_wardogs()
                    else:
                        self.active = feat
                elif self.active == feat:
                    self.active = None
                    if feat == "wardogs":
                        self.wardogs_status = "Abgebrochen"
                        self._cancel_wardogs_countdown()
            self._wake.set()

    # ---------- Arbeits-Schleife ----------
    def _wait(self, ms: int, feat: str) -> bool:
        """Wartet ms Millisekunden. Gibt False zurueck, wenn zwischendurch gestoppt wurde."""
        end = time.perf_counter() + ms / 1000.0
        while True:
            if self.active != feat or self._capturing:
                return False
            remaining = end - time.perf_counter()
            if remaining <= 0:
                return True
            self._wake.wait(remaining)
            self._wake.clear()

    def _sneak(self, down: bool):
        """Drueckt/loesst die eingestellte Sneak-Taste (Strg oder Shift)."""
        if down:
            self._sneak_used = SNEAK_KEYS.get(self.sneak_key, SC_LSHIFT)
        send_scancode(self._sneak_used, down)
        self._shift_down = down

    def _release_bridge_keys(self):
        if self._shift_down:
            self._sneak(False)
        if self._s_down:
            send_scancode(SC_S, False)
            self._s_down = False
        if self._side_down is not None:
            send_scancode(self._side_down, False)
            self._side_down = None

    def _bridge_cycle(self):
        first = not self._shift_down and not self._s_down
        # 1) ZUERST sneaken, damit man an der Kante gesichert ist
        if not self._shift_down:
            self._sneak(True)
            if not self._wait(60 if first else 20, "bridge"):
                return
        # 2) Bewegungstasten (S, optional A/D fuer Diagonal) gedrueckt halten
        if not self._s_down:
            send_scancode(SC_S, True)
            self._s_down = True
            side = SIDE_KEYS.get(self.side)
            if side:
                send_scancode(side, True)
                self._side_down = side
        # 3) Waehrend der ganzen Sneak-Phase immer wieder rechtsklicken:
        #    sobald das Fadenkreuz die Kante trifft, wird der Block gesetzt
        user32 = ctypes.windll.user32
        end = time.perf_counter() + self.sneak_ms / 1000.0
        while True:
            user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
            if not self._wait(25, "bridge"):
                return
            if time.perf_counter() >= end:
                break
        self.blocks += 1
        # 4) Erst jetzt entsneaken und ein Stueck auf den neuen Block zurueckgehen
        self._sneak(False)
        self._wait(self.walk_ms, "bridge")

    def _loop(self):
        user32 = ctypes.windll.user32
        while True:
            self._wake.clear()
            act = None if self._capturing else self.active
            if act != "bridge" and (self._s_down or self._shift_down):
                self._release_bridge_keys()

            if act == "clicker":
                down, up = BUTTONS.get(self.button, BUTTONS["left"])
                user32.mouse_event(down, 0, 0, 0, 0)
                user32.mouse_event(up, 0, 0, 0, 0)
                self.clicks += 1
                self._wait(max(self.interval_ms, 10), "clicker")
            elif act == "bridge":
                self._bridge_cycle()
            elif act == "wardogs":
                remaining = self._wardogs_deadline - time.perf_counter()
                if remaining > 0:
                    self.wardogs_status = "Nicht bewegen: %d" % max(1, math.ceil(remaining))
                    self._wake.wait(min(remaining, 0.1))
                    continue
                self._wardogs_deadline = None
                self.wardogs_status = "Suche nach " + WARDOGS_TEAMS[self.team][0]
                try:
                    self._wardogs_cycle()
                except (OSError, RuntimeError, ValueError, cv2.error, mss.exception.ScreenShotError) as error:
                    self.active = None
                    self.wardogs_status = "Fehler: " + str(error)
                    print("Wardogs-Bilderkennung fehlgeschlagen: %s" % error, file=sys.stderr)
            else:
                self._wake.wait()

    def _start_wardogs(self):
        if self.team not in WARDOGS_TEAMS:
            self.wardogs_status = "Ungültiges Team"
            return
        name, filename = WARDOGS_TEAMS[self.team]
        image_path = resource_path(os.path.join("assets", "teams", filename))
        if not os.path.isfile(image_path):
            self.wardogs_status = "PNG fehlt: " + filename
            self.active = None
            return
        with self._overlay_lock:
            if self._countdown_overlay is None:
                try:
                    self._countdown_overlay = CountdownOverlay()
                except RuntimeError as error:
                    self.active = None
                    self.wardogs_status = str(error)
                    print("Wardogs-Countdown konnte nicht gestartet werden: %s" % error, file=sys.stderr)
                    return
            self._countdown_overlay.show(WARDOGS_COUNTDOWN_SECONDS)
        self._wardogs_deadline = time.perf_counter() + WARDOGS_COUNTDOWN_SECONDS
        self.active = "wardogs"
        self.wardogs_status = "Nicht bewegen: %d" % WARDOGS_COUNTDOWN_SECONDS

    def _cancel_wardogs_countdown(self):
        self._wardogs_deadline = None
        if self._countdown_overlay is not None:
            self._countdown_overlay.hide()

    def _wardogs_cycle(self):
        name, filename = WARDOGS_TEAMS[self.team]
        cached = self._wardogs_templates.get(self.team)
        if cached is None:
            image_path = resource_path(os.path.join("assets", "teams", filename))
            image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
            if image is None or image.size == 0:
                self.active = None
                self.wardogs_status = "PNG ungültig: " + filename
                return
            if image.ndim == 3 and image.shape[2] == 4:
                alpha = image[:, :, 3]
                visible_y, visible_x = np.where(alpha >= 128)
                if not visible_x.size:
                    self.active = None
                    self.wardogs_status = "PNG ist vollständig transparent: " + filename
                    return
                bounds = (visible_y.min(), visible_y.max() + 1, visible_x.min(), visible_x.max() + 1)
                image = image[bounds[0]:bounds[1], bounds[2]:bounds[3]]
                mask = np.where(image[:, :, 3] >= 128, 255, 0).astype(np.uint8)
                template = image[:, :, :3]
            else:
                template = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
                mask = np.full(template.shape, 255, dtype=np.uint8)
            if float(template[mask > 0].std()) < 4:
                self.active = None
                self.wardogs_status = "PNG hat zu wenig Kontrast: " + filename
                return
            cached = (template, mask)
            self._wardogs_templates[self.team] = cached
        template, template_mask = cached

        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user32.GetClientRect.restype = wintypes.BOOL
        user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
        user32.ClientToScreen.restype = wintypes.BOOL
        user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
        user32.SetCursorPos.restype = wintypes.BOOL
        hwnd = user32.GetForegroundWindow()
        title_buffer = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        window_title = title_buffer.value.lower()
        if "wardogs" not in window_title:
            self.active = None
            self.wardogs_status = "Wardogs-Spiel in den Vordergrund holen"
            return

        client = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(client)):
            raise OSError("Wardogs-Clientbereich konnte nicht ermittelt werden.")
        origin = wintypes.POINT(client.left, client.top)
        if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            raise OSError("Wardogs-Bildschirmposition konnte nicht ermittelt werden.")
        region = {
            "left": origin.x,
            "top": origin.y,
            "width": client.right - client.left,
            "height": client.bottom - client.top,
        }
        if region["width"] <= 0 or region["height"] <= 0:
            raise RuntimeError("Wardogs-Fenster hat keine gültige Größe.")
        with mss.MSS() as screen:
            screenshot = np.asarray(screen.grab(region))
        frame = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)
        best_score = -1.0
        best_location = None
        best_size = None
        frame_height, frame_width = frame.shape[:2]
        template_height, template_width = template.shape[:2]

        for scale in WARDOGS_MATCH_SCALES:
            width = round(template_width * scale)
            height = round(template_height * scale)
            if width < 8 or height < 8 or width > frame_width or height > frame_height:
                continue
            interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
            resized = cv2.resize(template, (width, height), interpolation=interpolation)
            resized_mask = cv2.resize(template_mask, (width, height), interpolation=cv2.INTER_NEAREST)
            result = cv2.matchTemplate(frame, resized, cv2.TM_SQDIFF_NORMED, mask=resized_mask)
            difference, _, location, _ = cv2.minMaxLoc(result)
            score = 1.0 - difference
            if score > best_score:
                best_score = score
                best_location = location
                best_size = (width, height)

        if best_location is None or best_score < WARDOGS_MATCH_THRESHOLD:
            self.active = None
            self.wardogs_status = "Team nicht gefunden – Logo/Ansicht prüfen"
            return
        if self.active != "wardogs":
            return

        x = region["left"] + best_location[0] + best_size[0] // 2
        y = region["top"] + best_location[1] + best_size[1] // 2
        if not user32.SetCursorPos(x, y):
            raise OSError("Mauszeiger konnte nicht zum Wardogs-Team bewegt werden.")
        time.sleep(0.12)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        self.wardogs_clicks += 1
        self.wardogs_status = name + " angeklickt"
        self.active = None
        self._wake.set()

    # ---------- API fuer die Oberflaeche ----------
    def get_state(self):
        return {
            "active": None if self._capturing else self.active,
            "hotkeys": {k: key_display(v) for k, v in self.hotkeys.items()},
            "mode": self.mode,
            "clicks": self.clicks,
            "blocks": self.blocks,
            "team": self.team,
            "wardogs_clicks": self.wardogs_clicks,
            "wardogs_status": self.wardogs_status,
            "capturing": self._capturing,
        }

    def set_config(self, c):
        try:
            self.interval_ms = max(10, min(int(c.get("interval", 100)), 60000))
            self.sneak_ms = max(10, min(int(c.get("sneak", 150)), 500))
            self.walk_ms = max(10, min(int(c.get("walk", 150)), 500))
        except (TypeError, ValueError):
            pass
        if c.get("sneak_key") in SNEAK_KEYS:
            self.sneak_key = c["sneak_key"]
        if c.get("side") in ("none", "a", "d"):
            self.side = c["side"]
        if c.get("button") in BUTTONS:
            self.button = c["button"]
        if c.get("team") in WARDOGS_TEAMS and c["team"] != self.team:
            self.team = c["team"]
            if self.active == "wardogs":
                self.active = None
                self._cancel_wardogs_countdown()
            self.wardogs_status = "Ausgewählt: " + WARDOGS_TEAMS[self.team][0]
            self._wake.set()
        if c.get("mode") in ("toggle", "hold"):
            if c["mode"] != self.mode:
                if self.active == "wardogs":
                    self.wardogs_status = "Abgebrochen"
                    self._cancel_wardogs_countdown()
                self.active = None
                self._wake.set()
            self.mode = c["mode"]
        return self.get_state()

    def toggle(self, feat):
        if feat in self.hotkeys and (self.mode == "toggle" or feat == "wardogs"):
            if self.active == feat:
                self.active = None
                if feat == "wardogs":
                    self.wardogs_status = "Abgebrochen"
                    self._cancel_wardogs_countdown()
            elif feat == "wardogs":
                self._start_wardogs()
            else:
                self.active = feat
            self._wake.set()
        return self.get_state()

    def reset_clicks(self, feat):
        if feat == "wardogs":
            self.wardogs_clicks = 0
        elif feat == "bridge":
            self.blocks = 0
        else:
            self.clicks = 0
        return self.get_state()

    def capture_hotkey(self, feat):
        """Wartet auf die naechste Taste/Maustaste und setzt sie als Hotkey fuer feat."""
        if feat not in self.hotkeys:
            return self.get_state()
        self._capturing = True
        if self.active == "wardogs":
            self.wardogs_status = "Abgebrochen"
            self._cancel_wardogs_countdown()
        self.active = None
        self._wake.set()
        captured = []

        def on_press_cap(key):
            captured.append(key_id(key))
            return False

        def on_click_cap(x, y, button, pressed):
            if pressed:
                captured.append(key_id(button))
                return False

        k_listener = keyboard.Listener(on_press=on_press_cap)
        m_listener = mouse.Listener(on_click=on_click_cap)
        k_listener.start()
        m_listener.start()
        while not captured:
            time.sleep(0.05)
        k_listener.stop()
        m_listener.stop()

        self.hotkeys[feat] = captured[0]
        self._pressed.clear()
        self._capturing = False
        self._wake.set()
        return self.get_state()


def main():
    api = Api()
    webview.create_window(
        "WARDOGS AUTOKLICKER",
        resource_path("index.html"),
        js_api=api,
        width=980,
        height=680,
        min_size=(760, 580),
        background_color="#080808",
    )
    webview.start()


if __name__ == "__main__":
    main()