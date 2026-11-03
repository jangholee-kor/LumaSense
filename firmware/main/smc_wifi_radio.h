#pragma once
#include "esp_err.h"

/* Zero preserves driver defaults; other values use ESP-IDF's 0.25 dBm unit.
 * Returns success only after startup and, when requested, verified limiting.
 * The caller must not start connection attempts before this succeeds. */
esp_err_t smc_wifi_radio_start(int requested_qdbm);
