# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-05-02

First public release.

### Added
- **Read path** (MQTT-driven, AWS IoT mTLS, ~10s cadence):
  - Per base: battery %, battery status, WiFi RSSI, connection mode, alarm
    volume, online status sensors and the corresponding online + WiFi-
    configured binary sensors.
  - Per probe: effective temperature, ambient, target, all 5 zone
    thermistors (T1 tip → T5 rear) as individual sensors, battery %,
    cooking state / mode / UUID / user label, elapsed / remaining / total
    cook seconds.
  - Multi-zone "in meat" heuristic exposed as attributes on the probe's
    main temperature entity: `area_temperature`, `zone_min`, `zone_max`,
    `zones_in_meat`, `meat_coldest`, `meat_median`, `meat_hottest`.
  - Per-probe `cooking` and `overheat` binary sensors.
- **Write path:**
  - `number.<probe>_target_temperature` — target-temp slider, mutate-mode
    (preserves running `cookUuid`).
  - `select.<base>_alarm_volume` — high / medium / quiet.
  - `button.<probe>_finish_cook` and `button.<probe>_stop_cook` —
    auto-greyed when no cook is running.
- **Event bus:** `thermomaven_command_receipt` fires for every MQTT
  `device:cmd:receipt` so automations can react to command outcomes.
- **Config flow:** email + password + region (US / DE), validated by
  performing an actual login.
- **Setup hint:** the config-flow description recommends the throwaway-
  secondary-account pattern (share devices to a HA-only account) so HA
  doesn't compete with the user's phone for the primary session.
- **Documentation:** README, PROTOCOL.md (full reverse-engineering writeup),
  DEVELOPMENT.md (extension guide), ENTITIES.md (exhaustive entity list).
- **HACS support:** `hacs.json` + `info.md` for HACS-discoverable installs.

### Verified
- Live-tested against ThermoMaven P1 (WT11) on 2026-05-02. Login → MQTT
  subscribe → all five `cooking:action` verbs → setting:modify → all
  receipts confirmed.
- Other WT-series models (WT02/06/07/09/10) should work since they share
  the cloud protocol but are unverified — please open issues with debug
  logs if your device behaves differently.

### Known limitations
- Temperature unit hardcoded to °F. The login response carries
  `setting.temperatureUnit` ("F" or "C") but the integration doesn't
  plumb it through yet.
- Multi-step recipe cooks only show the first step's `setTemperature`.
  Step transitions arrive as fresh `cooking:action` commands the device
  handles internally — HA can't surface "we're on step 3 of 5".
- `cookingData` is outbound-only — recipes show as `cookingMode: "smart"`
  in status reports, indistinguishable from manual smart cooks.
- Finish / Stop buttons may report success while the device silently
  no-ops (probe still inserted/docked). See README & PROTOCOL.md.

[Unreleased]: https://github.com/kingchddg901/ha-thermomaven/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/kingchddg901/ha-thermomaven/releases/tag/v0.2.0
