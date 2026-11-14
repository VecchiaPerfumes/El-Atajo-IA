"""Motor de motion graphics: anima cada escena cuadro a cuadro, sincronizada con la voz.

Uso:  python -m gen.motion episodes/ep001.yaml [--sin-voz] [--solo-short]

Qué hace distinto del render estático:
- Fondo vivo (manchas de color que se mueven), barra de progreso y transición de barrido.
- Títulos que entran palabra por palabra con rebote; puntos que aparecen cuando la voz los dice.
- Subtítulos tipo karaoke (la palabra que suena se pinta del color de acento).
- Íconos emoji animados, conversaciones de chat que se escriben solas, contador de cifras.
- Efectos de sonido generados por código (sin derechos de autor) y música opcional.
Todo con Pillow + NumPy + FFmpeg: $0.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from gen import render as base  # voz (edge-tts), duración y utilidades

RAIZ = Path(__file__).resolve().parent.parent
FUENTES = RAIZ / "assets" / "fonts"
CANAL = yaml.safe_load((RAIZ / "canal.yaml").read_text(encoding="utf-8"))
FPS = 30
SR = 48000
PAUSA = 0.35  # silencio al final de cada escena

FONDO = (11, 14, 20)
ACENTO = (37, 211, 102)
ACENTO2 = (255, 196, 0)
VIOLETA = (124, 92, 255)
TEXTO = (242, 245, 248)
TENUE = (150, 160, 172)


# ---------------------------------------------------------------- utilidades
def ease_out_cubic(t):
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def ease_out_back(t, s=1.70158):
    t = min(max(t, 0.0), 1.0)
    return 1 + (s + 1) * (t - 1) ** 3 + s * (t - 1) ** 2


def prog(t, ini, dur):
    return 0.0 if t < ini else min(1.0, (t - ini) / dur)


@lru_cache(maxsize=64)
def fuente(nombre: str, tam: int):
    return ImageFont.truetype(str(FUENTES / nombre), tam)


@lru_cache(maxsize=64)
def emoji(car: str, tam: int) -> Image.Image:
    f = ImageFont.truetype(str(FUENTES / "NotoColorEmoji.ttf"), 109)
    im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((10, 10), car, font=f, embedded_color=True)
    im = im.crop(im.getbbox())
    return im.resize((tam, int(tam * im.height / im.width)), Image.LANCZOS)


def normal(p: str) -> str:
    p = unicodedata.normalize("NFD", p.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in p if unicodedata.category(c) != "Mn"))


def texto_sprite(texto, f, color, sombra=True) -> Image.Image:
    """Sprite con altura fija por fuente (ascendente+descendente) para que las palabras
    de una misma línea compartan la línea base."""
    asc, desc = f.getmetrics()
    pad = 14
    ancho = int(f.getlength(texto)) + pad * 2 + 6
    im = Image.new("RGBA", (ancho, asc + desc + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if sombra:
        d.text((pad + 3, pad + 5), texto, font=f, fill=(0, 0, 0, 140))
    d.text((pad, pad), texto, font=f, fill=color)
    return im


def pegar(lienzo: Image.Image, spr: Image.Image, x, y, escala=1.0, alfa=1.0, centro=False):
    if alfa <= 0.01 or escala <= 0.01:
        return
    if abs(escala - 1) > 0.01:
        spr = spr.resize((max(1, int(spr.width * escala)), max(1, int(spr.height * escala))),
                         Image.BILINEAR)
    if alfa < 0.99:
        a = spr.getchannel("A").point(lambda v: int(v * alfa))
        spr = spr.copy()
        spr.putalpha(a)
    if centro:
        x, y = x - spr.width / 2, y - spr.height / 2
    lienzo.alpha_composite(spr, (int(x), int(y)))


def envolver(texto, f, ancho):
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lineas, linea = [], ""
    for p in texto.split():
        prueba = (linea + " " + p).strip()
        if d.textlength(prueba, font=f) <= ancho or not linea:
            linea = prueba
        else:
            lineas.append(linea)
            linea = p
    lineas.append(linea)
    return lineas


def momento_de(palabras, frase, defecto):
    """Segundo en que la voz dice la primera palabra significativa de `frase`."""
    clave = [normal(w) for w in frase.split() if len(normal(w)) > 3]
    if not clave:
        return defecto
    for ini, _, w in palabras:
        if normal(w) == clave[0] and ini >= defecto - 6:
            return ini
    return defecto


# ---------------------------------------------------------------- fondo
class Fondo:
    def __init__(self, W, H, semilla=0):
        self.W, self.H = W, H
        g = np.linspace(0, 1, H)[:, None]
        base_arr = (np.array(FONDO) * (1 - g[..., None] * 0.3) + np.array((22, 28, 40)) * g[..., None] * 0.3)
        self.base = Image.fromarray(np.broadcast_to(base_arr, (H, W, 3)).astype(np.uint8)).convert("RGBA")
        r = int(min(W, H) * 0.55)
        self.manchas = []
        for color, a in ((ACENTO, 46), (VIOLETA, 54), ((0, 140, 255), 36)):
            m = Image.new("RGBA", (r * 2, r * 2), (0, 0, 0, 0))
            ImageDraw.Draw(m).ellipse([r // 2, r // 2, r * 3 // 2, r * 3 // 2], fill=color + (a,))
            self.manchas.append(m.filter(ImageFilter.GaussianBlur(r // 5)))
        self.fase = semilla
        # cuadrícula sutil de puntos (look "tech")
        grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(grid)
        paso = int(min(W, H) / 18)
        for x in range(paso // 2, W, paso):
            for y in range(paso // 2, H, paso):
                d.ellipse([x - 1.5, y - 1.5, x + 1.5, y + 1.5], fill=(255, 255, 255, 14))
        self.grid = grid

    def cuadro(self, t):
        im = self.base.copy()
        W, H = self.W, self.H
        for i, m in enumerate(self.manchas):
            k = t * 0.11 + self.fase + i * 2.1
            x = W * (0.5 + 0.42 * math.sin(k * (1 + i * 0.3))) - m.width / 2
            y = H * (0.5 + 0.38 * math.cos(k * 0.8 + i)) - m.height / 2
            im.alpha_composite(m, (int(x), int(y)))
        im.alpha_composite(self.grid)
        return im


# ---------------------------------------------------------------- subtítulos karaoke
class Karaoke:
    def __init__(self, palabras, W, H, vertical):
        self.vertical = vertical
        self.tam = 80 if vertical else 58
        self.f = fuente("Inter-Black.otf", self.tam)
        self.y = H * (0.70 if vertical else 0.865)
        self.W = W
        max_pal = 3 if vertical else 5
        self.grupos, g = [], []
        for w in palabras:
            g.append(w)
            if len(g) >= max_pal or w[2][-1:] in ".?!,:":
                self.grupos.append(g)
                g = []
        if g:
            self.grupos.append(g)
        self.cache = {}

    def sprite(self, gi, activa):
        k = (gi, activa)
        if k not in self.cache:
            g = self.grupos[gi]
            pal = [p[2].upper() if self.vertical else p[2] for p in g]
            esp = self.f.getlength(" ")
            anchos = [self.f.getlength(p) for p in pal]
            ancho = int(sum(anchos) + esp * (len(pal) - 1)) + 60
            alto = int(self.tam * 1.5)
            im = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle([0, 0, ancho, alto], 18, fill=(0, 0, 0, 120))
            x = 30
            for i, (p, a) in enumerate(zip(pal, anchos)):
                col = ACENTO if i == activa else TEXTO
                d.text((x, alto * 0.13), p, font=self.f, fill=col, stroke_width=3, stroke_fill=(0, 0, 0))
                x += a + esp
            self.cache[k] = im
        return self.cache[k]

    def dibujar(self, lienzo, t):
        for gi, g in enumerate(self.grupos):
            if g[0][0] - 0.05 <= t <= g[-1][1] + 0.12:
                activa = max((i for i, p in enumerate(g) if p[0] <= t), default=0)
                spr = self.sprite(gi, activa)
                e = 0.9 + 0.1 * ease_out_back(prog(t, g[0][0] - 0.05, 0.18))
                pegar(lienzo, spr, self.W / 2, self.y, escala=e, centro=True)
                return


# ---------------------------------------------------------------- escenas
class Escena:
    """Prepara sprites una vez y dibuja la escena en el instante t (segundos)."""

    def __init__(self, esc, palabras, dur, W, H, vertical, indice, total_escenas):
        self.e, self.pal, self.dur = esc, palabras, dur
        self.W, self.H, self.v = W, H, vertical
        self.i, self.n = indice, total_escenas
        self.s = W / 1920 if not vertical else W / 1080
        self.margen = (130 if not vertical else 80)
        self.ancho_txt = (W * 0.58) if not vertical else (W - 160)
        self.preparar()

    # ---- preparación
    def preparar(self):
        e, v = self.e, self.v
        tam_tit = (124 if e["tipo"] in ("portada", "cierre") else 96) if not v else 112
        if e["tipo"] == "dato":
            tam_tit = 84 if not v else 96
        self.f_tit = fuente("InterDisplay-Black.otf", tam_tit)
        self.lineas = envolver(e.get("titulo") or e.get("texto", ""), self.f_tit, self.ancho_txt)
        self.palabras_tit = []  # (sprite, x, y, retraso)
        y0 = self.H * (0.30 if not v else 0.34)
        if e["tipo"] in ("lista", "paso", "chat"):
            y0 = self.H * (0.25 if not v else 0.27)
        if e["tipo"] == "dato":
            y0 = self.H * (0.56 if not v else 0.47)
        k = 0
        alto_linea = tam_tit * 1.12
        for li, linea in enumerate(self.lineas):
            x = self.margen
            for p in linea.split():
                spr = texto_sprite(p, self.f_tit, TEXTO)
                self.palabras_tit.append((spr, x - 14, y0 + li * alto_linea - 14, k * 0.07))
                x += self.f_tit.getlength(p + " ")
                k += 1
        self.y_fin_tit = y0 + len(self.lineas) * alto_linea
        sub = e.get("subtitulo")
        self.spr_sub = texto_sprite(sub, fuente("Inter-Medium.otf", 54 if not v else 58), TENUE) if sub else None
        self.puntos = []
        if e.get("puntos"):
            n = len(e["puntos"])
            for j, p in enumerate(e["puntos"]):
                por_defecto = 0.6 + (self.dur * 0.75) * (j + 0.4) / n
                ini = momento_de(self.pal, p, por_defecto)
                f = fuente("Inter-Bold.otf", 58 if not v else 56)
                lineas = envolver(p, f, self.ancho_txt - 90)
                spr = Image.new("RGBA", (int(self.ancho_txt + 40), int(len(lineas) * 72 + 30)), (0, 0, 0, 0))
                d = ImageDraw.Draw(spr)
                d.rounded_rectangle([0, 0, spr.width - 1, spr.height - 1], 22, fill=(255, 255, 255, 18),
                                    outline=(255, 255, 255, 30), width=2)
                for li, l in enumerate(lineas):
                    d.text((92, 12 + li * 72), l, font=f, fill=TEXTO)
                self.puntos.append((spr, ini))
        icono = e.get("icono") or {"portada": "⚡", "dato": "⏰", "lista": "🎯", "paso": "🛠️",
                                   "cierre": "🎁", "chat": "💬"}.get(e["tipo"], "✨")
        self.spr_icono = emoji(icono, int(300 * self.s) if not v else 260)
        self.spr_check = emoji("✅", 54)
        if e["tipo"] == "paso":
            f = fuente("Inter-Black.otf", 44)
            txt = f"PASO {e['numero']}"
            w = int(f.getlength(txt)) + 70
            b = Image.new("RGBA", (w, 76), (0, 0, 0, 0))
            d = ImageDraw.Draw(b)
            d.rounded_rectangle([0, 0, w - 1, 75], 38, fill=ACENTO)
            d.text((35, 10), txt, font=f, fill=FONDO)
            self.spr_badge = b
        if e["tipo"] == "dato":
            self.f_cifra = fuente("InterDisplay-Black.otf", 230 if not v else 200)
        if e["tipo"] == "chat":
            self.burbujas = []
            fb = fuente("Inter-Bold.otf", 40 if not v else 44)
            n = len(e["mensajes"])
            for j, m in enumerate(e["mensajes"]):
                propio = j % 2 == 1
                lineas = envolver(m, fb, (520 if not v else 700))
                w = int(max(fb.getlength(l) for l in lineas)) + 56
                h = len(lineas) * 54 + 36
                b = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                d = ImageDraw.Draw(b)
                d.rounded_rectangle([0, 0, w - 1, h - 1], 26, fill=(0, 92, 75) if propio else (42, 50, 60))
                for li, l in enumerate(lineas):
                    d.text((28, 16 + li * 54), l, font=fb, fill=TEXTO)
                ini = momento_de(self.pal, m, 0.5 + self.dur * 0.8 * j / n)
                self.burbujas.append((b, propio, ini))
        if e["tipo"] == "cierre":
            f = fuente("Inter-Black.otf", 52)
            txt = "SUSCRÍBETE"
            w = int(f.getlength(txt)) + 120
            b = Image.new("RGBA", (w, 100), (0, 0, 0, 0))
            d = ImageDraw.Draw(b)
            d.rounded_rectangle([0, 0, w - 1, 99], 50, fill=(230, 33, 23))
            d.text((60, 18), txt, font=f, fill=(255, 255, 255))
            self.spr_sus = b

    def eventos_pop(self):
        """Momentos (s, relativos a la escena) donde suena un 'pop'."""
        ev = [ini for _, ini in self.puntos]
        if self.e["tipo"] == "chat":
            ev += [ini for _, _, ini in self.burbujas]
        return ev

    # ---- dibujo
    def dibujar(self, lienzo, t):
        e, v, W, H = self.e, self.v, self.W, self.H
        tipo = e["tipo"]
        # marca
        pegar(lienzo, self._marca(), self.margen - 50, H * (0.045 if not v else 0.06))
        # ícono flotante
        if tipo != "chat" or v:
            p = ease_out_back(prog(t, 0.15, 0.6))
            flot = math.sin(t * 2.2) * 14
            if not v:
                cx, cy = W * 0.80, H * 0.45 + flot
            else:
                cx, cy = W * 0.5, H * 0.17 + flot
            pegar(lienzo, self.spr_icono, cx, cy, escala=p * (1 + 0.03 * math.sin(t * 3)), centro=True,
                  alfa=min(1, p))
        # badge de paso
        if tipo == "paso":
            p = ease_out_back(prog(t, 0.05, 0.4))
            pegar(lienzo, self.spr_badge, self.margen, H * (0.25 if not v else 0.27) - 110, escala=p)
        # cifra con rebote
        if tipo == "dato":
            p = ease_out_back(prog(t, 0.1, 0.55), 2.2)
            spr = self._cifra()
            pegar(lienzo, spr, self.margen - 14, H * (0.20 if not v else 0.27), escala=max(p, 0.01),
                  alfa=min(1, p * 1.5))
        # título palabra por palabra
        for spr, x, y, ret in self.palabras_tit:
            p = prog(t, 0.12 + ret, 0.45)
            a = ease_out_cubic(p)
            pegar(lienzo, spr, x, y + (1 - a) * 50, alfa=a, escala=0.85 + 0.15 * ease_out_back(p))
        # subrayado y subtítulo
        if tipo in ("portada", "cierre"):
            ret = 0.12 + len(self.palabras_tit) * 0.07
            p = ease_out_cubic(prog(t, ret + 0.2, 0.5))
            if p > 0:
                d = ImageDraw.Draw(lienzo)
                y = self.y_fin_tit + 20
                d.rounded_rectangle([self.margen, y, self.margen + 260 * p, y + 14], 7, fill=ACENTO)
            if self.spr_sub:
                p = ease_out_cubic(prog(t, ret + 0.45, 0.5))
                pegar(lienzo, self.spr_sub, self.margen - 14, self.y_fin_tit + 60 + (1 - p) * 30, alfa=p)
        if tipo == "dato" and e.get("nota"):
            p = ease_out_cubic(prog(t, 1.2, 0.6))
            pegar(lienzo, self._nota(), self.margen - 14, self.y_fin_tit + 30, alfa=p * 0.9)
        # puntos que entran cuando la voz los dice
        y = self.y_fin_tit + 40
        for spr, ini in self.puntos:
            p = ease_out_cubic(prog(t, ini, 0.45))
            if p > 0:
                pegar(lienzo, spr, self.margen - 20 - (1 - p) * 120, y, alfa=p)
                c = ease_out_back(prog(t, ini + 0.15, 0.4), 3)
                pegar(lienzo, self.spr_check, self.margen + 25, y + 36, escala=c, centro=True)
            y += spr.height + 22
        # chat
        if tipo == "chat":
            self._chat(lienzo, t)
        # botón suscribirse con latido
        if tipo == "cierre":
            p = ease_out_back(prog(t, 1.0, 0.5))
            lat = 1 + 0.05 * max(0, math.sin((t - 1.5) * 6)) if t > 1.5 else 1
            pegar(lienzo, self.spr_sus, self.margen + self.spr_sus.width / 2,
                  self.y_fin_tit + 230, escala=p * lat, centro=True)
        # barra de progreso del video
        d = ImageDraw.Draw(lienzo)
        avance = (self.i + min(t / self.dur, 1)) / self.n
        d.rectangle([0, H - 8, W, H], fill=(255, 255, 255, 25))
        d.rectangle([0, H - 8, W * avance, H], fill=ACENTO)
        # barrido de transición al inicio
        p = prog(t, 0, 0.42)
        if p < 1:
            x = W * ease_out_cubic(p)
            d.rectangle([x, 0, W, H], fill=ACENTO)
            d.rectangle([x - 40, 0, x, H], fill=VIOLETA)

    def _chat(self, lienzo, t):
        v, W, H = self.v, self.W, self.H
        if not v:
            x0, y0, w, h = W * 0.60, H * 0.12, W * 0.34, H * 0.70
        else:
            x0, y0, w, h = 60, H * 0.40, W - 120, H * 0.26
        p = ease_out_cubic(prog(t, 0.1, 0.5))
        if p <= 0:
            return
        panel = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))
        d = ImageDraw.Draw(panel)
        d.rounded_rectangle([0, 0, w - 1, h - 1], 40, fill=(17, 27, 33, 235), outline=(255, 255, 255, 40), width=3)
        d.rounded_rectangle([0, 0, w - 1, 90], 40, fill=(32, 44, 51))
        d.rectangle([0, 50, w - 1, 90], fill=(32, 44, 51))
        d.ellipse([28, 18, 82, 72], fill=ACENTO)
        d.text((100, 24), self.e.get("contacto", "Cliente"), font=fuente("Inter-Bold.otf", 36), fill=TEXTO)
        visibles = [(b, pr, ini) for b, pr, ini in self.burbujas if t >= ini]
        y = h - 30
        for b, propio, ini in reversed(visibles):
            y -= b.height + 18
            if y < 100:
                break
            q = ease_out_back(prog(t, ini, 0.35))
            x = (w - b.width - 28) if propio else 28
            pegar(panel, b, x + (b.width * (1 - q) * (0.5 if propio else 0)), y, escala=max(q, 0.01))
        # "escribiendo..." antes del siguiente mensaje
        prox = [ini for _, _, ini in self.burbujas if ini > t]
        if prox and prox[0] - t < 0.9:
            for k in range(3):
                a = 0.4 + 0.6 * abs(math.sin(t * 6 + k))
                d.ellipse([40 + k * 30, h - 60, 58 + k * 30, h - 42], fill=(200, 200, 200, int(255 * a)))
        pegar(lienzo, panel, x0, y0 + (1 - p) * 80, alfa=p)

    @lru_cache(maxsize=1)
    def _marca(self):
        f = fuente("Inter-Black.otf", 34 if not self.v else 40)
        txt = CANAL["nombre"].upper()
        w = int(f.getlength(txt)) + 50
        im = Image.new("RGBA", (w, 60), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 6, 14, 54], 7, fill=ACENTO)
        d.text((32, 8), txt, font=f, fill=TEXTO)
        return im

    @lru_cache(maxsize=1)
    def _cifra(self):
        return texto_sprite(self.e["cifra"], self.f_cifra, ACENTO)

    @lru_cache(maxsize=1)
    def _nota(self):
        return texto_sprite(self.e["nota"], fuente("Inter-Medium.otf", 40), TENUE, sombra=False)


# ---------------------------------------------------------------- render por escena (proceso aparte)
def render_escena(args):
    esc, palabras, dur, W, H, vertical, i, n, destino = args
    fondo = Fondo(W, H, semilla=i * 1.7)
    escena = Escena(esc, palabras, dur, W, H, vertical, i, n)
    kar = Karaoke(palabras, W, H, vertical)
    total = int(round((dur + PAUSA) * FPS))
    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                           "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", str(destino)],
                          stdin=subprocess.PIPE)
    for k in range(total):
        t = k / FPS
        im = fondo.cuadro(t)
        escena.dibujar(im, t)
        kar.dibujar(im, t)
        ff.stdin.write(im.convert("RGB").tobytes())
    ff.stdin.close()
    if ff.wait():
        raise RuntimeError(f"ffmpeg falló en escena {i}")
    return escena.eventos_pop()


# ---------------------------------------------------------------- audio
def leer_audio(archivo: Path) -> np.ndarray:
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(archivo), "-f", "f32le",
                                   "-ac", "1", "-ar", str(SR), "-"])
    return np.frombuffer(raw, dtype=np.float32)


def sfx_whoosh():
    n = int(SR * 0.45)
    t = np.linspace(0, 1, n)
    ruido = np.random.default_rng(1).standard_normal(n).astype(np.float32)
    # filtro paso bajo móvil para dar sensación de barrido
    env = np.sin(np.pi * t) ** 2
    k = 40
    suave = np.convolve(ruido, np.ones(k) / k, mode="same")
    return (suave * env * 0.35).astype(np.float32)


def sfx_pop():
    n = int(SR * 0.12)
    t = np.arange(n) / SR
    f = 1400 * np.exp(-t * 18) + 500
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 35) * 0.22).astype(np.float32)


def mezclar(voces, duraciones, pops, destino: Path):
    total = sum(d + PAUSA for d in duraciones)
    pista = np.zeros(int(SR * (total + 0.5)), dtype=np.float32)
    whoosh, pop = sfx_whoosh(), sfx_pop()
    t0 = 0.0
    for voz, dur, ev in zip(voces, duraciones, pops):
        i0 = int(t0 * SR)
        a = leer_audio(voz)
        pista[i0:i0 + len(a)] += a
        pista[i0:i0 + len(whoosh)] += whoosh
        for s in ev:
            j = i0 + int(s * SR)
            pista[j:j + len(pop)] += pop[:max(0, len(pista) - j)]
        t0 += dur + PAUSA
    musica = sorted((RAIZ / "assets" / "musica").glob("*.mp3"))
    if musica:
        m = leer_audio(musica[0])
        reps = int(np.ceil(len(pista) / len(m)))
        m = np.tile(m, reps)[:len(pista)] * 0.08  # ~ -22 dB bajo la voz
        pista += m
    pista = np.clip(pista, -1, 1)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                    "-c:a", "pcm_s16le", str(destino)], input=pista.tobytes(), check=True)


# ---------------------------------------------------------------- miniatura
def miniatura(ep, destino: Path):
    m = ep["miniatura"]
    W, H = 1280, 720
    im = Fondo(W, H, semilla=3).cuadro(4.0)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 18, H], fill=ACENTO)
    pegar(im, texto_sprite(m["linea1"], fuente("InterDisplay-Black.otf", 150), ACENTO), 50, 120)
    y = 300
    for l in envolver(m["linea2"], fuente("InterDisplay-Black.otf", 104), 820):
        pegar(im, texto_sprite(l, fuente("InterDisplay-Black.otf", 104), TEXTO), 50, y)
        y += 118
    if m.get("icono"):
        ic = emoji(m["icono"], 330)
        pegar(im, ic.rotate(-8, expand=True, resample=Image.BICUBIC), 1040, 440, centro=True)
    if m.get("etiqueta"):
        f = fuente("Inter-Black.otf", 56)
        tw = f.getlength(m["etiqueta"])
        d.rounded_rectangle([1230 - tw - 60, 40, 1230, 130], 20, fill=ACENTO2)
        d.text((1230 - tw - 30, 52), m["etiqueta"], font=f, fill=FONDO)
    im.convert("RGB").save(destino, quality=92)


# ---------------------------------------------------------------- principal
def construir(ep, escenas, out: Path, tmp: Path, W, H, vertical, nombre, sin_voz):
    datos = []
    for i, esc in enumerate(escenas):
        mp3 = tmp / f"voz_{i:02d}.mp3"
        if not mp3.exists() or sin_voz:
            dur, pal = base.voz_escena(esc["narracion"], ep.get("voz", CANAL["voz"]),
                                       ep.get("velocidad", CANAL["velocidad"]), mp3, sin_voz)
            (tmp / f"voz_{i:02d}.json").write_text(json.dumps([dur, pal]))
        dur, pal = json.loads((tmp / f"voz_{i:02d}.json").read_text())
        datos.append((esc, pal, dur))
    n = len(escenas)
    trabajos = [(esc, pal, dur, W, H, vertical, i, n, tmp / f"{nombre}_{i:02d}.mp4")
                for i, (esc, pal, dur) in enumerate(datos)]
    with ProcessPoolExecutor() as ex:
        pops = list(ex.map(render_escena, trabajos))
    lista = tmp / f"{nombre}.txt"
    lista.write_text("".join(f"file '{t[-1].resolve()}'\n" for t in trabajos))
    video = tmp / f"{nombre}_video.mp4"
    base.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy", str(video)])
    audio = tmp / f"{nombre}.wav"
    mezclar([tmp / f"voz_{i:02d}.mp3" for i in range(n)], [d for _, _, d in datos], pops, audio)
    base.run(["ffmpeg", "-y", "-i", str(video), "-i", str(audio), "-c:v", "copy", "-c:a", "aac",
              "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out / f"{nombre}.mp4")])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episodio")
    ap.add_argument("--sin-voz", action="store_true")
    ap.add_argument("--solo-short", action="store_true")
    a = ap.parse_args()
    ep = yaml.safe_load(Path(a.episodio).read_text(encoding="utf-8"))
    out = RAIZ / "salida" / ep["id"]
    tmp = out / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    if not a.solo_short:
        construir(ep, ep["escenas"], out, tmp, 1920, 1080, False, "video", a.sin_voz)
    # Short: la escena de gancho más la siguiente, en vertical.
    construir(ep, ep["escenas"][:ep.get("short_escenas", 2)], out, tmp, 1080, 1920, True, "short", False)
    miniatura(ep, out / "miniatura.jpg")
    meta = {k: ep.get(k) for k in ("titulo", "descripcion", "etiquetas", "publicar")}
    if (out / "video.mp4").exists():
        meta["duracion_s"] = round(base.duracion(out / "video.mp4"), 1)
    (out / "metadatos.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Listo: {out}")


if __name__ == "__main__":
    main()
