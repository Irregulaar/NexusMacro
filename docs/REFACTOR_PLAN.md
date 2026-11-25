# Plan de refactor — Nexus Macro

Estado: **en ejecución**
Objetivo: que el macro sea predecible. Cada acción debe nacer de un estado
observado, ejecutarse una vez, verificarse y dejar un estado conocido. Nada de
tick con condiciones sueltas ni acciones que se repiten porque sí.

---

## 1. Diagnóstico (auditoría del código actual)

### 1.1 Problemas estructurales

| # | Problema | Consecuencia real |
|---|----------|-------------------|
| E1 | `engine.py` es un monolito de ~1280 líneas: visión, tienda, build, spawners, Play, Tab, batalla y scheduling viven en el mismo `tick()`. | Es imposible razonar qué acción tiene prioridad; los bugs se arreglan con parches que rompen otra cosa. |
| E2 | No existe una máquina de estados. El estado se deduce con banderas sueltas (`_pre_battle_done`, `_tab_done`, `_discard_until`, `_shop_state`, etc.). | Acciones que se repiten, se saltan o quedan bloqueadas para siempre. |
| E3 | El `tick()` comprueba Play, Descarte, Tab, tienda, build, spawners y batalla en cada vuelta, aunque la mayoría no aplique. | Detecciones falsas y clics en pantallas equivocadas. |
| E4 | El scheduling de spawners está incrustado en `tick()` con tres ramas y estado repartido. | Difícil de testear; el modo reloj/intervalo/continuo se comporta distinto sin motivo. |
| E5 | La UI (`ui.py`, ~2250 líneas) mezcla ventana, páginas, config, launcher, reconnect y control del motor. `EngineController.update_config` toca atributos privados del `Engine`. | Cambios de config en vivo frágiles; cualquier refactor interno rompe la UI. |
| E6 | 81 `except Exception` en el proyecto; muchos son `pass` silenciosos. | Fallos invisibles: el macro “no hace nada” y el log no dice por qué. |

### 1.2 Bugs concretos encontrados

| # | Bug | Estado |
|---|-----|--------|
| B1 | `_pre_battle_done = True` se ponía **antes** de ejecutar Fuse/Place. Si la acción fallaba, no se reintentaba hasta que desapareciera el botón Battle. | **Pendiente** (fase 3) |
| B2 | `Matcher.find()` solo verificaba los **4** mejores candidatos de `TM_CCORR_NORMED`. Si los 4 primeros eran falsos positivos, el botón real no se encontraba aunque estuviera en pantalla. | **Pendiente** (fase 1) |
| B3 | Detección de tienda global en cada tick: cualquier botón verde o X roja abría una “tienda”. | Corregido: la tienda solo existe dentro de un ciclo de spawner. |
| B4 | `Play` estaba bloqueado por `_tab_done`: después del primer Tab el macro dejaba de pulsar Play. | Corregido. |
| B5 | Tab esperaba a ver Build/Spawner; en batalla esos botones no existen, así que se saltaba para siempre. | Corregido: detecta también Forfeit/victoria y tiene fallback. |
| B6 | Stop no cancelaba Auto Reconnect; al cerrar Sober, el macro lo relanzaba. | Corregido. |
| B7 | La config se perdía porque los self-tests de UI abrían la ventana real y guardaban defaults. | Corregido; tests usan config temporal. |
| B8 | Valores escritos en spin boxes sin Enter no se guardaban. | Corregido con sync de widgets + `editingFinished`. |

### 1.3 Deuda técnica

- Acciones devuelven `bool` sin motivo; el llamador no distingue “no estaba”,
  “falló al hacer clic” o “se abrió otra pantalla”.
- Helpers de CV duplicados (`_find_template`, `_find_menu_button`,
  `_find_button_fast`) y thresholds dispersos.
- Tests llaman métodos privados del `Engine`; un refactor interno los rompe.
- No hay documento que explique qué hace cada módulo ni qué funciones tiene el
  programa.
- Capturas de debug sin metadatos del estado/acción que las produjo.
- `preview_while_running`, `auto_fuse_option`, `auto_best_place_option` y
  `max_buy_buttons` existen en config pero no se usan (código muerto).
- `_shop_scan(preferred_scale)` y `_wait_for_shop(preferred_scale)` reciben un
  parámetro que no usan.

---

## 2. Arquitectura objetivo

