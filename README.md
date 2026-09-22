# English Phrase N-Back

Juego de memoria n-back con frases del archivo `English_B2.xlsx`.

## Ejecutar

Desde esta carpeta, instala la librería gratuita de voces neuronales y inicia el servidor:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

Después abre [http://localhost:8000](http://localhost:8000).

Si se modifica el archivo Excel, regenera el catálogo con:

```bash
python3 scripts/import-xlsx.py
```

El catálogo se importa con las 5.000 filas del archivo, conservando cada frase y su traducción. Antes de cada partida, el servidor comprueba y genera si hace falta todos los audios del catálogo para el idioma elegido; los archivos existentes se reutilizan desde `.tts-cache`. La secuencia de la partida se mezcla antes de empezar. Si `edge-tts` no está disponible, usa las voces locales de macOS como alternativa.

Cuando se selecciona audio en inglés, la aplicación reutiliza los 5.000 MP3 de `audio_english/`, relacionados con las filas del Excel por su ID (`0001.mp3` a `5000.mp3`).

También se han generado 5.000 archivos españoles en `audio_spanish/`, usando la traducción de cada fila. Las traducciones repetidas comparten el mismo contenido de audio, pero cada fila conserva su archivo `0001.mp3` a `5000.mp3`.

En la pantalla inicial se puede elegir por separado el idioma de la frase mostrada (inglés por defecto o español) y el idioma del audio (español o inglés). Solo se muestra una versión de la frase, sin revelar una traducción adicional. El tiempo por frase se puede elegir entre 2 y 15 segundos; el valor inicial es 5 segundos.

En cada turno puntuable, el audio es la frase de hace `n` turnos o un distractor aleatorio. La frase visual actual (0-back) nunca se usa como audio del mismo turno ni como distractor; por eso la respuesta «Sí» solo es correcta cuando el audio coincide con la frase `n-back`.

La pantalla inicial incluye estadísticas históricas guardadas localmente en el navegador: sesiones, rondas, precisión media, mejor resultado y las cinco últimas partidas.

El navegador necesita este servidor local porque la aplicación carga `data/phrases.json` y solicita los audios preparados mediante `fetch`.
