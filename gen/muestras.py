"""Genera la misma frase con varias voces gratuitas para elegir la del canal."""
import asyncio
from pathlib import Path

import edge_tts

TEXTO = ("¿Tu negocio pierde clientes porque nadie contesta el WhatsApp a las once de la noche? "
         "Hoy lo arreglamos en diez minutos, gratis y sin programar.")
VOCES = ["es-MX-JorgeNeural", "es-MX-DaliaNeural", "es-US-AlonsoNeural", "es-US-PalomaNeural",
         "es-CO-GonzaloNeural", "es-AR-TomasNeural", "es-ES-AlvaroNeural", "es-ES-ElviraNeural"]


async def main():
    out = Path("salida/muestras")
    out.mkdir(parents=True, exist_ok=True)
    for v in VOCES:
        try:
            await edge_tts.Communicate(TEXTO, v, rate="+8%").save(str(out / f"{v}.mp3"))
            print("ok", v)
        except Exception as e:  # una voz caída no debe frenar el resto
            print("falló", v, e)


asyncio.run(main())
