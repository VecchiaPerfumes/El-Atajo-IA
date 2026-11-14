"""Sube a YouTube el video, el Short y la miniatura de un episodio ya renderizado.

Uso: python -m gen.upload ep001
Requiere las variables YT_CLIENT_ID, YT_CLIENT_SECRET y YT_REFRESH_TOKEN (ver README).
Ojo: mientras el proyecto de Google Cloud no pase la auditoría de YouTube, los videos
subidos por API quedan en privado. Hasta entonces, sube a mano desde YouTube Studio.
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

RAIZ = Path(__file__).resolve().parent.parent


def cliente():
    cred = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                       client_id=os.environ["YT_CLIENT_ID"],
                       client_secret=os.environ["YT_CLIENT_SECRET"],
                       token_uri="https://oauth2.googleapis.com/token")
    return build("youtube", "v3", credentials=cred)


def subir(yt, archivo, titulo, descripcion, etiquetas, publicar):
    estado = {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": False}
    if publicar:
        estado["publishAt"] = publicar
    cuerpo = {"snippet": {"title": titulo[:100], "description": descripcion,
                          "tags": etiquetas, "categoryId": "27", "defaultLanguage": "es",
                          "defaultAudioLanguage": "es"},
              "status": estado}
    req = yt.videos().insert(part="snippet,status", body=cuerpo,
                             media_body=MediaFileUpload(str(archivo), chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    print(f"Subido {archivo.name}: https://youtu.be/{resp['id']}")
    return resp["id"]


def main(ep_id):
    out = RAIZ / "salida" / ep_id
    meta = json.loads((out / "metadatos.json").read_text(encoding="utf-8"))
    yt = cliente()
    vid = subir(yt, out / "video.mp4", meta["titulo"], meta["descripcion"],
                meta["etiquetas"], meta.get("publicar"))
    yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(out / "miniatura.jpg"))).execute()
    # El Short sale 3 horas después del video largo y lo enlaza.
    pub_short = None
    if meta.get("publicar"):
        pub_short = (datetime.fromisoformat(meta["publicar"]) + timedelta(hours=3)).isoformat()
    subir(yt, out / "short.mp4", meta["titulo"][:90] + " #shorts",
          f"Video completo: https://youtu.be/{vid}", meta["etiquetas"], pub_short)


if __name__ == "__main__":
    main(sys.argv[1])
