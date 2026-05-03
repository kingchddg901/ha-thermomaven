# Entities Reference

Exhaustive list of every entity the integration exposes. Entity IDs are
derived from the device's `deviceName` (set in the official app) — examples
below assume `deviceName = "Grill thermo"`.

---

## Per base station

One HA "device" per ThermoMaven base station. All entities in this section
group under that device.

### Sensors

| Entity ID | Type | Unit | Source field | Notes |
|---|---|---|---|---|
| `sensor.grill_thermo_base_battery` | int | % | `batteryValue` | 0–100. While charging, polling rate causes apparent fluctuation — value is real. |
| `sensor.grill_thermo_base_battery_status` | string | – | `batteryStatus` | Observed: `normal`, `low`, `charging`. |
| `sensor.grill_thermo_base_wifi_rssi` | int | dBm | `wifiRssi` | Negative integer. |
| `sensor.grill_thermo_connection_mode` | string | – | `connectStatus` | Observed: `wifi`, `both`. Presumed: `ble`. |
| `sensor.grill_thermo_alarm_volume` | string | – | `volume` | Read-only sensor. See `select.*_alarm_volume` for the writable version. |
| `sensor.grill_thermo_online_status` | string | – | `globalStatus` | Observed: `online`. Presumed: `offline`. |

### Binary sensors

| Entity ID | Device class | Source field | Notes |
|---|---|---|---|
| `binary_sensor.grill_thermo_online` | `connectivity` | `globalStatus == "online"` | |
| `binary_sensor.grill_thermo_wifi_configured` | – | `hasWifiConfig` | Diagnostic. |

### Select

| Entity ID | Options | Effect |
|---|---|---|
| `select.grill_thermo_alarm_volume` | `high`, `medium`, `quiet` | Fires `<MODEL>:setting:modify` with `{volume: <option>}`. |

---

## Per probe

One set per probe (one for the WT11/P1, two for WT07/G2 and WT02/P2, four
for WT06/P4 and WT09/G4). Sub-entities of the base device, named with the
probe's color slot (`probe1`..`probe4`). The integration uses the friendly
"Probe N" form via translation placeholders.

### Sensors — temperatures

| Entity ID | Source | Notes |
|---|---|---|
| `sensor.grill_thermo_probe_1_temperature` | `curTemperature / 10` | The device's chosen "effective" reading (always equals one of T1..T5). **Carries multi-zone heuristic attributes — see below.** |
| `sensor.grill_thermo_probe_1_ambient` | `curAmbientTemperature / 10` | Air temp at probe handle (6th thermistor). |
| `sensor.grill_thermo_probe_1_target` | `setParams[0].setTemperature / 10` | Read-only sensor. See `number.*_target_temperature` for the writable version. |
| `sensor.grill_thermo_probe_1_t1_tip` | `areaTemperature[0] / 10` | Tip thermistor. Deepest in food when probe fully inserted. |
| `sensor.grill_thermo_probe_1_t2` | `areaTemperature[1] / 10` | |
| `sensor.grill_thermo_probe_1_t3_center` | `areaTemperature[2] / 10` | Center thermistor — best "uniform meat temp" candidate. |
| `sensor.grill_thermo_probe_1_t4` | `areaTemperature[3] / 10` | |
| `sensor.grill_thermo_probe_1_t5_rear` | `areaTemperature[4] / 10` | Rear/handle thermistor. Reads air when probe is shallow. |

#### Multi-zone heuristic attributes (on `*_temperature`)

| Attribute | Meaning |
|---|---|
| `area_temperature` | Full 5-element array `[T1, T2, T3, T4, T5]` in display unit — convenient for graphing all zones from a single entity. |
| `zone_min` / `zone_max` | Min/max across all 5 zones (incl. zones reading air). |
| `ambient` | Same as the ambient sensor — included for self-contained templates. |
| `zones_in_meat` | 0..5 — count of contiguous-from-tip zones differing from ambient by ≥5 °F. |
| `meat_coldest` | Min of in-meat zones only — the food-safety-relevant number. Absent when `zones_in_meat == 0`. |
| `meat_median` | Median of in-meat zones — the "true" doneness reading. Absent when `zones_in_meat == 0`. |
| `meat_hottest` | Max of in-meat zones — surface-sear risk. Absent when `zones_in_meat == 0`. |

