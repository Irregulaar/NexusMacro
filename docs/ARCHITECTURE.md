# Arquitectura y mapa de código — Nexus Macro

Este documento responde a dos preguntas:

1. **Qué tiene el programa** (funciones visibles y flujos reales).
2. **Qué hace cada parte del código** (módulo, clase, método y responsabilidad).

Se actualiza junto con el refactor. Si un módulo cambia, su sección cambia aquí.

---

## 1. Qué es Nexus Macro

Automatización de un tower defense de Roblox que corre dentro de **Sober** en
**gamescope**. El juego se renderiza a 1280×720; las imágenes de `templates/`
están calibradas para esa resolución. La resolución del monitor no importa
porque gamescope fija la resolución interna.

### 1.1 Funciones del programa

| Función | Qué hace |
|---------|----------|
| **Auto Battle** | Pulsa Battle cuando está disponible, descarta batallas guardadas y espera el cooldown. |
| **Auto Spawners** | En la ventana de refresco (reloj cada 5 min), intervalo o continuo: abre el spawner, compra los Buy visibles, scrollea y cierra la tienda. |
| **Auto Fuse** | Antes de Battle: Build → Fuse All ×2 → espera → Stop. Si hay batalla en curso, Forfeit → Confirm → Build. |
| **Auto Best Place** | Igual que Fuse, pero con Place Best. |
| **Auto Reconnect** | Si se pierde la ventana del juego y el macro lo lanzó, relanza Sober/gamescope y reinicia el motor. |
| **Pantalla Reconnect** | Detecta `reconnectbutton.png`; no hace clic: cierra Sober/gamescope, relanza y reintenta si la conexión falla. |
| **Auto Join** | Lanza Sober con `roblox://experience?placeId=...` y pulsa Play al aparecer. |
| **Acciones manuales** | Buy Spawners Now, Fuse Now, Best Place Now, con etiquetas de progreso. |
| **Launcher** | Lanza/para gamescope+Sober, minimiza/restaura la ventana host. |
| **Config** | Autoguardado atómico, backup, aplicación en vivo y validación tolerante. |
| **Debug** | Capturas PNG en `~/.local/share/NexusMacro/captures/` cuando algo falla. |

### 1.2 Pestañas de la UI

| Pestaña | Contenido |
|---------|-----------|
| **Connection** | Estado de Sober/gamescope, Launch/Stop Game/Reconnect, Place ID, Window (modo, minimizar, grab cursor), Auto Reconnect. |
| **Automation** | Toggles de Auto Battle/Spawners/Fuse/Best Place, estadísticas, tres botones de acción y el texto del próximo spawner. |
| **Settings** | Detección (umbral, escala, ignorar timer/precio), Buying & Scrolling, Game & gamescope (resolución, FPS, ruta, display, WM_CLASS). |
| **Log** | Salida completa, limpiar/copiar. |
| **About** | Versión, rutas, créditos. |

Ventana fija **880×560**, tema oscuro morado, sin preview ni editores de
templates.

---

## 2. Puntos de entrada

| Comando | Qué hace |
|---------|----------|
| `NexusMacro` | Abre la UI normal. Toma un lock de instancia única. |
| `NexusMacro --version` | Imprime `Nexus Macro X.Y.Z`. |
| `NexusMacro --selftest` | Detecta templates sobre un frame sintético (battle, spawner, buy, scroll). |
| `NexusMacro --ui-selftest` | Renderiza la UI offscreen a `/tmp/nexusmacro_ui.png` usando config temporal. |
| `NexusMacro --ui-config-test` | Abre la ventana real offscreen, cambia toggles/spin y verifica que se escriban y sobrevivan al cierre. Usa config temporal. |
| `NexusMacro --launch-test` | Prueba lanzar/parar Sober headless. |
| `NexusMacro --demo` | UI con preview de demo (sin motor). |

Archivo: `app.py`.

---

## 3. Flujo de ejecución

```text
app.py
  ├─ parse args / selftests
  ├─ QApplication + QLockFile (~/.local/share/NexusMacro/app.lock)
  ├─ Config.load()  (<project>/config/config.json)
  └─ MainWindow(config)
        ├─ EngineController  (hilo del motor, señales Qt)
        ├─ GamescopeLauncher (hilo de lanzamiento)
        └─ QTimer auto-reconnect / auto-detect / uptime

EngineController.start(config, matcher)
  └─ threading.Thread → Engine.run()
        ├─ backend.connect()  (Xwayland privado de gamescope)
        ├─ bucle: capture() → tick(frame) → sleep(idle_poll)
        └─ finally: backend.close(), log "Engine stopped."

Engine.tick(frame)  ← una sola acción por vuelta
  1. Discard modal       → clic, reset de pre-batalla
  2. Play                → clic, rearmar Tab, reset de pre-batalla
  3. Tab                 → una vez por entrada (HUD o fallback)
  4. Build menu abierto  → cerrar con Stop
  5. Shop sobrante       → cerrar (no comprar)
  6. Acción manual       → spawner
  7. Pre-batalla         → Fuse/Place, retry con backoff
  8. Spawner scheduler   → en partida: abrir tienda, comprar, cerrar (cooldown si falla)
  9. Battle              → clic, verificar modal/batalla
```

