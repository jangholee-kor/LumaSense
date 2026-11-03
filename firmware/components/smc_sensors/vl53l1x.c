#include "vl53l1x.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static int read_register(void *context, uint16_t reg, uint8_t *data, size_t length) {
    smc_tof_t *sensor = context;
    uint8_t address[] = {reg >> 8, reg & 255};
    return i2c_master_transmit_receive(sensor->device, address, 2, data, length, 50);
}

static int write_register(void *context, uint16_t reg, const uint8_t *data, size_t length) {
    smc_tof_t *sensor = context;
    if (length > 4) return ESP_ERR_INVALID_SIZE;
    uint8_t payload[6] = {reg >> 8, reg & 255};
    for (size_t i = 0; i < length; ++i) payload[i + 2] = data[i];
    return i2c_master_transmit(sensor->device, payload, length + 2, 50);
}

static void sleep_ms(void *context, unsigned milliseconds) {
    (void)context;
    vTaskDelay(pdMS_TO_TICKS(milliseconds));
}

esp_err_t smc_tof_reset(smc_tof_t *sensor) {
    sensor->running = false;
    sensor->last_sample_us = 0;
    sensor->latest.valid = false;
    /* Only sink SHUT. The module must pull it up to its own sensor supply. */
    gpio_set_level(sensor->shut_gpio, 0);
    sleep_ms(NULL, 10);
    gpio_set_level(sensor->shut_gpio, 1);
    sleep_ms(NULL, 10);
    int result = smc_tof_start(&sensor->io, sensor->roi_size);
    sensor->error = result == SMC_TOF_OK ? ESP_OK :
                    result == SMC_TOF_TIMEOUT ? ESP_ERR_TIMEOUT : ESP_ERR_INVALID_RESPONSE;
    sensor->running = sensor->error == ESP_OK;
    sensor->last_poll_us = esp_timer_get_time();
    sensor->started_us = sensor->last_poll_us;
    return sensor->error;
}

esp_err_t smc_tof_init(smc_tof_t *sensor, i2c_master_bus_handle_t bus, int shut_gpio, unsigned roi_size) {
    sensor->shut_gpio = shut_gpio;
    sensor->roi_size = roi_size;
    sensor->io = (smc_tof_io_t){sensor, read_register, write_register, sleep_ms};
    gpio_config_t pin = {.pin_bit_mask = 1ULL << shut_gpio, .mode = GPIO_MODE_OUTPUT_OD,
                         .pull_up_en = GPIO_PULLUP_DISABLE, .pull_down_en = GPIO_PULLDOWN_DISABLE};
    esp_err_t result = gpio_config(&pin);
    if (result != ESP_OK) return sensor->error = result;
    i2c_device_config_t device = {.dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = 0x29,
                                .scl_speed_hz = 100000};
    result = i2c_master_bus_add_device(bus, &device, &sensor->device);
    if (result != ESP_OK) return sensor->error = result;
    return smc_tof_reset(sensor);
}

void smc_tof_update(smc_tof_t *sensor) {
    int64_t now = esp_timer_get_time();
    if (!sensor->running || now - sensor->last_poll_us < 20000) return;
    sensor->last_poll_us = now;
    bool ready;
    smc_tof_result_t result = {0};
    int error = smc_tof_poll(&sensor->io, &ready, &result);
    if (error) {
        sensor->latest.valid = false;
        sensor->running = false;
        sensor->error = ESP_ERR_INVALID_RESPONSE;
    } else if (ready) {
        sensor->latest = result;
        sensor->last_sample_us = esp_timer_get_time();
        sensor->error = ESP_OK;
    }
}

bool smc_tof_valid(const smc_tof_t *sensor, int64_t now) {
    return sensor->running && sensor->latest.valid && sensor->last_sample_us > 0 &&
           now - sensor->last_sample_us < 500000;
}
