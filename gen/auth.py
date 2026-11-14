"""Ejecútalo UNA vez en tu computadora para obtener el YT_REFRESH_TOKEN.

1. En Google Cloud crea un proyecto, activa "YouTube Data API v3" y crea credenciales
   OAuth de tipo "App de escritorio". Descarga el JSON como client_secret.json.
2. pip install google-auth-oauthlib
3. python gen/auth.py client_secret.json  -> abre el navegador, inicia sesión con la
   cuenta del canal y copia el refresh token que se imprime.
"""
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    sys.argv[1], scopes=["https://www.googleapis.com/auth/youtube.upload",
                         "https://www.googleapis.com/auth/youtube"])
cred = flow.run_local_server(port=0, prompt="consent", access_type="offline")
print("YT_REFRESH_TOKEN =", cred.refresh_token)
