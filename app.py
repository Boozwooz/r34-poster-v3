"""
BoozStudio — R34 Poster  v3.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
100% vibe-coded. AI-assisted from start to finish.

Critical WD14 bug fix (v1/v2 → v3):
  In v1/v2, WD14 tags were completely off-topic.
  Root cause: the CSV contains all categories (~12,000 rows).
  The model outputs one probability per row, in CSV order.
  Filtering the CSV BEFORE building the internal tag list shifted
  all indices → completely wrong tags.
  Fix: load ALL rows, filter by category==0 at inference time
  using the original index.
"""

import customtkinter as ctk
from tkinter import filedialog, messagebox
import tkinter as tk
import re, json, time, threading, queue, logging
from pathlib import Path
from typing import Optional
import requests
from PIL import Image

# ── Logging ─────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("r34")

# ── Endpoints ────────────────────────────────────────────────────
CONFIG_PATH      = Path("config.json")
UPLOAD_ENDPOINT  = "https://rule34.xxx/index.php?page=dapi&s=post&q=index"
AUTOCOMPLETE_URL = "https://rule34.xxx/public/autocomplete.php?q={prefix}"

# ── Modern Color Palette (Cyber/Discord-inspired) ─────────────────
BG      = "#0E0E11"   # ultra-dark main background
SURFACE = "#18181C"   # cards, panels
PANEL   = "#202025"   # inputs, sunken areas
BORDER  = "#2A2A31"   # subtle borders
ACCENT  = "#6366F1"   # indigo/violet (Vercel/Stripe style)
GREEN   = "#10B981"   # success (emerald)
YELLOW  = "#F59E0B"   # warning (amber)
RED     = "#EF4444"   # error (rose/red)
TEXT1   = "#F4F4F5"   # primary text
TEXT2   = "#A1A1AA"   # secondary text
TEXT3   = "#52525B"   # disabled/placeholder text

# Status badge styles (text_color, fg_color)
STATUS_STYLES: dict[str, tuple[str, str]] = {
    "Pending":          (TEXT3,  PANEL),
    "Tagged":           (GREEN,  "#062817"),
    "Cleaned":          (ACCENT, "#171633"),
    "Validated ✓":      (GREEN,  "#062817"),
    "⚠ Unknown Tags":   (YELLOW, "#332107"),
    "Uploading…":       (YELLOW, "#332107"),
    "Success ✓":        (GREEN,  "#062817"),
    "Error ✗":          (RED,    "#300E0E"),
}

# Tag type colors in autocomplete dropdown
TYPE_CLR = {
    "general":   "#6ab0de",
    "character": "#7ec88e",
    "copyright": "#c678dd",
    "artist":    "#e06c75",
    "metadata":  TEXT2,
}

