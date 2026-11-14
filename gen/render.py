"""Genera video largo, Short vertical, miniatura y metadatos a partir de un episodio YAML.

Uso:  python -m gen.render episodes/ep001.yaml [--sin-voz]

--sin-voz usa silencio con la duración estimada (sirve para probar sin internet).
Todo es gratis: edge-tts (voz), Pillow (diapositivas), FFmpeg (montaje).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
FUENTES = RAIZ / "assets" / "fonts"
W, H = 1920, 1080

# Paleta de marca: fondo oscuro, acento verde WhatsApp/"dinero", texto claro.
FONDO = (14, 17, 22)
FONDO2 = (24, 30, 38)
ACENTO = (37, 211, 102)
TEXTO = (240, 243, 246)
TENUE = (150, 160, 172)


CANAL = yaml.safe_load((RAIZ / "canal.yaml").read_text(encoding="utf-8"))
MARCA = CANAL["nombre"].upper()


def fuente(nombre: str, tam: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FUENTES / nombre), tam)


# ---------------------------------------------------------------- voz
async def _tts(texto: str, voz: str, vel: str, destino: Path) -> list[tuple[float, float, str]]:
    import edge_tts

    com = edge_tts.Communicate(texto, voz, rate=vel, boundary="WordBoundary",
                               proxy=os.environ.get("TTS_PROXY"))
    palabras = []
    with open(destino, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                ini = ch["offset"] / 1e7
                palabras.append((ini, ini + ch["duration"] / 1e7, ch["text"]))
    return palabras


def voz_escena(texto: str, voz: str, vel: str, destino: Path, sin_voz: bool):
    """Devuelve (duración_segundos, palabras con tiempos)."""
    texto = " ".join(texto.split())
    if sin_voz:
        dur = max(3.0, len(texto) / 15.5)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{dur:.2f}",
             "-q:a", "9", str(destino)])
        pal = texto.split()
        paso = dur / len(pal)
        return dur, [(i * paso, (i + 1) * paso, p) for i, p in enumerate(pal)]
    palabras = asyncio.run(_tts(texto, voz, vel, destino))
    return duracion(destino), palabras


def duracion(archivo: Path) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", str(archivo)])
    return float(out.strip())


def run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode:
        sys.exit(f"Falló: {' '.join(map(str, cmd))}\n{r.stderr[-2000:]}")


# ---------------------------------------------------------------- diapositivas
def lienzo(w=W, h=H):
    img = Image.new("RGB", (w, h), FONDO)
    d = ImageDraw.Draw(img)
    # degradado sutil diagonal
    for y in range(h):
        t = y / h
        c = tuple(int(FONDO[i] * (1 - t) + FONDO2[i] * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=c)
    return img, d


def envolver(d, texto, f, ancho):
    lineas, linea = [], ""
    for p in texto.split():
        prueba = (linea + " " + p).strip()
        if d.textlength(prueba, font=f) <= ancho:
            linea = prueba
        else:
            lineas.append(linea)
            linea = p
    lineas.append(linea)
    return lineas


def marca(d, w=W):
    d.rounded_rectangle([80, 70, 92, 130], 6, fill=ACENTO)
    d.text((112, 72), MARCA, font=fuente("Inter-Bold.otf", 34), fill=TEXTO)


def diapositiva(esc: dict, destino: Path):
    img, d = lienzo()
    marca(d)
    t = esc["tipo"]
    if t in ("portada", "cierre"):
        f = fuente("InterDisplay-Black.otf", 120)
        lineas = envolver(d, esc["titulo"], f, W - 320)
        y = H // 2 - len(lineas) * 70 - 40
        for l in lineas:
            d.text((160, y), l, font=f, fill=TEXTO)
            y += 140
        d.rectangle([160, y + 20, 360, y + 32], fill=ACENTO)
        d.text((160, y + 60), esc.get("subtitulo", ""), font=fuente("Inter-Medium.otf", 54), fill=TENUE)
    elif t == "dato":
        d.text((160, 280), esc["cifra"], font=fuente("InterDisplay-Black.otf", 260), fill=ACENTO)
        y = 600
        for l in envolver(d, esc["texto"], fuente("Inter-Bold.otf", 72), W - 320):
            d.text((160, y), l, font=fuente("Inter-Bold.otf", 72), fill=TEXTO)
            y += 92
        if esc.get("nota"):
            d.text((160, H - 140), esc["nota"], font=fuente("Inter-Medium.otf", 34), fill=TENUE)
    elif t in ("lista", "paso"):
        y = 230
        if t == "paso":
            d.rounded_rectangle([160, y, 420, y + 70], 35, fill=ACENTO)
            d.text((195, y + 8), f"PASO {esc['numero']}", font=fuente("Inter-Black.otf", 46), fill=FONDO)
            y += 110
        for l in envolver(d, esc["titulo"], fuente("InterDisplay-Black.otf", 92), W - 320):
            d.text((160, y), l, font=fuente("InterDisplay-Black.otf", 92), fill=TEXTO)
            y += 110
        y += 40
        for p in esc.get("puntos", []):
            d.ellipse([165, y + 22, 195, y + 52], fill=ACENTO)
            d.text((230, y), p, font=fuente("Inter-Bold.otf", 62), fill=TEXTO)
            y += 105
    else:
        raise ValueError(f"tipo de escena desconocido: {t}")
    img.save(destino)


def diapositiva_vertical(esc: dict, destino: Path):
    """Versión 1080x1920 de la escena de gancho para el Short."""
    w, h = 1080, 1920
    img, d = lienzo(w, h)
    d.rounded_rectangle([80, 140, 92, 200], 6, fill=ACENTO)
    d.text((112, 142), MARCA, font=fuente("Inter-Bold.otf", 40), fill=TEXTO)
    f = fuente("InterDisplay-Black.otf", 132)
    lineas = envolver(d, esc.get("titulo") or esc.get("cifra", ""), f, w - 160)
    y = 430
    for l in lineas:
        d.text((80, y), l, font=f, fill=TEXTO)
        y += 150
    d.rectangle([80, y + 30, 280, y + 44], fill=ACENTO)
    sub = esc.get("subtitulo") or esc.get("texto", "")
    yy = y + 80
    for l in envolver(d, sub, fuente("Inter-Medium.otf", 64), w - 160):
        d.text((80, yy), l, font=fuente("Inter-Medium.otf", 64), fill=TENUE)
        yy += 80
    img.save(destino)


def burbuja(d, x, y, texto, propia, f):
    tw = d.textlength(texto, font=f)
    color = (0, 92, 75) if propia else (38, 45, 52)
    x0 = x - tw - 56 if propia else x
    d.rounded_rectangle([x0, y, x0 + tw + 56, y + 84], 26, fill=color)
    d.text((x0 + 28, y + 14), texto, font=f, fill=TEXTO)


def miniatura(ep: dict, destino: Path):
    m = ep["miniatura"]
    img, d = lienzo(1280, 720)
    d.rectangle([0, 0, 1280, 720], fill=FONDO)
    d.rectangle([0, 0, 22, 720], fill=ACENTO)
    d.text((70, 150), m["linea1"], font=fuente("InterDisplay-Black.otf", 150), fill=ACENTO)
    y = 330
    for l in envolver(d, m["linea2"], fuente("InterDisplay-Black.otf", 110), 1120):
        d.text((70, y), l, font=fuente("InterDisplay-Black.otf", 110), fill=TEXTO)
        y += 125
    if m.get("etiqueta"):
        f = fuente("Inter-Black.otf", 56)
        tw = d.textlength(m["etiqueta"], font=f)
        d.rounded_rectangle([1210 - tw - 60, 50, 1210, 140], 20, fill=(255, 196, 0))
        d.text((1210 - tw - 30, 62), m["etiqueta"], font=f, fill=FONDO)
    # Chat de ejemplo: refuerza visualmente la promesa (opcional por episodio).
    fb = fuente("Inter-Bold.otf", 40)
    chat = m.get("chat") or []
    y = 720 - 40 - 100 * len(chat)
    for i, linea in enumerate(chat):
        if i % 2 == 0:
            burbuja(d, 70, y, linea, False, fb)
        else:
            burbuja(d, 1210, y, linea, True, fb)
        y += 100
    img.save(destino, quality=92)


# ---------------------------------------------------------------- subtítulos
def ass_tiempo(s: float) -> str:
    h, r = divmod(s, 3600)
    m, r = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{r:05.2f}"


def subtitulos(palabras, destino: Path, vertical=False, max_pal=4):
    tam, margen = (88, 520) if vertical else (64, 70)
    res = "1080,1920" if vertical else "1920,1080"
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {res.split(',')[0]}
PlayResY: {res.split(',')[1]}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: S,Inter Black,{tam},&H00FFFFFF,&H0066D325,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,60,60,{margen},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    filas, grupo = [], []
    for w in palabras:
        grupo.append(w)
        fin_frase = w[2][-1:] in ".?!,"
        if len(grupo) >= max_pal or fin_frase:
            filas.append(grupo)
            grupo = []
    if grupo:
        filas.append(grupo)
    ev = []
    for g in filas:
        txt = " ".join(p[2] for p in g).upper() if vertical else " ".join(p[2] for p in g)
        ev.append(f"Dialogue: 0,{ass_tiempo(g[0][0])},{ass_tiempo(g[-1][1] + 0.05)},S,,0,0,0,,{txt}")
    destino.write_text(cab + "\n".join(ev) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- montaje
def clip_escena(png: Path, audio: Path, dur: float, destino: Path, vertical=False):
    """Diapositiva con zoom lento (Ken Burns) + audio."""
    fps = 30
    n = int(dur * fps) + 1
    if vertical:
        vf = (f"scale=2160:-1,zoompan=z='min(zoom+0.0006,1.08)':d={n}:"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps},setsar=1")
    else:
        vf = (f"scale=3840:-1,zoompan=z='min(zoom+0.0004,1.06)':d={n}:"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps={fps},setsar=1")
    run(["ffmpeg", "-y", "-loop", "1", "-i", str(png), "-i", str(audio), "-vf", vf,
         "-t", f"{dur + 0.35:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
         "-af", "apad", str(destino)])


def concatenar(clips, destino: Path, ass: Path):
    lista = destino.with_suffix(".txt")
    lista.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    tmp = destino.with_name(destino.stem + "_sin_subs.mp4")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy", str(tmp)])
    run(["ffmpeg", "-y", "-i", str(tmp), "-vf", f"subtitles={ass}:fontsdir={FUENTES}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy",
         "-movflags", "+faststart", str(destino)])
    tmp.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episodio")
    ap.add_argument("--sin-voz", action="store_true")
    a = ap.parse_args()

    ep = yaml.safe_load(Path(a.episodio).read_text(encoding="utf-8"))
    out = RAIZ / "salida" / ep["id"]
    tmp = out / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    clips, todas, t0 = [], [], 0.0
    for i, esc in enumerate(ep["escenas"]):
        png, mp3, mp4 = tmp / f"{i:02d}.png", tmp / f"{i:02d}.mp3", tmp / f"{i:02d}.mp4"
        diapositiva(esc, png)
        dur, pal = voz_escena(esc["narracion"], ep.get("voz", CANAL["voz"]),
                              ep.get("velocidad", CANAL["velocidad"]), mp3, a.sin_voz)
        clip_escena(png, mp3, dur, mp4)
        clips.append(mp4)
        todas += [(s + t0, e + t0, w) for s, e, w in pal]
        esc["_pal"], esc["_dur"], esc["_png"], esc["_mp3"] = pal, dur, png, mp3
        t0 += dur + 0.35
        print(f"escena {i + 1}/{len(ep['escenas'])}: {dur:.1f}s")

    ass = tmp / "subs.ass"
    subtitulos(todas, ass)
    concatenar(clips, out / "video.mp4", ass)

    # Short vertical: la escena de gancho (la primera).
    g = ep["escenas"][0]
    vclip, vpng = tmp / "short_raw.mp4", tmp / "short.png"
    diapositiva_vertical(g, vpng)
    clip_escena(vpng, g["_mp3"], g["_dur"], vclip, vertical=True)
    vass = tmp / "short.ass"
    subtitulos(g["_pal"], vass, vertical=True, max_pal=3)
    concatenar([vclip], out / "short.mp4", vass)

    miniatura(ep, out / "miniatura.jpg")
    meta = {k: ep[k] for k in ("titulo", "descripcion", "etiquetas", "publicar")}
    meta["duracion_s"] = round(duracion(out / "video.mp4"), 1)
    (out / "metadatos.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Listo: {out}")


if __name__ == "__main__":
    main()
