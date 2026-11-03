#include "bh1750.h"
#include "esp_timer.h"

esp_err_t bh1750_start(bh1750_t *sensor) {
    const uint8_t power_on = 0x01, continuous_high_resolution = 0x10;
    esp_err_t err = i2c_master_transmit(sensor->device, &power_on, 1, 50);
    if (err == ESP_OK) err = i2c_master_transmit(sensor->device, &continuous_high_resolution, 1, 50);
    sensor->ready_us = esp_timer_get_time() + 200000;
    return err;
}

esp_err_t bh1750_init(bh1750_t *sensor, int sda, int scl, uint8_t address) {
    if (address != 0x23 && address != 0x5c) return ESP_ERR_INVALID_ARG;
    i2c_master_bus_config_t bus = {.i2c_port = -1, .sda_io_num = sda, .scl_io_num = scl,
                                  .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
                                  .flags.enable_internal_pullup = true};
    esp_err_t err = i2c_new_master_bus(&bus, &sensor->bus);
    if (err != ESP_OK) return err;
    err = bh1750_attach(sensor, sensor->bus, address);
    if (err != ESP_OK && !sensor->device) { i2c_del_master_bus(sensor->bus); sensor->bus = NULL; }
    return err;
}

esp_err_t bh1750_attach(bh1750_t *sensor, i2c_master_bus_handle_t bus, uint8_t address) {
    if (address != 0x23 && address != 0x5c) return ESP_ERR_INVALID_ARG;
    sensor->bus = bus;
    i2c_device_config_t device = {.dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = address, .scl_speed_hz = 100000};
    esp_err_t err = i2c_master_bus_add_device(bus, &device, &sensor->device);
    if (err != ESP_OK) return err;
    return bh1750_start(sensor);
}

esp_err_t bh1750_read(bh1750_t *sensor, float *lux) {
    if (!sensor->device || esp_timer_get_time() < sensor->ready_us) return ESP_ERR_INVALID_STATE;
    uint8_t raw[2];
    esp_err_t err = i2c_master_receive(sensor->device, raw, sizeof(raw), 50);
    if (err == ESP_OK) *lux = (float)(((uint16_t)raw[0] << 8) | raw[1]) / 1.2f;
    return err;
}
