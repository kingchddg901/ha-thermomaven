# Development Guide

How to extend, debug, and contribute to ha-thermomaven.

---

## Architecture refresher

```
config_flow.py  ──►  __init__.py  ──►  coordinator.py  ──►  api.py
                                            │
                                            ├──► sensor.py
                                            ├──► binary_sensor.py
                                            ├──► number.py
                                            ├──► select.py
                                            └──► button.py
```

- **`api.py`** does all REST. Stateless except for `token` + `user_id`. No
  business logic.
- **`coordinator.py`** owns the MQTT connection (paho running in a worker
  thread, `loop_forever()`), maintains the in-memory device-state cache, and
  exposes high-level command helpers (`async_set_volume`,
  `async_set_target_temp`, `async_finish_cook`, `async_stop_cook`). All the
  cmdType / cmdData shape construction lives here.
- **`sensor.py`** defines the entity base classes (`_ThermoMavenEntity`,
  `_ProbeEntity`) — `binary_sensor.py`, `number.py`, `select.py`, `button.py`
  reuse these via `from .sensor import _ProbeEntity` to share device-info
  + listener-wiring boilerplate.
- **Discovery** is dynamic: every platform's `async_setup_entry` registers a
  `coordinator.add_listener(None, _discover)` callback that runs on every
  global-state update. New devices/probes that appear in `user:device:list`
  add new entities mid-runtime without restart.

---

## Local dev loop

The HA install lives at `\\192.168.4.104\config\` (mapped as `Z:\` for the
maintainer). The repo's working copy lives at `C:\Users\CKing\Documents\ha-thermomaven\`.

Files in `Z:\custom_components\thermomaven\` are the live-running copy.
Files in `C:\Users\CKing\Documents\ha-thermomaven\custom_components\thermomaven\`
are the repo source. They are not auto-synced — the workflow is:

1. Edit files in the repo working copy.
2. Copy the changed files to the HA config dir (`cp -r` from the repo to `Z:\`).
3. Restart HA (or reload the integration if the change is platform-only).
4. When happy, commit + push from the repo working copy.

For new contributors, the simplest setup is symlinking the repo
`custom_components/thermomaven` into your HA `custom_components/` directory
so edits land in HA immediately.

---

## Adding a new device model

Most of the integration is model-agnostic. The hardcoded model-specific bits:

1. **`const.py`** — add to `DEVICE_MODEL_NAMES` so the friendly name appears
   on the HA device card:
   ```python
   DEVICE_MODEL_NAMES = {
       ...
       "WT12": "ThermoMaven Whatever",
   }
   ```
2. **`coordinator.py` `_cmd_type()`** — falls back to "WT11" if no model is
   recognized. For a new model, no change needed — the function constructs
   `f"{model}:<verb>"` from the `deviceModel` field on the cached device info.
3. **`number.py`** target-temp range — currently `TARGET_TEMP_MIN=80`,
   `TARGET_TEMP_MAX=500`. Tighten if a new model has narrower bounds.

If the new device emits unfamiliar `cmdType` values you'll see them as
"unhandled cmdType" debug logs. The model's per-verb constructor lives in
`s5/O.<init>` of the dex (see PROTOCOL.md) — usually the suffix is identical
across models, only the prefix changes.

---

## Adding a new write verb

Pattern (using ChangeResting as an example):

1. **`const.py`** — `ACTION_CHANGE_RESTING = 4` already exists.
2. **`coordinator.py`** — add a method:
   ```python
   async def async_change_resting(self, device_id: str, probe_color: str) -> str:
       probe = self._probe(device_id, probe_color) or {}
       cook_uuid = probe.get(F_COOK_UUID)
       if not cook_uuid:
           raise RuntimeError("no active cook")
       cmd_data = {
           "probeColor":    probe_color,
           "cookingAction": ACTION_CHANGE_RESTING,
           "cookUuid":      cook_uuid,
       }
       cmd_type = self._cmd_type(device_id, CMD_TYPE_COOKING_ACTION_SUFFIX)
       return await self.api.send_command(device_id, cmd_type, cmd_data)
   ```
3. **`button.py`** — add a `_ChangeRestingButton` class mirroring `_FinishCookButton`,
   register it in `_discover()`, add the unique-id and translation slug.
4. **`strings.json` + `translations/en.json`** — add a `button.probe_change_resting.name`.

Verify with the recon `send_test.py` first (against the throwaway account) to
confirm the cmdData shape is accepted; only then add the entity.

---

## Adding a new sensor field

The device emits more fields than the integration currently exposes. To add
one (example: `temperaturePercentile[0]` as a "stability" sensor):

1. **`const.py`** — add a `F_TEMP_PERCENTILE = "temperaturePercentile"` if not
   already there.
2. **`sensor.py`** — add a `_ProbeStabilitySensor` class:
   ```python
   class _ProbeStabilitySensor(_ProbeEntity):
       _attr_state_class = SensorStateClass.MEASUREMENT
       _attr_entity_category = EntityCategory.DIAGNOSTIC

       def __init__(self, coordinator, device_id, color):
           super().__init__(coordinator, device_id, color, "stability")

       @property
       def native_value(self):
           arr = self._val(F_TEMP_PERCENTILE)
           return arr[0] if isinstance(arr, list) and arr else None
   ```
3. Register in `_build_probe_sensors`.
4. Add translation key.

---

## Debug logging

```yaml
# configuration.yaml
logger:
  default: info
  logs:
    custom_components.thermomaven: debug
