#pragma once
#include "driver/i2c_master.h"
#include "esp_err.h"
#include <stdint.h>
typedef struct {
    i2c_master_bus_handle_t bus;
    i2c_master_dev_handle_t device;
    int64_t ready_us;
} bh1750_t;
esp_err_t bh1750_init(bh1750_t *sensor, int sda, int scl, uint8_t address);
esp_err_t bh1750_attach(bh1750_t *sensor, i2c_master_bus_handle_t bus, uint8_t address);
esp_err_t bh1750_start(bh1750_t *sensor);
esp_err_t bh1750_read(bh1750_t *sensor, float *lux);
