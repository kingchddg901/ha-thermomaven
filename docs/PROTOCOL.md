# ThermoMaven Cloud Protocol

This document describes the protocol used between the official Android app
(`com.auros.thermomaven`, version 1.9.6, versionCode 1906) and the ThermoMaven
cloud, as recovered by APK reverse-engineering on 2026-05-02. The HA integration
in this repo speaks the same protocol.

It is published here so future maintainers don't have to re-derive any of this.
If Auros changes the protocol the integration will break — this document is
your map back to working code.

---

## TL;DR

```
                                      AWS IoT MQTT (mTLS, port 8883)
HA  ──── REST POST signed (md5) ────►  ThermoMaven cloud  ◄──── publish ────  Device
        api.iot.thermomaven.com       a2ubmaqm3a642j-ats.iot.us-west-2
                                      .amazonaws.com
HA  ◄──── subscribe per-user ─────────┘                  └──── connect mTLS ── Device
                       │
                       └── per-device pub topic for live status + receipts
```

- REST is used for login, device discovery, MQTT cert provisioning, and command-send.
- AWS IoT MQTT is used for realtime probe data and command receipts.
- Authentication is `x-token` from login, plus an MD5 sign over the headers + body
  using a shared `appKey`.

---

## REST signing scheme

Every signed call goes to `https://api.iot.thermomaven.com` (US/AU/CA/NZ) or
`https://api.iot.thermomaven.de` (EU/UK) as a POST. The body is a JSON object
or empty string.

### Required headers

| Header | Source | Notes |
|---|---|---|
| `x-appId` | embedded constant | recovered at runtime — see "Embedded credentials" |
| `x-appVersion` | "1906" | the app's versionCode |
| `x-deviceSn` | `md5(android_id)` lowercase hex | server validates format only — any 32-char hex works |
| `x-lang` | "en_US" etc. | optional, only included in sign if non-empty |
| `x-nonce` | random uuid hex | per-request anti-replay |
| `x-region` | "US" / "DE" / "FR" etc. | optional, only included in sign if non-empty |
| `x-timestamp` | server-time-aware ms | client can use local `currentTimeMillis()` |
| `x-token` | "none" pre-login, then the token from login response | |
| `x-sign` | computed (see below) | |

### Sign formula

Java reference (decompiled from `T5/o.c()` in classes.dex):

```python
def sign(headers: dict, body: str, app_key: str) -> str:
    """
    Build x-sign value.

    `headers` is the SortedMap of x-* headers (excluding x-sign itself,
    excluding x-h5ctrl which is added later for webview-only requests).
    Iteration is by sorted key (Java TreeMap natural ordering = ASCII).

    `body` is the literal JSON request body string. Empty body → omit
    the trailing | segment entirely.
    """
    joined = ";".join(f"{k}={v}" for k, v in sorted(headers.items()))
    s = app_key + "|" + joined
    if body and body.strip():
        s += "|" + body
    s = s.replace("\n", "")
    return md5(s.encode("utf-8")).hexdigest()
```

The hash function is plain MD5 (decompiled from `J5/y.d()`), UTF-8 input, lowercase
hex output. Not HMAC — `appKey` is just prepended as a salt. Reasonably
secure-by-obscurity, broken once `appKey` is recovered.

### Login passwords

`accountPassword` is sent as `md5(password)` in the request body. That MD5'd value
is what the server stores. Brute-forcing recovered hashes against rainbow tables
is trivial — don't reuse passwords.

### Token expiry

Tokens are accepted for a few days. The integration handles "token expired" by
re-running the full login sequence and persisting the new token to the config
entry.

---

## Embedded credentials

The app's `appId` and `appKey` are NOT plaintext in the binary. The strings
`ab2132389jd44f283j` and `adfjk2389248918ddz2f3329vv238jdf` that appear in
`libmodule_appnative.so` are **decoy log labels**, not real credentials.

Real credentials are assembled at runtime by `Java_h_A0_sk` from a sequence of
ARM64 immediate moves:

```asm
mov w9, #0x7061             ; lower 16 bits = "ap"
movk w9, #0x3032, lsl #16   ; upper 16 bits = "20" → w9 = "ap20" little-endian
mov w8, #0x36               ; "6"
sturb w8, [...]             ; store "6" → "ap206" so far
                            ; then std::string::append() pulls additional
                            ; short hex chunks from the .rodata pool
```

Recovered values (release branch at offset `0x22510`):

```
appId  = "ap4060eff28137181bd"   (5 + 7 + 7 = 19 chars — embedded "ap" prefix + hex)
appKey = "bcd4596f1bb8419a92669c8017bf25e8"   (32 chars — pure hex)
```

