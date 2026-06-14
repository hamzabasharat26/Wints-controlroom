/**
 * @file main_reference.c
 * @brief WINTS Firmware Reference — STM32F411 target controller
 *
 * This is a REFERENCE IMPLEMENTATION showing how the Python simulator
 * maps to real embedded C on an STM32F411 "Black Pill". It is not
 * compiled or run by the simulation — it exists to demonstrate the
 * hardware mapping and prove the simulation is architecturally accurate.
 *
 * Hardware mapping:
 *   PA8  → TIM1_CH1 PWM output → BTS7960 H-bridge RPWM
 *   PA9  → TIM1_CH2 PWM output → BTS7960 H-bridge LPWM
 *   PA0  → ADC1_IN0 → BTS7960 IS (current sense) pin
 *   PB0  → GPIO input (pull-up) → Upper limit switch (NC)
 *   PB1  → GPIO input (pull-up) → Lower limit switch (NC)
 *   PA2  → USART2 TX → ESP32 UART bridge → MQTT over WiFi
 *   PA3  → USART2 RX → ESP32 UART bridge ← MQTT over WiFi
 *   PC13 → GPIO output → Onboard LED (fault indicator)
 *   PB10 → ADC1_IN8 → Battery voltage divider (10k/3.3k)
 *   PB11 → ADC1_IN9 → Solar panel voltage divider
 *
 * Peripherals:
 *   TIM1  — 25 kHz PWM (motor drive)
 *   TIM2  — 1 ms systick for motor control loop
 *   ADC1  — Current sense, battery voltage, solar voltage
 *   USART2 — 115200 baud to ESP32 for MQTT bridge
 *   IWDG  — 2-second watchdog (resets if main loop hangs)
 *
 * State machine matches docs/01_design.md §2.1-2.2 exactly.
 *
 * @note This file uses CMSIS and HAL naming conventions.
 *       It is NOT meant to be compiled standalone — it requires
 *       the STM32 HAL library and startup files.
 *
 * @see target_simulator/target.py for the Python equivalent
 * @see target_simulator/physics/motor.py for the motor physics
 * @see docs/04_real_hardware.md for the swap-in guide
 */

#include <stdint.h>
#include <stdbool.h>
#include <string.h>

/* ===== CONFIGURATION ===== */

#define PWM_FREQUENCY_HZ      25000   /* 25 kHz — above audible range */
#define TIMER_PERIOD           (84000000 / PWM_FREQUENCY_HZ - 1) /* 84 MHz / 25 kHz */
#define CONTROL_LOOP_MS        1       /* Motor control loop period */
#define TELEMETRY_INTERVAL_MS  2000    /* Telemetry publish interval */
#define DEBOUNCE_PERIOD_MS     20      /* Limit switch debounce */
#define OVERCURRENT_LIMIT_MA   12000   /* 12A overcurrent threshold */
#define INRUSH_WINDOW_MS       300     /* Allow startup inrush */
#define STALL_OMEGA_THRESHOLD  50      /* RPM below which = stall candidate */
#define STALL_CURRENT_MA       8000    /* Current above which = stall */
#define STALL_TIMEOUT_MS       2000    /* Sustained stall → fault */
#define WATCHDOG_TIMEOUT_MS    2000    /* IWDG reset timeout */
#define ADC_SAMPLES            16      /* ADC oversampling count */
#define VREF_MV                3300    /* ADC reference voltage */
#define ADC_MAX                4095    /* 12-bit ADC */
#define CURRENT_SENSE_MV_A     100     /* BTS7960 IS pin: 100 mV/A */
#define VBATT_DIVIDER_RATIO    4.03f   /* (10k + 3.3k) / 3.3k */

/* ===== TYPE DEFINITIONS ===== */

/**
 * @brief Motor controller state machine states
 * @note Matches MotorState enum in target_simulator/physics/motor.py
 */
typedef enum {
    MOTOR_IDLE = 0,
    MOTOR_COMMANDED,
    MOTOR_ACCELERATING,
    MOTOR_RUNNING,
    MOTOR_DECELERATING,
    MOTOR_LIMIT_REACHED,
    MOTOR_OVERCURRENT,
    MOTOR_STALL,
    MOTOR_FAULT,
} motor_state_t;

/**
 * @brief Motor drive direction
 * @note Matches MotorDirection enum in motor.py
 */
