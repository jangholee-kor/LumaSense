#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SMC_LED_RESOLUTION_HZ 20000000
#define SMC_LED_SYMBOL_COUNT 25
#define SMC_LED_MAX_BRIGHTNESS 32
#define SMC_LED_STARTUP_MS 3000

typedef enum {
    SMC_LED_DISABLED, SMC_LED_STARTING, SMC_LED_PRESENT, SMC_LED_ABSENT, SMC_LED_SENSOR_ERROR
} smc_led_state_t;

typedef struct {
    smc_led_state_t state;
    uint8_t red, green, blue;
} smc_led_frame_t;

typedef struct {
    uint16_t high_ticks, low_ticks;
} smc_led_pulse_t;

smc_led_frame_t smc_led_frame(bool enabled, unsigned brightness, bool pins_ok,
                            bool light_ok, bool radar_ok, bool presence, uint64_t uptime_ms);
const char *smc_led_state_name(smc_led_state_t state);
void smc_led_encode(smc_led_frame_t frame, smc_led_pulse_t pulses[SMC_LED_SYMBOL_COUNT]);
bool smc_gpio_validate(const int *pins, size_t count, uint64_t valid_output_mask);
