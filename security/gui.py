"""Demonstration console for labs 6, 7 and 8.

Two modes, switched by the tabs at the top of the sidebar:

  Демонстрація     runs the scripted demos and streams their output
  Інтерактивно     keeps a live session with the access control server, so every
                   action can be performed by hand and the records it produced in
                   the audit journal appear beside it at once

Standard library only (tkinter), nothing installed.
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

from common import netproto, token  # noqa: E402
from common.audit import SUCCESS, AuditError, AuditLog, format_record  # noqa: E402

LAB6_PORT, LAB7_PORT, LIVE_PORT = 5607, 5707, 5717
JOURNAL = os.path.join(HERE, "lab_8", "logs", "audit.jsonl")
AUDITOR = "kovalenko"

# the subjects the demos enroll, with the PIN that opens each token
SUBJECTS = {
    "ostrovska": "1111",
    "shevchenko": "2222",
    "kovalenko": "3333",
    "mallory": "5555",
}
RIGHTS = ("read", "write", "delete", "grant", "own")

BG = "#1b1d23"
PANEL = "#15171c"
FG = "#d7dae0"
MUTED = "#8b93a1"
OK = "#5fb37a"
BAD = "#d4766a"
ACCENT = "#6ea8d8"
HEAD = "#d9b26a"
BTN = "#2a2e37"
BTN_HOT = "#343945"

TAGS = {"ok": OK, "bad": BAD, "head": HEAD, "muted": MUTED, "accent": ACCENT}


def classify(line):
    """Pick a colour tag for one line of a protocol."""
    s = line.strip()
    if not s:
        return None
    if s.startswith("===") or s.startswith("---"):
        return "head"
    for marker in ("GRANTED", "ALLOW", "AUTH OK", "ALLOWED", "SUCCESS",
                   "ЦІЛІСНІСТЬ ПІДТВЕРДЖЕНО", "Ознак порушень не виявлено"):
        if marker in s:
            return "ok"
    for marker in ("DENIED", "DENY", "FAIL", "Traceback", "Error",
                   "ЦІЛІСНІСТЬ ПОРУШЕНО", "[ВИСОКИЙ]", "не вдалося"):
        if marker in s:
            return "bad"
    if "[СЕРЕДНІЙ]" in s or s.startswith("Виявлено ознак"):
        return "head"
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


def port_is_open(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.25)
        return s.connect_ex((host, port)) == 0


def token_dir_of(slot):
    """Where this subject's token lives: the flash drive, or the stand-in folder."""
    try:
        drives = token.find_removable_drives()
    except Exception:
        drives = []
    explicit = None
    if not drives:
        explicit = os.path.join(os.environ.get("LOCALAPPDATA", HERE), "BPD_TOKEN")
    return token.resolve_token_dir(explicit, slot=slot)


def button(parent, text, command, font, **kw):
    opts = dict(bg=BTN, fg=FG, activebackground=BTN_HOT, activeforeground=FG,
                relief="flat", padx=10, pady=7, cursor="hand2", font=font)
    opts.update(kw)
    return tk.Button(parent, text=text, command=command, **opts)


