"""Demonstration console for labs 6 and 7.

A thin front end over the scripts that already exist: it runs them, streams their
output into one window and colours the verdicts, so a demonstration does not have
to be driven from a terminal. Standard library only (tkinter), nothing installed.
"""

import os
import queue
import socket
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from common import token  # noqa: E402

LAB6_PORT, LAB7_PORT = 5607, 5707

BG = "#1b1d23"
FG = "#d7dae0"
MUTED = "#8b93a1"
OK = "#5fb37a"
BAD = "#d4766a"
ACCENT = "#6ea8d8"
HEAD = "#d9b26a"

TAGS = {
    "ok": OK,
    "bad": BAD,
    "head": HEAD,
    "muted": MUTED,
    "accent": ACCENT,
}


def classify(line):
    """Pick a colour tag for one line of a protocol."""
    s = line.strip()
    if not s:
        return None
    if s.startswith("===") or s.startswith("---"):
        return "head"
    for marker in ("GRANTED", "ALLOW", "AUTH OK", "ALLOWED"):
        if marker in s:
            return "ok"
    for marker in ("DENIED", "DENY", "FAIL", "Traceback", "Error"):
        if marker in s:
            return "bad"
    if s.startswith("[") or "[SERVER]" in s or "[CLIENT]" in s:
        return "muted"
    return None


