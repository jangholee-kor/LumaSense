#include <assert.h>
#include <stdio.h>
#include "smc_wifi_radio.h"
#include "esp_wifi.h"

static int calls, expected_request;
static int8_t readback;
static esp_err_t start_error, set_error, read_error;

esp_err_t esp_wifi_start(void) {
    assert(calls++ == 0);
    return start_error;
}
esp_err_t esp_wifi_set_max_tx_power(int8_t power) {
    assert(calls++ == 1);
    assert(power == expected_request);
    return set_error;
}
esp_err_t esp_wifi_get_max_tx_power(int8_t *power) {
    assert(calls++ == 2);
    *power = readback;
    return read_error;
}
static void reset(int requested, int actual) {
    calls = 0;
    expected_request = requested;
    readback = (int8_t)actual;
    start_error = set_error = read_error = ESP_OK;
}

int main(void) {
    const int requests[] = {60, 44, 34, 8, 84};
    for (unsigned i = 0; i < sizeof(requests) / sizeof(requests[0]); ++i) {
        reset(requests[i], requests[i] == 84 ? 80 : requests[i]);
        assert(smc_wifi_radio_start(requests[i]) == ESP_OK);
        assert(calls == 3);
    }
    reset(61, 60); /* Driver step mapping must be allowed. */
    assert(smc_wifi_radio_start(61) == ESP_OK);
    reset(60, 44); /* Lower PHY/country limit must be allowed. */
    assert(smc_wifi_radio_start(60) == ESP_OK);
    reset(0, 80);
    assert(smc_wifi_radio_start(0) == ESP_OK && calls == 1);
    reset(60, 60);
    start_error = ESP_FAIL;
    assert(smc_wifi_radio_start(60) == ESP_FAIL && calls == 1);
    reset(60, 60);
    set_error = ESP_ERR_INVALID_ARG;
    assert(smc_wifi_radio_start(60) == ESP_ERR_INVALID_ARG && calls == 2);
    reset(60, 60);
    read_error = ESP_ERR_INVALID_STATE;
    assert(smc_wifi_radio_start(60) == ESP_ERR_INVALID_STATE && calls == 3);
    reset(60, 80);
    assert(smc_wifi_radio_start(60) == ESP_ERR_INVALID_STATE);
    reset(60, 0);
    assert(smc_wifi_radio_start(60) == ESP_ERR_INVALID_STATE);
    const int invalid[] = {-1, 1, 7, 85, 256};
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        reset(invalid[i], 60);
        assert(smc_wifi_radio_start(invalid[i]) == ESP_ERR_INVALID_ARG && calls == 0);
    }
    puts("Wi-Fi startup ordering, power requests, readback and failure tests passed");
    return 0;
}