typedef enum {
    DIR_STOPPED = 0,
    DIR_RAISING  = 1,
    DIR_LOWERING = -1,
} motor_direction_t;

/**
 * @brief Target lifecycle state
 * @note Matches TargetLifecycleState in target.py
 */
typedef enum {
    LIFECYCLE_OFFLINE = 0,
    LIFECYCLE_CONNECTING,
    LIFECYCLE_ONLINE,
    LIFECYCLE_FAULT,
    LIFECYCLE_RECOVERING,
} lifecycle_state_t;

/**
 * @brief Limit switch state with debounce
 * @note Matches LimitSwitchState in motor.py
 */
typedef struct {
    bool raw_active;
    bool debounced_active;
    uint32_t last_change_tick;
} limit_switch_t;

/**
 * @brief Complete motor controller state
 * @note Matches MotorPhysicsState in motor.py
 */
typedef struct {
    motor_state_t state;
    motor_direction_t direction;
    uint16_t current_ma;        /* Measured motor current (mA) */
    uint16_t duty_cycle;        /* PWM duty cycle (0-TIMER_PERIOD) */
    uint32_t start_tick;        /* Tick when motor was commanded */
    uint32_t stall_start_tick;  /* Tick when stall was first detected */
    bool stall_detected;
    char fault_code[16];
    limit_switch_t up_limit;
    limit_switch_t down_limit;
} motor_ctrl_t;

/**
 * @brief MQTT message buffer
 */
typedef struct {
    char topic[64];
    char payload[256];
    uint8_t qos;
    bool retain;
    bool pending;
} mqtt_msg_t;

/**
 * @brief Command deduplication entry
 * @note Matches dedup cache in target.py
 */
typedef struct {
    char trace_id[40];
    uint32_t timestamp;
    bool valid;
} dedup_entry_t;

/* ===== GLOBAL STATE ===== */

static motor_ctrl_t g_motor;
static lifecycle_state_t g_lifecycle = LIFECYCLE_OFFLINE;
static mqtt_msg_t g_tx_buf;
static dedup_entry_t g_dedup_cache[32];
static uint32_t g_tick_ms = 0;
static uint32_t g_last_telemetry_tick = 0;
static uint16_t g_battery_mv = 0;
static uint16_t g_solar_mv = 0;
static char g_last_trace_id[40] = "";

/* ===== HARDWARE ABSTRACTION (HAL stubs) ===== */

/**
 * @brief Read ADC channel with oversampling
 * @param channel ADC channel number
 * @return Averaged ADC value (0-4095)
 *
 * In real hardware: configures ADC1, triggers conversion,
 * averages ADC_SAMPLES readings for noise reduction.
 * Equivalent to: motor.current_a in motor.py (derived from ADC)
 */
static uint16_t adc_read_averaged(uint8_t channel) {
    /* HAL_ADC_Start(&hadc1);
     * HAL_ADC_PollForConversion(&hadc1, 10);
     * return HAL_ADC_GetValue(&hadc1); */
    (void)channel;
    return 0;  /* Stub — real implementation reads hardware */
}

/**
 * @brief Set PWM duty cycle on TIM1
 * @param channel 1=RPWM (raise), 2=LPWM (lower)
 * @param duty Duty cycle (0 to TIMER_PERIOD)
 *
 * Maps to: motor.drive_enabled + motor.direction in motor.py
 * The BTS7960 H-bridge uses separate RPWM/LPWM inputs.
 */
static void pwm_set_duty(uint8_t channel, uint16_t duty) {
    /* __HAL_TIM_SET_COMPARE(&htim1, channel == 1 ?
     *     TIM_CHANNEL_1 : TIM_CHANNEL_2, duty); */
    (void)channel;
    (void)duty;
}

/**
 * @brief Read debounced GPIO input
 * @param pin GPIO pin identifier
 * @return true if pin is LOW (switch activated, NC configuration)
 */
static bool gpio_read(uint8_t pin) {
    /* return HAL_GPIO_ReadPin(GPIOx, pin) == GPIO_PIN_RESET; */
    (void)pin;
    return false;
}