Cada acción deja un estado verificado o un debug con nota. El tick idle medido
en 1280×720 es ~75 ms (antes 884 ms).

## 4. Mapa de módulos

### `app.py` (284 líneas)
Entrada, flags de test, lock de instancia, `QApplication` y `MainWindow`.
No contiene lógica de juego.

### `nexusmacro/engine.py` (592 líneas) — orquestador
`Engine` decide **una acción por tick**, en prioridad estricta:

1. modal Discard,
2. Play,
3. Tab (una vez por entrada),
4. menú Build sobrante (cerrarlo),
5. tienda sobrante (cerrarla, nunca comprar),
6. acción manual,
7. Fuse / Best Place antes de Battle,
8. spawner programado,
9. Battle.

También conserva wrappers de compatibilidad (`_find_spawner`, `_buy_and_scroll`,
`_run_build_action`, `_tab_*`, etc.) para tests y diagnóstico. No hace CV de
bajo nivel.

### `nexusmacro/automation/` — componentes
| Archivo | Líneas | Responsabilidad |
|---------|--------|-----------------|
| `context.py` | 197 | `Runtime`: backend, config, matcher, stats, stop, sleep, clic, captura, log, debug con sidecar JSON. |
| `detection.py` | 150 | `ScreenDetector`: Play, Discard, Forfeit, Battle, HUD de partida, `idle_match`. Lectura pura. |
| `navigation.py` | 160 | `Navigator`: Play (cooldown 10 s), Tab one-shot **solo si `tabimage.png` está visible**, modal Discard verificado. |
| `shop.py` | 390 | `ShopSession`: `wait_opened`, `buy_and_scroll`, `close`; tolera el parpadeo de la X (5 reintentos de evidencia) y hace scroll antes de rendirse. |
| `build.py` | 300 | `BuildMenu`: `run_many` abre el menú una vez y ejecuta Fuse y/o Place ×2 con un solo Stop; Forfeit/Confirm; `last_discarded`. |
| `spawner.py` | 366 | `SpawnerFinder` multi-escala + fallback full-frame; `SpawnerScheduler` reloj/intervalo/continuo/start; `SpawnerAction`. |

### `nexusmacro/controller.py` (134 líneas)
`EngineController`: hilo del motor, señales Qt, acciones manuales y
`update_config` público. La UI ya no toca atributos privados del `Engine`.

### `nexusmacro/vision.py` (687 líneas)
Matcher de templates con máscara y NCC:
- `TemplateSpec` / `TEMPLATE_SPECS` / `DEFAULT_REGIONS`.
- `TemplateData` cacheado por clave/escala/ignores.
- `Match`, `Matcher.find/best/best_of/detect_all`, `template_status`, `reload`.
- **Rendimiento**: matching en gris, región por tipo de botón y 12–32
  candidatos verificados por NCC. El score final sigue siendo NCC. Tick idle
  medido: ~75 ms (antes 884 ms).
- `_prepare_mask`: bordes, zonas oscuras, alpha y precio.

### `nexusmacro/shopvision.py` (177 líneas)
Detección por color de la tienda:
- `buy_buttons`: verde sólido + blanco, dentro del panel.
- `close_button`: X roja + blanco verificada con template.
- `scrollbar`: barra tan/gold.
- `shop_open`: Buy o Close (la sesión estricta usa `ShopScan.open`).

### `nexusmacro/backend.py` (569 líneas)
X11/XTest: detección de display, captura, foco, movimiento suave + warp,
clics, series, scroll, drag, teclas y texto.

### `nexusmacro/launcher.py` (482 líneas)
`GamescopeLauncher`: comando gamescope, entorno SDL/Wayland, deep link de
Roblox, espera del display, PID/log, minimizar/restaurar host, stop y limpieza.

### `nexusmacro/config.py` (272 líneas)
`Config` + persistencia:
- `load` tolerante por campo, backup de JSON inválido, bool strings.
- `save` atómico con `fsync` y `config.json.bak`.
- `validate` con clamps/enums; `game_uri`.

### `nexusmacro/schedule.py` (52 líneas)
Ventana de refresco cada 5 min, próximo refresco y countdown.

### `nexusmacro/paths.py` (96 líneas)
Nombres, versión, directorios XDG, migración TowerPilot, icono y recursos.

