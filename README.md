# Generador de videos: El Atajo IA

Convierte un guion (`episodes/epXXX.yaml`) en un video largo 1920x1080 con voz y subtítulos, un Short vertical 1080x1920 y una miniatura 1280x720. Costo: $0.

| Pieza | Herramienta gratuita |
| --- | --- |
| Guiones | Claude, en el proyecto (escribe el YAML cada semana) |
| Voz | edge-tts (voces neuronales de Microsoft Edge) |
| Animación y miniatura | Pillow + NumPy, fuentes Inter y Noto Color Emoji (licencia OFL) |
| Montaje y subtítulos | FFmpeg |
| Servidor | GitHub Actions (gratis en repositorios públicos; 2.000 min/mes en privados) |
| Subida | YouTube Data API, o subida manual desde YouTube Studio |

## Motor de motion graphics (`gen/motion.py`)

Es el motor que usan los flujos. Anima cada escena sincronizada con la voz: título palabra por palabra, puntos que aparecen cuando la voz los dice, subtítulos tipo karaoke, chat de WhatsApp que se escribe solo, íconos animados, barra de progreso, transición de barrido y efectos de sonido generados por código. Si pones un .mp3 en `assets/musica/` (por ejemplo, de la Biblioteca de audio de YouTube), se usa como música de fondo baja. `gen/render.py` queda como versión estática simple.

Tipos de escena: `portada`, `dato`, `lista`, `paso`, `chat`, `cierre`. Campo opcional `icono` con un emoji.

## Cómo funciona

1. Claude escribe el episodio y abre un pull request con `episodes/epXXX.yaml`.
2. GitHub Actions genera el video con voz y lo deja en la pestaña Actions → "vista-previa".
3. Tú lo ves. Si está bien, haces merge; si no, comentas qué cambiar.
4. Al hacer merge se genera la versión final y, si configuraste los secretos, se sube programada.

## Probar en tu computadora

```bash
pip install -r requirements.txt     # y tener ffmpeg instalado
python -m gen.motion episodes/ep001.yaml
# resultado en salida/ep001/
```

`--sin-voz` genera el video con silencio, para probar sin internet.

## Configurar la subida automática (opcional)

1. En [Google Cloud Console](https://console.cloud.google.com/) crea un proyecto y activa "YouTube Data API v3".
2. Configura la pantalla de consentimiento OAuth (tipo Externo, agrégate como usuario de prueba) y crea credenciales "App de escritorio". Descarga el JSON.
3. En tu computadora: `pip install google-auth-oauthlib` y `python gen/auth.py client_secret.json`. Copia el refresh token.
4. En GitHub → Settings → Secrets → Actions crea `YT_CLIENT_ID`, `YT_CLIENT_SECRET` y `YT_REFRESH_TOKEN`.

Importante: Google deja en **privado** los videos subidos por API desde proyectos no auditados. Hasta pasar la auditoría ("YouTube API Services - Audit and Quota Extension Form"), descarga el artifact y súbelo a mano en YouTube Studio con la opción Programar (2 minutos por video).

## Riesgos conocidos

- edge-tts usa un servicio no oficial de Microsoft: puede dejar de funcionar sin aviso, y su uso comercial no está claramente autorizado. Alternativa gratuita: Kokoro TTS (licencia Apache 2.0), con calidad algo menor en español.
- La política de contenido "no auténtico" de YouTube exige que cada video aporte algo propio. No publiques sin revisar.