The 5 °F threshold is chosen to avoid false negatives during ambient-crossings
(meat reaching pit temp on long low-and-slows). It's hardcoded for now — open
an issue if you need it tunable.

### Sensors — non-temperature

| Entity ID | Type | Unit | Source | Notes |
|---|---|---|---|---|
| `sensor.grill_thermo_probe_1_battery` | int | % | `batteryValue` | Probe battery, 0–100. ~10% with 3 hours remaining is normal at end of a 16-hour cook. |
| `sensor.grill_thermo_probe_1_cooking_state` | string | – | `cookingState` | Observed: `cooking`, `charged`. Presumed: `idle`, `removed`, `done`, `resting`. |
| `sensor.grill_thermo_probe_1_cooking_mode` | string | – | `cookingMode` | `smart` or `manual`. Recipe cooks present as `smart`. |
| `sensor.grill_thermo_probe_1_cook_id` | string | – | `cookUuid` | Stable per cook session. Useful for "new cook started" automation triggers. |
| `sensor.grill_thermo_probe_1_label` | string | – | `probeNotes` | User-set label from the official app. Empty until first edit. |
| `sensor.grill_thermo_probe_1_elapsed` | int | s | `curCookSec` | Device-side cook timer. |
| `sensor.grill_thermo_probe_1_remaining` | int | s | `curRemainedSec` | Device's ETA. `null` until the device computes it (~1 min into a fresh cook). |
| `sensor.grill_thermo_probe_1_total` | int | s | `totalCookSec` | Device's total-target. |

### Binary sensors

| Entity ID | Device class | Source field | Notes |
|---|---|---|---|
| `binary_sensor.grill_thermo_probe_1_cooking` | `running` | `cooking` | True while a cook session is active. |
| `binary_sensor.grill_thermo_probe_1_overheat` | `problem` | `overheat` | True when probe exceeded its target temp's overheat threshold. |

### Number

| Entity ID | Range | Step | Unit | Effect |
|---|---|---|---|---|
| `number.grill_thermo_probe_1_target_temperature` | 80–500 | 1 | °F | Mutates running cook (preserves `cookUuid`). If no cook running, starts a fresh one. |

### Buttons

| Entity ID | Effect | Available when |
|---|---|---|
| `button.grill_thermo_probe_1_finish_cook` | Fires `<MODEL>:cooking:action(Finish=5)`. | A cook is running. |
| `button.grill_thermo_probe_1_stop_cook` | Fires `<MODEL>:cooking:action(STOP=2)`. | A cook is running. |

> [!IMPORTANT]
> See [PROTOCOL.md § "Lying success" caveat](PROTOCOL.md). Both buttons may
> ACK success without actually ending the cook if the probe is still inserted.

---

## When the probe is docked

When the probe seats on the base, the device drops most fields from the per-probe
payload — only `probeColor`, `cookingState: "charged"`, `cookingMode`, and
`setParams` survive. Affected entities flip to "unavailable":

- All temperature sensors (current / ambient / T1-T5).
- Battery sensor.
- All time sensors (elapsed / remaining / total).
- `cook_id`, `label` sensors.
- Both binary sensors (`cooking`, `overheat`).
- Both buttons (require an active cook).

The `cooking_state` sensor reports `charged`. The `target_temperature` number
keeps the last-active cook's target value (the device carries it over).

This is a useful signal for automations: `binary_sensor.*_cooking` going
`off` while `sensor.*_cooking_state == "charged"` is the canonical "probe
returned to dock" event.

---

## Events

| Event type | Fired when | Data |
|---|---|---|
| `thermomaven_command_receipt` | Any `device:cmd:receipt` MQTT message arrives | Full receipt envelope (see PROTOCOL.md) |

Use this to react to command outcomes — especially failures (`cmdData.cmdError != 0`).
