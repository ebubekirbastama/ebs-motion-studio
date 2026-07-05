import os
import sys
import re
import json
import time
import math
import shutil
import tempfile
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except Exception:
    HAS_PIL = False

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    BaseTk = TkinterDnD.Tk
    HAS_DND = True
except Exception:
    BaseTk = tk.Tk
    DND_FILES = None
    HAS_DND = False

APP_TITLE = "Video Studio PRO v6.3 Gold"
APP_VERSION = "6.4-obs-style-crop"
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
FORMATS = {
    "Instagram Gönderi 1:1": (1080, 1080),
    "Instagram Story 9:16": (1080, 1920),
    "YouTube Shorts 9:16": (1080, 1920),
    "Full HD 16:9": (1920, 1080),
}

COLORS = {
    "bg": "#070b14", "panel": "#101827", "panel2": "#151f32", "stroke": "#26344e",
    "text": "#e8eef8", "muted": "#8ea0bd", "accent": "#ff2d55", "accent2": "#2563eb",
    "canvas_bg": "#111827", "danger": "#dc2626",
    "gold1": "#f6c453", "gold2": "#b7791f", "gold3": "#7c4a03"
}


def tool_exists(name):
    return shutil.which(name) is not None


def check_ffmpeg():
    if not tool_exists("ffmpeg") or not tool_exists("ffprobe"):
        raise RuntimeError("FFmpeg/FFprobe bulunamadı. FFmpeg'i PATH'e ekleyin.")


def slugify(name):
    name = os.path.splitext(os.path.basename(name))[0].lower()
    tr = str.maketrans("çğıöşüİÇĞÖŞÜ", "cgiosuICGOSU")
    name = name.translate(tr)
    name = re.sub(r"[^a-z0-9]+", "_", name).strip("_")
    return name or "video"


def ffprobe_duration(path):
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path
        ], text=True, encoding="utf-8", errors="ignore")
        return float(json.loads(out).get("format", {}).get("duration", 0) or 0)
    except Exception:
        return 0.0


def ffprobe_size(path):
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", path
        ], text=True, encoding="utf-8", errors="ignore")
        s = json.loads(out).get("streams", [{}])[0]
        return int(s.get("width", 0) or 0), int(s.get("height", 0) or 0)
    except Exception:
        return 0, 0


def has_audio(path):
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "csv=p=0", path
        ], text=True, encoding="utf-8", errors="ignore").strip()
        return bool(out)
    except Exception:
        return False


def quote_arg(x):
    s = str(x)
    return '"' + s + '"' if " " in s else s


def run_cmd(cmd, log, stop_event=None):
    log(" ".join(quote_arg(x) for x in cmd) + "\n")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         text=True, encoding="utf-8", errors="ignore", creationflags=flags)
    try:
        for line in p.stdout:
            if stop_event and stop_event.is_set():
                try:
                    p.terminate()
                except Exception:
                    pass
                raise RuntimeError("İşlem durduruldu.")
            low = line.lower()
            if any(k in low for k in ("frame=", "time=", "speed=", "error", "failed", "invalid")):
                log(line)
    finally:
        if p.stdout:
            p.stdout.close()
    code = p.wait()
    if code != 0:
        raise RuntimeError(f"FFmpeg hata verdi. Çıkış kodu: {code}")


class Layer:
    _next = 1
    def __init__(self, path, kind, project_w, project_h):
        self.id = Layer._next; Layer._next += 1
        self.path = path
        self.kind = kind  # video/image
        self.name = os.path.basename(path)
        iw, ih = (ffprobe_size(path) if kind == "video" else self.image_size(path))
        if iw <= 0 or ih <= 0:
            iw, ih = 800, 600
        max_w, max_h = int(project_w * 0.75), int(project_h * 0.75)
        ratio = min(max_w / iw, max_h / ih, 1.0)
        self.w = max(40, int(iw * ratio))
        self.h = max(40, int(ih * ratio))
        self.x = int((project_w - self.w) / 2)
        self.y = int((project_h - self.h) / 2)
        self.start = 0.0
        self.duration = ffprobe_duration(path) if kind == "video" else 8.0
        if self.duration <= 0: self.duration = 8.0
        self.opacity = 1.0
        self.audio_enabled = True if kind == "video" else False
        self.crop_l = 0
        self.crop_t = 0
        self.crop_r = 0
        self.crop_b = 0
        self.visible = True
        self.locked = False
        self.thumb_path = None
        self.tk_image = None
        self.canvas_image_id = None
        self.canvas_box_id = None

    @staticmethod
    def image_size(path):
        if HAS_PIL:
            try:
                im = Image.open(path)
                return im.width, im.height
            except Exception:
                pass
        return 800, 600

    def to_dict(self):
        return {k: getattr(self, k) for k in ["path", "kind", "name", "x", "y", "w", "h", "start", "duration", "opacity", "audio_enabled", "crop_l", "crop_t", "crop_r", "crop_b", "visible", "locked"]}

    @classmethod
    def from_dict(cls, data, project_w, project_h):
        obj = cls(data["path"], data.get("kind", "image"), project_w, project_h)
        for k in ["name", "x", "y", "w", "h", "start", "duration", "opacity", "audio_enabled", "crop_l", "crop_t", "crop_r", "crop_b", "visible", "locked"]:
            if k in data: setattr(obj, k, data[k])
        return obj