```text
app.py                         entrada / flags / lock de instancia
nexusmacro/
  automation/
    context.py                 Runtime: backend, config, matcher, stats, stop,
                               sleep, click, captura, log, debug
    detection.py               ScreenDetector: play, discard, battle, build,
                               HUD de partida, modal
    navigation.py              Navigator: Play, Tab, batalla, descarte
    shop.py                    ShopSession: abrir/verificar, comprar, scroll,
                               cerrar; solo compra si el macro abrió la tienda
    build.py                   BuildMenu: abrir Build, Fuse/Place x2, Stop,
                               Forfeit/Confirm
    spawner.py                 SpawnerFinder + SpawnerScheduler + SpawnerAction
  engine.py                    orquestador: run(), tick(), prioridades y
                               transiciones; sin CV de bajo nivel
  vision.py                    matcher de templates (mejorado)
  shopvision.py                detección por color de Buy/Close/Scrollbar
  backend.py                   X11: captura e input
  launcher.py                  gamescope/Sober
  controller.py                hilo del motor + señales Qt (extraído de ui.py)
  ui.py                        ventana y páginas (solo presentación/config)
  config.py                    dataclass + persistencia robusta
  paths.py, schedule.py, hostwindow.py, ui_widgets.py
docs/
  REFACTOR_PLAN.md             este documento
  ARCHITECTURE.md              mapa de código + inventario funcional
```

### Prioridad de acciones (una por tick)

1. **Descarte** de batalla guardada (modal bloqueante, máxima prioridad).
2. **Play** si aparece (entrar a la partida).
3. **Tab** una vez al entrar (con detección de HUD y fallback).
4. **Acción manual** solicitada por la UI.
5. **Pre-batalla**: Fuse / Best Place antes de pulsar Battle.
6. **Spawner** según scheduler (reloj / intervalo / continuo).
7. **Battle** si el botón está visible y no hay modal.

Cada paso devuelve `ActionResult`/`bool` y el `tick()` solo continúa si la
acción realmente ocurrió. Las acciones bloqueantes terminan en un estado
verificado (menú cerrado, tienda cerrada, batalla iniciada).

### Contratos

- `Runtime`: única puerta a backend/config/matcher/callbacks/stats/stop.
- `ScreenDetector`: lectura pura; nunca hace clic.
- `Navigator`: acciones de navegación con verificación.
- `ShopSession`: dueño exclusivo de Buy/scroll/close. Solo se instancia tras un
  clic de spawner.
- `BuildMenu`: dueño de Build/Fuse/Place/Stop/Forfeit.
- `SpawnerScheduler`: decisión de “toca comprar” sin tocar la pantalla.
- `Engine`: decide, en orden, qué componente actúa.

---

## 3. Fases de ejecución

### Fase 0 — Documentación y red de seguridad
- [x] Auditoría y plan (`docs/REFACTOR_PLAN.md`).
- [x] Mapa de código y funciones (`docs/ARCHITECTURE.md`).
- [x] Baseline de tests: 38 OK.
- [x] Añadir tests de scheduler/detección antes de mover código (75 tests).

### Fase 1 — Visión y contexto
- [x] Crear `automation/context.py` con `Runtime`.
- [x] Crear `automation/detection.py` con `ScreenDetector`.
- [x] Aumentar candidatos (12–32) y pasar el matcher a gris + regiones.
- [x] Benchmark: tick idle 884 ms → ~75 ms; build 232→30 ms; spawner1
      228→66 ms; play 179→30 ms.

### Fase 2 — Componentes de acción
- [x] Extraer `ShopSession` (comprar/scrollear/cerrar/verificar).
- [x] Extraer `BuildMenu` (Fuse/Place, Forfeit, verificación de Stop).
- [x] Extraer `SpawnerFinder`, `SpawnerScheduler`, `SpawnerAction`.
- [x] Mantener wrappers temporales en `Engine` para no romper tests.

### Fase 3 — Orquestador
- [x] Reescribir `tick()` como pipeline por prioridades (9 pasos).
- [x] Corregir B1: `pre_battle_done` solo en éxito; reintento con backoff.
- [x] Verificar clic de Battle (Forfeit / botón desaparecido / modal).
- [x] Estado explícito de sesión de tienda y de partida.
- [x] `Engine.update_config()` para la UI (sin tocar privados).

### Fase 4 — UI
- [x] Extraer `EngineController` a `controller.py`.
- [x] `ui.py` llama a `engine.update_config()`; no escribe atributos privados.
- [x] Revisar señales de config y feedback de guardado.
- [x] Páginas extraídas a `ui_pages.py` (`UiPagesMixin`); sin cambios visuales.

### Fase 5 — Cierre
- [x] Tests: scheduler, detección, tienda, build, stop/reconnect, config.
- [x] `--selftest`, `--ui-selftest`, `--ui-config-test`.
- [x] Build + install (1.5.5).
- [x] Actualizar `docs/ARCHITECTURE.md` con el estado final y `README.md`.

