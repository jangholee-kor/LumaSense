#include "status_led.h"
#include <string.h>

void smc_status_led_init(smc_status_led_t *led, bool enabled, int gpio, unsigned brightness, bool pin_usable) {
    memset(led, 0, sizeof(*led));
    led->enabled = enabled;
    led->gpio = enabled ? gpio : -1;
    led->brightness = brightness > SMC_LED_MAX_BRIGHTNESS ? SMC_LED_MAX_BRIGHTNESS : brightness;
    if (!enabled) return;
    if (!pin_usable) {
        led->error = ESP_ERR_INVALID_ARG;
        return;
    }
    rmt_tx_channel_config_t config = {
        .gpio_num = gpio, .clk_src = RMT_CLK_SRC_DEFAULT, .resolution_hz = SMC_LED_RESOLUTION_HZ,
        .mem_block_symbols = 48, .trans_queue_depth = 1,
    };
    led->error = rmt_new_tx_channel(&config, &led->channel);
    rmt_copy_encoder_config_t encoder = {};
    if (led->error == ESP_OK) led->error = rmt_new_copy_encoder(&encoder, &led->encoder);
    if (led->error == ESP_OK) led->error = rmt_enable(led->channel);
    led->ready = led->error == ESP_OK;
    if (!led->ready) {
        if (led->encoder) rmt_del_encoder(led->encoder);
        if (led->channel) rmt_del_channel(led->channel);
        led->encoder = NULL;
        led->channel = NULL;
    }
}

void smc_status_led_update(smc_status_led_t *led, bool pins_ok, bool light_ok, bool radar_ok,
                           bool presence, uint64_t uptime_ms) {
    led->frame = smc_led_frame(led->enabled, led->brightness, pins_ok, light_ok, radar_ok, presence, uptime_ms);
    if (!led->ready || led->error != ESP_OK) return;
    uint8_t rgb[] = {led->frame.red, led->frame.green, led->frame.blue};
    if (led->written && !memcmp(rgb, led->last_rgb, sizeof(rgb))) return;
    smc_led_pulse_t pulses[SMC_LED_SYMBOL_COUNT];
    smc_led_encode(led->frame, pulses);
    for (unsigned i = 0; i < SMC_LED_SYMBOL_COUNT; ++i) {
        if (i == 24) {
            led->symbols[i] = (rmt_symbol_word_t){.level0 = 0, .duration0 = 1000, .level1 = 0, .duration1 = 1000};
        } else {
            led->symbols[i] = (rmt_symbol_word_t){.level0 = 1, .duration0 = pulses[i].high_ticks,
                                                .level1 = 0, .duration1 = pulses[i].low_ticks};
        }
    }
    rmt_transmit_config_t tx = {.loop_count = 0, .flags = {.queue_nonblocking = true, .eot_level = 0}};
    led->error = rmt_transmit(led->channel, led->encoder, led->symbols, sizeof(led->symbols), &tx);
    if (led->error == ESP_OK) led->error = rmt_tx_wait_all_done(led->channel, 20);
    if (led->error == ESP_OK) {
        memcpy(led->last_rgb, rgb, sizeof(rgb));
        led->written = true;
        ++led->updates;
    }
    /* On failure, latch the error. Do not mutate a possibly pending RMT buffer,
       repeatedly retry, or abort otherwise healthy sensor acquisition. */
}
