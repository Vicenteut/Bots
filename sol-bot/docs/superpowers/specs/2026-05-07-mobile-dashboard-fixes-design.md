# Sol Dashboard — Mobile Fixes (2026-05-07)

## Contexto

El dashboard (`sol_dashboard_api.py` + `templates/dashboard.html` + `static/dashboard.css`) ya tiene una capa móvil madura (Sprints 1–5: bottom tabs, drawer, bottom sheets, heatmap bucketing, long-press multi-select, etc.).

Esta iteración es una auditoría puntual con 4 fixes quirúrgicos identificados por revisión estática del CSS y JS móvil. No reescribe la capa móvil; sólo arregla bugs latentes y mejora feedback táctil.

## Issues

### 1. `:hover` pegado en touch (BUG)
`.lin-card:hover` (CSS:4488) y los botones (`button:not(:disabled):hover`, CSS:4529) aplican `transform: translateY(...)` sin envoltura `(hover: hover)`. En touch-only devices, `:hover` se activa al tocar y persiste hasta el siguiente tap fuera — el botón queda visualmente "levantado" y la card "alzada", sensación rota.

### 2. Botón ↻ refresh móvil sin handler (BUG)
`dashboard.html:1309` declara `<button class="lin-icn-btn" title="Refresh">↻</button>` dentro de `.mb-header-actions`, pero `mobileNav()` (JS:3513) no lo enlaza a nada. Tap → ningún efecto.

### 3. Tap target 40×40 en header móvil (HIG)
Las acciones del header móvil (`.mb-header-actions .lin-icn-btn`, CSS:1065) miden 40×40. Apple HIG y WCAG recomiendan ≥44×44. La hamburguesa ya está a 44; emparejar.

### 4. Falta feedback `:active` en `.mb-tab` (UX)
La barra inferior cambia color sólo al estar activa, pero no da feedback de press en el momento del tap. Los iOS/Android nativos hacen un flash ligero — ahora se siente mudo.

## Fixes propuestos

### Fix 1 — Wrap hover lifts en `(hover: hover) and (pointer: fine)`
En `dashboard.css`, mover el bloque `.lin-card:hover { transform... }` y los button hover lifts dentro de un `@media (hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)`. Mantener el `:active` press (que sí queremos en touch).

### Fix 2 — Conectar refresh móvil
Asignar `id="mb-refresh"` al botón en HTML. En `mobileNav()`, agregar listener que dispare un evento custom `sol:mobile-refresh` y llame a `location.reload()` como fallback simple. Estrategia mínima: `location.reload()` directo (cero riesgo, comportamiento previsible). Dejamos hook para futura granularidad por pantalla.

### Fix 3 — Bump tap target a 44×44
En la regla `.mb-header-actions .lin-icn-btn` (CSS:1065): cambiar `40px` → `44px`. Ítem único, no hay alineación que romper (header es 48+inset alto).

### Fix 4 — Press feedback `.mb-tab:active`
Agregar dentro del bloque `@media (max-width: 600px)`:
```css
.mb-tab:active { background: var(--surface-2); transform: scale(0.97); }
.mb-tab:active .mb-tab-icn { transform: scale(0.92); }
```
Transición ya existe global. Wrap dentro de `prefers-reduced-motion: no-preference` para el scale.

## No incluido (out-of-scope)

- Reescritura de transición universal `* { transition: ... }` (CSS:4468). Riesgo de regresión visual desproporcionado al beneficio.
- Swipe gestures entre tabs.
- Pull-to-refresh nativo.
- Auto-hide del header al scrollear.

Si los Sprints futuros piden ampliar, esto queda como backlog explícito.

## Criterios de éxito

1. Tras tocar un botón en el dashboard móvil y mover el dedo, el botón regresa a su estado base (no queda elevado).
2. Tap en ↻ del header móvil refresca la página.
3. `.mb-header-actions .lin-icn-btn` mide 44×44 (devtools mobile viewport).
4. Tap en un `.mb-tab` muestra flash de fondo + scale-down momentáneo.
5. `python3 -c "import ast; ast.parse(open('sol_dashboard_api.py').read())"` sigue OK; `systemctl restart sol-dashboard` levanta sin errores; CSS válido (sin parser warnings nuevos).

## Archivos tocados

- `static/dashboard.css` — fixes 1, 3, 4
- `templates/dashboard.html` — fix 2 (id + handler en `mobileNav()`)

## Rollback

Backups previos:
- `static/dashboard.css` → `static/dashboard.css.bak.pre-mobile-fixes-20260507`
- `templates/dashboard.html` → backups ya existentes; crear `dashboard.html.bak.pre-mobile-fixes-20260507`
