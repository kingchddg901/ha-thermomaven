# ha-thermomaven

Home Assistant custom integration for **ThermoMaven** (Auros) wireless meat thermometers.
Surfaces every probe sensor the device emits — including the multi-zone thermistor array the
official app hides — and lets HA control target temp, alarm volume, and cook lifecycle.

Tested live against a ThermoMaven P1 (WT11) but designed to work with the entire WT line
(P2/WT02, P4/WT06, G2/WT07, G4/WT09, G1/WT10, P1/WT11) since they share the cloud protocol.

> [!NOTE]
> This is an unofficial integration. It is not affiliated with or endorsed by Auros / ThermoMaven.
> It uses the same cloud APIs the official app uses; if Auros changes the protocol, the
> integration will break until updated.

> [!IMPORTANT]
> **Maintenance model.** This is a one-off scratch-an-itch project, not an actively-maintained
> integration. Scoped bugs on the maintainer's own hardware (WT11/P1) or small fixes get
> shipped quickly, but feature work, new device models, or sustained development effort are
> unlikely. For a more actively-maintained ThermoMaven HA integration see
> [djiesr/ThermoMaven-ha](https://github.com/djiesr/ThermoMaven-ha) — natural community home
> for this ecosystem.

---

## Features

### Read path (MQTT-driven, real-time, ~10s cadence)

**Per probe:**
- Effective probe temperature (the device-chosen reading)
- Ambient temperature (probe handle thermistor)
- Target temperature
- **All 5 zone temperatures (T1 tip → T5 rear)** as individual sensors
- Battery percent
- Cooking state, cooking mode, cook UUID, user-set probe label
- Elapsed / remaining / total cook seconds
- Cooking + overheat binary sensors

**Per base station:**
- Battery percent + status (normal / low / charging)
- WiFi RSSI (dBm)
- Connection mode (BLE / WiFi / both)
- Alarm volume
- Online status (sensor + binary)

**Multi-zone "is the probe in the meat?" heuristic** as attributes on the probe's main
temperature entity:
- `area_temperature`: full 5-element array (graph-friendly)
- `zone_min` / `zone_max`: range across all zones
- `zones_in_meat`: count of contiguous-from-tip zones differing from ambient by ≥5 °F
- `meat_coldest`: lowest in-meat zone — the food-safety-relevant number
- `meat_median`: center of in-meat zones — the "true" doneness reading
- `meat_hottest`: highest in-meat zone — surface-sear risk

This adapts automatically to cut size: a steak with only T1–T3 buried gives `zones_in_meat: 3`
and uses just those for the stats; a 16-hour brisket with all 5 buried gives `zones_in_meat: 5`.
If the probe slides out mid-cook, `zones_in_meat` drops — you can alert on it.

### Write path

- `number.<probe>_target_temperature` — sliding the target fires `cooking:action(START)`
  with the **running cook's UUID preserved**, so the device just picks up the new target
  without restarting the cook.
- `select.<base>_alarm_volume` — `high` / `medium` / `quiet`.
- `button.<probe>_finish_cook` and `button.<probe>_stop_cook` — fire `cooking:action`
  Finish (5) and Stop (2) respectively. Buttons auto-greyed when no cook is running.

### Event bus

Every device command receipt fires `thermomaven_command_receipt`:

```yaml
event_type: thermomaven_command_receipt
data:
  cmdId: "..."
  cmdType: "WT11:cooking:action"
  cmdData:
    cmdId: "..."          # the cmdId we sent
    cmdType: "..."        # the verb we asked for
    executeResult: success | failure
    errorCode: 0
    cmdError: 0           # non-zero = real failure (eg cmdError:4 = action invalid for cook state)
```

> [!IMPORTANT]
> **Finish / Stop "lying success" caveat.** The device will ACK Finish or Stop with
> `executeResult: success` while silently no-op'ing if the probe is still inserted /
> docked. The cook genuinely ends when the probe is physically removed from the food
> (or returns to the dock). HA cannot distinguish "succeeded" from "acknowledged but
> ignored" from the receipt alone — watch for `cookingState` to actually change in
> the next 1–2 status reports if your automation needs strong confirmation.

---

## Installation

### Via HACS (recommended once added to default repos)

In the meantime, add as a custom repository:

1. HACS → ⋮ menu → Custom repositories
2. URL: `https://github.com/kingchddg901/ha-thermomaven`
3. Type: Integration
4. Install **ThermoMaven**
5. Restart Home Assistant
6. Settings → Devices & Services → **Add Integration** → ThermoMaven

### Manual

1. Copy `custom_components/thermomaven/` into your HA `custom_components/` directory.
2. Restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → ThermoMaven.

---

## Recommended setup pattern: throwaway secondary account

The ThermoMaven cloud allows only one fully-active session per account. If HA logs in
with your primary account, your phone may compete for the session — leading to
intermittent disconnects on either side.

**Use a second account dedicated to HA:**

1. Sign up a throwaway ThermoMaven account on the Auros website / app.
2. From your **primary** account in the official app, share the device(s) to the throwaway.
3. Sign **HA** in with the throwaway.
4. Both phone and HA stream live data independently.

This is the same dual-account workaround used for cloud-IoT integrations like
`ha-prime-polaris`. The integration's setup-flow description reminds you of this.

---

## Templates: getting the most out of multi-zone

The whole point of a probe like the WT11 is the 5-zone thermistor array. The integration
exposes the array directly so you can build smarter readings than any single-temp probe
can give you.

```yaml
template:
  - sensor:
      # The "true" doneness number — median of zones currently in the meat.
      # Robust against probe slipping out a bit (T5 reads air temp).
      - name: "Probe 1 Doneness"
        unit_of_measurement: "°F"
        device_class: temperature
        availability: >
          {{ state_attr('sensor.grill_thermo_probe_1_temperature', 'zones_in_meat') | int(0) > 0 }}
        state: >
          {{ state_attr('sensor.grill_thermo_probe_1_temperature', 'meat_median') }}

      # The food-safety number — the coldest part of the meat.
      # Pull when this hits target, not when "the probe" hits it.
      - name: "Probe 1 Safe Temp"
        unit_of_measurement: "°F"
        device_class: temperature
        state: >
          {{ state_attr('sensor.grill_thermo_probe_1_temperature', 'meat_coldest') }}

      # Insertion-quality monitor — alert when probe falls out mid-cook.
      - name: "Probe 1 Insertion"
        state: >
          {% set n = state_attr('sensor.grill_thermo_probe_1_temperature', 'zones_in_meat') | int(0) %}
          {% if n == 0 %}Not inserted
          {% elif n < 3 %}Shallow ({{ n }}/5)
          {% else %}Good ({{ n }}/5){% endif %}
```

Tune the `5 °F` threshold in the integration if your cooks run with meat very close to
ambient (lower it) or you see false positives during ambient-crossings on long low-and-slows
(raise it).

---

## Supported devices

All current WT-series ThermoMaven thermometers should work — they share the cloud protocol.
Confirmed live: WT11 (P1).

| Model | Brand name | Probes |
|-------|-----------|--------|
| WT02  | ThermoMaven P2 | 2 |
| WT06  | ThermoMaven P4 | 4 |
| WT07  | ThermoMaven G2 | 2 |
| WT09  | ThermoMaven G4 | 4 |
| WT10  | ThermoMaven G1 | 1 |
| WT11  | ThermoMaven P1 | 1 |

If you have one of the unverified models and it works (or doesn't), please open an issue
with the device model and any non-status `cmdType` strings you see in HA's debug logs —
those are the most likely places for per-model differences.

---

## How it works

- **REST signing.** Every API call uses an MD5 sign over `appKey + sortedHeaders + body`.
- **AWS IoT MQTT mTLS.** After login, HA fetches a per-session X.509 client cert from
  `/app/mqtt/cert/apply`, downloads the `.p12` keystore, splits it into PEM, and
  connects to AWS IoT Core via `paho-mqtt` running in a worker thread.
- **Per-user firehose.** The cert authorizes one topic — `app/user/{userId}/sub` —
  which delivers a `user:device:list` snapshot that names per-device pub topics
  (`device/{model}/{deviceId}/pub`). HA dynamically subscribes to those for the
  realtime probe stream.
- **Write path.** Commands go via the same signed REST endpoint
  (`POST /app/command/send` with `{deviceId, deviceType, cmdType, cmdId, cmdData}`).
  The server queues, the device executes, and the device publishes a
  `device:cmd:receipt` MQTT message back containing the matching `cmdId`.

The architecture mirrors the official Android app exactly. No protocol shortcuts or
unofficial endpoints.

---

## Troubleshooting

- **"Invalid email or password."** Check that the throwaway account is using the
  region you selected (US vs DE). The wrong region returns a generic auth failure.
- **Entities "unavailable" after probe docks.** Expected — when the probe seats on
  the base, the device drops most fields from the per-probe payload (deviceSn,
  battery, all temps, cookUuid). Entities flip to unavailable until you remove the
  probe; the base-level entities (online, RSSI, base battery) keep working.
- **Finish/Stop button presses "do nothing".** See the lying-success caveat above —
  the device requires the probe to be physically removed before these verbs take
  real effect. The receipt event will still fire so you can verify the command was
  delivered.

Enable debug logging on the integration:

```yaml
logger:
  default: info
  logs:
    custom_components.thermomaven: debug
```

---

## More documentation

- [docs/PROTOCOL.md](docs/PROTOCOL.md) — full reverse-engineering writeup of the
  ThermoMaven cloud protocol (sign formula, embedded credential recovery,
  MQTT envelope shapes, every cmdData schema, the lying-success caveat).
- [docs/ENTITIES.md](docs/ENTITIES.md) — exhaustive list of every entity the
  integration exposes, what fields they read, what attributes they carry.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — how to extend the integration
  (new device model, new write verb, new sensor), debug logging, release
  process.
- [CHANGELOG.md](CHANGELOG.md) — release history.

## License

MIT. See [LICENSE](LICENSE).

## Acknowledgements

Protocol reverse-engineered from `com.auros.thermomaven` v1.9.6 using
[androguard](https://github.com/androguard/androguard) and
[capstone](https://www.capstone-engine.org/) for the JNI key recovery. Thanks to
Auros for shipping a perfectly functional, well-structured cloud API even if
unintentionally so.
