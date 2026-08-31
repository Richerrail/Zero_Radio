#!/usr/bin/env python3
"""
zero_radio.py — Petit lecteur audio vintage 8-bit glitché pour Zero.

Deux modes de lecture :
  - LOCAL  : fichiers MP3/WAV/OGG d'un dossier (backend pygame.mixer)
  - STREAM : URL directe (web radio, flux) ou lien YouTube (via yt-dlp + ffplay)

Raccourcis clavier :
  O            ouvrir un dossier
  F            ouvrir un fichier
  U            saisir une URL (YouTube / web radio)
  R            station radio prédéfinie suivante
  ESPACE       lecture / pause
  ← / →        piste précédente / suivante (local) ; radio précédente / suivante (stream)
  S            stop
  ESC          quitter

Usage :
    python3 zero_radio.py
    python3 zero_radio.py --dir /chemin/vers/musique
    python3 zero_radio.py --file /chemin/vers/track.mp3
    python3 zero_radio.py --url "https://www.youtube.com/watch?v=..."
"""

import argparse
import random
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pygame

# Dialogue natif (optionnel, via tkinter)
try:
    import tkinter as tk
    from tkinter import filedialog, simpledialog

    HAS_TK = True
except Exception:
    HAS_TK = False

MUSIC_DIR = Path("/run/media/k00/7AD6-F2A1/Zer0/music")
AUDIO_EXTS = (".mp3", ".wav", ".ogg")
WIDTH, HEIGHT = 480, 240
FPS = 30

# Palette rétro néon
BG = (10, 10, 16)
GREEN = (57, 255, 20)
CYAN = (0, 255, 255)
MAGENTA = (255, 0, 255)
DIM = (40, 40, 55)

# Stations radio prédéfinies (exemples, modifiables) — flux publics directs
RADIOS = [
    {"name": "SomaFM Groove Salad", "url": "https://ice1.somafm.com/groovesalad-256-mp3"},
    {"name": "Radio Paradise", "url": "https://stream.radioparadise.com/mp3-192"},
    {"name": "FIP (Radio France)", "url": "https://icecast.radiofrance.fr/fip-midfi.mp3"},
]

BUTTONS = [
    {"name": "open", "label": "OPEN", "x": 28, "w": 64},
    {"name": "url", "label": "URL", "x": 100, "w": 64},
    {"name": "prev", "label": "<<", "x": 172, "w": 64},
    {"name": "play", "label": ">", "x": 244, "w": 64},
    {"name": "stop", "label": "[]", "x": 316, "w": 64},
    {"name": "next", "label": ">>", "x": 388, "w": 64},
]


# ---------------------------------------------------------------------------
# Stream (web radio / YouTube)
# ---------------------------------------------------------------------------

def is_youtube(url):
    return ("youtube.com" in url) or ("youtu.be" in url)


def find_ytdlp():
    p = shutil.which("yt-dlp")
    if p:
        return p
    local = Path.home() / ".local" / "bin" / "yt-dlp"
    return str(local) if local.exists() else None


def resolve_stream_url(url):
    """Retourne (stream_url, err). Pour YouTube, résout via yt-dlp."""
    if not is_youtube(url):
        return url, None
    ytdlp = find_ytdlp()
    if not ytdlp:
        return None, "yt-dlp non installé"
    try:
        out = subprocess.check_output(
            [ytdlp, "-f", "bestaudio", "--get-url", "--no-playlist", url],
            stderr=subprocess.DEVNULL,
            timeout=45,
        ).decode("utf-8", "replace").strip().splitlines()
    except subprocess.TimeoutExpired:
        return None, "yt-dlp timeout"
    except Exception as exc:
        return None, f"yt-dlp: {exc}"
    if not out:
        return None, "yt-dlp n'a rien trouvé"
    return out[0], None


class StreamPlayer:
    """Lit un flux audio via ffplay, contrôlé par signaux (pause/resume/stop)."""

    def __init__(self):
        self.proc = None
        self.paused = False

    def play(self, url):
        """Lance la lecture. Retourne (ok, err)."""
        self.stop()
        stream_url, err = resolve_stream_url(url)
        if err:
            return False, err
        try:
            self.proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-i", stream_url],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return False, "ffplay introuvable"
        except Exception as exc:
            return False, str(exc)
        self.paused = False
        return True, None

    def pause(self):
        if self.proc and self.proc.poll() is None and not self.paused:
            self.proc.send_signal(signal.SIGSTOP)
            self.paused = True

    def resume(self):
        if self.proc and self.proc.poll() is None and self.paused:
            self.proc.send_signal(signal.SIGCONT)
            self.paused = False

    def stop(self):
        if self.proc and self.proc.poll() is None:
            if self.paused:
                self.proc.send_signal(signal.SIGCONT)  # réveiller pour pouvoir terminer
                self.paused = False
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None
        self.paused = False

    def is_busy(self):
        return self.proc is not None and self.proc.poll() is None

    def has_ended(self):
        return self.proc is not None and self.proc.poll() is not None


# ---------------------------------------------------------------------------
# Dialogues natifs (tkinter)
# ---------------------------------------------------------------------------

