#include "status_led.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static int failure, allocated, deleted_channels, deleted_encoders, transmitted, waited;
static rmt_symbol_word_t payload[SMC_LED_SYMBOL_COUNT];
esp_err_t rmt_new_tx_channel(const rmt_tx_channel_config_t *config, rmt_channel_handle_t *out) {
    assert(config->gpio_num == 38 && config->resolution_hz == 20000000);
    assert(config->mem_block_symbols >= SMC_LED_SYMBOL_COUNT && config->trans_queue_depth == 1);
    ++allocated;
    if (failure == 1) return ESP_FAIL;
    *out = (void *)1;
    return ESP_OK;
}
esp_err_t rmt_new_copy_encoder(const rmt_copy_encoder_config_t *config, rmt_encoder_handle_t *out) {
    (void)config;
    if (failure == 2) return ESP_FAIL;
    *out = (void *)2;
    return ESP_OK;
}
esp_err_t rmt_enable(rmt_channel_handle_t channel) { assert(channel); return failure == 3 ? ESP_FAIL : ESP_OK; }
esp_err_t rmt_del_encoder(rmt_encoder_handle_t encoder) { assert(encoder); ++deleted_encoders; return ESP_OK; }
esp_err_t rmt_del_channel(rmt_channel_handle_t channel) { assert(channel); ++deleted_channels; return ESP_OK; }
esp_err_t rmt_transmit(rmt_channel_handle_t channel, rmt_encoder_handle_t encoder, const void *data, size_t size,
                       const rmt_transmit_config_t *config) {
    assert(channel && encoder && size == sizeof(payload));
    assert(config->loop_count == 0 && config->flags.queue_nonblocking && !config->flags.eot_level);
    ++transmitted;
    memcpy(payload, data, size);
    return failure == 4 ? ESP_FAIL : ESP_OK;
}
esp_err_t rmt_tx_wait_all_done(rmt_channel_handle_t channel, int timeout) {
    assert(channel && timeout == 20);
    ++waited;
    return failure == 5 ? ESP_ERR_TIMEOUT : ESP_OK;
}
static void reset(void) {
    failure = allocated = deleted_channels = deleted_encoders = transmitted = waited = 0;
}
int main(void) {
    smc_status_led_t led;
    reset();
    smc_status_led_init(&led, false, -1, 0, false);
    smc_status_led_update(&led, true, true, true, true, 100);
    assert(!allocated && !transmitted && led.gpio == -1);
    smc_status_led_init(&led, true, 38, 4, false);
    assert(led.error == ESP_ERR_INVALID_ARG && !allocated);
    smc_status_led_update(&led, false, false, false, false, 0);
    assert(!transmitted);
    for (int error = 1; error <= 3; ++error) {
        reset(); failure = error;
        smc_status_led_init(&led, true, 38, 4, true);
        assert(!led.ready && led.error == ESP_FAIL && !led.channel && !led.encoder);
        assert(deleted_channels == (error >= 2) && deleted_encoders == (error >= 3));
    }
    reset();
    smc_status_led_init(&led, true, 38, 4, true);
    smc_status_led_update(&led, true, false, false, false, 0);
    assert(transmitted == 1 && waited == 1 && led.updates == 1);
    assert(payload[24].duration0 + payload[24].duration1 == 2000 && !payload[24].level0 && !payload[24].level1);
    for (int i = 0; i < 24; ++i) assert(payload[i].level0 && !payload[i].level1);
    smc_status_led_update(&led, true, false, false, false, 100);
    assert(transmitted == 1); /* Constant colors are not retransmitted every loop. */
    smc_status_led_update(&led, true, true, true, true, 200);
    assert(transmitted == 2 && led.frame.state == SMC_LED_PRESENT);
    smc_status_led_update(&led, true, false, true, true, 3000);
    smc_status_led_update(&led, true, false, true, true, 3500);
    assert(transmitted == 4 && !led.last_rgb[0] && !led.last_rgb[1] && !led.last_rgb[2]);
    for (int error = 4; error <= 5; ++error) {
        reset();
        smc_status_led_init(&led, true, 38, 4, true);
        failure = error;
        smc_status_led_update(&led, true, true, true, true, 100);
        assert(led.error != ESP_OK && !led.updates && transmitted == 1);
        rmt_symbol_word_t pending[SMC_LED_SYMBOL_COUNT];
        memcpy(pending, led.symbols, sizeof(pending));
        smc_status_led_update(&led, true, true, true, false, 500);
        assert(transmitted == 1 && !memcmp(pending, led.symbols, sizeof(pending)));
        assert(led.frame.state == SMC_LED_ABSENT); /* Model continues after transport failure. */
    }
    reset();
    smc_status_led_init(&led, true, 38, 0, true);
    smc_status_led_update(&led, true, true, true, true, 100);
    assert(transmitted == 1 && led.frame.state == SMC_LED_DISABLED);
    for (int i = 0; i < 24; ++i) assert(payload[i].duration0 == 6);
    puts("Status LED driver tests PASS: disabled/zero, GPIO rejection, init cleanup, change-only TX, bounded waits, failure latch/buffer lifetime");
    return 0;
}
