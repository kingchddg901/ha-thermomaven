"""
/* ============================================================
 * const.py — ThermoMaven Integration Constants
 * ============================================================
 *
 * Central registry for endpoints, payload field names, and
 * tuning knobs. Keeps magic strings out of the rest of the
 * integration.
 *
 * API discovered via APK reverse-engineering of ThermoMaven
 * v1.9.6 (com.auros.thermomaven, versionCode 1906). The native
 * lib libmodule_appnative.so assembles the appId/appKey at
 * runtime from a chain of mov/movk/strb instructions plus
 * embedded hex chunks (the plaintext strings in the .so are
 * decoy log labels, not the real keys).
 *
 * Architecture:
 *   - REST POST with x-* signed headers (md5 over appKey + sorted
 *     headers + body) for login + device list + cert apply
 *   - AWS IoT MQTT (mTLS, X.509 client cert from /app/mqtt/cert/apply)
 *     for realtime probe data
 *   - Single per-user firehose topic delivers a `user:device:list`
 *     snapshot, then per-device pub topics carry probe deltas
 * ============================================================
 */
"""

DOMAIN = "thermomaven"
MANUFACTURER = "ThermoMaven (Auros)"
NAME = "ThermoMaven"

# === REST API ================================================

API_BASE_US = "https://api.iot.thermomaven.com"
API_BASE_EU = "https://api.iot.thermomaven.de"

# Endpoints (all POST, all under base URL)
ENDPOINT_LOGIN = "app/account/login"
ENDPOINT_LOGOUT = "app/account/logout"
ENDPOINT_USER_GET = "app/user/get"
ENDPOINT_DEVICE_LIST_OWNED = "app/device/share/my/device/list"
ENDPOINT_DEVICE_LIST_SHARED = "app/device/share/shared/device/list"
ENDPOINT_DEVICE_MODEL_LIST = "app/device/model/list"
ENDPOINT_MQTT_CERT_APPLY = "app/mqtt/cert/apply"
ENDPOINT_COMMAND_SEND = "app/command/send"

# === Auth / signing ==========================================

# App identity recovered from Java_h_A0_sk in libmodule_appnative.so.
# Validated live against api.iot.thermomaven.com on 2026-05-02.
APP_ID = "ap4060eff28137181bd"
APP_KEY = "bcd4596f1bb8419a92669c8017bf25e8"
APP_VERSION_CODE = "1906"

# === MQTT (AWS IoT Core, mTLS) ===============================

MQTT_ENDPOINT = "a2ubmaqm3a642j-ats.iot.us-west-2.amazonaws.com"
MQTT_PORT = 8883
MQTT_REGION = "us-west-2"
MQTT_KEEPALIVE = 30
MQTT_RECONNECT_MIN = 5
MQTT_RECONNECT_MAX = 120

# Amazon Root CA 1 — fallback when the .p12 doesn't include the chain.
# https://www.amazontrust.com/repository/AmazonRootCA1.pem
AMAZON_ROOT_CA1 = """-----BEGIN CERTIFICATE-----
MIIDQTCCAimgAwIBAgITBmyfz5m/jAo54vB4ikPmljZbyjANBgkqhkiG9w0BAQsF
ADA5MQswCQYDVQQGEwJVUzEPMA0GA1UEChMGQW1hem9uMRkwFwYDVQQDExBBbWF6
b24gUm9vdCBDQSAxMB4XDTE1MDUyNjAwMDAwMFoXDTM4MDExNzAwMDAwMFowOTEL
MAkGA1UEBhMCVVMxDzANBgNVBAoTBkFtYXpvbjEZMBcGA1UEAxMQQW1hem9uIFJv
b3QgQ0EgMTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBALJ4gHHKeNXj
ca9HgFB0fW7Y14h29Jlo91ghYPl0hAEvrAIthtOgQ3pOsqTQNroBvo3bSMgHFzZM
9O6II8c+6zf1tRn4SWiw3te5djgdYZ6k/oI2peVKVuRF4fn9tBb6dNqcmzU5L/qw
IFAGbHrQgLKm+a/sRxmPUDgH3KKHOVj4utWp+UhnMJbulHheb4mjUcAwhmahRWa6
VOujw5H5SNz/0egwLX0tdHA114gk957EWW67c4cX8jJGKLhD+rcdqsq08p8kDi1L
93FcXmn/6pUCyziKrlA4b9v7LWIbxcceVOF34GfID5yHI9Y/QCB/IIDEgEw+OyQm
jgSubJrIqg0CAwEAAaNCMEAwDwYDVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMC
AYYwHQYDVR0OBBYEFIQYzIU07LwMlJQuCFmcx7IQTgoIMA0GCSqGSIb3DQEBCwUA
A4IBAQCY8jdaQZChGsV2USggNiMOruYou6r4lK5IpDB/G/wkjUu0yKGX9rbxenDI
U5PMCCjjmCXPI6T53iHTfIUJrU6adTrCC2qJeHZERxhlbI1Bjjt/msv0tadQ1wUs
N+gDS63pYaACbvXy8MWy7Vu33PqUXHeeE6V/Uq2V8viTO96LXFvKWlJbYK8U90vv
o/ufQJVtMVT8QtPHRh8jrdkPSHCa2XV4cdFyQzR1bldZwgJcJmApzyMZFo6IQ6XU
5MsI+yMRQ+hDKXJioaldXgjUkK642M4UwtBV8ob2xJNDd2ZhwLnoQdeXeGADbkpy
rqXRfboQnoZsG4q5WTP468SQvvG5
-----END CERTIFICATE-----
"""