The native lib also has anti-tamper code (`reflectGetSha1`, `checkSign`) that
verifies the APK signing certificate. Not relevant for a direct API client.

For posterity: the `0x2262c` branch in `Java_h_A0_sk` builds a *different* set
of credentials, but it's dead code (the branch test is on a flag the caller
always sets to a value that bypasses it).

---

## REST endpoints

All POST under base URL.

### Auth

| Endpoint | Body | Returns |
|---|---|---|
| `app/account/login` | `{accountName, accountPassword: md5(password), deviceInfo: "<brand> <model> <android>"}` | `{token, userId, user, setting, loginType, userAction}` |
| `app/account/logout` | (empty) | – |
| `app/account/password/{verify,modify,mail/send}` | (varies) | – |
| `app/user/{register,get,modify,delete,setting/get,setting/modify,activate/mail/resend}` | (varies) | – |

### Devices

| Endpoint | Returns |
|---|---|
| `app/device/share/my/device/list` | array of devices the account owns |
| `app/device/share/shared/device/list` | array of devices shared TO this account |
| `app/device/share/{invite,accept,decline,delete,detail,user/info/get}` | sharing workflow |
| `app/device/{bind,bind/code/create,unbind,modify,name/modify,model/list}` | device binding |

Device entries from `shared/device/list`:
```json
{
  "deviceShareId": <long>,
  "deviceSn": "WT...",
  "deviceName": "Grill thermo",
  "deviceModel": "WT11",
  "fromUserName": "Owner Name",
  "shareStatus": "accepted"
}
```

`deviceId` is **not** returned by these endpoints — it arrives via the
`user:device:list` MQTT snapshot only.

### MQTT cert

`app/mqtt/cert/apply` → returns:
```json
{
  "p12Url":      "https://file.iot.thermomaven.com/mqtt-cert/<yyyy>/<mm>/<dd>/<id>.p12",
  "p12Md5":      "<32-hex>",
  "p12Password": "<32-hex>",
  "clientId":    "android-<userId>-<region>-<deviceSn>",
  "subTopics":   ["app/user/<userId>/sub"]
}
```

The `.p12` is a PKCS12 keystore containing the AWS IoT client certificate +
private key + (sometimes) the CA chain. The integration verifies the MD5,
splits it to PEM, and uses `paho-mqtt`'s `tls_set_context()` with a manually-
built `ssl.SSLContext`.

### Commands

`app/command/send` body:
```json
{
  "deviceId":   "<deviceId from user:device:list>",
  "deviceType": "thermometer",
  "cmdType":    "<MODEL>:<verb>",
  "cmdId":      "<uuid hex>",
  "cmdData":    { ... }
}
```

The REST 200 only confirms the server queued the command. Actual device
execution is reported via a `device:cmd:receipt` MQTT message (see below).

---

## MQTT realtime channel

- Broker: `a2ubmaqm3a642j-ats.iot.us-west-2.amazonaws.com:8883` (AWS IoT Core).
- Auth: mTLS with the X.509 cert from `app/mqtt/cert/apply`.
- ALPN: `x-amzn-mqtt-ca` (set by integration; required for IoT Core).
- Keepalive: 30s. Reconnect 5s..120s exponential.
- Protocol: MQTT v3.1.1, clean session = true.

### Topics

The cert's IoT policy authorizes only the **per-user firehose** `app/user/{userId}/sub`.
Per-device pub topics are NOT directly subscribable via wildcard — the cert's
ACL would silently reject `device/+/+/pub`.

The user firehose delivers a `user:device:list` snapshot once on connect (and
again whenever the device list changes). Each device entry in the snapshot
carries its own `subTopics: ["device/<MODEL>/<deviceId>/pub"]`. The client
subscribes to those topics dynamically — those carry the realtime probe stream.

This is the same pattern the official app uses (`AmazonMqttImpl.autoSubUserTop()`
+ JS-bundle handler for `cmdType === "user:device:list"`).

### Envelope

Every MQTT message is a JSON object:

```json
{
  "cmdId":           "<32-hex>",
  "cmdSeqNo":        -1 | "5523",          // int on user firehose, STRING on per-device topics
  "cmdType":         "<discriminator>",
  "cmdData":         { ... },
  "serverTime":      <ms>,
  "serverTimeSecond":<s>,
  "deviceTime":      <ms>,
  "deviceTimeSecond":<s>,
  "deviceId":        "<id>",
  "deviceType":      "thermometer" | "user",
  "deviceModel":     "WT11",
  "userId":          "<id>",
  "appVersion":      "10",
  "controlBoardVersion": "10"
}
```