```

Useful log messages from the integration:
- `ThermoMaven MQTT loop started (clientId=...)` — connection succeeded.
- `auto-subscribed device/<MODEL>/<id>/pub` — coordinator picked up a new
  per-device topic from the snapshot.
- `unhandled cmdType=...` — surface a previously-unseen cmdType. If you see
  these in the field, please open an issue with the message body and we'll
  add handling.
- `ThermoMaven MQTT disconnected rc=...` — paho disconnect reason. `rc=0` is
  a clean close, `rc=1..7` are protocol-level issues, `rc=16` is auth failure
  (cert rotated server-side — restart the integration to re-fetch).

---

## Testing without HA

The companion recon scripts in the dev tree (not shipped in releases) are
runnable against the throwaway account directly:

```bash
# Verify auth + REST work end-to-end
python thermomaven_client.py

# Watch the live MQTT stream + JSONL-log everything
python mqtt_listen.py

# Fire write commands
python send_test.py volume high
python send_test.py target 205          # new cookUuid (replaces running cook)
python send_test.py mutate <uuid> 200   # reuse running cookUuid (mutate target)
python send_test.py finish <uuid>
python send_test.py stop <uuid>
python send_test.py raw "WT11:foo:bar" '{"key":"value"}'
```

These use the same `appId` / `appKey` / sign formula as the integration — if
the integration breaks but these still work, the bug is in HA-glue code, not
protocol.

---

## Reverse-engineering tools

If the protocol changes and you need to re-derive things:

```bash
pip install androguard capstone unicorn pyelftools
```

- **Find a string's xref:** `find_sign.py`. Edit `TARGET_STRINGS` to the new
  string you're hunting and re-run. Tells you which Java class/method
  references it.
- **Dump a method body:** `dump_method.py`. Edit `TARGETS` to the
  `(class, method)` you want, run, get both the decompiled Java AND the
  raw smali. The decompiler is sometimes lossy — always cross-check with
  smali for ground truth.
- **Disassemble native code:** `disasm_jni.py`. Currently hardcoded for
  `Java_h_A0_sk` but easy to retarget. If Auros adds a new native function
  (e.g. for cert pinning), this is your starting point.

The general flow is: grep for distinctive strings (e.g. `"app/command/send"`)
in the strings dump → find the method that uses them → trace what builds
the request body → trace what fields come from where → verify with a live
test.

---

## Release process

1. Make changes in the repo working copy.
2. Run a syntax check: `python -c "import ast; [ast.parse(open(f).read()) for f in glob.glob('custom_components/thermomaven/*.py')]"`.
3. Copy the changed files to `Z:\custom_components\thermomaven\` (or your
   HA config dir).
4. Restart HA. Verify entities still load, your change behaves as intended.
5. Bump `manifest.json` `version` per semver.
6. Update `CHANGELOG.md` with what changed.
7. `git add -A && git commit -m "vX.Y.Z — short summary"`.
8. `git tag -a vX.Y.Z -m "..."` and `git push --follow-tags`.
9. `gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."` — use the
   CHANGELOG section verbatim for the release notes.

HACS will pick up the new release within an hour or so.

---

## Code style

- Banner-comment headers at the top of each file. The pattern is
  `/* ============================================================` etc.
  Visually distinct from regular Python comments — easy to skim through
  files in IDEs.
- Type hints throughout. `from __future__ import annotations` at the top.
- 4-space indent. No black/ruff configured but PEP-8 in spirit.
- Field-name constants (`F_*`) for every JSON key. `cmdType` discriminator
  constants (`CMD_*`) for every observed cmdType. No magic strings in
  business logic.
- `_LOGGER = logging.getLogger(__name__)` at module top, never `print()`.
- `async_*` prefix for coroutines, no prefix for sync.
- Listener cleanup uses `entry.async_on_unload(remove_callable)` —
  unloading the entry releases all listeners automatically.