### `nexusmacro/ui.py` (1454 líneas) — ventana y lógica de UI
- `__init__`: estado, timers, config, matcher, launcher.
- `_build_ui`, `_build_top_bar`, `_build_tab_bar`, `_build_footer`.
- `_dark_page`, `_form_card`, `_add_form_row`.
- widgets ↔ config: `_make_spin/_make_double/_make_combo/_make_check`,
  `_set_config`, `_reflect_config_in_widget`, `_sync_config_from_widgets`,
  `_save_config_now`, `_load_config_into_widgets`.
- motor: `_start_engine`, `_stop_engine`, `_on_engine_finished`.
- reconnect/launcher: `_auto_reconnect_tick`, `_restart_engine_if_needed`,
  `_launch_sober`, `_begin_launch`, `_on_launcher_ready`.
- acciones manuales: `_buy_spawners_now`, `_run_optional_manual`.

### `nexusmacro/ui_pages.py` (673 líneas)
`UiPagesMixin`: construcción de las páginas Connection, Automation, Settings,
Log y About (cards, formularios, botones y textos). No contiene estado del
motor; usa los helpers de `MainWindow` y widgets de `ui_widgets.py`.

### `nexusmacro/ui_widgets.py` (286 líneas)
`Card`, `InfoCard`, `SectionHeader`, `ToggleSwitch`, `ToggleRow`,
`FeatureCard`, `StatCard`, `LogView`.

### `nexusmacro/hostwindow.py` (145 líneas)
Utilidades X11 para encontrar/minimizar/restaurar la ventana host.

## 5. Configuración (`Config`)

| Grupo | Campos principales | Default |
|-------|--------------------|---------|
| Features | `auto_battle`, `auto_spawners`, `auto_fuse`, `auto_best_place`, `auto_reconnect` | battle/spawners/reconnect on; fuse/place off |
| Visión | `threshold`, `scale`, `ignore_spawner_timer`, `ignore_buy_price` | 0.88, 1.0, 31, 0.45 |
| Compra | `buy_clicks`, `buy_click_delay`, `max_buy_buttons`, `max_cycle_buy_clicks`, `max_scrolls` | 5, 0.05, 20, 250, 15 |
| Scroll | `scroll_method`, `scroll_drag_px`, `scroll_drag_ms`, `scroll_settle_delay` | wheel, 220, 450, 1.2 |
| Spawners | `spawner_timing`, `spawner_window_seconds`, `spawner_interval_minutes`, `spawner_poll_seconds`, `spawner_threshold`, `spawner_preference` | clock, 55, 5, 30, 0.80, auto |
| Ritmo | `action_delay`, `battle_poll`, `battle_cooldown`, `idle_poll`, `cycle_delay`, `shop_open_timeout` | 0.07, 1.0, 2.0, 0.6, 1.0, 8.0 |
| Juego | `auto_join`, `game_place_id`, `window_width/height`, `gamescope_backend`, `gamescope_fps`, `gamescope_grab_cursor`, `minimize_on_start`, `gamescope_path`, `display`, `window_class` | 1280×720, sdl, 60, grab off, minimize on |
| Debug | `save_debug_frames` | true |

Ruta principal: `<project>/config/config.json` (portable). Si no se detecta
el proyecto: `~/.config/NexusMacro/config.json`.
Backup: `config.json.bak`.

---

## 6. Templates y detección

| Key | Archivo | Uso |
|-----|---------|-----|
| battle | battle1.png | Botón Battle |
| battle2 | battle2.png | Continuar tras victoria |
| yescontinue | yescontinue.png | Confirmar batalla en curso |
| spawner1 | spawners1.png | Spawner grande |
| spawner2 | spawners2.png | Spawner compacto |
| spawner3 | spawnerbutton3.png | Spawner con timer |
| build | build1.png | Abrir Build |
| fuseall | fuseallbutton.png | Fuse All |
| placebest | placebestbutton.png | Place Best |
| stop | stopbutton.png | Cerrar menú Build |
| forfeit | forfeitbutton.png | Rendirse en batalla |
| confirm | confirmbutton.png | Confirmar forfeit |
| discard | discardbutton.png | Descartar batalla guardada |
| play | playbutton.png | Play de Roblox |
| buy | buybutton.png | Fallback de Buy (color es primario) |
| scroll | scrollspawner.png | Fallback de scrollbar |
| close | closebutton.png | X de la tienda |
| tabimage | tabimage.png | Cabecera del leaderboard: solo entonces se pulsa Tab |
| reconnectbutton | reconnectbutton.png | Pantalla de reconexión: **nunca se pulsa**; se reinicia Sober/gamescope |

Umbrales: `threshold` global 0.88; plantillas de acción bajan a 0.70–0.75;
spawners usan `spawner_threshold` 0.80; shop por color no usa template salvo
Close/Scroll.