# Tags automatically stripped during cleaning
TAG_BLACKLIST = {
    "masterpiece","best_quality","absurdres","highres","ultra-detailed",
    "ultra_detailed","8k","4k","2k","hdr","high_resolution","bad_hands",
    "bad_anatomy","bad_prompt","realistic","photorealistic","nsfw","sfw",
    "score_9","score_8","score_7","score_6","score_5","score_4","score_3",
    "score_2","score_1","score_9_up","score_8_up","score_7_up","score_6_up",
    "aesthetic_score","aesthetic","quality",
}
LORA_RE = re.compile(r"<lora:[^>]+>|lora:[^\s,]+", re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════
#  Config  (keys compatible with config.json)
# ═══════════════════════════════════════════════════════════════
def load_config() -> dict:
    defaults = {
        "user_id": "", "api_key": "", "artist": "",
        "global_tags": "rating:explicit",
        "global_source": "", "delay": 6, "wd14_threshold": 0.35,
        "ai_generated": True,
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                defaults.update(json.load(f))
        except Exception as e:
            log.warning(f"config.json unreadable: {e}")
    else:
        # Auto-create config.json on first launch
        save_config(defaults)
        log.info("config.json created with default values.")
    return defaults


def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.error(f"Failed to save config: {e}")


# ═══════════════════════════════════════════════════════════════
#  Tag cleaning & assembly
# ═══════════════════════════════════════════════════════════════
def clean_tags(raw: str) -> str:
    """Normalize, deduplicate, and apply blacklist."""
    raw = LORA_RE.sub("", raw)
    tokens = re.split(r"[\s,]+", raw.strip())
    seen, result = set(), []
    for tok in tokens:
        tok = re.sub(r"[\"'\.]+", "", tok.lower().strip()).replace(" ", "_")
        if not tok or len(tok) < 2:
            continue
        if tok in TAG_BLACKLIST:
            continue
        if tok.startswith(("score_", "aesthetic_")):
            continue
        if tok in seen:
            continue
        seen.add(tok)
        result.append(tok)
    return " ".join(result)


def normalize_artist(artist: str) -> str:
    a = artist.strip().lower().replace(" ", "_")
    return f"{a}_(artist)" if a and not a.endswith("_(artist)") else a


def assemble_tags(global_tags: str, artist: str, char: str, desc: str,
                  ai_generated: bool = False) -> str:
    """
    Booru tag order: ai_generated (optional, first) → global → artist → char/series → desc
    """
    parts = ["ai_generated"] if ai_generated else []
    for t in global_tags.split():
        if t and t != "ai_generated":
            parts.append(t)
    if artist:
        parts.append(normalize_artist(artist))
    if char:
        parts.extend(clean_tags(char).split())
    if desc:
        parts.extend(clean_tags(desc).split())
    seen, final = set(), []
    for t in parts:
        if t not in seen:
            seen.add(t)
            final.append(t)
    return " ".join(final)


# ═══════════════════════════════════════════════════════════════
#  WD14 Tagger (ONNX) — Critical Index Fix
# ═══════════════════════════════════════════════════════════════
class WD14Tagger:
    """
    SmilingWolf/wd-v1-4-vit-tagger-v2 via onnxruntime.

    Critical bug fix (v1/v2 → v3):
    selected_tags.csv contains tags from ALL categories
    (0=general, 1=artist, 2=copyright, 3=character, 4=metadata).
    The model outputs a probability vector of length = total CSV rows.
    Index i in probs[] corresponds to row i of the CSV.
    In v1/v2, filtering by category=="0" BEFORE building self._tags
    shrank the list — indices no longer matched probabilities → wrong tags.
    FIX: load ALL rows, filter cat=="0" only at inference time using original index.
    """
    REPO = "SmilingWolf/wd-v1-4-vit-tagger-v2"
    SIZE = 448
    _lock   = threading.Lock()
    _loaded = False
    _sess   = None
    _tags:  list[str] = []   # one entry per CSV row (index preserved)
    _cats:  list[str] = []   # corresponding category

    @classmethod
    def _load(cls) -> bool:
        with cls._lock:
            if cls._loaded:
                return True
            try:
                from huggingface_hub import hf_hub_download
                import onnxruntime as ort, csv as csv_mod

                log.info("Loading WD14 model…")
                model_p = hf_hub_download(cls.REPO, "model.onnx")
                tags_p  = hf_hub_download(cls.REPO, "selected_tags.csv")

                avail = ort.get_available_providers()
                if "CUDAExecutionProvider" in avail:
                    prov = ["CUDAExecutionProvider", "CPUExecutionProvider"]
                    log.info("WD14 → CUDA GPU")
                elif "DmlExecutionProvider" in avail:
                    prov = ["DmlExecutionProvider", "CPUExecutionProvider"]
                    log.info("WD14 → DirectML GPU")
                else:
                    prov = ["CPUExecutionProvider"]
                    log.info("WD14 → CPU")

                cls._sess = ort.InferenceSession(model_p, providers=prov)

                # Load ALL rows (no filtering here — preserve indices!)
                with open(tags_p, newline="", encoding="utf-8") as f:
                    rows = list(csv_mod.DictReader(f))
                cls._tags = [r["name"] for r in rows]
                cls._cats = [r.get("category", "0") for r in rows]

                cls._loaded = True
                n0 = sum(1 for c in cls._cats if c == "0")
                log.info(f"WD14 ready — {len(cls._tags)} total tags, {n0} general (cat 0)")
                return True
            except Exception as e:
                log.error(f"WD14 error: {e}")
                return False

    @classmethod
    def predict(cls, path: str, threshold: float = 0.35) -> list[str]:
        import numpy as np
        if not cls._load():
            raise RuntimeError("WD14 model unavailable")

        img = Image.open(path)
        if img.mode != "RGB":
            img = img.convert("RGB")
        canvas = Image.new("RGB", (cls.SIZE, cls.SIZE), (255, 255, 255))
        img.thumbnail((cls.SIZE, cls.SIZE), Image.LANCZOS)
        canvas.paste(img, ((cls.SIZE - img.width) // 2,
                           (cls.SIZE - img.height) // 2))
        arr = np.array(canvas, dtype=np.float32)[:, :, ::-1][None]  # BGR

        inp  = cls._sess.get_inputs()[0].name
        prob = cls._sess.run(None, {inp: arr})[0][0]

        # Correct filtering: use original index → category 0 only
        return [
            cls._tags[i]
            for i, p in enumerate(prob)
            if p >= threshold
            and i < len(cls._tags)
            and cls._cats[i] == "0"
        ]


# ═══════════════════════════════════════════════════════════════
#  Rule34 Tag Validator
# ═══════════════════════════════════════════════════════════════
class TagValidator:
    """Checks tag existence via rule34.xxx autocomplete API."""
    _cache: dict[str, bool] = {}
    _lock = threading.Lock()
    SKIP = frozenset({
        "ai_generated", "rating:explicit", "rating:safe",
        "rating:questionable", "rating:general", "rating:sensitive",
    })

    @classmethod
    def exists(cls, tag: str) -> bool:
        tag = tag.lower().strip()
        if not tag or len(tag) < 2:
            return True
        if tag in cls.SKIP or tag.startswith("rating:"):
            return True
        with cls._lock:
            if tag in cls._cache:
                return cls._cache[tag]
        ok = True
        try:
            r = requests.get(
                AUTOCOMPLETE_URL.format(prefix=tag), timeout=6,
                headers={"User-Agent": "R34Uploader/3.0"}
            )
            if r.ok:
                ok = any(x.get("value", "").lower() == tag for x in r.json())
        except Exception:
            pass  # network unavailable → optimistic
        with cls._lock:
            cls._cache[tag] = ok
        return ok

    @classmethod
    def check_string(cls, s: str) -> list[str]:
        return [t for t in re.split(r"[\s,]+", s.strip())
                if t.strip() and len(t.strip()) >= 2
                and not cls.exists(t.strip())]


# ═══════════════════════════════════════════════════════════════
#  Tooltip helper
# ═══════════════════════════════════════════════════════════════
class Tooltip:
    """Simple hover tooltip for any widget."""
    def __init__(self, widget, text: str):
        self._widget = widget
        self._text   = text
        self._tip    = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _):
        if self._tip:
            return
        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.attributes("-topmost", True)
        tk.Label(
            self._tip, text=self._text, bg="#1e1e28", fg=TEXT2,
            font=("Segoe UI", 9), padx=8, pady=5,
            relief="flat", wraplength=280,
        ).pack()
        self._tip.geometry(f"+{x}+{y}")

    def _hide(self, _):
        if self._tip:
            self._tip.destroy()
            self._tip = None


# ═══════════════════════════════════════════════════════════════
#  AutocompleteEntry
# ═══════════════════════════════════════════════════════════════
class AutocompleteEntry(ctk.CTkFrame):
    """
    CTkEntry enhanced with a real-time Rule34 suggestion popup.
    Completes only the last token being typed.
    """
    DEBOUNCE  = 350
    MAX       = 12
    MIN_CHARS = 2

    def __init__(self, parent, placeholder="", height=30, **kw):
        super().__init__(parent, fg_color="transparent", height=height, **kw)
        self.columnconfigure(0, weight=1)
        self._e = ctk.CTkEntry(
            self, placeholder_text=placeholder, height=height,
            fg_color=PANEL, border_color=BORDER,
            text_color=TEXT1, placeholder_text_color=TEXT3,
        )
        self._e.grid(row=0, column=0, sticky="ew")

        self._pop:   Optional[tk.Toplevel] = None
        self._lb:    Optional[tk.Listbox]  = None
        self._job:   Optional[str]         = None
        self._cache: dict[str, list]       = {}
        self._items: list                  = []
        self._busy   = False

        self._e.bind("<KeyRelease>", self._key)
        self._e.bind("<Down>",       self._focus_lb)
        self._e.bind("<Escape>",     lambda e: self._hide())
        self._e.bind("<FocusOut>",   lambda e: self.after(200, self._maybe_hide))

    # ── Proxy ──────────────────────────────────────────────────
    def get(self):             return self._e.get()
    def delete(self, s, e="end"): self._e.delete(s, e)
    def insert(self, i, s):    self._e.insert(i, s)
    def bind(self, ev, fn, add=None): self._e.bind(ev, fn, add)
    def configure(self, **kw):
        try: self._e.configure(**kw)
        except: super().configure(**kw)

    # ── Current word (last token) ───────────────────────────────
    def _word(self) -> str:
        t = self._e.get()
        return t.rsplit(" ", 1)[-1].strip() if t.strip() else ""

    # ── Key handling ────────────────────────────────────────────
    def _key(self, ev):
        NAV = {"Return","Tab","Up","Down","Left","Right",
               "Escape","Shift_L","Shift_R","Control_L","Control_R"}
        if ev.keysym in NAV:
            if ev.keysym == "Return": self._hide()
            return
        if self._job: self.after_cancel(self._job)
        w = self._word()
        if len(w) < self.MIN_CHARS:
            self._hide()
            return
        self._job = self.after(self.DEBOUNCE, lambda: self._fetch(w))

    def _fetch(self, prefix: str):
        if prefix in self._cache:
            self._show(self._cache[prefix])
            return
        threading.Thread(target=self._req, args=(prefix,), daemon=True).start()

    def _req(self, prefix: str):
        try:
            r = requests.get(AUTOCOMPLETE_URL.format(prefix=prefix),
                             timeout=5, headers={"User-Agent": "R34Uploader/3.0"})
            data = r.json()[:self.MAX] if r.ok else []
        except Exception:
            data = []
        self._cache[prefix] = data
        self.after(0, lambda: self._show(data))

    # ── Popup ───────────────────────────────────────────────────
    def _show(self, items: list):
        if not items:
            self._hide()
            return
        self._items = items

        if self._pop is None or not self._pop.winfo_exists():
            self._pop = tk.Toplevel(self)
            self._pop.wm_overrideredirect(True)
            self._pop.attributes("-topmost", True)
            frm = tk.Frame(self._pop, bg=SURFACE,
                           highlightthickness=1, highlightbackground=ACCENT)
            frm.pack(fill="both", expand=True)
            self._lb = tk.Listbox(
                frm, bg=SURFACE, fg=TEXT1,
                selectbackground="#1f3d6e", selectforeground=TEXT1,
                font=("Segoe UI", 10), relief="flat", bd=0,
                activestyle="none", exportselection=False,
            )
            self._lb.pack(fill="both", expand=True, padx=1, pady=1)
            self._lb.bind("<ButtonPress-1>", self._pick)
            self._lb.bind("<Return>",        self._pick)
            self._lb.bind("<Up>",            self._lb_up)
            self._lb.bind("<Down>",          self._lb_down)
            self._lb.bind("<Escape>",
                lambda e: (self._hide(), self._e.focus_set()))

        ICON = {"general":"○","character":"◆","copyright":"◇",
                "artist":"★","metadata":"·"}
        self._lb.delete(0, "end")
        for it in items:
            tp = it.get("type", "general")
            self._lb.insert("end", f"  {ICON.get(tp,'○')}  {it.get('label', it.get('value',''))}")
        for i, it in enumerate(items):
            self._lb.itemconfig(i, foreground=TYPE_CLR.get(
                it.get("type","general"), TEXT2))

        try:
            self.update_idletasks()
            x = self._e.winfo_rootx()
            y = self._e.winfo_rooty() + self._e.winfo_height() + 2
            w = max(self._e.winfo_width(), 280)
            h = min(len(items) * 24 + 4, 260)
            self._pop.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _hide(self):
        if self._pop and self._pop.winfo_exists():
            self._pop.destroy()
        self._pop = None
        self._lb  = None

    def _maybe_hide(self):
        if self._busy:
            return
        try:
            if self.winfo_toplevel().focus_get() == self._lb:
                return
        except Exception:
            pass
        self._hide()

    def _pick(self, ev):
        """Click or Enter on a suggestion → complete the current token."""
        self._busy = True
        if ev.type == tk.EventType.ButtonPress:
            idx = self._lb.nearest(ev.y)
            self._lb.selection_clear(0, "end")
            self._lb.selection_set(idx)
        else:
            sel = self._lb.curselection()
            idx = sel[0] if sel else None
        self.after(10, lambda: self._complete(idx))

    def _complete(self, idx):
        if idx is None or not self._items:
            self._busy = False
            return
        val = self._items[idx].get("value", "") if idx < len(self._items) else ""
        if not val:
            self._busy = False
            return
        text = self._e.get()
        new  = (text.rsplit(" ",1)[0] + " " + val + " ") if " " in text.rstrip() \
               else val + " "
        self._e.delete(0, "end")
        self._e.insert(0, new)
        self._hide()
        self._busy = False
        self._e.focus_set()

    def _focus_lb(self, ev):
        if self._lb and self._lb.winfo_exists():
            self._lb.focus_set()
            self._lb.selection_set(0)
        return "break"

    def _lb_up(self, ev):
        sel = self._lb.curselection()
        if sel and sel[0] > 0:
            self._lb.selection_clear(0,"end")
            self._lb.selection_set(sel[0]-1)
        return "break"

    def _lb_down(self, ev):
        sel  = self._lb.curselection()
        last = self._lb.size() - 1
        if sel and sel[0] < last:
            self._lb.selection_clear(0,"end")
            self._lb.selection_set(sel[0]+1)
        return "break"


# ═══════════════════════════════════════════════════════════════
#  ImageCard — compact modern image card
# ═══════════════════════════════════════════════════════════════
class ImageCard(ctk.CTkFrame):
    def __init__(self, parent, filepath: str, on_remove, **kw):
        super().__init__(parent, corner_radius=8,
                         fg_color=SURFACE, border_color=BORDER,
                         border_width=1, **kw)
        self.filepath  = filepath
        self.on_remove = on_remove
        self._ref      = None
        self._has_val  = False
        self._build()
        self.set_status("Pending")

    def _build(self):
        self.columnconfigure(1, weight=1)

        # ── Thumbnail ─────────────────────────────────────────────
        try:
            img = Image.open(self.filepath)
            img.thumbnail((56, 56), Image.LANCZOS)
            self._ref = ctk.CTkImage(img, size=(56, 56))
            thumb = ctk.CTkLabel(self, image=self._ref, text="")
        except Exception:
            thumb = ctk.CTkLabel(self, text="?", width=56, height=56,
                                  fg_color=PANEL, corner_radius=6,
                                  text_color=TEXT3)
        thumb.grid(row=0, column=0, rowspan=7,
                   padx=(10, 8), pady=10, sticky="n")

        # ── Header: filename + badge + remove button ──────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=1, sticky="ew", padx=(0,10), pady=(10,3))
        hdr.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            hdr, text=Path(self.filepath).name,
            text_color=TEXT1, anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=0, sticky="ew")

        self._badge = ctk.CTkLabel(
            hdr, text="Pending", text_color=TEXT3,
            fg_color=PANEL, corner_radius=5,
            font=ctk.CTkFont(size=10, weight="bold"),
            width=120, height=20, padx=8,
        )
        self._badge.grid(row=0, column=1, padx=(8, 0))

        remove_btn = ctk.CTkButton(
            hdr, text="✕", width=22, height=22, corner_radius=4,
            fg_color="#200808", hover_color=RED, text_color="#cc4444",
            command=lambda: self.on_remove(self),
        )
        remove_btn.grid(row=0, column=2, padx=(6, 0))
        Tooltip(remove_btn, "Remove this image from the list")

        # ── Input fields ──────────────────────────────────────────
        self.char_entry = AutocompleteEntry(
            self,
            placeholder="👤  Character & Series  (e.g. gojo_satoru  jujutsu_kaisen)",
            height=30,
        )
        self.char_entry.grid(row=1, column=1, sticky="ew",
                              padx=(0,10), pady=(0,1))
        ctk.CTkLabel(
            self, text="  Include both the character name AND the series name, separated by a space.",
            text_color=TEXT3, font=ctk.CTkFont(size=9), anchor="w",
        ).grid(row=2, column=1, sticky="ew", padx=(0,10), pady=(0,4))

        self.tags_entry = AutocompleteEntry(
            self,
            placeholder="🏷  Descriptive Tags  (autocomplete active — type to see suggestions)",
            height=30,
        )
        self.tags_entry.grid(row=3, column=1, sticky="ew",
                              padx=(0,10), pady=(0,1))
        ctk.CTkLabel(
            self, text="  Separate tags with spaces · Use underscores for multi-word tags (e.g. blue_eyes, big_breasts)",
            text_color=TEXT3, font=ctk.CTkFont(size=9), anchor="w",
        ).grid(row=4, column=1, sticky="ew", padx=(0,10), pady=(0,4))

        self.src_entry = ctk.CTkEntry(
            self,
            placeholder_text="🔗  Source URL  (link to the original post/tweet where you published this image — optional)",
            height=26,
            fg_color=PANEL, border_color=BORDER,
            text_color=TEXT1, placeholder_text_color=TEXT3,
        )
        self.src_entry.grid(row=5, column=1, sticky="ew",
                             padx=(0,10), pady=(0,10))

        # Validation label (hidden until validation runs)
        self._val_lbl = ctk.CTkLabel(
            self, text="", anchor="w",
            font=ctk.CTkFont(size=10), text_color=YELLOW,
            wraplength=500,
        )

    # ── Public API ─────────────────────────────────────────────
    def set_status(self, s: str):
        fg, bg = STATUS_STYLES.get(s, (TEXT3, PANEL))
        self._badge.configure(text=s, text_color=fg, fg_color=bg)

    def show_validation(self, unknown: list[str]):
        if unknown:
            self._val_lbl.configure(
                text=f"⚠  Not found on Rule34 (typo? or tag doesn't exist yet): {', '.join(unknown)}",
                text_color=YELLOW,
            )
            self.set_status("⚠ Unknown Tags")
        else:
            self._val_lbl.configure(
                text="✓  All tags exist on Rule34 — good to go!",
                text_color=GREEN,
            )
            self.set_status("Validated ✓")
        if not self._has_val:
            self._val_lbl.grid(row=6, column=1, sticky="ew",
                                padx=(0,10), pady=(0,8))
            self._has_val = True

    def get_tags(self)   -> str: return self.tags_entry.get().strip()
    def get_char(self)   -> str: return self.char_entry.get().strip()
    def get_source(self) -> str: return self.src_entry.get().strip()

    def set_tags(self, t: str):
        self.tags_entry.delete(0, "end")
        self.tags_entry.insert(0, t)

    def set_char(self, t: str):
        self.char_entry.delete(0, "end")
        self.char_entry.insert(0, t)

    def set_source(self, t: str):
        self.src_entry.delete(0, "end")
        self.src_entry.insert(0, t)


# ═══════════════════════════════════════════════════════════════
#  Main Application
# ═══════════════════════════════════════════════════════════════
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.configure(fg_color=BG)

        self.title("BoozStudio — R34 Poster  v3.0")
        self.geometry("1320x860")
        self.minsize(1040, 660)

        self._cfg   = load_config()
        self._cards: list[ImageCard] = []
        self._q     = queue.Queue()
        self._uploading = False

        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main()
        self._load_cfg()
        self._dispatcher()
        self.protocol("WM_DELETE_WINDOW", self._close)

        # Keyboard shortcuts
        self.bind("<Control-o>", lambda e: self._load())
        self.bind("<Control-s>", lambda e: self._save())

    # ══════════════════════════════════════════════════════════
    #  Sidebar
    # ══════════════════════════════════════════════════════════
    def _build_sidebar(self):
        outer = ctk.CTkFrame(self, width=290, corner_radius=0,
                              fg_color="#090d13")
        outer.grid(row=0, column=0, sticky="nsew")
        outer.grid_propagate(False)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        sb = ctk.CTkScrollableFrame(
            outer, fg_color="transparent",
            scrollbar_button_color=PANEL,
            scrollbar_button_hover_color=BORDER,
        )
        sb.grid(row=0, column=0, sticky="nsew")
        sb.columnconfigure(0, weight=1)
        self._sb = sb

        def sep():
            nonlocal r
            ctk.CTkFrame(sb, height=1, fg_color=BORDER).grid(
                row=r, column=0, sticky="ew", padx=14, pady=6)
            r += 1

        def sec(icon, title):
            nonlocal r
            ctk.CTkLabel(sb, text=f"{icon}  {title}",
                         text_color=TEXT2, anchor="w",
                         font=ctk.CTkFont(size=11, weight="bold")).grid(
                row=r, column=0, padx=14, pady=(10,4), sticky="w")
            r += 1

        def lbl(text):
            nonlocal r
            ctk.CTkLabel(sb, text=text, text_color=TEXT3, anchor="w",
                         font=ctk.CTkFont(size=10)).grid(
                row=r, column=0, padx=16, sticky="w", pady=(2,0))
            r += 1

        def ent(var=None, ph="", show="", h=30):
            nonlocal r
            e = ctk.CTkEntry(sb, textvariable=var, placeholder_text=ph,
                             show=show, height=h,
                             fg_color=PANEL, border_color=BORDER,
                             text_color=TEXT1, placeholder_text_color=TEXT3)
            e.grid(row=r, column=0, padx=12, pady=(1,2), sticky="ew")
            r += 1
            return e

        r = 0

        # ── Title ────────────────────────────────────────────────
        ctk.CTkLabel(sb, text="BoozStudio",
                     text_color=ACCENT,
                     font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=r, column=0, padx=16, pady=(18,0), sticky="w"); r+=1
        ctk.CTkLabel(sb, text="R34 Poster",
                     text_color=TEXT1,
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=r, column=0, padx=16, pady=(0,2), sticky="w"); r+=1
        ctk.CTkLabel(sb, text="v3.0  •  Batch Tagger & Uploader",
                     text_color=TEXT3, font=ctk.CTkFont(size=10)).grid(
            row=r, column=0, padx=16, pady=(0,6), sticky="w"); r+=1
        sep()

        # ── Account ──────────────────────────────────────────────
        sec("🔑", "Rule34 Account")

        # Login info box
        info_box = ctk.CTkFrame(sb, fg_color="#0d1f0d", corner_radius=8,
                                border_color="#1a4a1a", border_width=1)
        info_box.grid(row=r, column=0, padx=12, pady=(0, 8), sticky="ew"); r+=1
        info_box.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            info_box,
            text="How login works:",
            text_color=GREEN, anchor="w",
            font=ctk.CTkFont(size=10, weight="bold"),
        ).grid(row=0, column=0, padx=10, pady=(8, 2), sticky="w")

        ctk.CTkLabel(
            info_box,
            text=(
                "1. Click  Start Upload\n"
                "2. A browser window opens\n"
                "3. Log in to Rule34 once\n"
                "4. Your session is saved\n"
                "    automatically forever"
            ),
            text_color=TEXT2, anchor="w", justify="left",
            font=ctk.CTkFont(size=10),
        ).grid(row=1, column=0, padx=10, pady=(0, 8), sticky="w")

        ctk.CTkLabel(
            info_box,
            text="No need to enter your password\nin the app — ever.",
            text_color=TEXT3, anchor="w", justify="left",
            font=ctk.CTkFont(size=9),
        ).grid(row=2, column=0, padx=10, pady=(0, 8), sticky="w")

        sep()

        # ── Content ──────────────────────────────────────────────
        sec("🎨", "Content")

        # AI Generated checkbox
        self.ai_gen_var = ctk.BooleanVar(value=True)
        ai_cb = ctk.CTkCheckBox(
            sb, text="🤖  AI Generated Content",
            variable=self.ai_gen_var,
            checkbox_width=18, checkbox_height=18,
            corner_radius=4,
            fg_color=ACCENT, hover_color="#4f52d4",
            text_color=TEXT1, font=ctk.CTkFont(size=11),
        )
        ai_cb.grid(row=r, column=0, padx=14, pady=(4, 8), sticky="w"); r+=1
        Tooltip(ai_cb, "Check this if the images are AI-generated.\nAdds the 'ai_generated' tag automatically.")

        lbl("Artist")
        self.artist_var = ctk.StringVar()
        art_entry = ent(self.artist_var, "name  (_(artist) appended automatically)")
        Tooltip(art_entry, "Your artist name. The suffix _(artist) is\nadded automatically to match booru format.")

        # Warning box for artist tag
        art_warn = ctk.CTkFrame(sb, fg_color="#1f1500", corner_radius=6,
                                border_color="#3d2a00", border_width=1)
        art_warn.grid(row=r, column=0, padx=12, pady=(0, 6), sticky="ew"); r+=1
        art_warn.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            art_warn,
            text="⚠  The artist tag must already exist\n"
                 "on Rule34 or the upload will fail.\n"
                 "It is NOT checked by  ④  Validate.",
            text_color=YELLOW, anchor="w", justify="left",
            font=ctk.CTkFont(size=9),
        ).grid(row=0, column=0, padx=8, pady=6, sticky="w")

        lbl("Global Tags")
        self.gtags_var = ctk.StringVar()
        gtags_entry = ent(self.gtags_var, "rating:explicit")
        Tooltip(gtags_entry, "Tags applied to every image.\nSeparate with spaces.")

        # Rating tags mini-legend
        rating_box = ctk.CTkFrame(sb, fg_color="#111118", corner_radius=6,
                                   border_color=BORDER, border_width=1)
        rating_box.grid(row=r, column=0, padx=12, pady=(0,6), sticky="ew"); r+=1
        rating_box.columnconfigure(0, weight=1)
        ctk.CTkLabel(rating_box, text="Rating tag — pick one:",
                     text_color=TEXT3, font=ctk.CTkFont(size=9, weight="bold"),
                     anchor="w").grid(row=0, column=0, padx=8, pady=(5,2), sticky="w")
        ratings_row = ctk.CTkFrame(rating_box, fg_color="transparent")
        ratings_row.grid(row=1, column=0, padx=6, pady=(0,6), sticky="w")
        for col, (tag, color, desc) in enumerate([
            ("rating:explicit",      RED,    "18+ / NSFW"),
            ("rating:questionable",  YELLOW, "Suggestive"),
            ("rating:safe",          GREEN,  "Safe / SFW"),
        ]):
            f = ctk.CTkFrame(ratings_row, fg_color="transparent")
            f.grid(row=0, column=col, padx=(0,8))
            ctk.CTkLabel(f, text=tag, text_color=color,
                         font=ctk.CTkFont(size=8, weight="bold")).pack(anchor="w")
            ctk.CTkLabel(f, text=desc, text_color=TEXT3,
                         font=ctk.CTkFont(size=8)).pack(anchor="w")

        lbl("Global Source URL")
        self.gsrc_var = ctk.StringVar()
        src_entry = ent(self.gsrc_var, "https://…  (optional, applied to all images)")
        Tooltip(src_entry, "Where did you originally post these images?\n(e.g. your Twitter/X, Pixiv, or Patreon link)\nThis is shown on Rule34 as the image source.\nCan be overridden per-image in each card.")
        sep()

        # ── Settings ─────────────────────────────────────────────
        sec("⚙", "Settings")

        self.delay_var = ctk.IntVar(value=6)
        lbl("Wait time between uploads  (anti-ban)")
        drow = ctk.CTkFrame(sb, fg_color="transparent")
        drow.grid(row=r, column=0, padx=12, sticky="ew", pady=(2,2)); r+=1
        drow.columnconfigure(0, weight=1)
        self._dlbl = ctk.CTkLabel(drow, text="6 s", width=38, text_color=ACCENT,
                                   font=ctk.CTkFont(size=13, weight="bold"))
        self._dlbl.grid(row=0, column=1, padx=(8,0))
        delay_slider = ctk.CTkSlider(drow, from_=3, to=30, number_of_steps=27,
                       variable=self.delay_var, button_color=ACCENT,
                       progress_color="#1a3a6a",
                       command=lambda v: self._dlbl.configure(
                           text=f"{int(float(v))} s"))
        delay_slider.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(sb, text="  Too low = risk of ban. 6s is safe for most cases.",
                     text_color=TEXT3, font=ctk.CTkFont(size=9), anchor="w").grid(
            row=r, column=0, padx=14, pady=(0,6), sticky="w"); r+=1

        self.thresh_var = ctk.DoubleVar(value=0.35)
        lbl("AI Tagger Sensitivity  (WD14)")
        trow = ctk.CTkFrame(sb, fg_color="transparent")
        trow.grid(row=r, column=0, padx=12, sticky="ew", pady=(2,2)); r+=1
        trow.columnconfigure(0, weight=1)
        self._tlbl = ctk.CTkLabel(trow, text="0.35", width=38, text_color=ACCENT,
                                   font=ctk.CTkFont(size=13, weight="bold"))
        self._tlbl.grid(row=0, column=1, padx=(8,0))
        thresh_slider = ctk.CTkSlider(trow, from_=0.15, to=0.70, number_of_steps=55,
                       variable=self.thresh_var, button_color=ACCENT,
                       progress_color="#1a3a6a",
                       command=lambda v: self._tlbl.configure(
                           text=f"{float(v):.2f}"))
        thresh_slider.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(sb,
                     text="  0.20 = lots of tags   0.35 = balanced   0.60 = few tags\n"
                          "  Start at 0.35 — adjust if results are too noisy or sparse.",
                     text_color=TEXT3, font=ctk.CTkFont(size=9),
                     anchor="w", justify="left").grid(
            row=r, column=0, padx=14, pady=(0,8), sticky="w"); r+=1
        sep()

        # ── Numbered action buttons ───────────────────────────────
        sec("▶", "Workflow")

        def action_btn(num, label, cmd, bg, hover, h=34, tip=""):
            nonlocal r
            f = ctk.CTkFrame(sb, fg_color="transparent")
            f.grid(row=r, column=0, padx=12, pady=2, sticky="ew"); r+=1
            f.columnconfigure(1, weight=1)
            ctk.CTkLabel(f, text=num, width=24, height=24,
                         fg_color=bg, corner_radius=12,
                         text_color="white",
                         font=ctk.CTkFont(size=10, weight="bold")).grid(
                row=0, column=0, padx=(0,8))
            btn = ctk.CTkButton(f, text=label, command=cmd, height=h,
                          corner_radius=6, fg_color=bg, hover_color=hover,
                          text_color=TEXT1,
                          font=ctk.CTkFont(size=12))
            btn.grid(row=0, column=1, sticky="ew")
            if tip:
                Tooltip(btn, tip)

        action_btn("①", "Load Images  (Ctrl+O)", self._load, "#1a3050", "#243e6a",
                   tip="Open a file picker to add images to the queue.")
        action_btn("②", "AI Auto-Tag  (WD14)",   self._autotag, "#102438", "#183450",
                   tip="Run the WD14 ONNX tagger on every image.\nFirst run downloads ~680 MB from HuggingFace.")
        action_btn("③", "Clean Tags",              self._clean, "#0e2818", "#163820",
                   tip="Normalize, deduplicate, and remove blacklisted tags\n(quality scores, LoRA tokens, etc.)")
        action_btn("④", "Validate on Rule34",       self._validate, "#2a2006", "#3a2c08",
                   tip="Check every tag against Rule34's autocomplete API.\nUnknown tags are highlighted in amber.")

        # Main upload button (prominent)
        self._upload_btn = ctk.CTkButton(
            sb, text="⑤   Start Upload",
            command=self._upload, height=42, corner_radius=8,
            fg_color="#125412", hover_color="#1a7a1a",
            text_color="white",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self._upload_btn.grid(row=r, column=0, padx=12, pady=(4,2), sticky="ew"); r+=1
        Tooltip(self._upload_btn, "Open a browser window and upload all images.\nYou may need to solve CAPTCHAs manually.")

        ctk.CTkButton(
            sb, text="🗑   Clear List",
            command=self._clear, height=28, corner_radius=6,
            fg_color="#1a0606", hover_color="#2a0c0c", text_color=TEXT3,
            font=ctk.CTkFont(size=11),
        ).grid(row=r, column=0, padx=12, pady=(0,4), sticky="ew"); r+=1
        sep()

        # ── Progress ──────────────────────────────────────────────
        self.pb = ctk.CTkProgressBar(sb, height=6, corner_radius=3,
                                      fg_color=PANEL, progress_color=ACCENT)
        self.pb.set(0)
        self.pb.grid(row=r, column=0, padx=12, sticky="ew"); r+=1

        self._sv = ctk.StringVar(value="Ready")
        ctk.CTkLabel(sb, textvariable=self._sv, text_color=TEXT2,
                     font=ctk.CTkFont(size=10), wraplength=250,
                     justify="left", anchor="w").grid(
            row=r, column=0, padx=16, pady=(4,8), sticky="ew"); r+=1

        save_btn = ctk.CTkButton(
            sb, text="💾  Save Configuration  (Ctrl+S)",
            command=self._save, height=28, corner_radius=6,
            fg_color=PANEL, hover_color=BORDER, text_color=TEXT2,
            font=ctk.CTkFont(size=10),
        )
        save_btn.grid(row=r, column=0, padx=12, pady=(0,6), sticky="ew"); r+=1
        Tooltip(save_btn, "Save current settings to config.json.\nSettings are also auto-saved on exit.")
        sep()

        # ── About ─────────────────────────────────────────────────
        ctk.CTkLabel(sb, text="ℹ  About",
                     text_color=TEXT2, anchor="w",
                     font=ctk.CTkFont(size=11, weight="bold")).grid(
            row=r, column=0, padx=14, pady=(10,4), sticky="w"); r+=1

        ctk.CTkLabel(sb,
                     text="BoozStudio — R34 Poster v3.0\n100% Vibe-Coded  🤖\n\nOpen Source — MIT License",
                     text_color=TEXT3, font=ctk.CTkFont(size=9),
                     anchor="w", justify="left").grid(
            row=r, column=0, padx=16, pady=(0,4), sticky="w"); r+=1

        ctk.CTkButton(
            sb, text="⭐  View on GitHub",
            command=lambda: __import__("webbrowser").open(
                "https://github.com/BoozAIYaoi/r34-poster"),
            height=26, corner_radius=6,
            fg_color=PANEL, hover_color=BORDER, text_color=TEXT2,
            font=ctk.CTkFont(size=10),
        ).grid(row=r, column=0, padx=12, pady=(0,20), sticky="ew"); r+=1

    # ══════════════════════════════════════════════════════════
    #  Main area (batch panel + image cards)
    # ══════════════════════════════════════════════════════════
    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        # ── Batch edit panel ──────────────────────────────────────
        bp = ctk.CTkFrame(main, fg_color=SURFACE, corner_radius=8,
                           border_color=BORDER, border_width=1)
        bp.grid(row=0, column=0, sticky="ew", padx=14, pady=(14,6))
        bp.columnconfigure(0, weight=1)

        # Header row: title + image count badge
        hdr_row = ctk.CTkFrame(bp, fg_color="transparent")
        hdr_row.grid(row=0, column=0, padx=12, pady=(8,4), sticky="ew", columnspan=4)
        hdr_row.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            hdr_row, text="Batch Edit  —  apply to all cards at once",
            text_color=TEXT2, font=ctk.CTkFont(size=11),
        ).grid(row=0, column=0, sticky="w")

        self._count_badge = ctk.CTkLabel(
            hdr_row, text="0 images", text_color=ACCENT,
            fg_color=PANEL, corner_radius=5,
            font=ctk.CTkFont(size=10, weight="bold"),
            width=80, height=20, padx=8,
        )
        self._count_badge.grid(row=0, column=1, padx=(8, 0))

        self._batch_e = ctk.CTkEntry(
            bp, placeholder_text="Common tags to apply to all images...",
            height=30, fg_color=PANEL, border_color=BORDER,
            text_color=TEXT1, placeholder_text_color=TEXT3,
        )
        self._batch_e.grid(row=1, column=0, padx=(12,6), pady=(0,10), sticky="ew")

        for col, (label, cmd, bg, hov, tip) in enumerate([
            ("↺  Replace",  self._batch_replace, "#28154e", "#38206a",
             "Replace tags on every card with the text above."),
            ("＋  Append",   self._batch_append,  "#122040", "#1c2e58",
             "Append the text above to every card's existing tags."),
            ("⊡  Copy #1",   self._copy_first,    "#0e2216", "#183020",
             "Copy the first card's tags & character to all other cards."),
        ], start=1):
            btn = ctk.CTkButton(bp, text=label, command=cmd, width=130,
                          height=30, corner_radius=6, fg_color=bg,
                          hover_color=hov, text_color=TEXT1,
                          font=ctk.CTkFont(size=11))
            btn.grid(row=1, column=col, padx=4, pady=(0,10))
            Tooltip(btn, tip)

        # ── Scrollable card list ──────────────────────────────────
        self._sf = ctk.CTkScrollableFrame(
            main, fg_color=BG, label_text="",
            scrollbar_button_color=PANEL,
            scrollbar_button_hover_color=BORDER,
        )
        self._sf.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0,14))
        self._sf.columnconfigure(0, weight=1)

        self._empty = ctk.CTkFrame(self._sf, fg_color="transparent")
        self._empty.grid(row=0, column=0, pady=80)

        ctk.CTkLabel(
            self._empty, text="📂",
            text_color=TEXT3, font=ctk.CTkFont(size=48),
        ).pack()
        ctk.CTkLabel(
            self._empty, text="No images loaded",
            text_color=TEXT2, font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(pady=(8, 2))
        ctk.CTkLabel(
            self._empty,
            text="Click  ①  Load Images  or press  Ctrl+O  to get started.",
            text_color=TEXT3, font=ctk.CTkFont(size=12),
        ).pack()

    # ══════════════════════════════════════════════════════════
    #  Card management
    # ══════════════════════════════════════════════════════════
    def _refresh(self):
        for i, c in enumerate(self._cards):
            c.grid(row=i, column=0, sticky="ew", pady=(0,6))
        if self._cards:
            self._empty.grid_remove()
        else:
            self._empty.grid(row=0, column=0, pady=80)
        # Update count badge
        n = len(self._cards)
        self._count_badge.configure(text=f"{n} image{'s' if n != 1 else ''}")

    def _remove(self, card: ImageCard):
        card.grid_forget()
        card.destroy()
        self._cards.remove(card)
        self._refresh()

    # ══════════════════════════════════════════════════════════
    #  Workflow actions
    # ══════════════════════════════════════════════════════════
    def _load(self):
        paths = filedialog.askopenfilenames(
            title="Select Images",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp"),
                       ("All Files", "*.*")])
        if not paths:
            return
        existing = {c.filepath for c in self._cards}
        gsrc = self.gsrc_var.get().strip()
        n = 0
        for p in paths:
            if p in existing:
                continue
            card = ImageCard(self._sf, p, self._remove)
            if gsrc:
                card.set_source(gsrc)
            self._cards.append(card)
            n += 1
        self._refresh()
        self._st(f"{n} image(s) loaded — {len(self._cards)} total")

    def _autotag(self):
        if not self._cards:
            messagebox.showinfo("Info", "No images in the queue.")
            return
        # Warn on first run if model is not yet cached
        cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
        model_cached = cache_dir.exists() and any(
            cache_dir.glob("*wd*tagger*")
        )
        if not model_cached and not WD14Tagger._loaded:
            if not messagebox.askyesno(
                "AI Tagger — First Time Setup",
                "The WD14 AI tagger model needs to be downloaded.\n\n"
                "Download size:  ~680 MB  (one-time only)\n"
                "Time:  a few minutes depending on your connection\n\n"
                "After this first download, the model is saved on your\n"
                "computer and reused instantly every time.\n\n"
                "Start the download now?"
            ):
                return
        thr = round(self.thresh_var.get(), 2)
        threading.Thread(target=self._autotag_t, args=(thr,), daemon=True).start()

    def _autotag_t(self, thr: float):
        n = len(self._cards)
        self._q.put(("st", "Loading AI tagger… (first run: downloading ~680 MB, please wait)"))
        for i, c in enumerate(self._cards):
            fname = Path(c.filepath).name
            self._q.put(("st", f"Tagging image {i+1} of {n}  —  {fname}"))
            self._q.put(("pb", i / n))
            try:
                tags = WD14Tagger.predict(c.filepath, thr)
                self._q.put(("set_tags", (c, " ".join(tags))))
                self._q.put(("set_status", (c, "Tagged")))
                self._q.put(("st", f"Image {i+1}/{n} tagged — {len(tags)} tags found  ({fname})"))
                log.info(f"[{i+1}/{n}] {len(tags)} tags → {fname}")
            except Exception as e:
                log.error(f"WD14 error: {e}")
                self._q.put(("set_status", (c, "Error ✗")))
                self._q.put(("st", f"Error tagging {fname} — try again or tag manually"))
        self._q.put(("pb", 1.0))
        self._q.put(("st", f"Done! All {n} image(s) tagged. Run  ③ Clean Tags  next."))

    def _clean(self):
        for c in self._cards:
            c.set_tags(clean_tags(c.get_tags()))
            c.set_char(clean_tags(c.get_char()))
            c.set_status("Cleaned")
        if self._cards:
            self._st(f"Tags cleaned — {len(self._cards)} image(s)")

    def _validate(self):
        if not self._cards:
            messagebox.showinfo("Info", "No images in the queue.")
            return
        threading.Thread(target=self._validate_t, daemon=True).start()

    def _validate_t(self):
        n = len(self._cards)
        self._q.put(("st", "Checking tags against Rule34 database…"))
        for i, c in enumerate(self._cards):
            self._q.put(("pb", i / n))
            self._q.put(("st", f"Checking image {i+1} of {n}  —  {Path(c.filepath).name}"))
            unknown = TagValidator.check_string(c.get_char() + " " + c.get_tags())
            self._q.put(("validation", (c, unknown)))
            time.sleep(0.3)
        self._q.put(("pb", 1.0))
        self._q.put(("st",
            "Validation done! Amber badges = unknown tags (fix or ignore). "
            "Green badges = all good. You can upload now."))

    def _test_connection(self):
        """Quick connectivity check to rule34.xxx."""
        def _check():
            self._q.put(("st", "Testing connection to Rule34.xxx…"))
            try:
                r = requests.get("https://rule34.xxx", timeout=8,
                                 headers={"User-Agent": "R34Uploader/3.0"})
                if r.ok:
                    self._q.put(("st", "✓  Connection to Rule34.xxx OK"))
                    self.after(0, lambda: messagebox.showinfo(
                        "Connection OK",
                        "Successfully reached Rule34.xxx!\n\n"
                        "Note: credential validation only happens during upload."))
                else:
                    self._q.put(("st", f"⚠  Rule34.xxx returned HTTP {r.status_code}"))
            except Exception as e:
                self._q.put(("st", f"✗  Connection failed: {e}"))
                self.after(0, lambda: messagebox.showerror(
                    "Connection Failed",
                    f"Could not reach Rule34.xxx:\n{e}\n\n"
                    "Check your internet connection."))
        threading.Thread(target=_check, daemon=True).start()

    def _upload(self):
        if self._uploading:
            return
        if not self._cards:
            messagebox.showinfo("Info", "No images in the queue.")
            return
        if not messagebox.askyesno(
            "Confirm Upload",
            f"Upload {len(self._cards)} image(s) via browser automation?\n\n"
            f"1. A browser window will open.\n"
            f"2. Log in to Rule34 if prompted (first time only).\n"
            f"3. Solve any CAPTCHA when asked.\n"
            f"4. The tool will handle the rest!"
        ):
            return
        self._clean()
        self._uploading = True
        self._upload_btn.configure(state="disabled", fg_color="#0a2a0a",
                                    text="⑤   Uploading…")
        threading.Thread(target=self._upload_t, daemon=True).start()

    def _upload_t(self):
        art       = self.artist_var.get().strip()
        gtags     = self.gtags_var.get().strip()
        gsrc      = self.gsrc_var.get().strip()
        delay     = self.delay_var.get()
        ai_gen    = self.ai_gen_var.get()
        n         = len(self._cards)
        ok = fail = 0

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self._q.put(("st", "Error: Playwright not installed. Run RUN.bat to fix this."))
            self._q.put(("upload_done", None))
            return

        try:
            with sync_playwright() as p:
                self._q.put(("st", "Opening browser…"))
                browser_data = str(Path("browser_data").absolute())

                # Persistent context — keeps login session saved between runs
                context = p.chromium.launch_persistent_context(
                    user_data_dir=browser_data,
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                    viewport={"width": 1000, "height": 800}
                )
                page = context.pages[0] if context.pages else context.new_page()

                # --- 1. LOGIN CHECK ---
                self._q.put(("st", "Checking login status…"))
                page.goto("https://rule34.xxx/index.php?page=account&s=login",
                          wait_until="domcontentloaded")

                if page.locator('input[name="user"]').is_visible():
                    # Not logged in — let the user do it manually in the browser
                    self._q.put(("st", "Please log in to Rule34 in the browser window. Waiting…"))
                    try:
                        # Wait up to 5 minutes for the user to log in
                        page.wait_for_selector('a[href*="s=logout"]', timeout=300000)
                        self._q.put(("st", "Logged in! Session saved for future uploads."))
                    except Exception:
                        raise RuntimeError("Login timed out. Please try again.")
                else:
                    self._q.put(("st", "Already logged in. Starting uploads…"))

                # --- 2. UPLOADS ---
                for i, c in enumerate(self._cards):
                    fname = Path(c.filepath).name
                    self._q.put(("st", f"Upload {i+1}/{n}  —  {fname}"))
                    self._q.put(("pb", i / n))
                    self._q.put(("set_status", (c, "Uploading…")))

                    tags = assemble_tags(gtags, art, c.get_char(), c.get_tags(),
                                         ai_generated=ai_gen)
                    source = c.get_source() or gsrc

                    # Extract rating from tags
                    rating_val = "e"  # Default: Explicit
                    if "rating:explicit" in tags:
                        rating_val = "e"
                        tags = tags.replace("rating:explicit", "").strip()
                    elif "rating:safe" in tags:
                        rating_val = "s"
                        tags = tags.replace("rating:safe", "").strip()
                    elif "rating:questionable" in tags:
                        rating_val = "q"
                        tags = tags.replace("rating:questionable", "").strip()

                    page.goto("https://rule34.xxx/index.php?page=post&s=add",
                              wait_until="domcontentloaded")

                    self._q.put(("st", f"[{i+1}/{n}] Waiting for upload page (CAPTCHA?)…"))
                    page.wait_for_selector('input[type="file"][name="upload"]', timeout=300000)

                    self._q.put(("st", f"[{i+1}/{n}] Filling in fields…"))
                    page.set_input_files('input[type="file"][name="upload"]',
                                         str(Path(c.filepath).absolute()))
                    page.fill('input[name="source"]', source)
                    page.locator('input[name="tags"], textarea[name="tags"]').fill(tags)

                    try:
                        page.click(f'input[name="rating"][value="{rating_val}"]')
                    except Exception:
                        pass  # Ignore if rating buttons not found

                    self._q.put(("st", f"[{i+1}/{n}] YOUR TURN: solve the CAPTCHA and click Upload!"))

                    try:
                        # Wait up to 1 hour for manual CAPTCHA + submit
                        with page.expect_navigation(timeout=3600000):
                            pass

                        if "s=view" in page.url or "id=" in page.url:
                            ok += 1
                            self._q.put(("set_status", (c, "Success ✓")))
                        else:
                            err_loc = page.locator('#notice, .error, h1:has-text("Error")')
                            if err_loc.is_visible():
                                err = err_loc.first.text_content().strip()
                                fail += 1
                                self._q.put(("set_status", (c, "Error ✗")))
                                log.error(f"Upload error: {err}")
                            else:
                                # No clear error and URL changed — assume success
                                ok += 1
                                self._q.put(("set_status", (c, "Success ✓")))
                    except Exception as e:
                        fail += 1
                        self._q.put(("set_status", (c, "Error ✗")))
                        log.error(f"Error: {e}")

                    if i < n - 1:
                        for s in range(delay, 0, -1):
                            self._q.put(("st", f"Anti-ban pause: {s}s…"))
                            time.sleep(1)

                context.close()

        except Exception as e:
            log.error(f"Playwright error: {e}")
            self._q.put(("st", f"Critical error: {e}"))

        finally:
            self._q.put(("pb", 1.0))
            self._q.put(("st", f"Upload complete — {ok} succeeded, {fail} failed"))
            self._q.put(("upload_done", None))

    # ── Batch edit ───────────────────────────────────────────────
    def _batch_replace(self):
        t = self._batch_e.get().strip()
        if t:
            for c in self._cards:
                c.set_tags(t)

    def _batch_append(self):
        t = self._batch_e.get().strip()
        if t:
            for c in self._cards:
                ex = c.get_tags()
                c.set_tags((ex + " " + t).strip() if ex else t)

    def _copy_first(self):
        if len(self._cards) >= 2:
            tags = self._cards[0].get_tags()
            char = self._cards[0].get_char()
            for c in self._cards[1:]:
                c.set_tags(tags)
                c.set_char(char)

    def _clear(self):
        if not self._cards:
            return
        if messagebox.askyesno("Clear Queue", "Remove all images from the queue?"):
            for c in self._cards:
                c.grid_forget()
                c.destroy()
            self._cards.clear()
            self._refresh()
            self.pb.set(0)
            self._st("Queue cleared")

    # ══════════════════════════════════════════════════════════
    #  Thread-safe UI dispatcher (polls queue every 80ms)
    # ══════════════════════════════════════════════════════════
    def _dispatcher(self):
        try:
            while True:
                ev, data = self._q.get_nowait()
                if   ev == "st":          self._st(data)
                elif ev == "pb":          self.pb.set(data)
                elif ev == "set_status":  data[0].set_status(data[1])
                elif ev == "set_tags":    data[0].set_tags(data[1])
                elif ev == "validation":  data[0].show_validation(data[1])
                elif ev == "upload_done":
                    self._uploading = False
                    self._upload_btn.configure(
                        state="normal", fg_color="#125412",
                        text="⑤   Start Upload")
        except queue.Empty:
            pass
        self.after(80, self._dispatcher)

    # ══════════════════════════════════════════════════════════
    #  Config persistence
    # ══════════════════════════════════════════════════════════
    def _load_cfg(self):
        c = self._cfg
        self.artist_var.set(c.get("artist", ""))
        self.gtags_var.set(c.get("global_tags", "rating:explicit"))
        self.gsrc_var.set(c.get("global_source", ""))
        self.ai_gen_var.set(bool(c.get("ai_generated", True)))
        d = int(c.get("delay", 6))
        t = float(c.get("wd14_threshold", 0.35))
        self.delay_var.set(d)
        self.thresh_var.set(t)
        self._dlbl.configure(text=f"{d} s")
        self._tlbl.configure(text=f"{t:.2f}")

    def _save(self):
        save_config({
            "artist":         self.artist_var.get().strip(),
            "global_tags":    self.gtags_var.get().strip(),
            "global_source":  self.gsrc_var.get().strip(),
            "ai_generated":   self.ai_gen_var.get(),
            "delay":          self.delay_var.get(),
            "wd14_threshold": round(self.thresh_var.get(), 2),
        })
        self._st("Configuration saved ✓")

    def _close(self):
        self._save()
        self.destroy()

    def _st(self, msg: str):
        self._sv.set(msg)


# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = App()
    app.mainloop()
