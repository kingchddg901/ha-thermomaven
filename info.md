## ThermoMaven

Real-time monitoring and control of ThermoMaven (Auros) wireless meat thermometers
in Home Assistant, via the same AWS IoT MQTT cloud the official app uses.

**What you get:**
- Live probe + ambient temperatures (every ~10 seconds)
- All five thermistors (T1 tip → T5 rear) as individual sensors
- Multi-zone heuristic — automatic "is the probe in meat?" detection that scales from
  steaks to briskets
- Base-station diagnostics (battery, WiFi, connection mode, alarm volume)
- Write controls — target temperature, alarm volume, finish/stop cook
- Event bus integration for command receipts

**Recommended:** create a throwaway ThermoMaven account, share devices to it from
your primary, and sign HA in with the throwaway. See README for details.
