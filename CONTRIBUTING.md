# Contributing

Thanks for helping. Nexus Macro is a small, test-heavy project; please keep
changes focused and include a test when behaviour changes.

## Development

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./run_dev.sh
```

Run the checks before opening a PR:

```bash
./.venv/bin/python -m unittest discover -s tests -q
./.venv/bin/python app.py --selftest
QT_QPA_PLATFORM=offscreen ./.venv/bin/python app.py --ui-config-test
```

## Guidelines

- The engine must stay usable without the UI: `nexusmacro/engine.py` is the
  orchestrator, `nexusmacro/automation/` contains components.
- Do not click the Roblox Reconnect button. Restart the game instead.
- Shop actions only run after a spawner click. Never scan the whole screen for
  Buy buttons.
- Keep the config portable: no absolute user paths in committed files.
- Templates are calibrated to 1280x720. A template change needs a real capture
  and a note in the PR.
- Do not commit `config/`, `dist/`, `release/`, `.venv/` or `vendor/gamescope/`.

## Architecture

Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and
[`docs/REFACTOR_PLAN.md`](docs/REFACTOR_PLAN.md) before touching the engine.