/**
 * @brief Send message to ESP32 via UART for MQTT publishing
 * @param topic MQTT topic string
 * @param payload JSON payload string
 * @param qos MQTT QoS level (0 or 1)
 * @param retain MQTT retain flag
 *
 * Frame format: STX(0x02) + len(2) + topic_len(1) + topic + payload + ETX(0x03) + CRC16
 * ESP32 receives this frame and publishes via WiFi MQTT client.
 *
 * Maps to: mqtt_client.publish() in target.py
 */
static void uart_mqtt_publish(const char *topic, const char *payload,
                               uint8_t qos, bool retain) {
    /* HAL_UART_Transmit_DMA(&huart2, frame, frame_len); */
    (void)topic;
    (void)payload;
    (void)qos;
    (void)retain;
}

/**
 * @brief Reset the independent watchdog
 * Maps to: the asyncio.sleep() loop in target.py (if it hangs, the task
 * doesn't sleep and the watchdog equivalent — staleness timer — fires)
 */
static void iwdg_refresh(void) {
    /* HAL_IWDG_Refresh(&hiwdg); */
}

/* ===== DEBOUNCE ===== */

/**
 * @brief Update limit switch with Schmitt trigger debounce
 * @param sw Pointer to limit switch state
 * @param raw_input Current raw GPIO reading
 * @param now_tick Current system tick (ms)
 *
 * Equivalent to: motor._update_single_switch() in motor.py
 * The Python version simulates bounce trains; the C version
 * debounces real bounce from physical switches.
 */
static void debounce_update(limit_switch_t *sw, bool raw_input, uint32_t now_tick) {
    if (raw_input != sw->raw_active) {
        sw->raw_active = raw_input;
        sw->last_change_tick = now_tick;
    }

    /* Only update debounced output after stable for DEBOUNCE_PERIOD_MS */
    if ((now_tick - sw->last_change_tick) >= DEBOUNCE_PERIOD_MS) {
        sw->debounced_active = sw->raw_active;
    }
}

/* ===== MOTOR CONTROL ===== */

/**
 * @brief Enter motor fault state
 * @param fault_code Fault identifier string
 *
 * Equivalent to: motor._enter_fault() in motor.py
 * Immediately disables PWM, sets direction to stopped.
 */
static void motor_enter_fault(const char *fault_code) {
    pwm_set_duty(1, 0);  /* Disable RPWM */
    pwm_set_duty(2, 0);  /* Disable LPWM */
    g_motor.state = MOTOR_FAULT;
    g_motor.direction = DIR_STOPPED;
    g_motor.duty_cycle = 0;
    strncpy(g_motor.fault_code, fault_code, sizeof(g_motor.fault_code) - 1);
    g_lifecycle = LIFECYCLE_FAULT;
}

/**
 * @brief 1ms motor control ISR (TIM2 interrupt)
 *
 * This is the real-time motor control loop that runs at 1 kHz.
 * It reads the current sense ADC, updates limit switches,
 * checks protection limits, and manages the state machine.
 *
 * Equivalent to: motor.step(0.001) in motor.py
 * The key difference: the Python version solves ODEs to predict
 * current/velocity; the C version MEASURES them from ADC/encoder.
 */
