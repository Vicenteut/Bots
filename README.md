# Bots

## sol-bot/
Command center editorial para Threads. Documentacion completa: [sol-bot/README.md](sol-bot/README.md).

- Publicacion Threads-only desde dashboard y Telegram
- Imagenes, carruseles y videos
- Videos normalizados con ffmpeg antes de publicar
- Videos servidos a Threads mediante URL HTTPS temporal
- Analytics e insights
- Trending scanner
- Content calendar

### Deploy notes
- Requiere `ffmpeg` y `ffprobe` instalados en el servidor para publicar videos.
- `THREADS_MEDIA_HOST` queda disponible para hosting propio, pero Threads requiere HTTPS para procesar media.
- Las imagenes locales usan `THREADS_IMAGE_HOST=litterbox` por defecto para generar una URL HTTPS temporal compatible con Threads.
- Los videos locales usan `THREADS_VIDEO_HOST=litterbox` por defecto para generar una URL HTTPS temporal compatible con Threads.
- `THREADS_IMAGE_TTL` y `THREADS_VIDEO_TTL` permiten ajustar la duracion de esas URLs temporales, por defecto `1h`.

## armandito/
Asistente personal en Telegram.
- Tareas y recordatorios
- Notas y carpetas (texto, fotos, archivos)
- Google Calendar integration
- Briefing matutino y wrap-up nocturno
- AI fallback (Claude Haiku)
