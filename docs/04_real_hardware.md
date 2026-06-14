# Real Hardware Swap-In Guide

> How to replace the Python simulator with STM32 + ESP32 physical targets.

## 1. Hardware Bill of Materials

| Component | Per Target | Qty (10) | Unit Cost |
|-----------|-----------|----------|-----------|
| STM32F411 "Black Pill" | 1 | 10 | $3.50 |
| ESP32 DevKit v1 | 1 | 10 | $4.00 |
| BTS7960 H-Bridge Module | 1 | 10 | $5.00 |
| MY1016 12V DC Motor | 1 | 10 | $25.00 |
| NPN Limit Switch (NC) ×2 | 2 | 20 | $0.50 |
| 4S LiFePO4 100Ah Battery | 1 | 10 | $150.00 |
| 200W Solar Panel | 1 | 10 | $80.00 |
| Victron SmartSolar MPPT | 1 | 10 | $50.00 |
| Ubiquiti NanoBeam 5AC | 1 | 10 | $90.00 |
| USB Camera (720p) ×2 | 2 | 20 | $15.00 |
| IP67 Enclosure | 1 | 10 | $20.00 |

## 2. Firmware Flashing

### STM32 Firmware
```bash
# Using STM32CubeProgrammer
STM32_Programmer_CLI -c port=SWD -w firmware/main_reference.bin 0x08000000 -v
```

### ESP32 MQTT Bridge
```bash
# Using Arduino CLI or PlatformIO
cd firmware/esp32_bridge
pio run --target upload
```

## 3. What Changes, What Stays

### NO CHANGES NEEDED:
- **MQTT topic contract** — identical JSON schemas
- **Control room dashboard** — works unchanged
- **Command tracker** — same trace_id flow
- **Config structure** — same wints.yaml (remove simulator-only fields)
- **Video infrastructure** — swap test patterns for real camera URLs

### CHANGES NEEDED:

| Simulator Component | Real Hardware Equivalent |
|---------------------|------------------------|
| `motor.py` ODE solver | ADC current sense on BTS7960 IS pin |
| `battery.py` coulomb counting | INA226 coulomb counter IC or ADC + voltage divider |
| `solar.py` irradiance model | Real panel + MPPT controller reading |
| `rf_link.py` FSPL model | ESP32 `WiFi.RSSI()` API call |
| `target.py` asyncio loop | FreeRTOS tasks on STM32 |
| Fault injector HTTP API | Physical fault simulation (short pins, disconnect cables) |

## 4. Wiring Diagram

```
STM32F411 Black Pill
├── PA8  → TIM1_CH1 → BTS7960 RPWM (raise PWM)
├── PA9  → TIM1_CH2 → BTS7960 LPWM (lower PWM)
├── PA0  → ADC1_IN0 → BTS7960 IS pin (current sense)
├── PB0  → GPIO IN  → Upper limit switch (NC to GND, 10k pullup)
├── PB1  → GPIO IN  → Lower limit switch (NC to GND, 10k pullup)
├── PA2  → USART2_TX → ESP32 GPIO16 (UART RX)
├── PA3  → USART2_RX → ESP32 GPIO17 (UART TX)
├── PB10 → ADC1_IN8 → Battery voltage divider (10k + 3.3k)
├── PB11 → ADC1_IN9 → Solar panel voltage divider (10k + 3.3k)
└── PC13 → GPIO OUT → Onboard LED (fault indicator)

BTS7960 H-Bridge
├── RPWM ← PA8
├── LPWM ← PA9
├── R_EN ← 3.3V (always enabled)
├── L_EN ← 3.3V (always enabled)
├── IS   → PA0 (current sense: 100 mV/A)
├── VCC  ← 12V battery bus
├── M+   → Motor terminal A
└── M-   → Motor terminal B

ESP32 DevKit (WiFi→MQTT Bridge)
├── GPIO16 (RX) ← PA2 (STM32 TX) via level shifter
├── GPIO17 (TX) → PA3 (STM32 RX) via level shifter
├── WiFi → connects to 5 GHz AP at control room
└── MQTT → paho-mqtt or PubSubClient library
```

## 5. MQTT Topic Contract (Unchanged)

The physical targets use the same MQTT topics as the simulator:

```
wints/T-{XX}/status    (QoS 1, retain) → StatusPayload JSON
wints/T-{XX}/telemetry (QoS 0)         → TelemetryPayload JSON
wints/T-{XX}/cmd       (QoS 1)         → CommandPayload JSON
wints/broadcast/cmd    (QoS 1)         → CommandPayload JSON
```

## 6. Commissioning Checklist

- [ ] Flash STM32 firmware and verify LED blink
- [ ] Flash ESP32 bridge and verify WiFi connection
- [ ] Verify UART communication between STM32 and ESP32
- [ ] Connect motor and verify direction (RAISE = target goes UP)
- [ ] Verify limit switches trigger at end of travel
- [ ] Verify BTS7960 current sense readings with multimeter
- [ ] Connect battery and verify voltage reading
- [ ] Run `wints doctor` and verify target appears online
- [ ] Send RAISE command and verify physical motion
- [ ] Verify camera streams are accessible via RTSP
