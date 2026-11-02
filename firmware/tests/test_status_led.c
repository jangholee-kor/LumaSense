#include "status_led_model.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static smc_led_frame_t frame(bool light_ok, bool radar_ok, bool presence, uint64_t time_ms) {
    return smc_led_frame(true, 4, true, light_ok, radar_ok, presence, time_ms);
}

int main(void) {
    smc_led_frame_t value = frame(false, false, false, 0);
    assert(value.state == SMC_LED_STARTING && value.blue == 4 && !value.red && !value.green);
    assert(frame(true, false, true, 2999).state == SMC_LED_STARTING);
    value = frame(true, false, true, 3000);
    assert(value.state == SMC_LED_SENSOR_ERROR && value.red == 4);
    value = frame(false, true, false, 3500);
    assert(value.state == SMC_LED_SENSOR_ERROR && !value.red && !value.green && !value.blue);
    assert(frame(false, true, true, 4000).red == 4);
    value = frame(true, true, true, 200);
    assert(value.state == SMC_LED_PRESENT && value.green == 4 && !value.red && !value.blue);
    value = frame(true, true, false, 4000);
    assert(value.state == SMC_LED_ABSENT && value.red == 4 && value.green == 4 && !value.blue);
    /* Error wins over a previously reported presence/absence; recovery is immediate. */
    assert(frame(false, true, true, 4000).state == SMC_LED_SENSOR_ERROR);
    assert(frame(true, false, false, 4000).state == SMC_LED_SENSOR_ERROR);
    assert(frame(true, true, true, 4001).state == SMC_LED_PRESENT);
    assert(smc_led_frame(true, 4, false, true, true, true, 0).state == SMC_LED_SENSOR_ERROR);
    value = smc_led_frame(false, 4, true, true, true, true, 4000);
    assert(value.state == SMC_LED_DISABLED && !value.red && !value.green && !value.blue);
    assert(smc_led_frame(true, 0, true, true, true, true, 4000).state == SMC_LED_DISABLED);
    assert(smc_led_frame(true, 255, true, true, true, true, 4000).green == 32);
    assert(!strcmp(smc_led_state_name(SMC_LED_SENSOR_ERROR), "sensor_error"));

    smc_led_pulse_t pulses[SMC_LED_SYMBOL_COUNT];
    value = (smc_led_frame_t){.red = 0x80, .green = 0x01, .blue = 0x81};
    smc_led_encode(value, pulses);
    const unsigned one_bits[] = {7, 8, 16, 23};
    for (unsigned i = 0; i < 24; ++i) {
        bool bit = false;
        for (unsigned j = 0; j < sizeof(one_bits) / sizeof(one_bits[0]); ++j) bit |= i == one_bits[j];
        assert(pulses[i].high_ticks == (bit ? 13 : 6));
        assert(pulses[i].high_ticks + pulses[i].low_ticks == 25);
    }
    assert(SMC_LED_RESOLUTION_HZ == 20000000);
    assert(!pulses[24].high_ticks && pulses[24].low_ticks == 2000);

    uint64_t mask = (UINT64_C(1) << 49) - 1;
    int pins[] = {8, 9, 16, 17, 38};
    assert(smc_gpio_validate(pins, 5, mask));
    pins[4] = 8;
    assert(!smc_gpio_validate(pins, 5, mask));
    assert(smc_gpio_validate(pins, 4, mask)); /* Disabled LED does not reserve its GPIO. */
    const int invalid[] = {-1, 0, 3, 19, 20, 26, 35, 37, 45, 46, 49, 64};
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        pins[4] = invalid[i];
        assert(!smc_gpio_validate(pins, 5, mask));
    }
    pins[4] = 38;
    assert(!smc_gpio_validate(pins, 5, mask & ~(UINT64_C(1) << 38)));
    assert(!smc_gpio_validate(NULL, 5, mask));
    puts("Status LED native tests PASS: startup, presence, absence, error priority/blink, disable, brightness, GRB timing, GPIO conflicts");
    return 0;
}