class App(BaseTk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1420x860")
        self.minsize(980, 620)
        self.configure(bg=COLORS["bg"])
        self.project_format = tk.StringVar(value="Instagram Story 9:16")
        self.project_w, self.project_h = FORMATS[self.project_format.get()]
        self.bg_path = tk.StringVar(value="")
        self.audio_path = tk.StringVar(value="")
        self.outro_image_path = tk.StringVar(value="")
        self.outro_audio_path = tk.StringVar(value="")
        self.outro_duration_var = tk.DoubleVar(value=4.0)
        self.outro_transition_var = tk.StringVar(value="Smooth Left")
        self.outro_transition_dur_var = tk.DoubleVar(value=0.7)
        self.duration_var = tk.DoubleVar(value=8.0)
        self.encoder_var = tk.StringVar(value="libx264")
        self.crf_var = tk.IntVar(value=23)
        self.layers = []
        self.selected = None
        self.stop_event = threading.Event()
        self.drag = {"active": False, "mode": None, "handle": None, "sx": 0, "sy": 0, "ox": 0, "oy": 0, "ow": 0, "oh": 0}
        self.canvas_scale = 1
        self.canvas_origin = (0, 0)
        self._thumb_dir = os.path.join(tempfile.gettempdir(), "video_studio_v6_thumbs")
        os.makedirs(self._thumb_dir, exist_ok=True)
        self._build_ui()
        self._enable_dnd()
        self.after(200, self.refresh_canvas)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Panel.TFrame", background=COLORS["panel"])
        style.configure("Panel2.TFrame", background=COLORS["panel2"])
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background=COLORS["panel"], foreground=COLORS["text"], font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=COLORS["panel"], foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=COLORS["bg"], foreground="white", font=("Segoe UI", 19, "bold"))
        style.configure("Header.TLabel", background=COLORS["panel"], foreground="white", font=("Segoe UI", 12, "bold"))
        style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=(10, 6), background="#1f2a44", foreground=COLORS["text"], borderwidth=0)
        style.map("TButton", background=[("active", "#2d3b5f")], foreground=[("disabled", "#94a3b8")])
        style.configure("Accent.TButton", background=COLORS["accent"], foreground="white")
        style.map("Accent.TButton", background=[("active", "#e11d48")])
        style.configure("Gold.TButton", background=COLORS["gold2"], foreground="#fff7d6", relief="raised", borderwidth=1)
        style.map("Gold.TButton", background=[("active", COLORS["gold1"]), ("pressed", COLORS["gold3"])], foreground=[("active", "#111827")])
        style.configure("Danger.TButton", background=COLORS["danger"], foreground="white")
        style.configure("TCheckbutton", background=COLORS["panel"], foreground=COLORS["text"])
        style.configure("TEntry", fieldbackground="#0b1220", foreground=COLORS["text"], insertcolor=COLORS["text"], bordercolor=COLORS["stroke"])
        style.configure("TCombobox", fieldbackground="#0b1220", background="#0b1220", foreground="#e8eef8", arrowcolor="#f6c453", bordercolor=COLORS["stroke"], lightcolor=COLORS["stroke"], darkcolor=COLORS["stroke"])
        style.map("TCombobox", fieldbackground=[("readonly", "#0b1220"), ("!disabled", "#0b1220")], foreground=[("readonly", "#e8eef8"), ("!disabled", "#e8eef8")], selectbackground=[("readonly", "#0b1220")], selectforeground=[("readonly", "#e8eef8")])
        style.configure("TSpinbox", fieldbackground="#0b1220", background="#0b1220", foreground="#e8eef8", arrowcolor="#f6c453", bordercolor=COLORS["stroke"], insertcolor="#e8eef8")
        style.map("TSpinbox", fieldbackground=[("!disabled", "#0b1220")], foreground=[("!disabled", "#e8eef8")])

    def _build_ui(self):
        self._style()
        top = ttk.Frame(self, padding=(14, 10))
        top.pack(fill="x")
        ttk.Label(top, text=APP_TITLE, style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="✦ Render Başlat", style="Gold.TButton", command=self.start_render).pack(side="right", padx=4)
        ttk.Button(top, text="▶ Ön İzleme MP4", style="Gold.TButton", command=self.preview_mp4).pack(side="right", padx=4)
        ttk.Button(top, text="💾 Kaydet", command=self.save_project).pack(side="right", padx=4)
        ttk.Button(top, text="📂 Aç", command=self.open_project).pack(side="right", padx=4)

        self.paned = tk.PanedWindow(self, orient="horizontal", sashwidth=6, bg=COLORS["bg"], bd=0, relief="flat")
        self.paned.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self.left = ttk.Frame(self.paned, style="Panel.TFrame", padding=12)
        self.center = ttk.Frame(self.paned, style="Panel.TFrame", padding=10)
        self.right = ttk.Frame(self.paned, style="Panel.TFrame", padding=12)
        self.paned.add(self.left, minsize=240, width=330)
        self.paned.add(self.center, minsize=420, width=760)
        self.paned.add(self.right, minsize=260, width=330)

        self._left_panel()
        self._center_panel()
        self._right_panel()

        bottom = ttk.Frame(self, style="Panel.TFrame", padding=10)
        bottom.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Label(bottom, text="İşlem Günlüğü", style="Header.TLabel").pack(anchor="w")
        self.logbox = tk.Text(bottom, height=5, bg="#070b14", fg="#d6e0f0", insertbackground="white", relief="flat", font=("Consolas", 9), wrap="word")
        self.logbox.pack(fill="x", pady=(6, 0))
        self.log("Hazır. v6 gerçek layer, sürükle-bırak, boyutlandırma ve otomatik Output klasörü aktif.\n")

    def _left_panel(self):
        ttk.Label(self.left, text="Medya", style="Header.TLabel").pack(anchor="w")
        ttk.Label(self.left, text="Video, resim ve logo ekle. Katmanlar canvas üzerinde sürüklenebilir.", style="Muted.TLabel", wraplength=280).pack(anchor="w", pady=(2, 10))
        btnrow = ttk.Frame(self.left, style="Panel.TFrame")
        btnrow.pack(fill="x")
        ttk.Button(btnrow, text="+ Video", command=self.add_video_layer).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(btnrow, text="+ Resim/Logo", command=self.add_image_layer).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.layer_list = tk.Listbox(self.left, height=12, bg="#070b14", fg=COLORS["text"], selectbackground=COLORS["accent"], relief="flat", activestyle="none", font=("Segoe UI", 10))
        self.layer_list.pack(fill="both", expand=True, pady=10)
        self.layer_list.bind("<<ListboxSelect>>", self.on_layer_select)
        lbtn = ttk.Frame(self.left, style="Panel.TFrame")
        lbtn.pack(fill="x")
        ttk.Button(lbtn, text="Yukarı", command=lambda: self.move_layer(-1)).pack(side="left", expand=True, fill="x", padx=(0, 3))
        ttk.Button(lbtn, text="Aşağı", command=lambda: self.move_layer(1)).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(lbtn, text="Sil", style="Danger.TButton", command=self.delete_layer).pack(side="left", expand=True, fill="x", padx=(3, 0))

        ttk.Label(self.left, text="Arka Plan", style="Header.TLabel").pack(anchor="w", pady=(14, 6))
        self._file_row(self.left, "Arka plan video", self.bg_path, self.pick_bg)
        self._file_row(self.left, "Ana müzik / ses", self.audio_path, self.pick_audio)
        ttk.Label(self.left, text="Video Sonu / Outro", style="Header.TLabel").pack(anchor="w", pady=(14, 6))
        self._file_row(self.left, "Son resim", self.outro_image_path, self.pick_outro_image)
        self._file_row(self.left, "Son ses", self.outro_audio_path, self.pick_outro_audio)
        orow = ttk.Frame(self.left, style="Panel.TFrame"); orow.pack(fill="x", pady=4)
        ttk.Label(orow, text="Son süre sn", style="Panel.TLabel", width=14).pack(side="left")
        ttk.Spinbox(orow, from_=1, to=60, increment=0.5, textvariable=self.outro_duration_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Label(self.left, text="Çıktı klasörü artık otomatik oluşur: ./Output/tarih-saat/", style="Muted.TLabel", wraplength=300).pack(anchor="w", pady=(10, 0))

    def _file_row(self, parent, text, var, cmd):
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=text, style="Panel.TLabel", width=14).pack(side="left")
        ent = ttk.Entry(row, textvariable=var)
        ent.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="Seç", command=cmd).pack(side="left")

    def _center_panel(self):
        head = ttk.Frame(self.center, style="Panel.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Canlı Önizleme", style="Header.TLabel").pack(side="left")
        ttk.Combobox(head, textvariable=self.project_format, values=list(FORMATS.keys()), state="readonly", width=22).pack(side="right")
        self.project_format.trace_add("write", lambda *_: self.change_format())
        self.canvas_wrap = ttk.Frame(self.center, style="Panel2.TFrame", padding=10)
        self.canvas_wrap.pack(fill="both", expand=True, pady=(8, 8))
        self.canvas = tk.Canvas(self.canvas_wrap, bg="#050814", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.refresh_canvas())
        self.canvas.bind("<ButtonPress-1>", self.canvas_down)
        self.canvas.bind("<B1-Motion>", self.canvas_move)
        self.canvas.bind("<ButtonRelease-1>", self.canvas_up)
        self.canvas.bind("<MouseWheel>", self.canvas_wheel)
        self.canvas.bind("<Delete>", lambda e: self.delete_layer())
        foot = ttk.Frame(self.center, style="Panel.TFrame")
        foot.pack(fill="x")
        ttk.Label(foot, text="Nesneyi sürükle. Tutamaçlardan boyutlandır. CTRL + tutamaç = içerikten kırp. Mouse tekeri ölçekler.", style="Muted.TLabel").pack(side="left")

    def _right_panel(self):
        ttk.Label(self.right, text="Özellikler", style="Header.TLabel").pack(anchor="w")
        ttk.Label(self.right, text="Seçili katmanın boyut, konum ve zaman ayarları.", style="Muted.TLabel", wraplength=280).pack(anchor="w", pady=(2, 10))
        self.prop_name = tk.StringVar(value="Katman seçilmedi")
        ttk.Label(self.right, textvariable=self.prop_name, style="Panel.TLabel", wraplength=300).pack(anchor="w", pady=(0, 8))
        self.vars = {k: tk.DoubleVar(value=0) for k in ["x", "y", "w", "h", "start", "duration", "opacity", "crop_l", "crop_t", "crop_r", "crop_b"]}
        for k, label in [("x", "X"), ("y", "Y"), ("w", "Genişlik"), ("h", "Yükseklik"), ("start", "Başlangıç sn"), ("duration", "Süre sn"), ("opacity", "Opacity 0-1"), ("crop_l", "Kırp Sol"), ("crop_t", "Kırp Üst"), ("crop_r", "Kırp Sağ"), ("crop_b", "Kırp Alt")]:
            row = ttk.Frame(self.right, style="Panel.TFrame")
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=label, style="Panel.TLabel", width=12).pack(side="left")
            sp = ttk.Spinbox(row, from_=-5000 if k in ("x","y") else 0, to=10000, increment=0.05 if k in ("start","duration","opacity") else 1, textvariable=self.vars[k], command=self.apply_props)
            sp.pack(side="left", fill="x", expand=True)
            sp.bind("<KeyRelease>", lambda e: self.apply_props())
        self.visible_var = tk.BooleanVar(value=True)
        self.audio_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.right, text="Görünür", variable=self.visible_var, command=self.apply_props).pack(anchor="w", pady=(8, 4))
        ttk.Checkbutton(self.right, text="Bu video katmanının sesini kullan", variable=self.audio_enabled_var, command=self.apply_props).pack(anchor="w", pady=4)
        ttk.Button(self.right, text="✦ Formata sığdır / boşluklu", style="Gold.TButton", command=self.fit_selected_inside).pack(fill="x", pady=4)
        ttk.Button(self.right, text="Seçili katmanı ortala", command=self.center_selected).pack(fill="x", pady=4)
        ttk.Button(self.right, text="Oranı koruyarak 100% yap", command=self.reset_selected_size).pack(fill="x", pady=4)

        ttk.Label(self.right, text="Render", style="Header.TLabel").pack(anchor="w", pady=(18, 6))
        r = ttk.Frame(self.right, style="Panel.TFrame"); r.pack(fill="x", pady=4)
        ttk.Label(r, text="Proje süresi", style="Panel.TLabel", width=12).pack(side="left")
        ttk.Spinbox(r, from_=1, to=600, increment=0.5, textvariable=self.duration_var).pack(side="left", fill="x", expand=True)
        r = ttk.Frame(self.right, style="Panel.TFrame"); r.pack(fill="x", pady=4)
        ttk.Label(r, text="Encoder", style="Panel.TLabel", width=12).pack(side="left")
        ttk.Combobox(r, textvariable=self.encoder_var, values=["libx264", "h264_nvenc", "h264_qsv", "h264_amf"], state="readonly").pack(side="left", fill="x", expand=True)
        r = ttk.Frame(self.right, style="Panel.TFrame"); r.pack(fill="x", pady=4)
        ttk.Label(r, text="CRF/CQ", style="Panel.TLabel", width=12).pack(side="left")
        ttk.Spinbox(r, from_=18, to=32, textvariable=self.crf_var).pack(side="left", fill="x", expand=True)
        ttk.Button(self.right, text="✦ Altın Render Başlat", style="Gold.TButton", command=self.start_render).pack(fill="x", pady=(12, 4))
        ttk.Button(self.right, text="Durdur", style="Danger.TButton", command=lambda: self.stop_event.set()).pack(fill="x", pady=4)

    def _enable_dnd(self):
        if not HAS_DND:
            self.log("Sürükle-bırak için: python -m pip install tkinterdnd2\n")
            return
        for w in [self.canvas, self.layer_list, self.left, self.center, self.right]:
            try:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self.on_drop)
            except Exception:
                pass
        self.log("Sürükle-bırak aktif. Video/resim/ses dosyalarını pencereye bırakabilirsiniz.\n")

    def log(self, text):
        if hasattr(self, "logbox"):
            self.logbox.insert("end", text)
            self.logbox.see("end")
            self.update_idletasks()

    def pick_bg(self):
        p = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mov *.mkv *.webm *.avi *.m4v"), ("Tüm dosyalar", "*.*")])
        if p: self.bg_path.set(p); self.refresh_canvas()

    def pick_audio(self):
        p = filedialog.askopenfilename(filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac *.ogg *.flac"), ("Tüm dosyalar", "*.*")])
        if p: self.audio_path.set(p)

    def pick_outro_image(self):
        p = filedialog.askopenfilename(filetypes=[("Görsel", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Tüm dosyalar", "*.*")])
        if p:
            self.outro_image_path.set(p)
            self.refresh_canvas()

    def pick_outro_audio(self):
        p = filedialog.askopenfilename(filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac *.ogg *.flac"), ("Tüm dosyalar", "*.*")])
        if p:
            self.outro_audio_path.set(p)

    def add_video_layer(self):
        paths = filedialog.askopenfilenames(filetypes=[("Video", "*.mp4 *.mov *.mkv *.webm *.avi *.m4v"), ("Tüm dosyalar", "*.*")])
        for p in paths: self.add_layer(p, "video")

    def add_image_layer(self):
        paths = filedialog.askopenfilenames(filetypes=[("Görsel", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Tüm dosyalar", "*.*")])
        for p in paths: self.add_layer(p, "image")

    def on_drop(self, event):
        for p in self.tk.splitlist(event.data):
            p = p.strip("{}")
            ext = os.path.splitext(p)[1].lower()
            if ext in VIDEO_EXTS:
                if not self.bg_path.get(): self.bg_path.set(p)
                else: self.add_layer(p, "video")
            elif ext in IMAGE_EXTS:
                self.add_layer(p, "image")
            elif ext in AUDIO_EXTS:
                self.audio_path.set(p)
        self.refresh_canvas()

    def add_layer(self, path, kind):
        check_ffmpeg() if kind == "video" else None
        layer = Layer(path, kind, self.project_w, self.project_h)
        self.layers.append(layer)
        self.sync_duration_to_layers()
        self.make_thumb(layer)
        self.refresh_layer_list()
        self.select_layer(layer)
        self.refresh_canvas()

    def make_thumb(self, layer):
        if not HAS_PIL: return
        try:
            if layer.kind == "image":
                layer.thumb_path = layer.path
                return
            out = os.path.join(self._thumb_dir, f"thumb_{layer.id}.jpg")
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.run(["ffmpeg", "-y", "-ss", "0.2", "-i", layer.path, "-frames:v", "1", "-q:v", "3", out], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            if os.path.exists(out): layer.thumb_path = out
        except Exception:
            pass

    def refresh_layer_list(self):
        self.layer_list.delete(0, "end")
        for i, l in enumerate(reversed(self.layers)):
            icon = "🎬" if l.kind == "video" else "🖼"
            self.layer_list.insert("end", f"{icon} {l.name}")
        if self.selected in self.layers:
            idx = len(self.layers) - 1 - self.layers.index(self.selected)
            self.layer_list.selection_clear(0, "end"); self.layer_list.selection_set(idx)

    def on_layer_select(self, event=None):
        sel = self.layer_list.curselection()
        if not sel: return
        layer = list(reversed(self.layers))[sel[0]]
        self.select_layer(layer)

    def select_layer(self, layer):
        self.selected = layer
        self.prop_name.set(layer.name)
        for k in self.vars:
            self.vars[k].set(getattr(layer, k))
        self.visible_var.set(layer.visible)
        self.audio_enabled_var.set(bool(getattr(layer, "audio_enabled", False)))
        self.refresh_layer_list()
        self.refresh_canvas()

    def apply_props(self):
        l = self.selected
        if not l: return
        try:
            l.x = int(float(self.vars["x"].get())); l.y = int(float(self.vars["y"].get()))
            l.w = max(1, int(float(self.vars["w"].get()))); l.h = max(1, int(float(self.vars["h"].get())))
            l.start = max(0, float(self.vars["start"].get())); l.duration = max(0.05, float(self.vars["duration"].get()))
            l.opacity = min(1, max(0, float(self.vars["opacity"].get()))); l.visible = bool(self.visible_var.get())
            l.audio_enabled = bool(self.audio_enabled_var.get()) if l.kind == "video" else False
            l.crop_l = max(0, int(float(self.vars["crop_l"].get()))); l.crop_t = max(0, int(float(self.vars["crop_t"].get())))
            l.crop_r = max(0, int(float(self.vars["crop_r"].get()))); l.crop_b = max(0, int(float(self.vars["crop_b"].get())))
            # Crop değeri katman boyutunu geçmesin
            l.crop_l = min(l.crop_l, max(0, l.w - 2)); l.crop_r = min(l.crop_r, max(0, l.w - l.crop_l - 1))
            l.crop_t = min(l.crop_t, max(0, l.h - 2)); l.crop_b = min(l.crop_b, max(0, l.h - l.crop_t - 1))
            self.sync_duration_to_layers()
            self.refresh_canvas()
        except Exception:
            pass

    def move_layer(self, direction):
        if not self.selected or self.selected not in self.layers: return
        i = self.layers.index(self.selected); ni = max(0, min(len(self.layers)-1, i - direction))
        if ni != i:
            self.layers[i], self.layers[ni] = self.layers[ni], self.layers[i]
            self.refresh_layer_list(); self.refresh_canvas()

    def delete_layer(self):
        if not self.selected: return
        if self.selected in self.layers: self.layers.remove(self.selected)
        self.selected = None; self.prop_name.set("Katman seçilmedi")
        self.refresh_layer_list(); self.refresh_canvas()

    def fit_selected_inside(self):
        """Seçili videoyu/görseli formata boşluk bırakarak sığdırır."""
        if not self.selected:
            return
        l = self.selected
        iw, ih = ffprobe_size(l.path) if l.kind == "video" else Layer.image_size(l.path)
        if iw <= 0 or ih <= 0:
            iw, ih = l.w, l.h
        margin_x = int(self.project_w * 0.06)
        margin_y = int(self.project_h * 0.06)
        box_w = max(20, self.project_w - margin_x * 2)
        box_h = max(20, self.project_h - margin_y * 2)
        ratio = min(box_w / iw, box_h / ih)
        l.w = max(20, int(iw * ratio))
        l.h = max(20, int(ih * ratio))
        l.x = int((self.project_w - l.w) / 2)
        l.y = int((self.project_h - l.h) / 2)
        l.crop_l = l.crop_t = l.crop_r = l.crop_b = 0
        self.select_layer(l)

    def center_selected(self):
        if not self.selected: return
        self.selected.x = int((self.project_w - self.selected.w)/2); self.selected.y = int((self.project_h - self.selected.h)/2)
        self.select_layer(self.selected)

    def reset_selected_size(self):
        if not self.selected: return
        iw, ih = ffprobe_size(self.selected.path) if self.selected.kind == "video" else Layer.image_size(self.selected.path)
        if iw > 0 and ih > 0:
            self.selected.w, self.selected.h = iw, ih
            self.select_layer(self.selected)

    def change_format(self):
        self.project_w, self.project_h = FORMATS[self.project_format.get()]
        self.refresh_canvas()

    def canvas_rect(self):
        cw, ch = max(100, self.canvas.winfo_width()), max(100, self.canvas.winfo_height())
        scale = min((cw-30)/self.project_w, (ch-30)/self.project_h)
        scale = max(0.05, scale)
        sw, sh = self.project_w * scale, self.project_h * scale
        ox, oy = (cw - sw)/2, (ch - sh)/2
        self.canvas_scale = scale; self.canvas_origin = (ox, oy)
        return ox, oy, sw, sh

    def to_canvas(self, x, y):
        ox, oy = self.canvas_origin; s = self.canvas_scale
        return ox + x*s, oy + y*s

    def to_project(self, x, y):
        ox, oy = self.canvas_origin; s = self.canvas_scale
        return (x-ox)/s, (y-oy)/s

    def refresh_canvas(self):
        if not hasattr(self, "canvas"): return
        c = self.canvas; c.delete("all")
        ox, oy, sw, sh = self.canvas_rect()
        c.create_rectangle(0, 0, c.winfo_width(), c.winfo_height(), fill="#050814", outline="")
        c.create_rectangle(ox-5, oy-5, ox+sw+5, oy+sh+5, fill="#0b1220", outline="#1d2a44", width=2)
        if self.bg_path.get() and HAS_PIL:
            self.draw_media_preview(self.bg_path.get(), ox, oy, sw, sh, cover=True, muted=True)
        else:
            c.create_rectangle(ox, oy, ox+sw, oy+sh, fill=COLORS["canvas_bg"], outline="#334155")
            c.create_text(ox+sw/2, oy+sh/2, text="ARKA PLAN", fill=COLORS["muted"], font=("Segoe UI", 18, "bold"))
        for l in self.layers:
            if not l.visible: continue
            x, y = self.to_canvas(l.x, l.y); ww, hh = l.w*self.canvas_scale, l.h*self.canvas_scale
            self.draw_layer(l, x, y, ww, hh)
        c.create_text(ox+10, oy+12, text=f"{self.project_format.get()}  {self.project_w}x{self.project_h}", anchor="w", fill="white", font=("Segoe UI", 9, "bold"))

    def draw_media_preview(self, path, x, y, w, h, cover=False, muted=False):
        try:
            source = path
            if os.path.splitext(path)[1].lower() in VIDEO_EXTS:
                temp = os.path.join(self._thumb_dir, "bg_thumb.jpg")
                if not os.path.exists(temp) or os.path.getmtime(temp) < os.path.getmtime(path):
                    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                    subprocess.run(["ffmpeg", "-y", "-ss", "0.2", "-i", path, "-frames:v", "1", "-q:v", "3", temp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
                source = temp
            im = Image.open(source).convert("RGBA")
            if cover:
                ratio = max(w/im.width, h/im.height)
                nw, nh = max(1, int(im.width*ratio)), max(1, int(im.height*ratio))
                im = im.resize((nw, nh), Image.LANCZOS)
                im = im.crop(((nw-int(w))//2, (nh-int(h))//2, (nw+int(w))//2, (nh+int(h))//2))
            else:
                im = im.resize((max(1,int(w)), max(1,int(h))), Image.LANCZOS)
            if muted:
                # subtle dark overlay for professional preview
                overlay = Image.new("RGBA", im.size, (0,0,0,70))
                im = Image.alpha_composite(im, overlay)
            photo = ImageTk.PhotoImage(im)
            self.canvas._images = getattr(self.canvas, "_images", []) + [photo]
            self.canvas.create_image(x, y, image=photo, anchor="nw")
        except Exception:
            self.canvas.create_rectangle(x, y, x+w, y+h, fill="#111827", outline="#475569")

    def draw_layer(self, l, x, y, w, h):
        if HAS_PIL and l.thumb_path:
            try:
                im = Image.open(l.thumb_path).convert("RGBA")
                cl, ct, cr, cb = int(getattr(l, "crop_l", 0)), int(getattr(l, "crop_t", 0)), int(getattr(l, "crop_r", 0)), int(getattr(l, "crop_b", 0))
                # OBS tarzı kırpma: kaynak önce crop dahil toplam boyuta ölçeklenir,
                # sonra sadece görünen kutu kadar alan kesilir. Sonradan tekrar büyütülmez.
                sw = max(2, int(w + max(0, cl) + max(0, cr)))
                sh = max(2, int(h + max(0, ct) + max(0, cb)))
                tmp = im.resize((sw, sh), Image.LANCZOS)
                cl, ct = min(max(0, cl), sw-2), min(max(0, ct), sh-2)
                right = min(sw, cl + max(1, int(w)))
                bottom = min(sh, ct + max(1, int(h)))
                im = tmp.crop((cl, ct, right, bottom))
                im = im.resize((max(1,int(w)), max(1,int(h))), Image.LANCZOS)
                if l.opacity < 1:
                    alpha = im.getchannel("A").point(lambda p: int(p*l.opacity))
                    im.putalpha(alpha)
                photo = ImageTk.PhotoImage(im)
                self.canvas._images = getattr(self.canvas, "_images", []) + [photo]
                self.canvas.create_image(x, y, image=photo, anchor="nw", tags=(f"layer{l.id}", "layer"))
            except Exception:
                self.canvas.create_rectangle(x, y, x+w, y+h, fill="#1e293b", outline="#64748b", tags=(f"layer{l.id}", "layer"))
        else:
            fill = "#1f2937" if l.kind == "video" else "#334155"
            self.canvas.create_rectangle(x, y, x+w, y+h, fill=fill, outline="#64748b", tags=(f"layer{l.id}", "layer"))
            self.canvas.create_text(x+w/2, y+h/2, text=l.name[:24], fill="white", tags=(f"layer{l.id}", "layer"))
        if l == self.selected:
            self.canvas.create_rectangle(x, y, x+w, y+h, outline=COLORS["gold1"], width=2)
            sz = 7
            handles = {
                "nw": (x, y), "n": (x+w/2, y), "ne": (x+w, y),
                "e": (x+w, y+h/2), "se": (x+w, y+h), "s": (x+w/2, y+h),
                "sw": (x, y+h), "w": (x, y+h/2),
            }
            for name, (hx, hy) in handles.items():
                self.canvas.create_rectangle(hx-sz, hy-sz, hx+sz, hy+sz, fill=COLORS["gold1"], outline="#fff7d6", tags=("handle", name))
            self.canvas.create_text(x, y-16, text=l.name[:28], anchor="w", fill="#fff7d6", font=("Segoe UI", 9, "bold"))

    def handle_at(self, cx, cy):
        """Return resize handle name under mouse for selected layer."""
        if not self.selected:
            return None
        l = self.selected
        x, y = self.to_canvas(l.x, l.y)
        w, h = l.w * self.canvas_scale, l.h * self.canvas_scale
        sz = 12
        handles = {
            "nw": (x, y), "n": (x+w/2, y), "ne": (x+w, y),
            "e": (x+w, y+h/2), "se": (x+w, y+h), "s": (x+w/2, y+h),
            "sw": (x, y+h), "w": (x, y+h/2),
        }
        for name, (hx, hy) in handles.items():
            if hx-sz <= cx <= hx+sz and hy-sz <= cy <= hy+sz:
                return name
        return None

    def hit_layer(self, cx, cy):
        px, py = self.to_project(cx, cy)
        for l in reversed(self.layers):
            if l.visible and l.x <= px <= l.x+l.w and l.y <= py <= l.y+l.h:
                return l, px, py
        return None, px, py

    def canvas_down(self, e):
        self.canvas.focus_set()
        handle = self.handle_at(e.x, e.y)
        if handle and self.selected:
            l = self.selected
            px, py = self.to_project(e.x, e.y)
            self.drag = {"active": True, "mode": "resize", "handle": handle, "sx": px, "sy": py, "ox": l.x, "oy": l.y, "ow": l.w, "oh": l.h, "crop_l": getattr(l, "crop_l", 0), "crop_t": getattr(l, "crop_t", 0), "crop_r": getattr(l, "crop_r", 0), "crop_b": getattr(l, "crop_b", 0)}
            return
        l, px, py = self.hit_layer(e.x, e.y)
        if l:
            self.select_layer(l)
            self.drag = {"active": True, "mode": "move", "handle": None, "sx": px, "sy": py, "ox": l.x, "oy": l.y, "ow": l.w, "oh": l.h}
        else:
            self.selected = None; self.prop_name.set("Katman seçilmedi"); self.refresh_layer_list(); self.refresh_canvas()

    def canvas_move(self, e):
        if not self.drag.get("active") or not self.selected: return
        px, py = self.to_project(e.x, e.y); l = self.selected
        dx, dy = px - self.drag["sx"], py - self.drag["sy"]
        if self.drag["mode"] == "move":
            l.x = int(self.drag["ox"] + dx); l.y = int(self.drag["oy"] + dy)
        else:
            h = self.drag.get("handle") or "se"
            x, y, w, hh = self.drag["ox"], self.drag["oy"], self.drag["ow"], self.drag["oh"]
            # CTRL basılıyken OBS mantığında kırpma yapılır:
            # Kenarı içeri çektiğinde hem crop değeri artar hem de görünen kutu aynı miktarda küçülür.
            # Böylece üstten kırpınca nesne aşağı kayar ve yüksekliği azalır; crop edilen alan ekranda görünmez.
            if e.state & 0x0004:
                cl0 = int(self.drag.get("crop_l", getattr(l, "crop_l", 0)))
                ct0 = int(self.drag.get("crop_t", getattr(l, "crop_t", 0)))
                cr0 = int(self.drag.get("crop_r", getattr(l, "crop_r", 0)))
                cb0 = int(self.drag.get("crop_b", getattr(l, "crop_b", 0)))
                nx, ny, nw, nh = x, y, w, hh
                min_size = 20

                if "w" in h:
                    delta = int(dx)
                    max_delta = max(0, w - min_size)
                    delta = max(-cl0, min(delta, max_delta))
                    nx = int(x + delta)
                    nw = int(w - delta)
                    l.crop_l = max(0, cl0 + delta)
                if "e" in h:
                    delta = int(dx)
                    max_left = -(w - min_size)
                    delta = max(max_left, min(delta, cr0))
                    nw = int(w + delta)
                    l.crop_r = max(0, cr0 - delta)
                if "n" in h:
                    delta = int(dy)
                    max_delta = max(0, hh - min_size)
                    delta = max(-ct0, min(delta, max_delta))
                    ny = int(y + delta)
                    nh = int(hh - delta)
                    l.crop_t = max(0, ct0 + delta)
                if "s" in h:
                    delta = int(dy)
                    max_up = -(hh - min_size)
                    delta = max(max_up, min(delta, cb0))
                    nh = int(hh + delta)
                    l.crop_b = max(0, cb0 - delta)

                l.x, l.y, l.w, l.h = nx, ny, max(min_size, nw), max(min_size, nh)
            else:
                nx, ny, nw, nh = x, y, w, hh
                if "e" in h:
                    nw = max(20, int(w + dx))
                if "s" in h:
                    nh = max(20, int(hh + dy))
                if "w" in h:
                    nw = max(20, int(w - dx)); nx = int(x + (w - nw))
                if "n" in h:
                    nh = max(20, int(hh - dy)); ny = int(y + (hh - nh))
                # Shift basılıysa oranı koru
                if (e.state & 0x0001) and w > 0 and hh > 0:
                    ratio = w / hh
                    if h in ("e", "w"):
                        nh = max(20, int(nw / ratio))
                    elif h in ("n", "s"):
                        nw = max(20, int(nh * ratio))
                    else:
                        if abs(dx) >= abs(dy): nh = max(20, int(nw / ratio))
                        else: nw = max(20, int(nh * ratio))
                    if "w" in h: nx = int(x + (w - nw))
                    if "n" in h: ny = int(y + (hh - nh))
                l.x, l.y, l.w, l.h = nx, ny, nw, nh
        for k in self.vars: self.vars[k].set(getattr(l, k))
        self.refresh_canvas()

    def canvas_up(self, e):
        self.drag["active"] = False

    def canvas_wheel(self, e):
        if not self.selected: return
        l = self.selected
        factor = 1.06 if e.delta > 0 else 0.94
        cx, cy = l.x + l.w/2, l.y + l.h/2
        l.w = max(20, int(l.w*factor)); l.h = max(20, int(l.h*factor))
        l.x = int(cx - l.w/2); l.y = int(cy - l.h/2)
        self.select_layer(l)

    def output_dir(self):
        base = os.path.join(os.getcwd(), "Output")
        out = os.path.join(base, time.strftime("%Y-%m-%d_%H-%M-%S"))
        os.makedirs(out, exist_ok=True)
        return out

    def layer_video_filter(self, idx, layer, label, dur, start, alpha, image=False):
        lw, lh = max(2, int(layer.w)), max(2, int(layer.h))
        cl = max(0, int(getattr(layer, "crop_l", 0)))
        ct = max(0, int(getattr(layer, "crop_t", 0)))
        cr = max(0, int(getattr(layer, "crop_r", 0)))
        cb = max(0, int(getattr(layer, "crop_b", 0)))
        # OBS tarzı kırpma: toplam kaynak alan = görünen kutu + crop kenarları.
        # Crop sonrası çıktı tekrar eski boyuta büyütülmez; görünen kutu zaten lw/lh'dir.
        sw, sh = max(2, lw + cl + cr), max(2, lh + ct + cb)
        crop = f",crop={lw}:{lh}:{cl}:{ct}" if (cl or ct or cr or cb) else ""
        pts = "PTS-STARTPTS" if image else f"PTS-STARTPTS+{start}/TB"
        return f"[{idx}:v]scale={sw}:{sh},setsar=1{crop},trim=0:{dur:.3f},setpts={pts}{alpha}[{label}]"

    def xfade_name(self):
        m = {
            "Fade": "fade", "Fade Black": "fadeblack", "Fade White": "fadewhite", "Dissolve": "dissolve",
            "Smooth Left": "smoothleft", "Smooth Right": "smoothright", "Smooth Up": "smoothup", "Smooth Down": "smoothdown",
            "Slide Left": "slideleft", "Slide Right": "slideright", "Slide Up": "slideup", "Slide Down": "slidedown",
            "Wipe Left": "wipeleft", "Wipe Right": "wiperight", "Wipe Up": "wipeup", "Wipe Down": "wipedown",
            "Circle Open": "circleopen", "Circle Close": "circleclose", "Distance": "distance"
        }
        return m.get(self.outro_transition_var.get(), "smoothleft")

    def get_full_timeline_duration(self):
        """Render süresini katmanların gerçek sürelerine göre otomatik hesaplar.
        Böylece 3 dakikalık video 8 saniyeye/5 saniyeye kırpılmaz.
        Kullanıcının süre alanı daha uzunsa onu da dikkate alır.
        """
        try:
            manual = float(self.duration_var.get())
        except Exception:
            manual = 0.0
        max_end = manual
        for l in self.layers:
            if not getattr(l, "visible", True):
                continue
            try:
                start = max(0.0, float(getattr(l, "start", 0.0)))
                dur = float(getattr(l, "duration", 0.0))
                if l.kind == "video":
                    real_dur = ffprobe_duration(l.path)
                    if real_dur > 0:
                        # Katman süresi yanlışlıkla kısa kaldıysa gerçek video süresini esas al.
                        dur = max(dur, real_dur)
                max_end = max(max_end, start + max(0.05, dur))
            except Exception:
                pass
        # Eğer hiç katman yoksa ama arka plan video varsa onun süresini kullan.
        if max_end <= 0 and self.bg_path.get():
            try:
                max_end = ffprobe_duration(self.bg_path.get())
            except Exception:
                max_end = 8.0
        return max(0.1, max_end or 8.0)

    def sync_duration_to_layers(self):
        """Süre kutusunu otomatik olarak en uzun video/katman süresine çeker."""
        try:
            full = self.get_full_timeline_duration()
            if full > float(self.duration_var.get()) + 0.01:
                self.duration_var.set(round(full, 2))
        except Exception:
            pass

    def build_cmd(self, out_path, preview=False):
        check_ffmpeg()
        if not self.bg_path.get():
            raise RuntimeError("Arka plan videosu seçilmedi.")
        if not self.layers and not self.outro_image_path.get():
            raise RuntimeError("En az bir video/resim katmanı veya video sonu resmi ekleyin.")

        w, h = self.project_w, self.project_h
        full_main_dur = self.get_full_timeline_duration()
        # Ön izleme hızlı açılması için ilk 8 saniye ile sınırlıdır; render tam süreyi alır.
        main_dur = min(full_main_dur, 8.0) if preview else full_main_dur
        outro_dur = 0.0 if preview else (float(self.outro_duration_var.get()) if self.outro_image_path.get() else 0.0)
        total_dur = main_dur + outro_dur

        cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", self.bg_path.get()]
        input_index = 1
        layer_input_indices = []
        for l in self.layers:
            if l.kind == "image":
                cmd += ["-loop", "1", "-t", str(total_dur), "-i", l.path]
            else:
                cmd += ["-i", l.path]
            layer_input_indices.append(input_index)
            input_index += 1

        main_audio_idx = None
        if self.audio_path.get():
            cmd += ["-stream_loop", "-1", "-i", self.audio_path.get()]
            main_audio_idx = input_index
            input_index += 1

        outro_img_idx = None
        if self.outro_image_path.get():
            cmd += ["-loop", "1", "-t", str(max(0.1, outro_dur)), "-i", self.outro_image_path.get()]
            outro_img_idx = input_index
            input_index += 1

        outro_audio_idx = None
        if self.outro_audio_path.get() and outro_dur > 0:
            cmd += ["-stream_loop", "-1", "-i", self.outro_audio_path.get()]
            outro_audio_idx = input_index
            input_index += 1

        parts = []
        # MAIN PART
        parts.append(f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},trim=0:{main_dur:.3f},setpts=PTS-STARTPTS,boxblur=5:1,format=rgba[base0]")
        last = "base0"
        overlay_count = 0
        for n, l in enumerate(self.layers):
            if not l.visible:
                continue
            idx = layer_input_indices[n]
            start = float(l.start)
            end = min(main_dur, float(l.start) + float(l.duration))
            if end <= 0 or start >= main_dur:
                continue
            label = f"ly{n}"
            alpha = f",format=rgba,colorchannelmixer=aa={l.opacity:.3f}" if l.opacity < 1 else ",format=rgba"
            if l.kind == "image":
                parts.append(self.layer_video_filter(idx, l, label, main_dur, 0.0, alpha, image=True))
            else:
                segdur = max(0.05, min(float(l.duration), main_dur - start))
                parts.append(self.layer_video_filter(idx, l, label, segdur, start, alpha, image=False))
            out = f"base{overlay_count+1}"
            enable = f":enable='between(t,{start:.3f},{end:.3f})'"
            parts.append(f"[{last}][{label}]overlay={int(l.x)}:{int(l.y)}{enable}:format=auto[{out}]")
            last = out
            overlay_count += 1
        parts.append(f"[{last}]format=yuv420p[vmain]")

        final_label = "vmain"
        if outro_img_idx is not None and outro_dur > 0:
            parts.append(f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},trim=0:{outro_dur:.3f},setpts=PTS-STARTPTS,boxblur=8:1,format=rgba[obg]")
            parts.append(f"[{outro_img_idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,trim=0:{outro_dur:.3f},setpts=PTS-STARTPTS,format=rgba[oimg]")
            parts.append(f"[obg][oimg]overlay=(W-w)/2:(H-h)/2:format=auto,format=yuv420p[voutro]")
            xdur = min(float(self.outro_transition_dur_var.get()), max(0.1, main_dur - 0.05), max(0.1, outro_dur - 0.05))
            xoff = max(0.05, main_dur - xdur)
            parts.append(f"[vmain][voutro]xfade=transition={self.xfade_name()}:duration={xdur:.3f}:offset={xoff:.3f},format=yuv420p[v]")
            final_label = "v"
            total_dur = max(0.1, main_dur + outro_dur - xdur)

        audio_parts = []
        audio_labels = []
        if main_audio_idx is not None:
            audio_parts.append(f"[{main_audio_idx}:a]atrim=0:{main_dur:.3f},asetpts=PTS-STARTPTS[abg]")
            audio_labels.append("[abg]")
        for n, l in enumerate(self.layers):
            if l.kind == "video" and getattr(l, "audio_enabled", True) and has_audio(l.path):
                idx = layer_input_indices[n]
                start = max(0.0, float(l.start))
                segdur = max(0.05, min(float(l.duration), main_dur - start))
                if segdur <= 0:
                    continue
                delay = int(start * 1000)
                lab = f"[al{n}]"
                audio_parts.append(f"[{idx}:a]atrim=0:{segdur:.3f},asetpts=PTS-STARTPTS,adelay={delay}|{delay}{lab}")
                audio_labels.append(lab)
        if outro_audio_idx is not None and outro_dur > 0:
            delay = int(main_dur * 1000)
            audio_parts.append(f"[{outro_audio_idx}:a]atrim=0:{outro_dur:.3f},asetpts=PTS-STARTPTS,adelay={delay}|{delay}[aout]")
            audio_labels.append("[aout]")
        if audio_labels:
            if len(audio_labels) == 1:
                audio_parts.append(f"{audio_labels[0]}atrim=0:{total_dur:.3f},asetpts=PTS-STARTPTS[a]")
            else:
                audio_parts.append(f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}:duration=longest:dropout_transition=0,atrim=0:{total_dur:.3f},asetpts=PTS-STARTPTS[a]")
            parts.extend(audio_parts)

        cmd += ["-filter_complex", ";".join(parts), "-map", f"[{final_label}]"]
        if audio_labels:
            cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-an"]

        enc = self.encoder_var.get()
        if preview:
            cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"]
        elif enc == "libx264":
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(int(self.crf_var.get()))]
        else:
            cmd += ["-c:v", enc, "-preset", "fast", "-cq", str(int(self.crf_var.get()))]
        cmd += ["-t", str(total_dur), "-r", "30", "-movflags", "+faststart", "-shortest", out_path]
        return cmd

    def preview_mp4(self):
        try:
            out = os.path.join(tempfile.gettempdir(), f"studio_preview_{int(time.time())}.mp4")
            run_cmd(self.build_cmd(out, preview=True), self.log, self.stop_event)
            if os.name == "nt": os.startfile(out)
            elif sys.platform == "darwin": subprocess.Popen(["open", out])
            else: subprocess.Popen(["xdg-open", out])
        except Exception as e:
            self.log(f"HATA: {e}\n"); messagebox.showerror("Ön izleme hatası", str(e))

    def start_render(self):
        self.stop_event.clear()
        threading.Thread(target=self.render_worker, daemon=True).start()

    def render_worker(self):
        try:
            outdir = self.output_dir()
            name = slugify(self.layers[0].name if self.layers else "video")
            fmt = slugify(self.project_format.get())
            out = os.path.join(outdir, f"{name}_{fmt}.mp4")
            self.log(f"\nRender klasörü: {outdir}\n")
            run_cmd(self.build_cmd(out, preview=False), self.log, self.stop_event)
            self.log(f"BİTTİ: {out}\n")
            messagebox.showinfo("Tamamlandı", f"Çıktı oluşturuldu:\n{out}")
        except Exception as e:
            self.log(f"HATA: {e}\n"); messagebox.showerror("Render hatası", str(e))

    def project_data(self):
        return {"version": APP_VERSION, "format": self.project_format.get(), "bg": self.bg_path.get(), "audio": self.audio_path.get(), "outro_image": self.outro_image_path.get(), "outro_audio": self.outro_audio_path.get(), "outro_duration": self.outro_duration_var.get(), "outro_transition": self.outro_transition_var.get(), "outro_transition_dur": self.outro_transition_dur_var.get(), "duration": self.duration_var.get(), "encoder": self.encoder_var.get(), "crf": self.crf_var.get(), "layers": [l.to_dict() for l in self.layers]}

    def save_project(self):
        p = filedialog.asksaveasfilename(defaultextension=".vproj", filetypes=[("Video Studio Proje", "*.vproj"), ("JSON", "*.json")])
        if not p: return
        with open(p, "w", encoding="utf-8") as f: json.dump(self.project_data(), f, ensure_ascii=False, indent=2)
        self.log(f"Proje kaydedildi: {p}\n")

    def open_project(self):
        p = filedialog.askopenfilename(filetypes=[("Video Studio Proje", "*.vproj *.json"), ("Tüm dosyalar", "*.*")])
        if not p: return
        with open(p, "r", encoding="utf-8") as f: data = json.load(f)
        self.project_format.set(data.get("format", "Instagram Story 9:16")); self.change_format()
        self.bg_path.set(data.get("bg", "")); self.audio_path.set(data.get("audio", "")); self.outro_image_path.set(data.get("outro_image", "")); self.outro_audio_path.set(data.get("outro_audio", "")); self.outro_duration_var.set(float(data.get("outro_duration", 4))); self.outro_transition_var.set(data.get("outro_transition", "Smooth Left")); self.outro_transition_dur_var.set(float(data.get("outro_transition_dur", 0.7))); self.duration_var.set(float(data.get("duration", 8))); self.sync_duration_to_layers()
        self.encoder_var.set(data.get("encoder", "libx264")); self.crf_var.set(int(data.get("crf", 23)))
        self.layers = []
        for d in data.get("layers", []):
            if os.path.exists(d.get("path", "")):
                l = Layer.from_dict(d, self.project_w, self.project_h); self.layers.append(l); self.make_thumb(l)
        self.selected = None; self.refresh_layer_list(); self.refresh_canvas(); self.log(f"Proje açıldı: {p}\n")


if __name__ == "__main__":
    App().mainloop()
