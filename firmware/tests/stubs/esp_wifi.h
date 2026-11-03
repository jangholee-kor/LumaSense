#pragma once
#include <stdint.h>
#include "esp_err.h"

/* Host-only Wi-Fi API boundary; firmware builds use the ESP-IDF header. */
esp_err_t esp_wifi_start(void);
esp_err_t esp_wifi_set_max_tx_power(int8_t power);
esp_err_t esp_wifi_get_max_tx_power(int8_t *power);