# === Config-entry / options keys =============================

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_REGION = "region"
CONF_TOKEN = "token"
CONF_USER_ID = "user_id"
CONF_DEVICE_SN = "device_sn"

REGION_US = "US"
REGION_EU = "DE"
REGION_DEFAULT = REGION_US

# === Payload field names =====================================
# Match the JSON keys observed in MQTT messages.

# Top-level envelope
F_CMD_ID = "cmdId"
F_CMD_SEQ_NO = "cmdSeqNo"
F_CMD_TYPE = "cmdType"
F_CMD_DATA = "cmdData"
F_SERVER_TIME = "serverTime"
F_DEVICE_TIME = "deviceTime"
F_DEVICE_ID = "deviceId"
F_DEVICE_TYPE = "deviceType"
F_DEVICE_MODEL = "deviceModel"
F_USER_ID = "userId"

# Device-list snapshot fields
F_DEVICES = "devices"
F_DEVICE_SN = "deviceSn"
F_DEVICE_NAME = "deviceName"
F_DEVICE_LOGO = "deviceLogo"
F_SUB_TOPICS = "subTopics"
F_LAST_STATUS_CMD = "lastStatusCmd"
F_FIRMWARE_VERSION_CODE = "firmwareVersionCode"
F_BIND_TIME = "bindTime"
F_SHARE_FLAG = "shareFlag"

# Status-report base-station fields
F_GLOBAL_STATUS = "globalStatus"      # "online" / (presumed) "offline"
F_BATTERY_STATUS = "batteryStatus"    # "normal" / (presumed) "low"
F_BATTERY_VALUE = "batteryValue"      # 0-100 percent
F_WIFI_RSSI = "wifiRssi"              # dBm, negative integer
F_HAS_WIFI_CONFIG = "hasWifiConfig"
F_CONNECT_STATUS = "connectStatus"    # "both" observed; presumably also "ble"/"wifi"
F_VOLUME = "volume"                   # "high" observed; quiet/medium presumed
F_PROBES = "probes"

# Per-probe fields
F_PROBE_COLOR = "probeColor"          # "probe1" .. "probeN"
F_PROBE_NOTES = "probeNotes"          # user-set label
F_COOKING_STATE = "cookingState"      # "cooking" / "idle" / etc
F_COOKING_MODE = "cookingMode"        # "smart" / others tbd
F_COOK_UUID = "cookUuid"              # stable per cook session
F_START_CLIENT = "startClient"        # "device" / "app"
F_SET_PARAMS = "setParams"            # list of stages, each with setTemperature
F_SET_TEMPERATURE = "setTemperature"  # tenths of degree
F_CUR_TEMPERATURE = "curTemperature"  # tenths of degree
F_AREA_TEMPERATURE = "areaTemperature"  # 5-element list (multi-zone probe)
F_CUR_AMBIENT_TEMPERATURE = "curAmbientTemperature"  # tenths of degree
F_TEMP_PERCENTILE = "temperaturePercentile"  # 7-element list, fluctuates
F_TOTAL_COOK_SEC = "totalCookSec"
F_CUR_COOK_SEC = "curCookSec"
F_CUR_REMAINED_SEC = "curRemainedSec"
F_OVERHEAT = "overheat"
F_COOKING = "cooking"

# === cmdType discriminators ==================================

CMD_USER_DEVICE_LIST = "user:device:list"
CMD_DEVICE_CMD_RECEIPT = "device:cmd:receipt"
# Per-model status reports — derived as f"{deviceModel}:status:report"

CMD_TYPE_STATUS_SUFFIX = ":status:report"
CMD_TYPE_COOKING_ACTION_SUFFIX = ":cooking:action"
CMD_TYPE_SETTING_MODIFY_SUFFIX = ":setting:modify"
CMD_TYPE_PROBE_SEARCH_SUFFIX  = ":probe:search"
CMD_TYPE_ALERT_DISMISS_SUFFIX = ":alert:dismiss"

# cookingAction enum (from chunk-common.js: e[e.START=1]=...)
ACTION_START          = 1
ACTION_STOP           = 2
ACTION_CHANGE_RESTING = 4
ACTION_FINISH         = 5

# Volume enum values for setting:modify (observed in JS bundle's volume picker)
VOLUME_OPTIONS = ["high", "medium", "quiet"]

# Target-temp number entity bounds (in displayed °F units, before TEMP_SCALE).
# Server has no documented bounds; ~80°F (chilled meat) to ~500°F (overshoot
# protection on most probes is 575°F) is a sane HA UI range.
TARGET_TEMP_MIN = 80
TARGET_TEMP_MAX = 500
TARGET_TEMP_STEP = 1

# Default startClient string when HA initiates a command.
START_CLIENT_HA = "android"   # the server's enum is loose — "android" is accepted

# === Scaling / units =========================================

# All temperatures are integer tenths of a degree in the unit the
# device is configured for. Divide by 10 to get the displayed value.
TEMP_SCALE = 10.0

# === HA event names ==========================================

EVENT_PROBE_ALARM = f"{DOMAIN}_probe_alarm"
EVENT_COMMAND_RECEIPT = f"{DOMAIN}_command_receipt"

# === Device model aliases ====================================
# From asset device_model_release.json. Used for friendly model names.

DEVICE_MODEL_NAMES = {
    "WT02": "ThermoMaven P2",
    "WT06": "ThermoMaven P4",
    "WT07": "ThermoMaven G2",
    "WT09": "ThermoMaven G4",
    "WT10": "ThermoMaven G1",
    "WT11": "ThermoMaven P1",
}