def host_address():
    """The address of this machine on the local network, for the VM to connect to."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def port_is_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.25)
        return s.connect_ex(("127.0.0.1", port)) == 0


class Console(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Безпека програм та даних — лабораторні 6 і 7")
        self.geometry("1100x660")
        self.minsize(900, 520)
        self.configure(bg=BG)

        self.lines = queue.Queue()
        self.worker = None
        self.servers = []

        self._build()
        self.after(80, self._drain)
        self._refresh_status()

    # --- layout ---

    def _build(self):
        mono = tkfont.Font(family="Consolas", size=10)
        ui = tkfont.Font(family="Segoe UI", size=10)

        side = tk.Frame(self, bg=BG, padx=14, pady=14)
        side.pack(side="left", fill="y")

        tk.Label(side, text="Демонстрація", bg=BG, fg=FG,
                 font=tkfont.Font(family="Segoe UI", size=13, weight="bold")).pack(anchor="w")
        tk.Label(side, text="лабораторні 6 і 7", bg=BG, fg=MUTED, font=ui).pack(anchor="w", pady=(0, 14))

        self.buttons = {}
        for key, text, cmd in (
            ("lab6", "Лабораторна 6\nаутентифікація за токеном", self.run_lab6),
            ("lab7", "Лабораторна 7\nкерування доступом", self.run_lab7),
            ("matrix", "Матриця доступу", self.show_matrix),
        ):
            b = tk.Button(side, text=text, command=cmd, font=ui, bg="#2a2e37", fg=FG,
                          activebackground="#343945", activeforeground=FG, relief="flat",
                          justify="left", anchor="w", padx=12, pady=9, width=26, cursor="hand2")
            b.pack(fill="x", pady=3)
            self.buttons[key] = b

        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=12)

        tk.Label(side, text="Для прогону на двох машинах", bg=BG, fg=MUTED, font=ui).pack(anchor="w")
        self.buttons["servers"] = tk.Button(
            side, text="Запустити сервери", command=self.toggle_servers, font=ui,
            bg="#2a2e37", fg=FG, activebackground="#343945", activeforeground=FG,
            relief="flat", padx=12, pady=9, width=26, cursor="hand2")
        self.buttons["servers"].pack(fill="x", pady=3)

        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=12)

        tk.Button(side, text="Очистити вивід", command=self.clear, font=ui, bg=BG, fg=MUTED,
                  activebackground=BG, activeforeground=FG, relief="flat",
                  padx=12, pady=6, cursor="hand2").pack(fill="x")

        self.status = tk.Label(side, text="", bg=BG, fg=MUTED, font=ui, justify="left",
                               anchor="w", wraplength=210)
        self.status.pack(side="bottom", anchor="w", pady=(14, 0))

        main = tk.Frame(self, bg=BG, padx=0, pady=14)
        main.pack(side="right", fill="both", expand=True)

        self.out = tk.Text(main, bg="#15171c", fg=FG, font=mono, wrap="none",
                           relief="flat", padx=14, pady=12, insertbackground=FG)
        bar = tk.Scrollbar(main, command=self.out.yview)
        self.out.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.out.pack(side="left", fill="both", expand=True, padx=(0, 14))

        for name, colour in TAGS.items():
            self.out.tag_configure(name, foreground=colour)
        self.out.tag_configure("head", foreground=HEAD, spacing1=6, spacing3=2)

        self.write("Готово до демонстрації.", "accent")
        self.write("Оберіть дію ліворуч. Вивід програм з'являтиметься тут.", "muted")
        self.write("")

    # --- output ---

    def write(self, text="", tag=None):
        self.out.insert("end", text + "\n", tag or ())
        self.out.see("end")

    def _drain(self):
        while True:
            try:
                item = self.lines.get_nowait()
            except queue.Empty:
                break
            if item is None:
                self._finished()
            else:
                self.write(item, classify(item))
        self.after(80, self._drain)

    def clear(self):
        self.out.delete("1.0", "end")

    # --- running things ---

    def _busy(self, busy):
        for key in ("lab6", "lab7", "matrix"):
            self.buttons[key].configure(state="disabled" if busy else "normal")

    def _finished(self):
        self.worker = None
        self._busy(False)
        self.write("")
        self.write("— готово —", "accent")
        self.write("")
        self._refresh_status()

    def _spawn(self, args, cwd):
        """Run a command and stream its output into the window."""
        def work():
            try:
                p = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace", bufsize=1,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
                for line in p.stdout:
                    self.lines.put(line.rstrip("\n"))
                p.wait()
            except Exception as exc:
                self.lines.put(f"Error: {exc}")
            finally:
                self.lines.put(None)

        self._busy(True)
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _powershell(self, script, cwd):
        return self._spawn(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", script], cwd)

    def run_lab6(self):
        self.write("Лабораторна 6 — аутентифікація за токеном безпеки", "head")
        self._powershell(os.path.join(HERE, "lab_6", "demo.ps1"), os.path.join(HERE, "lab_6"))

    def run_lab7(self):
        self.write("Лабораторна 7 — дискреційне керування доступом", "head")
        self._powershell(os.path.join(HERE, "lab_7", "demo.ps1"), os.path.join(HERE, "lab_7"))

    def show_matrix(self):
        self.write("Поточна матриця доступу", "head")
        self._spawn([sys.executable, os.path.join(HERE, "lab_7", "show_matrix.py")],
                    os.path.join(HERE, "lab_7"))

    # --- servers for the two-machine run ---

    def toggle_servers(self):
        if self.servers:
            for p in self.servers:
                p.terminate()
            self.servers = []
            self.write("Сервери зупинено.", "muted")
        else:
            for folder, port in (("lab_6", LAB6_PORT), ("lab_7", LAB7_PORT)):
                cwd = os.path.join(HERE, folder)
                p = subprocess.Popen(
                    [sys.executable, "server.py", "--host", "0.0.0.0", "--port", str(port),
                     "--db", os.path.join(HERE, "lab_6", "server_db.json")],
                    cwd=cwd, creationflags=subprocess.CREATE_NO_WINDOW)
                self.servers.append(p)
            ip = host_address()
            self.write("Сервери запущено на 0.0.0.0", "head")
            self.write(f"  лабораторна 6 — {ip}:{LAB6_PORT}", "accent")
            self.write(f"  лабораторна 7 — {ip}:{LAB7_PORT}", "accent")
            self.write("  у віртуальній машині запустіть CLIENT_TO_HOST.bat", "muted")
        self._refresh_status()

    # --- status line ---

    def _refresh_status(self):
        try:
            drives = token.find_removable_drives()
        except Exception:
            drives = []
        where = drives[0] if drives else "тека-замінник (флешки немає)"

        running = bool(self.servers) or port_is_open(LAB6_PORT)
        self.buttons["servers"].configure(
            text="Зупинити сервери" if self.servers else "Запустити сервери")

        self.status.configure(
            text=f"Токен: {where}\nСервери: {'працюють' if running else 'зупинено'}\n"
                 f"Адреса хоста: {host_address()}")
        self.after(2000, self._refresh_status)

    def destroy(self):
        for p in self.servers:
            p.terminate()
        super().destroy()


if __name__ == "__main__":
    Console().mainloop()