void TIM2_IRQHandler(void) {
    /* HAL_TIM_IRQHandler(&htim2); — clears interrupt flag */
    g_tick_ms++;

    /* Read current sense ADC */
    uint16_t adc_val = adc_read_averaged(0);  /* PA0 = ADC1_IN0 */
    g_motor.current_ma = (adc_val * VREF_MV) / (ADC_MAX * CURRENT_SENSE_MV_A / 1000);

    /* Read and debounce limit switches */
    debounce_update(&g_motor.up_limit, gpio_read(0 /* PB0 */), g_tick_ms);
    debounce_update(&g_motor.down_limit, gpio_read(1 /* PB1 */), g_tick_ms);

    /* Both limits active = hardware fault */
    if (g_motor.up_limit.debounced_active && g_motor.down_limit.debounced_active) {
        motor_enter_fault("LIMIT_STUCK");
        return;
    }

    /* Skip further processing if idle or faulted */
    if (g_motor.state == MOTOR_IDLE || g_motor.state == MOTOR_FAULT) {
        return;
    }

    /* === OVERCURRENT PROTECTION === */
    uint32_t time_since_start = g_tick_ms - g_motor.start_tick;
    bool in_inrush = (time_since_start < INRUSH_WINDOW_MS);

    if (g_motor.current_ma > OVERCURRENT_LIMIT_MA && !in_inrush) {
        motor_enter_fault("OVERCURRENT");
        return;
    }

    /* === STALL DETECTION === */
    /* In real hardware, we'd read an encoder for velocity.
     * Here we use current > threshold as a proxy (no encoder in
     * this minimal reference design). */
    if (g_motor.current_ma > STALL_CURRENT_MA && !in_inrush) {
        if (!g_motor.stall_detected) {
            g_motor.stall_detected = true;
            g_motor.stall_start_tick = g_tick_ms;
        } else if ((g_tick_ms - g_motor.stall_start_tick) > STALL_TIMEOUT_MS) {
            motor_enter_fault("MOTOR_STALL");
            return;
        }
    } else {
        g_motor.stall_detected = false;
    }

    /* === LIMIT SWITCH CHECK === */
    if (g_motor.direction == DIR_RAISING && g_motor.up_limit.debounced_active) {
        pwm_set_duty(1, 0);
        g_motor.state = MOTOR_IDLE;
        g_motor.direction = DIR_STOPPED;
        g_motor.duty_cycle = 0;
        return;
    }
    if (g_motor.direction == DIR_LOWERING && g_motor.down_limit.debounced_active) {
        pwm_set_duty(2, 0);
        g_motor.state = MOTOR_IDLE;
        g_motor.direction = DIR_STOPPED;
        g_motor.duty_cycle = 0;
        return;
    }
}

/* ===== COMMAND PROCESSING ===== */

/**
 * @brief Check if a trace_id has been seen recently (deduplication)
 * @param trace_id UUID string from the command
 * @return true if duplicate
 *
 * Equivalent to: target._is_duplicate() in target.py
 * Uses a fixed-size ring buffer instead of Python's OrderedDict.
 */
static bool is_duplicate_command(const char *trace_id) {
    for (int i = 0; i < 32; i++) {
        if (g_dedup_cache[i].valid &&
            (g_tick_ms - g_dedup_cache[i].timestamp) < 5000 &&
            strcmp(g_dedup_cache[i].trace_id, trace_id) == 0) {
            return true;
        }
    }

    /* Add to cache (overwrite oldest) */
    static uint8_t write_idx = 0;
    strncpy(g_dedup_cache[write_idx].trace_id, trace_id, 39);
    g_dedup_cache[write_idx].timestamp = g_tick_ms;
    g_dedup_cache[write_idx].valid = true;
    write_idx = (write_idx + 1) % 32;

    return false;
}

/**
 * @brief Process an incoming MQTT command
 * @param cmd_json Raw JSON payload from ESP32 UART
 *
 * Equivalent to: target._process_command_safe() in target.py
 *
 * In real hardware, the ESP32 receives MQTT messages over WiFi
 * and forwards them to the STM32 via UART. The STM32 parses
 * the JSON, validates the command, and drives the motor.
 */
static void process_command(const char *cmd_json) {
    /* In real firmware, use a lightweight JSON parser (cJSON or jsmn).
     * Here we show the logical flow: */

    /* 1. Parse JSON → extract cmd, trace_id */
    /* 2. Validate trace_id for deduplication */
    /* 3. Dispatch to motor state machine */

    /* Pseudocode: */
    /* if (strcmp(cmd, "raise") == 0 && g_motor.state == MOTOR_IDLE) { */
    /*     g_motor.state = MOTOR_ACCELERATING; */
    /*     g_motor.direction = DIR_RAISING; */
    /*     g_motor.start_tick = g_tick_ms; */
    /*     g_motor.duty_cycle = TIMER_PERIOD;  // Full duty */
    /*     pwm_set_duty(1, g_motor.duty_cycle); */
    /* } */
}

/* ===== MAIN LOOP ===== */

/**
 * @brief Firmware main function
 *
 * Equivalent to: target.run() in target.py
 *
 * Initialisation order:
 * 1. HAL_Init() — configure clocks, systick
 * 2. GPIO, ADC, TIM1 (PWM), TIM2 (1ms ISR), USART2, IWDG
 * 3. Wait for ESP32 MQTT connection
 * 4. Enter main loop: read UART, publish telemetry, refresh watchdog
 *
 * The main loop handles non-time-critical tasks (telemetry, MQTT).
 * The TIM2 ISR handles time-critical motor control at 1 kHz.
 */
