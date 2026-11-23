"""RPX-PLC Flasher: installa via USB il firmware RPX-PLC pubblicato (o un file locale) e mostra la console della scheda.

Il firmware arriva dal repository pubblico ReplayTechSolution/RPX-PLC-firmware: manifest.json della release scelta
(versione, SHA-256 e dimensione dell'immagine completa rpx-plc-factory.bin = bootloader + partizioni + applicazione,
da scrivere all'indirizzo 0). L'immagine viene controllata prima di toccare la scheda.
Programma, progetto e configurazione restano nella scheda; solo "Cancella tutto" li toglie.
Adattato dal flasher di LIZA-SYS IO.   Da sorgente:  py -3 rpx_flasher.py    Eseguibile: build.ps1

Copyright (C) 2026 Replay Tech Solution

This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation; either version 2 of the License, or (at your option) any later
version. This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the
implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
(COPYING.txt) for more details. Il programma usa esptool (GPL v2 o successiva) per scrivere la memoria della scheda.
Sorgente: https://github.com/ReplayTechSolution/RPX-PLC-firmware/tree/main/flasher
"""

import contextlib
import hashlib
import io
import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from tkinter import filedialog, messagebox, ttk

import serial
import serial.tools.list_ports

APP = "RPX-PLC Flasher"
APP_VER = "1.1.1"
REPO = os.environ.get("RPX_RELEASE_REPO", "ReplayTechSolution/RPX-PLC-firmware")
BASE = f"https://github.com/{REPO}/releases"
API_RELEASES = f"https://api.github.com/repos/{REPO}/releases?per_page=50"
SITE = "https://replaytechsolution.github.io/RPX-PLC-firmware/"
ESPRESSIF_VID = 0x303A  # USB integrata dell'ESP32-S3: la porta USB-C della scheda
USB_UART_VIDS = {0x1A86, 0x10C4, 0x0403}
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
RX_ETH = re.compile(r"Ethernet: (\d+\.\d+\.\d+\.\d+)")
RX_WIFI = re.compile(r"Wi-Fi: (\d+\.\d+\.\d+\.\d+)")
RX_AP = re.compile(r"Access point (\S+)\s+http://([\d.]+)/")
RX_VER = re.compile(r"RPX-PLC (\d+\.\d+\.\d+\S*) su")
RX_PCT = re.compile(r"\((\d+)\s*%\)")
MON_MAX = 5000

# colori: tema scuro dell'ambiente di ingegneria, verde e rosso del marchio Replay
C = {"bg": "#12171c", "surface": "#1a2128", "surface2": "#222b33", "border": "#33404c", "text": "#e6eaee", "muted": "#9aa6b1",
     "accent": "#0b8a43", "accent_hi": "#13a855", "red": "#e01a2f", "ok": "#34c77b", "warn": "#f0a33a", "err": "#f06060", "console": "#0c1013"}
FONT, MONO = "Segoe UI", "Consolas"


def asset(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name)


def fetch(url, timeout=30):
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(f"{url}{sep}t={int(time.time())}" if url.endswith(".json") else url,
                                 headers={"User-Agent": f"RPX-PLC-Flasher/{APP_VER}", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def ver_key(v):
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)(?:-([a-z]+)\.?(\d+)?)?", v or "")
    if not m:
        return (0, 0, 0, 0, 0)
    pre = {"alpha": 1, "beta": 2, "rc": 3}.get(m.group(4), 9) if m.group(4) else 10
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), pre, int(m.group(5) or 0))


def port_label(p):
    desc = re.sub(r"\s*\(COM\d+\)$", "", p.description if p.description and p.description != "n/a" else "")
    return f"{p.device}  ·  {'Scheda RPX-PLC (USB-C)' if p.vid == ESPRESSIF_VID else desc or 'porta seriale'}"


class QueueWriter(io.TextIOBase):
    """stdout di esptool -> finestra"""

    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(("log", s))
        return len(s)

    def flush(self):
        pass