---

## 7. Rutas de datos

| Ruta | Contenido |
|------|-----------|
| `<project>/config/config.json` | Configuración portable (principal) |
| `<project>/config/config.json.bak` | Versión anterior |
| `<project>/config/config.invalid-*.json` | JSON corrupto preservado |
| `<project>/config/templates/` | Overrides de usuario (opcional) |
| `~/.config/NexusMacro/` | Fallback sin proyecto + migración antigua |
| `~/.local/share/NexusMacro/captures/` | Capturas de debug |
| `~/.local/share/NexusMacro/app.lock` | Lock de instancia |
| `~/.local/share/NexusMacro/gamescope.pid` / `.log` | Launcher |
| `templates/` del proyecto | Imágenes empaquetadas |

---

## 8. Hilos y ciclo de vida

- **GUI**: hilo principal Qt. Timers de uptime, reconnect, auto-detect.
- **EngineController**: `threading.Thread` daemon con `Event` de stop. Emite
  señales Qt para log/status/stats.
- **GamescopeLauncher**: `threading.Thread` daemon para lanzar y esperar el
  display. Señales vía `LauncherBridge`.
- **Acciones manuales**: hilos separados lanzados por el controlador; no
  bloquean la UI.
- **Stop**: set del evento; las acciones hacen `_check_stop()` en cada espera.
  Stop también cancela Auto Reconnect.

---

## 9. Tests

| Archivo | Cubre |
|---------|-------|
| `tests/test_engine.py` | Tick, batalla, tienda, spawners, build, Tab, Play, descarte, scroll, stop. |
| `tests/test_automation.py` | Scheduler (reloj/intervalo/continuo/start), detección, retry de pre-batalla, menú sobrante, `update_config`. |
| `tests/test_shopvision.py` | Buy/Close/Scroll por color y escala. |
| `tests/test_schedule.py` | Ventana de refresco y countdown. |
| `tests/test_ui_config.py` | Guardado de toggles/números, sync de spin, Stop cancela reconnect. |
| `tests/test_config_persistence.py` | Roundtrip, valores inválidos, JSON corrupto, backup, bool strings. |

Total: **60 tests OK**.

Comandos:

```bash
./.venv/bin/python -m unittest discover -s tests -q
./.venv/bin/python app.py --selftest
QT_QPA_PLATFORM=offscreen ./.venv/bin/python app.py --ui-selftest
QT_QPA_PLATFORM=offscreen ./.venv/bin/python app.py --ui-config-test
```

## 10. Limitaciones conocidas

- Los templates están calibrados a 1280×720 y escala 1.0; cambios de HUD del
  juego requieren recalibrar imágenes.
- El juego puede tardar en cargar; Tab espera HUD o un fallback de 20 s.
- La detección de tienda por color puede fallar si el juego cambia la paleta.
- Los campos heredados `preview_while_running`, `auto_fuse_option` y
  `auto_best_place_option` fueron eliminados. `max_buy_buttons` ahora se usa.
- Las regiones de búsqueda (`DEFAULT_REGIONS`) asumen el HUD a 1280×720; si el
  juego mueve un botón, hay que ajustar la región o la imagen.
- Los spawners se intentan cuando hay HUD de partida. Si el clic de spawner no
  abre tienda, hay un cooldown de 15 s para no repetir el mismo clic.
- Play tiene un cooldown de 10 s para no encadenar partidas en la pantalla de
  carga.
- El botón Reconnect de Roblox nunca se pulsa; se reinicia el juego completo.
- La config es portable en `<project>/config/`; `install.sh` deja un marcador
  en `~/.local/bin/NexusMacro.home` y `Path=` en el lanzador.
- La UI no tiene editor de templates a propósito.
- No hay git en el proyecto; los cambios se respaldan manualmente.

---

## 11. Registro de actualizaciones de este documento

- Inicial: inventario del código previo al refactor y arquitectura objetivo.
- 2026-11-24: refactor completado (1.5.0): motor dividido en orquestador +
  `automation/*`; controlador Qt extraído; matcher en gris con regiones.
- 2026-11-24: 1.5.1 hotfix de Discard (fallback centrado y clic verificado).
- 2026-11-24: 1.5.2 manuales sin motores concurrentes, scroll tolerante a la X
  y verificación de Battle más larga.
- 2026-11-24: 1.5.3 un solo menú Build para Fuse+Place, Tab condicionado a
  `tabimage.png`.
- 2026-11-24: 1.5.4 pantalla Reconnect sin clic (reinicio completo), config
  portable en el proyecto, icono multi-tamaño/desktop, sin botón Open Templates
  y subtítulo “Build a Tower Defense Autopilot”; 60 tests.