_TK_ROOT = None


def _tk_root():
    global _TK_ROOT
    if not HAS_TK:
        return None
    if _TK_ROOT is None:
        try:
            _TK_ROOT = tk.Tk()
            _TK_ROOT.withdraw()
        except Exception:
            return None
    return _TK_ROOT


def ask_open_folder():
    root = _tk_root()
    if root is None:
        return None
    try:
        return filedialog.askdirectory(parent=root, title="Choisir un dossier audio")
    except Exception:
        return None


def ask_open_file():
    root = _tk_root()
    if root is None:
        return None
    try:
        return filedialog.askopenfilename(
            parent=root,
            title="Choisir un fichier audio",
            filetypes=[("Audio", "*.mp3 *.wav *.ogg"), ("Tous les fichiers", "*.*")],
        )
    except Exception:
        return None


def ask_url():
    root = _tk_root()
    if root is None:
        return None
    try:
        return simpledialog.askstring("ZERO RADIO", "URL (YouTube / web radio) :", parent=root)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Rendu
# ---------------------------------------------------------------------------

def scan_tracks(directory):
    directory = Path(directory)
    if not directory.exists():
        return []
    return sorted([p for p in directory.iterdir() if p.suffix.lower() in AUDIO_EXTS])


def draw_text(screen, font, text, x, y, color, glitch=False):
    if glitch and random.random() < 0.15:
        offset = random.randint(-3, 3)
        color = random.choice([GREEN, CYAN, MAGENTA])
        screen.blit(font.render(text, True, color), (x + offset, y))
    else:
        screen.blit(font.render(text, True, color), (x, y))


def draw_button(screen, font, btn, y, hovered, active):
    color = CYAN if hovered else GREEN
    rect = pygame.Rect(btn["x"], y, btn["w"], 40)
    pygame.draw.rect(screen, color, rect, 2, border_radius=4)
    if active:
        pygame.draw.rect(screen, color, rect.inflate(-6, -6), border_radius=2)
    label = btn["label"]
    if btn["name"] == "play":
        label = "||" if active else ">"
    txt = font.render(label, True, BG if active else color)
    screen.blit(txt, txt.get_rect(center=rect.center))
    return rect


# ---------------------------------------------------------------------------
# Boucle principale
# ---------------------------------------------------------------------------