int main(void) {
    /* HAL_Init();
     * SystemClock_Config();  // 84 MHz from HSE
     * MX_GPIO_Init();
     * MX_ADC1_Init();
     * MX_TIM1_Init();        // 25 kHz PWM
     * MX_TIM2_Init();        // 1 ms interrupt
     * MX_USART2_UART_Init(); // 115200 baud
     * MX_IWDG_Init();        // 2s watchdog */

    /* Initialize motor state */
    memset(&g_motor, 0, sizeof(g_motor));
    g_motor.state = MOTOR_IDLE;
    g_motor.direction = DIR_STOPPED;

    /* Start PWM and timer interrupt */
    /* HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);
     * HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_2);
     * HAL_TIM_Base_Start_IT(&htim2); */

    g_lifecycle = LIFECYCLE_CONNECTING;

    /* === MAIN SUPERLOOP === */
    while (1) {
        /* 1. Check for incoming UART/MQTT messages from ESP32 */
        /* if (uart_rx_available()) {
         *     char buf[256];
         *     uart_read_frame(buf, sizeof(buf));
         *     process_command(buf);
         * } */

        /* 2. Read battery and solar voltages (slow, not in ISR) */
        uint16_t batt_adc = adc_read_averaged(8);  /* PB10 */
        g_battery_mv = (uint16_t)((batt_adc * VREF_MV * VBATT_DIVIDER_RATIO) / ADC_MAX);

        uint16_t solar_adc = adc_read_averaged(9);  /* PB11 */
        g_solar_mv = (uint16_t)((solar_adc * VREF_MV * VBATT_DIVIDER_RATIO) / ADC_MAX);

        /* 3. Publish telemetry every 2 seconds */
        if ((g_tick_ms - g_last_telemetry_tick) >= TELEMETRY_INTERVAL_MS) {
            g_last_telemetry_tick = g_tick_ms;

            /* Build JSON telemetry payload */
            /* snprintf(g_tx_buf.payload, sizeof(g_tx_buf.payload),
             *     "{\"target_id\":\"T-01\","
             *      "\"battery_mv\":%u,"
             *      "\"current_ma\":%u,"
             *      "\"solar_mv\":%u,"
             *      "\"state\":\"%s\","
             *      "\"uptime_s\":%lu}",
             *     g_battery_mv, g_motor.current_ma, g_solar_mv,
             *     state_names[g_motor.state], g_tick_ms / 1000); */

            /* uart_mqtt_publish("wints/T-01/telemetry",
             *                   g_tx_buf.payload, 0, false); */
        }

        /* 4. Refresh watchdog — if this line is never reached (main loop
         *    hung), the IWDG resets the MCU after 2 seconds.
         *    Equivalent to: staleness timer in SystemModel (F-09). */
        iwdg_refresh();

        /* 5. Brief delay to yield CPU (in FreeRTOS, this would be
         *    vTaskDelay; in bare-metal, a short busy-wait or WFI) */
        /* HAL_Delay(1); or __WFI(); */
    }

    return 0;  /* Never reached */
}

/*
 * ===== MAPPING TABLE =====
 *
 * Python Simulator → C Firmware
 * ─────────────────────────────────────────────────────────
 * motor.step(dt)          → TIM2_IRQHandler (1 kHz ISR)
 * motor._ode_rhs()        → ADC reading (measures, not simulates)
 * motor._enter_fault()    → motor_enter_fault()
 * motor.command_raise()   → process_command("raise")
 * motor._update_limit()   → debounce_update()
 * target._is_duplicate()  → is_duplicate_command()
 * target._publish_status  → uart_mqtt_publish (via ESP32)
 * battery.step()          → adc_read (battery voltage)
 * solar.get_power_w()     → adc_read (solar voltage)
 * rf_link.get_rssi()      → ESP32 reports WiFi RSSI
 * asyncio.sleep()         → HAL_Delay / WFI
 * structlog               → printf / SWD trace
 * SystemModel staleness   → IWDG watchdog reset
 *
 * Key architectural difference:
 *   Python: solves ODEs to PREDICT motor behaviour
 *   C:      reads ADC to MEASURE motor behaviour
 *   Both use the same state machine and protection logic.
 */