### `cmdType` discriminators

| `cmdType` | Where it appears | Carries |
|---|---|---|
| `user:device:list` | user firehose only | full account snapshot incl. per-device pub topics |
| `<MODEL>:status:report` | per-device pub topic | base + probes state |
| `device:cmd:receipt` | per-device pub topic | echo of a previously-sent command |
| `<MODEL>:cooking:action` | outbound only | command envelope, not received |
| `<MODEL>:setting:modify` | outbound only | command envelope, not received |
| `<MODEL>:probe:search` | outbound only | command envelope, not received |
| `<MODEL>:alert:dismiss` | outbound only | command envelope, not received |

Per-model `cmdType` strings are constructed in `s5/O.<init>(deviceModel, lowerDeviceModel)`
of the dex — that class also enumerates every alarm code the device emits
(e.g. `WT11-base-charging-error`, `WT11-probe-low-battery`, etc.).

---

## Status report payload

`<MODEL>:status:report` has this `cmdData` shape when probe is **active**:

```json
{
  "globalStatus": "online",          // observed; "offline" presumed
  "batteryStatus": "normal" | "low" | "charging",
  "batteryValue": 25,                // 0-100 % (base battery)
  "wifiRssi": -30,                   // dBm
  "hasWifiConfig": true,
  "connectStatus": "both" | "wifi" | "ble",
  "volume": "high" | "medium" | "quiet",
  "probes": [
    {
      "deviceSn":     "WPTBAC...",   // probe SN, distinct from base SN
      "probeColor":   "probe1",      // also "probe2".."probe4"
      "probeNotes":   "My food",     // user-set label; only present after first edit
      "cookingState": "cooking",     // observed: "cooking", "charged"; presumed "idle"/"removed"/"done"/"resting"
      "cookingMode":  "smart",       // "smart" | "manual"
      "cookUuid":     "<32-hex>",
      "startClient":  "device" | "android" | "ios",
      "setParams":    [{"setTemperature": 2030}],   // tenths of degree
      "curTemperature": 1860,                       // tenths
      "areaTemperature": [1860, 1860, 1860, 1860, 1860],   // 5-element T1..T5
      "curAmbientTemperature": 1846,                // tenths
      "temperaturePercentile": [2,0,2,7,1,7,0],     // 7 elements; [1] always 0
      "batteryValue": 100,                          // probe % 0-100
      "totalCookSec": 54000,
      "curCookSec": 54000,
      "curRemainedSec": 11068,                      // null on fresh cook before ETA computed
      "cooking": true,
      "overheat": false
    }
  ]
}
```

When probe is **docked**, the per-probe object collapses to a stub with most
fields removed:

```json
{
  "probeColor":   "probe1",
  "cookingState": "charged",                        // <-- the dock signal
  "cookingMode":  "smart",                          // last-active cook's mode (carried over)
  "setParams":    [{"setTemperature": 2000}]        // last target carried over
}
```

All temperature, battery, timer, deviceSn, and cookUuid fields disappear.
HA entities should fall back to "unknown" when their backing field is missing.

### Multi-zone notes

- `areaTemperature[0]` = T1 (tip of probe — deepest in food).
- `areaTemperature[4]` = T5 (rear / handle end).
- `curAmbientTemperature` is a **6th** thermistor (air at handle).
- `curTemperature` is the device-chosen "effective" reading — always equals
  one of the 5 `areaTemperature[*]` values (typically the lowest in steady-state).
- `temperaturePercentile` is a 7-element array. Element `[1]` was always 0 in
  every capture. Other elements fluctuate independently and don't correlate
  cleanly with anything we identified — best guess: a noise/stability indicator.

### Tempscale