class Btn(tk.Label):
    """Pulsante piatto (ttk non permette i colori su Windows)."""

    def __init__(self, parent, text, command, kind="normal", big=False, **kw):
        self.kind, self.command, self.enabled = kind, command, True
        super().__init__(parent, text=text, cursor="hand2", font=(FONT, 12 if big else 10, "bold" if big or kind == "primary" else "normal"),
                         padx=24 if big else 12, pady=9 if big else 5, bd=0, highlightthickness=1, **kw)
        self.bind("<Enter>", lambda e: self._paint(True))
        self.bind("<Leave>", lambda e: self._paint(False))
        self.bind("<Button-1>", lambda e: self.enabled and self.command and self.command())
        self._paint(False)

    def _paint(self, hover):
        if not self.enabled:
            bg, fg, bd = C["surface2"], C["muted"], C["border"]
        elif self.kind == "primary":
            bg, fg, bd = (C["accent_hi"] if hover else C["accent"]), "#ffffff", C["accent"]
        else:
            bg, fg, bd = (C["border"] if hover else C["surface2"]), C["text"], C["border"]
        self.configure(bg=bg, fg=fg, highlightbackground=bd, highlightcolor=bd)

    def set(self, enabled=None, text=None):
        if enabled is not None:
            self.enabled = enabled
            self.configure(cursor="hand2" if enabled else "arrow")
        if text is not None:
            self.configure(text=text)
        self._paint(False)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP} {APP_VER}")
        self.configure(bg=C["bg"])
        self.geometry("980x720")
        self.minsize(820, 600)
        with contextlib.suppress(Exception):
            self.iconbitmap(asset("app.ico"))
        self.q = queue.Queue()
        self.ports = []
        self.manifest = None      # versione scelta: manifest della release
        self.local_file = None    # oppure un file .bin dal PC
        self.busy = False
        self.mon_on = False
        self.mon = None
        self.mon_lines = 0
        self.erase = tk.BooleanVar(value=False)
        self.autoscroll = tk.BooleanVar(value=True)
        self.access = {}
        self._style()
        self._build()
        self._scan_ports()
        self.after(80, self._pump)
        self.load_latest()

    # ---------------- interfaccia ----------------
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TCombobox", fieldbackground=C["surface2"], background=C["surface2"], foreground=C["text"], arrowcolor=C["text"],
                    bordercolor=C["border"], lightcolor=C["border"], darkcolor=C["border"])
        s.map("TCombobox", fieldbackground=[("readonly", C["surface2"])], foreground=[("readonly", C["text"])])
        self.option_add("*TCombobox*Listbox.background", C["surface2"])
        self.option_add("*TCombobox*Listbox.foreground", C["text"])
        s.configure("G.Horizontal.TProgressbar", troughcolor=C["surface2"], background=C["accent"], bordercolor=C["border"],
                    lightcolor=C["accent"], darkcolor=C["accent"])

    def lbl(self, parent, text, muted=False, size=10, bold=False, **kw):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=C["muted"] if muted else C["text"], font=(FONT, size, "bold" if bold else "normal"), **kw)

    def card(self, parent, step, title):
        f = tk.Frame(parent, bg=C["surface"], highlightthickness=1, highlightbackground=C["border"], padx=14, pady=10)
        h = tk.Frame(f, bg=C["surface"])
        h.pack(fill="x")
        tk.Label(h, text=step, bg=C["accent"], fg="#fff", font=(FONT, 10, "bold"), width=2).pack(side="left")
        self.lbl(h, title, size=11, bold=True).pack(side="left", padx=8)
        return f

    def _build(self):
        top = tk.Frame(self, bg="#0b0f12", padx=16, pady=10)
        top.pack(fill="x")
        logo = tk.Canvas(top, width=26, height=26, bg="#0b0f12", highlightthickness=0)
        logo.create_polygon(4, 3, 24, 13, 4, 23, fill=C["accent"])
        logo.pack(side="left")
        tk.Label(top, text="RPX", bg="#0b0f12", fg="#fff", font=(FONT, 16, "bold")).pack(side="left", padx=(6, 0))
        tk.Label(top, text="-PLC  Flasher", bg="#0b0f12", fg="#fff", font=(FONT, 16)).pack(side="left")
        tk.Label(top, text="Replay Tech Solution · installazione del firmware via USB", bg="#0b0f12", fg=C["muted"], font=(FONT, 9)).pack(side="right")
        bar = tk.Canvas(self, height=4, bg=C["bg"], highlightthickness=0)
        bar.pack(fill="x")
        bar.bind("<Configure>", lambda e: (bar.delete("all"), [bar.create_rectangle(e.width * i / 3, 0, e.width * (i + 1) / 3, 4, fill=c, width=0)
                                                               for i, c in enumerate((C["accent"], "#ffffff", C["red"]))]))

        body = tk.Frame(self, bg=C["bg"], padx=14, pady=12)
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg=C["bg"], width=380)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        right = tk.Frame(body, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))

        # 1. scheda
        c1 = self.card(left, "1", "Scheda")
        c1.pack(fill="x")
        self.lbl(c1, "Collega la scheda al PC con il cavo USB-C.", muted=True, wraplength=340, justify="left").pack(anchor="w", pady=(6, 4))
        row = tk.Frame(c1, bg=C["surface"])
        row.pack(fill="x")
        self.port_var = tk.StringVar()
        self.port_cb = ttk.Combobox(row, textvariable=self.port_var, state="readonly", font=(FONT, 10))
        self.port_cb.pack(side="left", fill="x", expand=True)
        Btn(row, "Aggiorna", self._scan_ports).pack(side="left", padx=(6, 0))
        self.port_info = self.lbl(c1, "", muted=True, wraplength=340, justify="left")
        self.port_info.pack(anchor="w", pady=(4, 0))

        # 2. versione
        c2 = self.card(left, "2", "Firmware")
        c2.pack(fill="x", pady=10)
        self.ver_lbl = self.lbl(c2, "Ricerca dell'ultima versione…", wraplength=340, justify="left")
        self.ver_lbl.pack(anchor="w", pady=(6, 2))
        self.notes_lbl = self.lbl(c2, "", muted=True, size=9, wraplength=340, justify="left")
        self.notes_lbl.pack(anchor="w")
        row2 = tk.Frame(c2, bg=C["surface"])
        row2.pack(fill="x", pady=(6, 0))
        Btn(row2, "Altre versioni…", self.choose_version).pack(side="left")
        Btn(row2, "File dal PC…", self.choose_file).pack(side="left", padx=6)
        self.manual_btn = Btn(c2, "Manuale di questa versione", self.download_manual)
        self.manual_btn.pack(anchor="w", pady=(6, 0))
        self.manual_btn.set(enabled=False)

        # 3. installazione
        c3 = self.card(left, "3", "Installazione")
        c3.pack(fill="x")
        tk.Checkbutton(c3, text="Cancella tutto (impostazioni di fabbrica:\nprogramma, progetto e configurazione)", variable=self.erase, justify="left",
                       bg=C["surface"], fg=C["warn"], selectcolor=C["surface2"], activebackground=C["surface"], activeforeground=C["warn"],
                       font=(FONT, 9)).pack(anchor="w", pady=(6, 6))
        self.install_btn = Btn(c3, "Installa sulla scheda", self.install, kind="primary", big=True)
        self.install_btn.pack(fill="x")
        self.progress = ttk.Progressbar(c3, style="G.Horizontal.TProgressbar", maximum=100)
        self.progress.pack(fill="x", pady=(8, 2))
        self.step_lbl = self.lbl(c3, "", muted=True, size=9, wraplength=340, justify="left")
        self.step_lbl.pack(anchor="w")

        # accesso al PLC (dalla console)
        c4 = self.card(left, "✓", "Accesso al PLC")
        c4.pack(fill="x", pady=10)
        self.access_box = tk.Frame(c4, bg=C["surface"])
        self.access_box.pack(fill="x", pady=(6, 0))
        self.lbl(self.access_box, "Gli indirizzi compaiono qui quando la scheda si avvia (console accesa).", muted=True, size=9, wraplength=340, justify="left").pack(anchor="w")

        # console
        head = tk.Frame(right, bg=C["bg"])
        head.pack(fill="x")
        self.lbl(head, "Console della scheda", bold=True, size=11).pack(side="left")
        self.mon_state = self.lbl(head, "● spenta", muted=True, size=9)
        self.mon_state.pack(side="left", padx=10)
        Btn(head, "Salva…", self.mon_save).pack(side="right")
        Btn(head, "Pulisci", self.mon_clear).pack(side="right", padx=6)
        self.mon_btn = Btn(head, "Accendi", self.toggle_monitor)
        self.mon_btn.pack(side="right")
        tk.Checkbutton(head, text="segui", variable=self.autoscroll, bg=C["bg"], fg=C["muted"], selectcolor=C["surface2"],
                       activebackground=C["bg"], font=(FONT, 9)).pack(side="right", padx=6)
        wrap = tk.Frame(right, bg=C["border"], padx=1, pady=1)
        wrap.pack(fill="both", expand=True, pady=(6, 0))
        self.txt = tk.Text(wrap, bg=C["console"], fg="#cfd8df", insertbackground="#fff", font=(MONO, 9), bd=0, wrap="none", state="disabled", padx=8, pady=6)
        sb = ttk.Scrollbar(wrap, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(fill="both", expand=True)
        for tag, col in (("ok", C["ok"]), ("err", C["err"]), ("warn", C["warn"]), ("sys", C["accent_hi"]), ("E", C["err"]), ("W", C["warn"]), ("I", "#8fd19e")):
            self.txt.tag_configure(tag, foreground=col)
        foot = tk.Frame(self, bg=C["bg"], padx=14, pady=6)
        foot.pack(fill="x")
        link = self.lbl(foot, "Manuale e versioni pubblicate", size=9)
        link.configure(fg=C["accent_hi"], cursor="hand2")
        link.bind("<Button-1>", lambda e: webbrowser.open(SITE))
        link.pack(side="left")
        self.lbl(foot, f"{APP} {APP_VER}", muted=True, size=9).pack(side="right")
        lic = self.lbl(foot, "Licenze (GPL) e sorgente", size=9)
        lic.configure(fg=C["accent_hi"], cursor="hand2")
        lic.bind("<Button-1>", lambda e: self.show_licenses())
        lic.pack(side="right", padx=14)

    def show_licenses(self):
        """Avviso di licenza (GPL v2 o successiva), sorgente e licenze dei componenti inclusi nell'eseguibile."""
        w = tk.Toplevel(self)
        w.title(f"{APP} - licenze")
        w.geometry("820x560")
        head = (f"{APP} {APP_VER}  -  Copyright (C) 2026 Replay Tech Solution\n"
                "Software libero: GNU General Public License versione 2 o (a tua scelta) successiva, SENZA ALCUNA GARANZIA.\n"
                "Sorgente: https://github.com/ReplayTechSolution/RPX-PLC-firmware/tree/main/flasher\n\n")
        t = tk.Text(w, wrap="none", font=(MONO, 9), padx=8, pady=6)
        sb = ttk.Scrollbar(w, command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(fill="both", expand=True)
        body = head
        for name in ("LICENZE.txt", "COPYING.txt"):
            with contextlib.suppress(OSError), open(asset(name), encoding="utf-8") as f:
                body += f.read() + "\n\n"
        t.insert("1.0", body)
        t.configure(state="disabled")

    # ---------------- messaggi dai thread ----------------
    def say(self, text, tag=None):
        self.q.put(("say", (text, tag)))

    def _pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "say":
                    self._write(val[0] + "\n", val[1])
                elif kind == "log":  # esptool: avanzamento in percentuale
                    for part in re.split(r"[\r\n]+", val):
                        if not part.strip():
                            continue
                        m = RX_PCT.search(part)
                        if m and "Writing" in part:
                            self.progress["value"] = int(m.group(1))
                            self.step_lbl.configure(text=f"Scrittura: {m.group(1)}%")
                            continue
                        self._write(part.strip() + "\n")
                elif kind == "mon":
                    self._write(val, None, console=True)
                elif kind == "step":
                    self.step_lbl.configure(text=val)
                elif kind == "latest":
                    self._show_version(*val)
                elif kind == "done":
                    self._install_done(val)
                elif kind == "monstate":
                    self.mon_state.configure(text=val[0], fg=val[1])
                elif kind == "access":
                    self.access.update(val)
                    self._show_access()
                elif kind == "versions":
                    self._versions_dialog(val)
                elif kind == "manualdone":
                    self.manual_btn.set(enabled=bool(self.manifest), text=f"Manuale della versione {self.manifest['version']}" if self.manifest else "Manuale di questa versione")
        except queue.Empty:
            pass
        self.after(80, self._pump)

    def _write(self, s, tag=None, console=False):
        t = self.txt
        t.configure(state="normal")
        if console and tag is None:
            tag = "sys" if s.startswith("— ") else s[:1] if s[:2] in ("E ", "W ", "I ") else None
        t.insert("end", s, tag)
        self.mon_lines += s.count("\n")
        if self.mon_lines > MON_MAX:
            t.delete("1.0", f"{self.mon_lines - MON_MAX + 1}.0")
            self.mon_lines = MON_MAX
        if self.autoscroll.get():
            t.see("end")
        t.configure(state="disabled")

    # ---------------- porte ----------------
    def _scan_ports(self):
        self.ports = sorted(serial.tools.list_ports.comports(), key=lambda p: (p.vid != ESPRESSIF_VID, p.device))
        labels = [port_label(p) for p in self.ports]
        self.port_cb["values"] = labels
        if labels and (not self.port_var.get() or self.port_var.get() not in labels):
            self.port_var.set(labels[0])
        if not labels:
            self.port_var.set("")
        board = any(p.vid == ESPRESSIF_VID for p in self.ports)
        self.port_info.configure(text="Scheda trovata." if board else "Nessuna scheda RPX-PLC: controlla il cavo USB-C (deve essere un cavo dati).",
                                 fg=C["ok"] if board else C["warn"])

    def port_name(self):
        v = self.port_var.get()
        return v.split()[0] if v else None

    # ---------------- versioni ----------------
    def load_latest(self):
        def work():
            try:
                m = json.loads(fetch(f"{BASE}/latest/download/manifest.json"))
                self.q.put(("latest", (m, None)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("latest", (None, f"Versioni non raggiungibili ({e}). Serve Internet, oppure usa «File dal PC»." )))
        threading.Thread(target=work, daemon=True).start()

    def _show_version(self, m, err):
        if err:
            self.ver_lbl.configure(text=err, fg=C["warn"])
            return
        self.manifest, self.local_file = m, None
        self.manual_btn.set(enabled=True, text=f"Manuale della versione {m['version']}")
        d = m.get("date", "")
        d = "/".join(reversed(d.split("-"))) if d else ""
        self.ver_lbl.configure(text=f"Versione {m['version']}" + (f" del {d}" if d else ""), fg=C["text"], font=(FONT, 11, "bold"))
        self.notes_lbl.configure(text=m.get("notes", ""))
        if not m.get("factory_sha256"):
            self.notes_lbl.configure(text=(m.get("notes", "") + "\n(immagine senza impronta SHA-256: si controlla solo la dimensione)").strip())

    def choose_version(self):
        def work():
            try:
                rel = json.loads(fetch(API_RELEASES))
                vs = [r["tag_name"].lstrip("v") for r in rel if r["tag_name"].startswith("v") and not r.get("draft")
                      and any(a["name"] == "rpx-plc-factory.bin" for a in r.get("assets", []))]
                self.q.put(("versions", sorted(vs, key=ver_key, reverse=True)))
            except Exception as e:  # noqa: BLE001
                self.say(f"✖ Elenco delle versioni non disponibile: {e}", "err")
        threading.Thread(target=work, daemon=True).start()

    def _versions_dialog(self, vs):
        if not vs:
            messagebox.showinfo(APP, "Nessuna versione pubblicata.")
            return
        w = tk.Toplevel(self, bg=C["surface"], padx=16, pady=14)
        w.title("Versioni pubblicate")
        w.transient(self)
        self.lbl(w, "Scegli la versione da installare:").pack(anchor="w")
        lb = tk.Listbox(w, bg=C["surface2"], fg=C["text"], selectbackground=C["accent"], font=(FONT, 10), height=min(12, len(vs)), bd=0)
        for v in vs:
            lb.insert("end", v)
        lb.selection_set(0)
        lb.pack(fill="both", pady=8)

        def use():
            v = lb.get(lb.curselection()[0]) if lb.curselection() else None
            w.destroy()
            if not v:
                return
            def work():
                try:
                    m = json.loads(fetch(f"{BASE}/download/v{v}/manifest.json"))
                    self.q.put(("latest", (m, None)))
                except Exception as e:  # noqa: BLE001
                    self.say(f"✖ Manifest della versione {v} non disponibile: {e}", "err")
            threading.Thread(target=work, daemon=True).start()
        Btn(w, "Usa questa versione", use, kind="primary").pack(fill="x")

    def choose_file(self):
        path = filedialog.askopenfilename(title="Immagine del firmware", filetypes=[("Immagine completa RPX-PLC", "*.bin"), ("Tutti i file", "*.*")])
        if not path:
            return
        with open(path, "rb") as f:
            head = f.read(4)
        if head[:1] != b"\xe9":
            messagebox.showerror(APP, "Il file non è un'immagine per ESP32.")
            return
        size = os.path.getsize(path)
        if size < 0x30000:
            messagebox.showerror(APP, "Serve l'immagine completa (rpx-plc-factory.bin, con bootloader e partizioni),\nnon il file dell'aggiornamento via rete (rpx-plc.bin).")
            return
        self.local_file, self.manifest = path, None
        self.manual_btn.set(enabled=False, text="Manuale di questa versione")
        self.ver_lbl.configure(text=f"File: {os.path.basename(path)}", fg=C["text"], font=(FONT, 11, "bold"))
        self.notes_lbl.configure(text=f"{size // 1024} kB, dal PC")

    # ---------------- manuale ----------------
    def download_manual(self):
        """Scarica nella cartella Download il manuale allegato alla release della versione scelta e lo apre."""
        m = self.manifest
        if not m:
            return
        ver = m["version"]
        names = [m["manual"]] if m.get("manual") else [f"RPX-PLC-Manuale-{ver}.pdf", f"RPX-PLC-Manuale-{ver}.html"]
        self.manual_btn.set(enabled=False, text="Scarico il manuale…")

        def work():
            err = None
            for name in names:
                try:
                    data = fetch(f"{BASE}/download/v{ver}/{name}", timeout=120)
                except Exception as e:  # noqa: BLE001 - si prova il nome successivo
                    err = e
                    continue
                folder = os.path.join(os.path.expanduser("~"), "Downloads")
                if not os.path.isdir(folder):
                    folder = os.path.expanduser("~")
                path = os.path.join(folder, name)
                with open(path, "wb") as f:
                    f.write(data)
                self.say(f"✔ Manuale della versione {ver} salvato in {path}", "ok")
                with contextlib.suppress(Exception):
                    os.startfile(path)
                break
            else:
                self.say(f"✖ Manuale della versione {ver} non disponibile ({err}).", "err")
            self.q.put(("manualdone", ver))
        threading.Thread(target=work, daemon=True).start()

    # ---------------- installazione ----------------
    def install(self):
        if self.busy:
            return
        port = self.port_name()
        if not port:
            messagebox.showwarning(APP, "Collega la scheda e scegli la porta.")
            return
        if not self.manifest and not self.local_file:
            messagebox.showwarning(APP, "Nessun firmware scelto: serve Internet o un file dal PC.")
            return
        what = self.local_file and os.path.basename(self.local_file) or f"la versione {self.manifest['version']}"
        if self.erase.get():
            if not messagebox.askyesno(APP, f"Installo {what} e CANCELLO tutto: programma, progetto, configurazione e dati a ritenzione.\n"
                                            "La scheda torna alle impostazioni di fabbrica. Continuare?", icon="warning"):
                return
        elif not messagebox.askyesno(APP, f"Installo {what} sulla scheda in {port}.\nProgramma, progetto e configurazione restano. Continuare?"):
            return
        restart_mon = self.mon_on
        if self.mon_on:
            self.stop_monitor()
        self.busy = True
        self.install_btn.set(enabled=False, text="Installazione in corso…")
        self.progress["value"] = 0
        threading.Thread(target=self._install_work, args=(port, self.erase.get(), restart_mon), daemon=True).start()

    def _install_work(self, port, erase, restart_mon):
        ok = False
        try:
            if self.local_file:
                path, label = self.local_file, os.path.basename(self.local_file)
            else:
                m = self.manifest
                label = f"versione {m['version']}"
                tmp = os.path.join(tempfile.gettempdir(), "rpx-plc-flasher", m["version"])
                os.makedirs(tmp, exist_ok=True)
                path = os.path.join(tmp, "rpx-plc-factory.bin")
                want_sha, want_size = m.get("factory_sha256"), m.get("factory_size")
                good = lambda d: (not want_sha or hashlib.sha256(d).hexdigest() == want_sha) and (not want_size or len(d) == want_size)
                data = open(path, "rb").read() if os.path.exists(path) else None
                if data is None or not good(data):
                    self.q.put(("step", "Scarico l'immagine del firmware…"))
                    self.say(f"Scarico rpx-plc-factory.bin della versione {m['version']}…")
                    data = fetch(f"{BASE}/download/v{m['version']}/rpx-plc-factory.bin", timeout=180)
                    if not good(data):
                        raise RuntimeError("il file scaricato non corrisponde al manifest (SHA-256). Installazione annullata, la scheda non è stata toccata.")
                    with open(path, "wb") as f:
                        f.write(data)
                self.say("Immagine verificata (SHA-256)." if want_sha else "Immagine scaricata.", "ok")
            self.q.put(("step", "Scrittura sulla scheda… non scollegare il cavo."))
            self.say(f"— Scrittura di {label} su {port}{' con cancellazione totale' if erase else ''}", "sys")
            import esptool  # caricato solo qui: la finestra si apre prima

            cmd = ["--chip", "esp32s3", "--port", port, "--baud", "921600", "--before", "default-reset", "--after", "hard-reset",
                   "write-flash", "-z"] + (["--erase-all"] if erase else []) + ["0x0", path]
            w = QueueWriter(self.q)
            with contextlib.redirect_stdout(w), contextlib.redirect_stderr(w):
                try:
                    esptool.main(cmd)
                    ok = True
                except SystemExit as e:
                    ok = not e.code
                except Exception as e:  # noqa: BLE001 - esptool.FatalError e simili
                    print(f"\n{e}")
            if ok:
                self.say(f"✔ {label} installata. La scheda si riavvia.", "ok")
            else:
                self.say("✖ Installazione non riuscita. Controlla il cavo e la porta; chiudi i programmi che usano le porte seriali. "
                         "Se la scheda non risponde: tieni premuto BOOT, premi e rilascia RESET, rilascia BOOT e riprova.", "err")
        except Exception as e:  # noqa: BLE001
            self.say(f"✖ {e}", "err")
        self.q.put(("done", (ok, restart_mon)))

    def _install_done(self, val):
        ok, restart_mon = val
        self.busy = False
        self.progress["value"] = 100 if ok else 0
        self.step_lbl.configure(text="Fatto: la console mostra l'avvio della scheda." if ok else "Non riuscita.")
        self.install_btn.set(enabled=True, text="Installa sulla scheda")
        if ok or restart_mon:
            self.access = {}
            self._show_access()
            self.after(600, self.start_monitor)  # si segue l'avvio per leggere gli indirizzi

    # ---------------- console ----------------
    def toggle_monitor(self):
        self.stop_monitor() if self.mon_on else self.start_monitor()

    def start_monitor(self):
        port = self.port_name()
        if not port or self.mon_on:
            return
        self.mon_on = True
        self.mon_btn.set(text="Spegni")
        threading.Thread(target=self._mon_work, args=(port,), daemon=True).start()

    def stop_monitor(self):
        self.mon_on = False
        self.mon_btn.set(text="Accendi")
        self.mon_state.configure(text="● spenta", fg=C["muted"])
        if self.mon:
            with contextlib.suppress(Exception):
                self.mon.close()

    def _mon_work(self, port):
        buf = b""
        while self.mon_on:
            try:
                s = serial.Serial()
                s.port, s.baudrate, s.timeout = port, 115200, 0.1
                s.dtr = s.rts = False  # aprire la porta non deve riavviare la scheda
                s.open()
                self.mon = s
                self.q.put(("monstate", (f"● collegata a {port}", C["ok"])))
                self.q.put(("mon", f"— console su {port}\n"))
                while self.mon_on:
                    data = s.read(4096)
                    if not data:
                        continue
                    buf += data
                    *lines, buf = buf.split(b"\n")
                    for ln in lines:
                        t = ANSI.sub("", ln.decode("utf-8", "replace")).rstrip("\r")
                        self._scan(t)
                        self.q.put(("mon", t + "\n"))
            except Exception:  # noqa: BLE001 - scheda in riavvio o scollegata: si riprova
                if self.mon_on:
                    self.q.put(("monstate", (f"● in attesa di {port}…", C["warn"])))
            finally:
                if self.mon:
                    with contextlib.suppress(Exception):
                        self.mon.close()
                    self.mon = None
            if self.mon_on:
                time.sleep(0.3)

    def _scan(self, t):
        if m := RX_VER.search(t):
            self.q.put(("access", {"ver": m.group(1)}))
        if m := RX_ETH.search(t):
            self.q.put(("access", {"eth": m.group(1)}))
        if m := RX_WIFI.search(t):
            self.q.put(("access", {"wifi": m.group(1)}))
        if m := RX_AP.search(t):
            self.q.put(("access", {"ap": (m.group(1), m.group(2))}))

    def _show_access(self):
        for w in self.access_box.winfo_children():
            w.destroy()
        a = self.access
        if not a:
            self.lbl(self.access_box, "Gli indirizzi compaiono qui quando la scheda si avvia (console accesa).", muted=True, size=9,
                     wraplength=340, justify="left").pack(anchor="w")
            return
        if a.get("ver"):
            self.lbl(self.access_box, f"Firmware in funzione: {a['ver']}", size=9).pack(anchor="w")

        def link(text, url):
            r = tk.Frame(self.access_box, bg=C["surface"])
            r.pack(fill="x", pady=2)
            self.lbl(r, text, size=9).pack(side="left")
            Btn(r, "Apri", lambda: webbrowser.open(url)).pack(side="right")
        if a.get("eth"):
            link(f"Ethernet: http://{a['eth']}/", f"http://{a['eth']}/")
        if a.get("wifi"):
            link(f"WiFi: http://{a['wifi']}/", f"http://{a['wifi']}/")
        if a.get("ap"):
            ssid, ip = a["ap"]
            link(f"Access point «{ssid}» (password rpx-plc-setup se non cambiata): http://{ip}/", f"http://{ip}/")

    def mon_clear(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")
        self.mon_lines = 0

    def mon_save(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile=f"rpx-plc-console-{time.strftime('%Y%m%d-%H%M%S')}.txt",
                                            filetypes=[("Testo", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt.get("1.0", "end"))


def selftest(path):
    """Controllo dell'eseguibile: esptool, i suoi stub e le immagini ci sono. Scrive l'esito in path."""
    out = io.StringIO()
    ok = all(os.path.exists(asset(n)) for n in ("app.ico", "COPYING.txt", "LICENZE.txt"))
    try:
        import esptool
        import esptool.targets  # noqa: F401

        with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
            esptool.main(["version"])
        ok = ok and esptool.__version__ in out.getvalue()
    except Exception as e:  # noqa: BLE001
        out.write(repr(e))
        ok = False
    with open(path, "w", encoding="utf-8") as f:
        f.write(("OK " if ok else "ERRORE ") + out.getvalue().strip())
    return 0 if ok else 1


def main():
    if os.environ.get("RPX_FLASHER_SELFTEST"):
        return selftest(os.environ["RPX_FLASHER_SELFTEST"])
    with contextlib.suppress(Exception):  # nitidezza sugli schermi ad alta risoluzione
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    app = App()

    def close():
        if app.busy and not messagebox.askyesno(APP, "Installazione in corso: chiudere lo stesso? La scheda potrebbe restare senza firmware."):
            return
        app.stop_monitor()
        app.destroy()
    app.protocol("WM_DELETE_WINDOW", close)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
