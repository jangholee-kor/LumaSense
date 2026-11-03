#pragma once
#include "driver/i2c_master.h"
#include "esp_err.h"
#include "vl53l1x_core.h"

typedef struct {
    i2c_master_dev_handle_t device;
    smc_tof_io_t io;
    smc_tof_result_t latest;
    int shut_gpio;
    unsigned roi_size;
    int64_t last_sample_us;
    int64_t last_poll_us;
    int64_t started_us;
    esp_err_t error;
    bool running;
} smc_tof_t;

esp_err_t smc_tof_init(smc_tof_t *sensor, i2c_master_bus_handle_t bus, int shut_gpio, unsigned roi_size);
esp_err_t smc_tof_reset(smc_tof_t *sensor);
void smc_tof_update(smc_tof_t *sensor);
bool smc_tof_valid(const smc_tof_t *sensor, int64_t now);
