# Bots

## sol-bot/
Bot automatizado de noticias para Threads.
- Publicacion Threads-only desde dashboard y Telegram
- Imagenes, carruseles y videos
- Videos normalizados con ffmpeg antes de publicar
- Videos servidos a Threads mediante URL HTTPS temporal
- Analytics e insights
- Trending scanner
- Content calendar

### Deploy notes
- Requiere `ffmpeg` y `ffprobe` instalados en el servidor para publicar videos.
- `THREADS_MEDIA_HOST` sirve imagenes desde el host propio.
- Los videos locales usan `THREADS_VIDEO_HOST=litterbox` por defecto para generar una URL HTTPS temporal compatible con Threads.
- `THREADS_VIDEO_TTL` permite ajustar la duracion de esa URL temporal, por defecto `1h`.

## armandito/
Asistente personal en Telegram.
- Tareas y recordatorios
- Notas y carpetas (texto, fotos, archivos)
- Google Calendar integration
- Briefing matutino y wrap-up nocturno
- AI fallback (Claude Haiku)