class Console(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Безпека програм та даних — лабораторні 6, 7 і 8")
        self.geometry("1240x720")
        self.minsize(1020, 600)
        self.configure(bg=BG)

        self.lines = queue.Queue()
        self.worker = None
        self.servers = []
        self.live_server = None
        self.sock = None
        self.live_user = None
        self.audit_seen = 0
        self.view = "demo"

        self._build()
        self.after(80, self._drain)
        self._refresh_status()

    # ------------------------------------------------------------------ layout

    def _build(self):
        self.mono = tkfont.Font(family="Consolas", size=10)
        self.ui = tkfont.Font(family="Segoe UI", size=10)
        self.ui_bold = tkfont.Font(family="Segoe UI", size=10, weight="bold")

        side = tk.Frame(self, bg=BG, padx=14, pady=14)
        side.pack(side="left", fill="y")

        tk.Label(side, text="Лабораторні 6, 7, 8", bg=BG, fg=FG,
                 font=tkfont.Font(family="Segoe UI", size=12, weight="bold")).pack(anchor="w")

        tabs = tk.Frame(side, bg=BG)
        tabs.pack(fill="x", pady=(10, 12))
        self.tabs = {}
        for key, text in (("demo", "Демонстрація"), ("live", "Інтерактивно")):
            b = button(tabs, text, lambda k=key: self.switch(k), self.ui_bold, width=12, pady=6)
            b.pack(side="left", padx=(0, 4))
            self.tabs[key] = b

        self.panel_demo = tk.Frame(side, bg=BG)
        self.panel_live = tk.Frame(side, bg=BG)
        self._build_panel_demo(self.panel_demo)
        self._build_panel_live(self.panel_live)

        self.status = tk.Label(side, text="", bg=BG, fg=MUTED, font=self.ui,
                               justify="left", anchor="w", wraplength=230)
        self.status.pack(side="bottom", anchor="w", pady=(14, 0))

        main = tk.Frame(self, bg=BG, pady=14)
        main.pack(side="right", fill="both", expand=True)
        self.main_demo = tk.Frame(main, bg=BG)
        self.main_live = tk.Frame(main, bg=BG)
        self._build_main_demo(self.main_demo)
        self._build_main_live(self.main_live)

        self.switch("demo")
        self.write("Готово до демонстрації.", "accent")
        self.write("Ліворуч угорі — перемикач режимів. «Інтерактивно» дає живу сесію "
                   "із сервером,", "muted")
        self.write("де кожна дія одразу показує, що вона залишила в журналі аудиту.", "muted")
        self.write("")

    def _build_panel_demo(self, side):
        self.buttons = {}
        for key, text, cmd in (
            ("lab6", "Лабораторна 6\nаутентифікація за токеном", self.run_lab6),
            ("lab7", "Лабораторна 7\nкерування доступом", self.run_lab7),
            ("matrix", "Матриця доступу", self.show_matrix),
        ):
            b = button(side, text, cmd, self.ui, justify="left", anchor="w", width=26, pady=9)
            b.pack(fill="x", pady=3)
            self.buttons[key] = b

        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=12)
        tk.Label(side, text="Лабораторна 8 — реєстрація", bg=BG, fg=MUTED,
                 font=self.ui).pack(anchor="w", pady=(0, 4))
        for key, text, cmd in (
            ("lab8", "Демонстрація", self.run_lab8),
            ("journal", "Журнал аудиту", self.show_journal),
            ("verify", "Перевірити цілісність", self.verify_journal),
            ("analyze", "Підозрілі події", self.analyze_journal),
            ("table", "Таблиця дій і записів", self.build_table),
        ):
            b = button(side, text, cmd, self.ui, justify="left", anchor="w", width=26)
            b.pack(fill="x", pady=2)
            self.buttons[key] = b

        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=12)
        tk.Label(side, text="Для прогону на двох машинах", bg=BG, fg=MUTED,
                 font=self.ui).pack(anchor="w")
        self.buttons["servers"] = button(side, "Запустити сервери", self.toggle_servers,
                                         self.ui, width=26, pady=9)
        self.buttons["servers"].pack(fill="x", pady=3)

        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=12)
        button(side, "Очистити вивід", self.clear, self.ui, bg=BG, fg=MUTED,
               activebackground=BG, pady=6).pack(fill="x")

    def _build_panel_live(self, side):
        def label(text, pady=(10, 2)):
            tk.Label(side, text=text, bg=BG, fg=MUTED, font=self.ui).pack(anchor="w", pady=pady)

        def chooser(var, values, width=24):
            m = tk.OptionMenu(side, var, *values)
            m.configure(bg=BTN, fg=FG, activebackground=BTN_HOT, activeforeground=FG,
                        relief="flat", highlightthickness=0, font=self.ui,
                        anchor="w", width=width)
            m["menu"].configure(bg=BTN, fg=FG, activebackground=ACCENT, font=self.ui)
            m.pack(fill="x")
            return m

        label("Суб'єкт", (0, 2))
        self.var_subject = tk.StringVar(value="ostrovska")
        self.var_subject.trace_add("write", lambda *_: self._subject_changed())
        chooser(self.var_subject, list(SUBJECTS))

        row = tk.Frame(side, bg=BG)
        row.pack(fill="x", pady=(8, 0))
        tk.Label(row, text="PIN", bg=BG, fg=MUTED, font=self.ui).pack(side="left")
        self.var_pin = tk.StringVar(value=SUBJECTS["ostrovska"])
        tk.Entry(row, textvariable=self.var_pin, width=8, bg=PANEL, fg=FG, relief="flat",
                 insertbackground=FG, font=self.ui).pack(side="left", padx=8)
        self.btn_login = button(row, "Увійти", self.toggle_session, self.ui_bold, width=10)
        self.btn_login.pack(side="right")

        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=12)

        label("Об'єкт", (0, 2))
        self.var_object = tk.StringVar(value="finance_q1")
        self.menu_object = chooser(self.var_object, ["finance_q1"])

        label("Текст (для «дописати» і «створити»)")
        self.var_text = tk.StringVar(value="нотатка з інтерактивної панелі")
        tk.Entry(side, textvariable=self.var_text, bg=PANEL, fg=FG, relief="flat",
                 insertbackground=FG, font=self.ui).pack(fill="x")

        label("Операція з об'єктом")
        grid = tk.Frame(side, bg=BG)
        grid.pack(fill="x")
        for i, (text, op) in enumerate((("Читати", "read"), ("Дописати", "write"),
                                        ("Видалити", "delete"), ("Створити", "create"))):
            b = button(grid, text, lambda o=op: self.do_object(o), self.ui, width=11)
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 4), pady=2)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        label("Права: кому і яке")
        rights = tk.Frame(side, bg=BG)
        rights.pack(fill="x")
        self.var_target = tk.StringVar(value="shevchenko")
        self.var_right = tk.StringVar(value="read")
        for var, values, width in ((self.var_target, list(SUBJECTS), 12),
                                   (self.var_right, list(RIGHTS), 8)):
            m = tk.OptionMenu(rights, var, *values)
            m.configure(bg=BTN, fg=FG, activebackground=BTN_HOT, activeforeground=FG,
                        relief="flat", highlightthickness=0, font=self.ui, width=width)
            m["menu"].configure(bg=BTN, fg=FG, activebackground=ACCENT, font=self.ui)
            m.pack(side="left", padx=(0, 4))

        rrow = tk.Frame(side, bg=BG)
        rrow.pack(fill="x", pady=4)
        button(rrow, "Надати", lambda: self.do_rights("grant"), self.ui, width=11).pack(side="left")
        button(rrow, "Відкликати", lambda: self.do_rights("revoke"), self.ui,
               width=11).pack(side="left", padx=4)

        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=12)
        button(side, "Прочитати журнал аудиту", lambda: self.do_plain("audit"),
               self.ui, width=26).pack(fill="x", pady=2)
        button(side, "Мої повноваження", lambda: self.do_plain("caps"),
               self.ui, width=26).pack(fill="x", pady=2)
        button(side, "Перелік об'єктів", lambda: self.do_plain("list"),
               self.ui, width=26).pack(fill="x", pady=2)

    def _pane(self, parent, title, height):
        wrap = tk.Frame(parent, bg=BG)
        tk.Label(wrap, text=title, bg=BG, fg=HEAD, font=self.ui_bold,
                 anchor="w").pack(fill="x", pady=(0, 4))
        text = tk.Text(wrap, bg=PANEL, fg=FG, font=self.mono, wrap="none", relief="flat",
                       padx=12, pady=10, height=height, insertbackground=FG)
        bar = tk.Scrollbar(wrap, command=text.yview)
        text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        for name, colour in TAGS.items():
            text.tag_configure(name, foreground=colour)
        return wrap, text

    def _build_main_demo(self, main):
        self.out = tk.Text(main, bg=PANEL, fg=FG, font=self.mono, wrap="none",
                           relief="flat", padx=14, pady=12, insertbackground=FG)
        bar = tk.Scrollbar(main, command=self.out.yview)
        self.out.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.out.pack(side="left", fill="both", expand=True, padx=(0, 14))
        for name, colour in TAGS.items():
            self.out.tag_configure(name, foreground=colour)
        self.out.tag_configure("head", foreground=HEAD, spacing1=6, spacing3=2)

    def _build_main_live(self, main):
        box = tk.Frame(main, bg=BG, padx=0)
        box.pack(fill="both", expand=True, padx=(0, 14))

        wrap1, self.live_out = self._pane(box, "Що сталося", 13)
        wrap1.pack(fill="both", expand=True)

        wrap2, self.live_audit = self._pane(
            box, "Нові записи в журналі аудиту (саме від цієї дії)", 13)
        wrap2.pack(fill="both", expand=True, pady=(12, 0))

    def switch(self, view):
        self.view = view
        for key, b in self.tabs.items():
            b.configure(bg=ACCENT if key == view else BTN,
                        fg=BG if key == view else FG)
        self.panel_demo.pack_forget()
        self.panel_live.pack_forget()
        self.main_demo.pack_forget()
        self.main_live.pack_forget()
        if view == "demo":
            self.panel_demo.pack(fill="x")
            self.main_demo.pack(fill="both", expand=True)
        else:
            self.panel_live.pack(fill="x")
            self.main_live.pack(fill="both", expand=True)
            if not self.sock:
                self.say("Натисніть «Увійти», щоб відкрити сесію із сервером.", "muted")

    # ------------------------------------------------------------------ output

    def write(self, text="", tag=None):
        self.out.insert("end", text + "\n", tag or ())
        self.out.see("end")

    def say(self, text="", tag=None, pane=None):
        pane = pane or self.live_out
        pane.insert("end", text + "\n", tag or ())
        pane.see("end")

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

    # ------------------------------------------------- running scripted things

    BUSY_KEYS = ("lab6", "lab7", "matrix", "lab8", "journal", "verify", "analyze", "table")

    def _busy(self, busy):
        for key in self.BUSY_KEYS:
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
                # a child started without a console inherits a non-Unicode code page,
                # and Cyrillic output would come back as question marks
                env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
                p = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace", bufsize=1,
                                     env=env,
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
        # PowerShell writes in the console code page; told to use UTF-8 it matches
        # how this window decodes the stream
        prelude = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        return self._spawn(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", prelude + f"& '{script}'"], cwd)

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

    def _lab8_tool(self, script, title, *extra):
        self.write(title, "head")
        self._spawn([sys.executable, os.path.join(HERE, "lab_8", script), *extra],
                    os.path.join(HERE, "lab_8"))

    def run_lab8(self):
        self.write("Лабораторна 8 — підсистема реєстрації", "head")
        self._powershell(os.path.join(HERE, "lab_8", "demo.ps1"), os.path.join(HERE, "lab_8"))

    def show_journal(self):
        self._lab8_tool("audit_view.py", "Журнал аудиту", "--tail", "25")

    def verify_journal(self):
        self._lab8_tool("audit_verify.py", "Перевірка цілісності журналу")

    def analyze_journal(self):
        self._lab8_tool("audit_analyze.py", "Пошук ознак порушень безпеки")

    def build_table(self):
        self._lab8_tool("report_table.py", "Таблиця «дія користувача — запис у журналі»")

    # ------------------------------------------------------ interactive session

    def _subject_changed(self):
        self.var_pin.set(SUBJECTS.get(self.var_subject.get(), ""))

    def _stand_is_ready(self):
        db = os.path.join(HERE, "lab_6", "server_db.json")
        if not os.path.isfile(db):
            return False
        try:
            return os.path.isfile(token.token_file(token_dir_of("u_ostrovska")))
        except Exception:
            return False

    def _prepare_stand(self):
        """Enrol the subjects and seed the objects, once."""
        self.say("Стенд не підготовлений — реєструю суб'єктів і об'єкти…", "muted")
        self.update()
        lab6, lab7 = os.path.join(HERE, "lab_6"), os.path.join(HERE, "lab_7")
        db = os.path.join(lab6, "server_db.json")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        flash = bool(token.find_removable_drives())
        extra = [] if flash else ["--token-dir",
                                  os.path.join(os.environ.get("LOCALAPPDATA", HERE), "BPD_TOKEN")]
        people = [("ostrovska", "Kateryna#2026", "1111"), ("shevchenko", "Taras#1814", "2222"),
                  ("kovalenko", "Olha#7731", "3333")]
        for user, password, pin in people:
            subprocess.run([sys.executable, os.path.join(lab6, "enroll.py"), "--user", user,
                            "--password", password, "--pin", pin, "--slot", f"u_{user}",
                            "--db", db] + extra, cwd=lab6, env=env, capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run([sys.executable, os.path.join(lab6, "enroll.py"), "--user", "mallory",
                        "--password", "Mallory#666", "--pin", "5555", "--slot", "u_mallory",
                        "--no-db"] + extra, cwd=lab6, env=env, capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        if not os.path.isfile(os.path.join(lab7, "acl.json")):
            subprocess.run([sys.executable, os.path.join(lab7, "seed_objects.py")],
                           cwd=lab7, env=env, capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        self.say("Стенд готовий.", "muted")

    def _ensure_live_server(self):
        if port_is_open(LIVE_PORT):
            return True
        lab7 = os.path.join(HERE, "lab_7")
        os.makedirs(os.path.dirname(JOURNAL), exist_ok=True)
        self.live_server = subprocess.Popen(
            [sys.executable, "server.py", "--port", str(LIVE_PORT),
             "--db", os.path.join(HERE, "lab_6", "server_db.json"),
             "--audit", JOURNAL, "--auditor", AUDITOR],
            cwd=lab7, creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(40):
            if port_is_open(LIVE_PORT):
                return True
            self.after(50)
            self.update()
        self.say("Сервер не піднявся.", "bad")
        return False

    def _journal(self):
        return AuditLog(JOURNAL)

    def _audit_mark(self):
        """Remember how many records the journal holds before an action."""
        try:
            self.audit_seen = len(self._journal().read_all())
        except (AuditError, OSError):
            self.audit_seen = 0

    def _audit_show(self):
        """Show only what this action appended."""
        self.live_audit.delete("1.0", "end")
        try:
            records = self._journal().read_all()
        except (AuditError, OSError) as exc:
            self.say(f"журнал недоступний: {exc}", "bad", self.live_audit)
            return
        fresh = records[self.audit_seen:]
        if not fresh:
            self.say("(ця дія не залишила записів у журналі)", "muted", self.live_audit)
            return
        for entry in fresh:
            tag = "ok" if entry["result"] == SUCCESS else "bad"
            self.say(format_record(entry), tag, self.live_audit)
        self.audit_seen = len(records)

    def toggle_session(self):
        if self.sock:
            self._disconnect("сесію завершено")
            return

        user = self.var_subject.get()
        self.live_out.delete("1.0", "end")
        if not self._stand_is_ready():
            self._prepare_stand()
        if not self._ensure_live_server():
            return

        self._audit_mark()
        self.say(f"Дія: вхід у систему як «{user}» (токен + PIN {self.var_pin.get()})", "head")
        try:
            slot_dir = token_dir_of(f"u_{user}")
            data = token.read_token(slot_dir, self.var_pin.get())
        except token.TokenError as exc:
            self.say(f"ВІДМОВА ще на боці клієнта: {exc}", "bad")
            self.say("До сервера запит не пішов, тож у журналі цієї спроби немає.", "muted")
            self._audit_show()
            return

        self.say(f"токен прочитано: {token.token_file(slot_dir)}", "muted")
        try:
            self.sock = netproto.connect("127.0.0.1", LIVE_PORT, timeout=10)
            netproto.send(self.sock, {"op": "auth", "user_id": data["user_id"],
                                      "pwd_hash": data["pwd_hash"]})
            response = netproto.recv(self.sock)
        except OSError as exc:
            self.say(f"мережна помилка: {exc}", "bad")
            self.sock = None
            return

        if response.get("status") != "ok":
            self.say(f"АУТЕНТИФІКАЦІЮ ВІДХИЛЕНО: {response.get('reason')}", "bad")
            self.sock.close()
            self.sock = None
        else:
            self.live_user = data["user_id"]
            self.say(f"АУТЕНТИФІКАЦІЮ ПРОЙДЕНО: {response.get('reason')}", "ok")
            self.btn_login.configure(text="Вийти")
            self.after(150, self._refresh_objects)
        self._audit_show()
        self._refresh_status()

    def _disconnect(self, why):
        self._audit_mark()
        try:
            if self.sock:
                netproto.send(self.sock, {"op": "quit"})
                self.sock.close()
        except OSError:
            pass
        self.sock = None
        self.live_user = None
        self.btn_login.configure(text="Увійти")
        self.say("")
        self.say(f"Дія: {why}", "head")
        self.after(200, self._audit_show)
        self._refresh_status()

    def _command(self, request, title):
        """One action: send it, show the verdict, show what it left in the journal."""
        if not self.sock:
            self.say("Спершу увійдіть у систему.", "bad")
            return None
        self._audit_mark()
        self.say("")
        self.say(f"Дія: {title}", "head")
        try:
            netproto.send(self.sock, request)
            response = netproto.recv(self.sock)
        except (OSError, netproto.ProtocolError) as exc:
            self.say(f"з'єднання втрачено: {exc}", "bad")
            self.sock = None
            self.btn_login.configure(text="Увійти")
            self._refresh_status()
            return None

        allowed = response.get("status") == "ok"
        self.say(("ДОЗВОЛЕНО: " if allowed else "ВІДХИЛЕНО: ") + str(response.get("message")),
                 "ok" if allowed else "bad")
        if response.get("text"):
            for line in response["text"].splitlines():
                self.say("    " + line, "muted")
        self.after(150, self._audit_show)
        return response

    def do_object(self, op):
        obj = self.var_object.get()
        request = {"op": op, "object": obj}
        titles = {"read": f"прочитати об'єкт «{obj}»",
                  "write": f"дописати в об'єкт «{obj}»",
                  "delete": f"видалити об'єкт «{obj}»",
                  "create": f"створити об'єкт «{obj}»"}
        if op in ("write", "create"):
            request["text"] = self.var_text.get()
        self._command(request, titles[op])
        if op in ("create", "delete"):
            self.after(300, self._refresh_objects)

    def do_rights(self, op):
        obj, target, right = self.var_object.get(), self.var_target.get(), self.var_right.get()
        verb = "надати" if op == "grant" else "відкликати"
        self._command({"op": op, "object": obj, "subject": target, "right": right},
                      f"{verb} право «{right}» на «{obj}» суб'єктові «{target}»")

    def do_plain(self, op):
        titles = {"audit": "прочитати журнал аудиту",
                  "caps": "переглянути власні повноваження",
                  "list": "переглянути перелік об'єктів"}
        request = {"op": op}
        if op == "audit":
            request["count"] = 10
        self._command(request, titles[op])

    def _refresh_objects(self):
        """Fill the object chooser from what the server actually holds."""
        if not self.sock:
            return
        try:
            netproto.send(self.sock, {"op": "list"})
            response = netproto.recv(self.sock)
        except (OSError, netproto.ProtocolError):
            return
        names = [ln.split()[0] for ln in (response.get("text") or "").splitlines() if ln.strip()]
        if not names:
            return
        menu = self.menu_object["menu"]
        menu.delete(0, "end")
        for name in names:
            menu.add_command(label=name, command=lambda v=name: self.var_object.set(v))
        if self.var_object.get() not in names:
            self.var_object.set(names[0])

    # ------------------------------------------------- servers for the VM run

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
                     "--db", os.path.join(HERE, "lab_6", "server_db.json"),
                     "--audit", JOURNAL, "--auditor", AUDITOR],
                    cwd=cwd, creationflags=subprocess.CREATE_NO_WINDOW)
                self.servers.append(p)
            ip = host_address()
            self.write("Сервери запущено на 0.0.0.0", "head")
            self.write(f"  лабораторна 6 — {ip}:{LAB6_PORT}", "accent")
            self.write(f"  лабораторна 7 — {ip}:{LAB7_PORT}", "accent")
            self.write("  у віртуальній машині запустіть CLIENT_TO_HOST.bat", "muted")
        self._refresh_status()

    # ----------------------------------------------------------- status line

    def _refresh_status(self):
        try:
            drives = token.find_removable_drives()
        except Exception:
            drives = []
        where = drives[0] if drives else "тека-замінник"
        running = bool(self.servers) or port_is_open(LAB6_PORT)
        self.buttons["servers"].configure(
            text="Зупинити сервери" if self.servers else "Запустити сервери")

        session = f"сесія: {self.live_user}" if self.sock else "сесія: немає"
        self.status.configure(
            text=f"Токен: {where}\nСервери: {'працюють' if running else 'зупинено'}\n"
                 f"{session}\nАдреса хоста: {host_address()}")
        self.after(2000, self._refresh_status)

    def destroy(self):
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass
        for p in list(self.servers) + ([self.live_server] if self.live_server else []):
            try:
                p.terminate()
            except Exception:
                pass
        super().destroy()


if __name__ == "__main__":
    Console().mainloop()