All temperatures are integer **tenths of a degree** in the user-configured
unit (the device's setting, F or C). Divide by 10 for display.

The login response carries the user's preferred unit at `setting.temperatureUnit`
("F" or "C"). The integration currently hardcodes °F — TODO to plumb that
through.

---

## Command catalog (write path)

All commands use `cmdType: "<MODEL>:<verb>"`. The same shape goes through
either REST `/app/command/send` or via Bluetooth direct (the app does both).
HA only uses REST.

### `<MODEL>:cooking:action`

| `cookingAction` | Constant | Use |
|---|---|---|
| 1 | `START` | start fresh cook OR mutate target on running cook (uuid divergence keys behavior) |
| 2 | `STOP` | stop cook |
| 4 | `ChangeResting` | switch to resting phase (only valid if cook has a rest target) |
| 5 | `Finish` | end cook session |

#### START / mutate cmdData

```json
{
  "probeColor":    "probe1",
  "cookingAction": 1,
  "cookingMode":   "smart",                  // "smart" | "manual"
  "cookUuid":      "<uuid>",                 // new uuid = fresh cook (replaces running);
                                             // reuse running cook's uuid to mutate
  "startClient":   "android",                // "ios" | "android" | "device" — must
                                             // match origin when mutating
  "setParams":     [{"setTemperature": 2030}],   // tenths of degree
  "cookingData":   { "dataType": "manual",
                     "dataId": "",
                     "dataName": "Manual cook",
                     "dataImgUrl": "" }
}
```

Special case: when mutating a cook started ON the device (`startClient: "device"`),
the JS app sets `cookingData: null` instead of an object. HA replicates this.

#### STOP / Finish / ChangeResting cmdData

Minimal — just identify the cook:

```json
{
  "probeColor":    "probe1",
  "cookingAction": 5,
  "cookUuid":      "<running uuid>"
}
```

#### "Lying success" caveat

For STOP and Finish, the device acknowledges with `executeResult: "success"`
**but silently no-ops** if the probe is still inserted/docked. The cook
genuinely ends only when the probe is physically removed.

The receipt is therefore not authoritative for these verbs — HA should also
watch for `cookingState` to actually change in the next 1–2 status reports.
This is documented behavior, not a bug in the integration.

ChangeResting, by contrast, returns a clean `executeResult: "failure", cmdError: 4`
when invalid (smart-mode cook with no rest target).

### `<MODEL>:setting:modify`

One field per call:

```json
{ "volume": "high" }                    // "high" | "medium" | "quiet"
{ "readyNotification": ... }            // observed in JS, not characterized
{ "screenBrightness":  ... }            // observed in JS, not characterized
```

### Receipts

`device:cmd:receipt` arrives on the per-device pub topic:

```json
{
  "cmdId":         "<the cmdId we sent>",
  "cmdType":       "<the verb we sent>",
  "executeResult": "success" | "failure",
  "errorCode":     0,
  "cmdError":      0
}
```

`cmdError` codes seen in the wild:
- `0` — accepted (or silent no-op for STOP/Finish-while-inserted).
- `1` — generic invalid-state rejection.
- `4` — action not applicable to current cook (e.g. ChangeResting on smart-mode).

`cmdError != 0` is the only **reliable** failure signal.

The HA integration fires every receipt as the `thermomaven_command_receipt`
event so automations can react. The matching `cmdId` lets you correlate to
the entity press / number set / service call that issued the command.

---

## Recipe / guide cooks

Recipes use `cookingMode: "smart"` in status reports — **indistinguishable**
from manual smart cooks. `cookingData` is **only sent outbound** in the
`cooking:action` command and is never reflected back in `:status:report`.

This means HA cannot tell "you're in recipe X" from MQTT alone — only by
tracking the `cookingData` HA itself sent. Multi-step recipes appear to be
implemented as the device firing a fresh `cooking:action` per step transition,
not by sending the whole step array up front.

For now the integration treats all cooks as single-stage and exposes only the
first `setParams[0].setTemperature`.

---

## Asset configuration

The app fetches a JSON dictionary of region URLs, MQTT broker info, OTA
package versions, and similar at startup. The same dict is bundled inside
the APK at `assets/app_dist_release_us_en.json` (and per-region/per-locale
variants).

The MQTT broker hostname, file CDN, and base URLs in this document came from
that file — not from the dex. If Auros migrates regions or rotates the broker
they will update this file before pushing app updates.

The HA integration hardcodes the values that haven't changed since at least
v1.6 of the app. If they ever do change, this file is the canonical source.

---

## Reference files

In this repo (under `apk_research/` if you check out the recon companion repo,
or in the integration's commit history):

- `disasm_jni.py` — capstone-driven ARM64 disassembler that recovers the
  appId/appKey from `Java_h_A0_sk`.
- `find_sign.py` / `find_xref.py` / `dump_method.py` — androguard-driven
  cross-referencing tools used to locate the signing class, command sender,
  and command-type constructor.
- `thermomaven_client.py` — pure-Python REST client. Useful for debugging
  authentication issues without restarting HA.
- `mqtt_listen.py` — paho-mqtt subscriber that JSONL-logs every message.
  Run it during a real cook and you'll see every cmdType pass through.
- `send_test.py` — write-path tester with named modes (`volume`, `target`,
  `mutate`, `finish`, `stop`, `resting`, `raw`).

These are not shipped in the integration but were used to verify everything
in this document.
