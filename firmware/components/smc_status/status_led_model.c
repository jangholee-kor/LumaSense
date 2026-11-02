#include "status_led_model.h"

smc_led_frame_t smc_led_frame(bool enabled, unsigned brightness, bool pins_ok,
                            bool light_ok, bool radar_ok, bool presence, uint64_t uptime_ms) {
    smc_led_frame_t frame = {.state = SMC_LED_DISABLED};
    if (!enabled || !brightness) return frame;
    uint8_t level = brightness > SMC_LED_MAX_BRIGHTNESS ? SMC_LED_MAX_BRIGHTNESS : brightness;
    if (!pins_ok || ((!light_ok || !radar_ok) && uptime_ms >= SMC_LED_STARTUP_MS)) {
        frame.state = SMC_LED_SENSOR_ERROR;
        if (uptime_ms % 1000 < 500) frame.red = level;
    } else if (!light_ok || !radar_ok) {
        frame.state = SMC_LED_STARTING;
        frame.blue = level;
    } else if (presence) {
        frame.state = SMC_LED_PRESENT;
        frame.green = level;
    } else {
        frame.state = SMC_LED_ABSENT;
        frame.red = frame.green = level;
    }
    return frame;
}

const char *smc_led_state_name(smc_led_state_t state) {
    switch (state) {
        case SMC_LED_DISABLED: return "disabled";
        case SMC_LED_STARTING: return "starting";
        case SMC_LED_PRESENT: return "present";
        case SMC_LED_ABSENT: return "absent";
        case SMC_LED_SENSOR_ERROR: return "sensor_error";
        default: return "unknown";
    }
}

void smc_led_encode(smc_led_frame_t frame, smc_led_pulse_t pulses[SMC_LED_SYMBOL_COUNT]) {
    const uint8_t grb[] = {frame.green, frame.red, frame.blue};
    for (unsigned i = 0; i < 24; ++i) {
        /* 20MHz: 0=0.30us/0.95us, 1=0.65us/0.60us. GRB, MSB first. */
        pulses[i].high_ticks = (grb[i / 8] & (0x80 >> (i % 8))) ? 13 : 6;
        pulses[i].low_ticks = 25 - pulses[i].high_ticks;
    }
    /* SK6812MINI-HS requires >80us low; send 100us after all 24 bits. */
    pulses[24] = (smc_led_pulse_t){.high_ticks = 0, .low_ticks = 2000};
}

bool smc_gpio_validate(const int *pins, size_t count, uint64_t valid_output_mask) {
    if (!pins || !count) return false;
    uint64_t used = 0;
    for (size_t i = 0; i < count; ++i) {
        int pin = pins[i];
        if (pin < 0 || pin >= 64 || !(valid_output_mask & (UINT64_C(1) << pin)) ||
            pin == 19 || pin == 20 || pin == 0 || pin == 3 || pin == 45 || pin == 46 ||
            (pin >= 26 && pin <= 37)) return false;
        uint64_t bit = UINT64_C(1) << pin;
        if (used & bit) return false;
        used |= bit;
    }
    return true;
}
