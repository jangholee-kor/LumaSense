#pragma once
#include "status_led_model.h"
#include "driver/rmt_tx.h"

typedef struct {
    bool enabled, ready, written;
    int gpio;
    unsigned brightness;
    esp_err_t error;
    smc_led_frame_t frame;
    uint8_t last_rgb[3];
    uint32_t updates;
    rmt_channel_handle_t channel;
    rmt_encoder_handle_t encoder;
    rmt_symbol_word_t symbols[SMC_LED_SYMBOL_COUNT];
} smc_status_led_t;

void smc_status_led_init(smc_status_led_t *led, bool enabled, int gpio, unsigned brightness, bool pin_usable);
void smc_status_led_update(smc_status_led_t *led, bool pins_ok, bool light_ok, bool radar_ok,
                           bool presence, uint64_t uptime_ms);
