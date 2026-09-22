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

El catálogo puede provenir del Excel o de los subtítulos procesados desde la pantalla inicial. Antes de cada partida se prepara y precarga la secuencia usando audios ya existentes. Una vez iniciada la partida no se invocan modelos de IA ni se generan audios: el navegador solo reproduce los audios precargados y muestra las frases.

Cuando se usa el catálogo del Excel y se selecciona audio en inglés, la aplicación reutiliza los MP3 de `audio_english/`, relacionados con las filas por su ID.

Los audios generados a partir de subtítulos se guardan en `audio/<subtítulo>/en/` y `audio/<subtítulo>/es/`. La traducción y la síntesis con modelos locales solo se ejecutan al pulsar «Procesar subtítulos»; al terminar y justo antes de iniciar una partida, el servidor libera los modelos.

En la pantalla inicial se puede elegir una voz independiente para los audios en inglés y español. `MMS-TTS` usa la voz neural fija del modelo; las demás opciones son voces instaladas de macOS. La voz forma parte de la caché, por lo que cambiarla genera audios nuevos.

En la pantalla inicial se puede elegir por separado el idioma de la frase mostrada (inglés por defecto o español) y el idioma del audio (español o inglés). Solo se muestra una versión de la frase, sin revelar una traducción adicional. El tiempo por frase se puede elegir entre 2 y 15 segundos; el valor inicial es 5 segundos.

En cada turno puntuable, el audio es la frase de hace `n` turnos o un distractor aleatorio. La frase visual actual (0-back) nunca se usa como audio del mismo turno ni como distractor; por eso la respuesta «Sí» solo es correcta cuando el audio coincide con la frase `n-back`.

La pantalla inicial incluye estadísticas históricas guardadas localmente en el navegador: sesiones, rondas, precisión media, mejor resultado y las cinco últimas partidas.

El navegador necesita este servidor local porque la aplicación carga `data/phrases.json` y solicita los audios preparados mediante `fetch`.
