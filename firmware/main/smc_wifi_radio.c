#include "smc_wifi_radio.h"
#include "esp_wifi.h"

esp_err_t smc_wifi_radio_start(int requested_qdbm) {
    if (requested_qdbm != 0 && (requested_qdbm < 8 || requested_qdbm > 84))
        return ESP_ERR_INVALID_ARG;
    esp_err_t result = esp_wifi_start();
    if (result != ESP_OK || requested_qdbm == 0) return result;
    result = esp_wifi_set_max_tx_power((int8_t)requested_qdbm);
    if (result != ESP_OK) return result;
    int8_t actual = 0;
    result = esp_wifi_get_max_tx_power(&actual);
    if (result != ESP_OK) return result;
    /* Driver mapping and regulatory restrictions may lower the request. */
    return actual >= 8 && actual <= requested_qdbm ? ESP_OK : ESP_ERR_INVALID_STATE;
}