---

## 4. Criterios de aceptación

1. Ninguna acción de tienda se ejecuta sin un clic previo de spawner.
2. Fuse/Place se reintenta si falla; no queda bloqueado por una bandera.
3. Tab se pulsa exactamente una vez por entrada a partida (Play o reconnect).
4. Stop cancela Auto Reconnect y no relanza juegos.
5. La config se guarda y se aplica en vivo; el footer muestra `Saved HH:MM`.
6. Un valor inválido de config no borra el resto.
7. `Matcher.find()` encuentra el botón real aunque haya falsos positivos
   delante (test de recall).
8. Todos los tests pasan; el binario empaquetado pasa `--ui-config-test`.
9. Cada módulo nuevo tiene una sección en `docs/ARCHITECTURE.md`.
10. El log explica cada decisión importante y cada fallo con captura.

---

## 5. Riesgos y mitigaciones

- **Mover código de tienda/build puede romper clicks ya afinados.**
  Mitigación: mover sin cambiar constantes; tests existentes + nuevos.
- **Aumentar candidatos de visión puede subir el uso de CPU.**
  Mitigación: medir con `--selftest` y limitar candidatos por tipo; caché de
  templates ya existente.
- **La UI es grande; extraer el controlador puede romper señales.**
  Mitigación: mover `EngineController` tal cual, con test de UI offscreen.
- **No hay git.** Mitigación: copia de seguridad del árbol antes de mover
  archivos (`/tmp/nexusmacro_refactor_backup`).

---

## 6. Resultados medidos

| Métrica | Antes | Después |
|---------|-------|---------|
| Tick idle (1280×720) | 884 ms | ~75 ms |
| `build` find | 232 ms | ~30 ms |
| `play` find | 179 ms | ~30 ms |
| `spawner1` find | 228 ms | ~66 ms |
| `forfeit` find | 161 ms | ~16 ms |
| Tests | 38 | 75 OK |

Cambios de comportamiento:
- La tienda solo se abre/compra después de un clic de spawner.
- Una tienda sobrante se cierra; nunca se compra desde ella.
- El menú Build sobrante se cierra antes de cualquier otra acción.
- `max_buy_buttons` ahora limita de verdad los Buy por pasada.
- Los self-tests de UI usan config temporal y no tocan la del usuario.
- Las capturas de debug llevan un `.json` con tag, nota, fecha y config.

## 7. Registro de cambios del refactor

- 2026-11-24: Fase 0: plan + arquitectura + baseline de tests.
- 2026-11-24: Ajustes previos: tienda session-gated, Tab por HUD, Stop
  cancela reconnect, Play sin bloqueo, config persistente y backup.
- 2026-11-24: Fases 1–5 completadas; versión 1.5.0.
- 2026-11-24: **1.5.1** — hotfix de Discard: el fallback por color se
  restringe al centro del modal, se verifica el clic y un falso positivo se
  ignora 60 s. Evita el bucle de clics sobre el badge rojo del menú Build.
- 2026-11-24: **1.5.2** — acciones manuales Fuse/Best Place se ejecutan en el
  motor principal (sin dos motores compitiendo por el menú Build); la tienda
  tolera el parpadeo de la X y hace scroll; la transición de Battle se verifica
  durante 2.5 s y no se reintenta pre-batalla encima.
- 2026-11-24: **1.5.3** — Fuse y Best Place comparten **un solo** menú Build
  (abrir → Fuse → Place → cerrar una vez). Tab solo se pulsa si aparece
  `tabimage.png` en pantalla; sin imagen no se envía Tab.
- 2026-11-24: **1.5.4** — `reconnectbutton.png` ya no se pulsa: se cierra
  Sober/gamescope y se relanza, con reintento. Config portable en
  `<project>/config/`. Icono del usuario a 64/256/512 y `.desktop` con ruta
  absoluta. Quitado Open Templates; subtítulo “Build a Tower Defense
  Autopilot”.
- 2026-11-24: **1.5.7** — arreglo de `log(QString,QString)` en el launcher,
  scroll dentro del panel de Settings (cierre con X) y fallback de Discard.
- 2026-11-24: **1.5.6** — gamescope en `/usr/games` para Debian/Ubuntu.
- 2026-11-24: **1.5.5** — arreglo de instalación en otras distros
  (`LD_LIBRARY_PATH` de PyInstaller, SDL Wayland, errores de flatpak), ventana
  proporcional a la pantalla, Tab con CCOEFF real y Classic Forfeit automático
  una sola vez.