def main(args):
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("ZERO RADIO // 8-BIT")
    clock = pygame.time.Clock()

    try:
        font_big = pygame.font.SysFont("consolas", 28, bold=True)
        font_med = pygame.font.SysFont("consolas", 20, bold=True)
        font_small = pygame.font.SysFont("consolas", 14)
    except Exception:
        font_big = pygame.font.Font(None, 32)
        font_med = pygame.font.Font(None, 24)
        font_small = pygame.font.Font(None, 18)

    stream = StreamPlayer()

    # État
    mode = "local"  # "local" | "stream"
    music_dir = Path(args.dir) if args.dir else MUSIC_DIR
    tracks = scan_tracks(music_dir)
    idx = 0
    playing = False
    paused = False
    current_url = None
    current_label = ""
    radio_idx = None

    # --- commandes internes -------------------------------------------------

    def set_local_track(new_idx):
        nonlocal idx, playing, paused
        if not tracks:
            return
        idx = new_idx % len(tracks)
        pygame.mixer.music.load(str(tracks[idx]))
        pygame.mixer.music.play()
        playing = True
        paused = False

    def find_radio(url):
        for i, r in enumerate(RADIOS):
            if r["url"] == url:
                return i
        return None

    def start_url(url):
        nonlocal mode, playing, paused, current_url, current_label, radio_idx
        stream.stop()
        ok, err = stream.play(url)
        mode = "stream"
        current_url = url
        if not ok:
            current_label = f"ERR: {err}"
            playing = False
            paused = False
            radio_idx = None
            return
        ri = find_radio(url)
        radio_idx = ri
        current_label = RADIOS[ri]["name"] if ri is not None else (url[:44])
        playing = True
        paused = False

    def toggle_play():
        nonlocal playing, paused
        if mode == "local":
            if playing and not paused:
                pygame.mixer.music.pause()
                paused = True
            elif paused:
                pygame.mixer.music.unpause()
                paused = False
            elif tracks:
                pygame.mixer.music.play()
                playing = True
        else:
            if stream.is_busy() and not stream.paused:
                stream.pause()
            elif stream.is_busy() and stream.paused:
                stream.resume()
            elif current_url:
                start_url(current_url)

    def stop_all():
        nonlocal playing, paused
        if mode == "local":
            pygame.mixer.music.stop()
        else:
            stream.stop()
        playing = False
        paused = False

    def step(delta):
        if mode == "local":
            set_local_track(idx + delta)
        else:
            nonlocal radio_idx
            if not RADIOS:
                return
            i = radio_idx if radio_idx is not None else -1
            start_url(RADIOS[(i + delta) % len(RADIOS)]["url"])

    def open_folder():
        nonlocal mode, playing, paused, tracks, idx, music_dir
        d = ask_open_folder()
        if not d:
            return
        music_dir = Path(d)
        tracks = scan_tracks(music_dir)
        idx = 0
        stream.stop()
        mode = "local"
        if tracks:
            set_local_track(0)
        else:
            pygame.mixer.music.stop()
            playing = False
            paused = False

    def open_file():
        nonlocal mode, playing, paused, tracks, idx, music_dir
        f = ask_open_file()
        if not f:
            return
        p = Path(f)
        music_dir = p.parent
        tracks = [p]
        idx = 0
        stream.stop()
        mode = "local"
        set_local_track(0)

    def prompt_url():
        u = ask_url()
        if u and u.strip():
            start_url(u.strip())

    # Démarrage initial
    if args.url:
        start_url(args.url)
    elif args.file and Path(args.file).exists():
        music_dir = Path(args.file).parent
        tracks = [Path(args.file)]
        mode = "local"
        set_local_track(0)
    elif tracks:
        set_local_track(0)

    button_rects = {}
    running = True

    while running:
        dt = clock.tick(FPS) / 1000.0
        mouse = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    toggle_play()
                elif event.key == pygame.K_RIGHT:
                    step(1)
                elif event.key == pygame.K_LEFT:
                    step(-1)
                elif event.key == pygame.K_s:
                    stop_all()
                elif event.key == pygame.K_o:
                    open_folder()
                elif event.key == pygame.K_f:
                    open_file()
                elif event.key == pygame.K_u:
                    prompt_url()
                elif event.key == pygame.K_r:
                    step(1)

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for name, rect in button_rects.items():
                    if rect.collidepoint(mouse):
                        if name == "open":
                            open_folder()
                        elif name == "url":
                            prompt_url()
                        elif name == "play":
                            toggle_play()
                        elif name == "stop":
                            stop_all()
                        elif name == "next":
                            step(1)
                        elif name == "prev":
                            step(-1)

        # Auto-next (local) / fin de flux (stream)
        if mode == "local":
            if playing and not paused and not pygame.mixer.music.get_busy():
                if tracks:
                    set_local_track(idx + 1)
        else:
            if stream.has_ended():
                stream.proc = None
                playing = False
                paused = False

        # État affiché
        if mode == "local":
            is_playing = playing and not paused
            status = "PLAY" if (playing and not paused) else ("PAUSE" if paused else "STOP")
            label = tracks[idx].stem[:30] if tracks else f"NO TRACKS IN {music_dir.name}"
        else:
            busy = stream.is_busy()
            sp = stream.paused
            is_playing = busy and not sp
            status = "PLAY" if (busy and not sp) else ("PAUSE" if sp else "STOP")
            label = current_label

        glitching = is_playing and random.random() < 0.25

        # Dessin
        screen.fill(BG)

        for y in range(0, HEIGHT, 4):
            pygame.draw.line(screen, (20, 20, 30), (0, y), (WIDTH, y))

        title = "ZERO RADIO"
        if glitching and random.random() < 0.3:
            title = "".join(c.upper() if random.random() > 0.1 else c.lower() for c in title)
        draw_text(screen, font_big, title, 20, 16, GREEN, glitch=glitching)

        mode_tag = "[LOCAL]" if mode == "local" else "[STREAM]"
        draw_text(screen, font_small, mode_tag, 20, 52, GREEN if mode == "local" else MAGENTA)

        draw_text(screen, font_med, f"{status}  {label}", 20, 72, CYAN, glitch=glitching)

        # Visualizer 8-bit
        if is_playing:
            bars = 16
            bw = 16
            for i in range(bars):
                h = random.randint(5, 60)
                x = 20 + i * (bw + 8)
                y = 158 - h
                color = GREEN if h < 35 else CYAN if h < 50 else MAGENTA
                pygame.draw.rect(screen, color, (x, y, bw, h))
        else:
            for i in range(16):
                pygame.draw.rect(screen, DIM, (20 + i * 24, 148, 16, 10))

        # Boutons
        by = 180
        for btn in BUTTONS:
            rect = draw_button(
                screen, font_med, btn, by,
                hovered=btn["x"] <= mouse[0] <= btn["x"] + btn["w"] and by <= mouse[1] <= by + 40,
                active=(btn["name"] == "play" and is_playing),
            )
            button_rects[btn["name"]] = rect

        # Effet glitch overlay
        if glitching:
            for _ in range(random.randint(1, 5)):
                gx = random.randint(0, WIDTH)
                gy = random.randint(0, HEIGHT)
                gw = random.randint(20, 120)
                gh = random.randint(2, 8)
                pygame.draw.rect(screen, random.choice([GREEN, CYAN, MAGENTA]), (gx, gy, gw, gh))

        pygame.display.flip()

    stream.stop()
    pygame.mixer.music.stop()
    pygame.quit()
    sys.exit(0)


def parse_args():
    parser = argparse.ArgumentParser(description="ZERO RADIO — lecteur audio 8-bit (local + stream)")
    parser.add_argument("--dir", help="dossier audio à ouvrir")
    parser.add_argument("--file", help="fichier audio à jouer")
    parser.add_argument("--url", help="URL (web radio / YouTube) à jouer")
    return parser.parse_args()


if __name__ == "__main__":
    main(parse_args())
