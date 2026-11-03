#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sdkconfig.h"
#include "cJSON.h"
#include "bh1750.h"
#include "vl53l1x.h"
#include "status_led.h"
#include "driver/usb_serial_jtag.h"
#include "esp_system.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "soc/soc_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define FIRMWARE_VERSION "0.3.0"
#define LINE_CAPACITY 2048
_Static_assert(CONFIG_ESP_MAIN_TASK_STACK_SIZE >= 8192, "Main task stack must be at least 8192 bytes");
static char input_line[LINE_CAPACITY];
static i2c_master_bus_handle_t bus;
static bh1750_t light;
static smc_tof_t tof;
static smc_status_led_t led;
static bool pins_ok, light_ok;
static float lux;
static int64_t light_at;
static int report_ms = CONFIG_SMC_REPORT_MS;
static uint32_t sequence, usb_dropped;
static char boot_id[17];

static void send_json(cJSON *root) {
    if (!root) return;
    char *text = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!text) return;
    /* A disconnected USB host must not stall sensor collection. */
    size_t length = strlen(text);
    if (usb_serial_jtag_is_connected()) {
        int sent = usb_serial_jtag_write_bytes(text, length, pdMS_TO_TICKS(10));
        if (sent != (int)length) ++usb_dropped;
        usb_serial_jtag_write_bytes("\n", 1, pdMS_TO_TICKS(10));
    }
    free(text);
}

static bool valid_light(int64_t now) { return light_ok && light_at && now - light_at < 1000000; }

static void telemetry(void) {
    int64_t now = esp_timer_get_time();
    bool light_valid = valid_light(now), tof_valid = smc_tof_valid(&tof, now);
    cJSON *root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "ver", 2);
    cJSON_AddStringToObject(root, "type", "telemetry");
    cJSON_AddStringToObject(root, "device", "smart-monitor-s3");
    cJSON_AddStringToObject(root, "presence_sensor", "vl53l1x");
    cJSON_AddStringToObject(root, "firmware", FIRMWARE_VERSION);
    cJSON_AddStringToObject(root, "boot_id", boot_id);
    cJSON_AddNumberToObject(root, "seq", sequence++);
    cJSON_AddNumberToObject(root, "uptime_ms", (double)(now / 1000));
    cJSON_AddBoolToObject(root, "light_ok", light_valid);
    cJSON_AddBoolToObject(root, "tof_ok", tof_valid);
    cJSON_AddBoolToObject(root, "sensor_ok", light_valid && tof_valid);
    if (light_valid) cJSON_AddNumberToObject(root, "lux", lux); else cJSON_AddNullToObject(root, "lux");
    if (tof_valid) cJSON_AddNumberToObject(root, "distance_mm", tof.latest.distance_mm);
    else cJSON_AddNullToObject(root, "distance_mm");
    cJSON_AddNumberToObject(root, "tof_raw_status", tof.latest.raw_status);
    if (tof.last_sample_us) cJSON_AddNumberToObject(root, "tof_sample_age_ms", (double)((now - tof.last_sample_us) / 1000));
    else cJSON_AddNullToObject(root, "tof_sample_age_ms");
    cJSON_AddStringToObject(root, "tof_error", esp_err_to_name(tof.error));
    cJSON_AddNumberToObject(root, "roi_size", CONFIG_SMC_TOF_ROI_SIZE);
    cJSON_AddNumberToObject(root, "usb_dropped_lines", usb_dropped);
    cJSON_AddNumberToObject(root, "free_heap", esp_get_free_heap_size());
    cJSON_AddNumberToObject(root, "main_stack_min_free_bytes", uxTaskGetStackHighWaterMark(NULL));
    send_json(root);
}

static void command(const char *line) {
    cJSON *request = cJSON_ParseWithOpts(line, NULL, true);
    cJSON *reply = cJSON_CreateObject();
    cJSON_AddNumberToObject(reply, "ver", 1);
    cJSON_AddStringToObject(reply, "type", "ack");
    cJSON *id = cJSON_GetObjectItemCaseSensitive(request, "id");
    if (cJSON_IsString(id)) cJSON_AddStringToObject(reply, "id", id->valuestring);
    cJSON *name = cJSON_GetObjectItemCaseSensitive(request, "cmd");
    cJSON *version = cJSON_GetObjectItemCaseSensitive(request, "ver");
    esp_err_t result = ESP_ERR_INVALID_ARG;
    if (cJSON_IsNumber(version) && version->valuedouble == 1 && cJSON_IsString(name)) {
        cJSON_AddStringToObject(reply, "cmd", name->valuestring);
        if (!strcmp(name->valuestring, "ping")) result = ESP_OK;
        else if (!strcmp(name->valuestring, "get_status")) {
            result = ESP_OK;
            cJSON_AddStringToObject(reply, "device", "smart-monitor-s3");
            cJSON_AddStringToObject(reply, "firmware", FIRMWARE_VERSION);
            cJSON_AddStringToObject(reply, "presence_sensor", "vl53l1x");
            cJSON_AddNumberToObject(reply, "sda_gpio", CONFIG_SMC_I2C_SDA);
            cJSON_AddNumberToObject(reply, "scl_gpio", CONFIG_SMC_I2C_SCL);
            cJSON_AddNumberToObject(reply, "shut_gpio", CONFIG_SMC_TOF_SHUT_GPIO);
            cJSON_AddNumberToObject(reply, "roi_size", CONFIG_SMC_TOF_ROI_SIZE);
            cJSON_AddNumberToObject(reply, "report_ms", report_ms);
        } else if (!strcmp(name->valuestring, "tof_reset")) {
            if (pins_ok && tof.device) result = smc_tof_reset(&tof);
            else result = ESP_ERR_INVALID_STATE;
        } else if (!strcmp(name->valuestring, "set_reporting")) {
            cJSON *interval = cJSON_GetObjectItemCaseSensitive(request, "interval_ms");
            if (cJSON_IsNumber(interval) && isfinite(interval->valuedouble) &&
                floor(interval->valuedouble) == interval->valuedouble && interval->valuedouble >= 100 &&
                interval->valuedouble <= 5000) {
                report_ms = interval->valueint;
                result = ESP_OK;
            }
        } else result = ESP_ERR_NOT_SUPPORTED;
    }
    cJSON_AddBoolToObject(reply, "ok", result == ESP_OK);
    cJSON_AddStringToObject(reply, "error", esp_err_to_name(result));
    cJSON_AddStringToObject(reply, "boot_id", boot_id);
    cJSON_AddNumberToObject(reply, "uptime_ms", (double)(esp_timer_get_time() / 1000));
    send_json(reply);
    cJSON_Delete(request);
}

void app_main(void) {
    snprintf(boot_id, sizeof(boot_id), "%08lx%08lx", (unsigned long)esp_random(), (unsigned long)esp_random());
    const int pins[] = {CONFIG_SMC_I2C_SDA, CONFIG_SMC_I2C_SCL, CONFIG_SMC_TOF_SHUT_GPIO,
#ifdef CONFIG_SMC_STATUS_LED_ENABLE
                        CONFIG_SMC_STATUS_LED_GPIO,
#endif
    };
    pins_ok = smc_gpio_validate(pins, sizeof(pins) / sizeof(pins[0]), SOC_GPIO_VALID_OUTPUT_GPIO_MASK);
    usb_serial_jtag_driver_config_t usb = {.tx_buffer_size = 8192, .rx_buffer_size = 4096};
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb));
#ifdef CONFIG_SMC_STATUS_LED_ENABLE
    smc_status_led_init(&led, true, CONFIG_SMC_STATUS_LED_GPIO, CONFIG_SMC_STATUS_LED_BRIGHTNESS, pins_ok);
#else
    smc_status_led_init(&led, false, -1, 0, false);
#endif
    if (pins_ok) {
        i2c_master_bus_config_t config = {.i2c_port = -1, .sda_io_num = CONFIG_SMC_I2C_SDA,
            .scl_io_num = CONFIG_SMC_I2C_SCL, .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7};
        esp_err_t error = i2c_new_master_bus(&config, &bus);
        if (error != ESP_OK) pins_ok = false;
    }
    if (pins_ok) {
        bh1750_attach(&light, bus, CONFIG_SMC_BH1750_ADDR);
        smc_tof_init(&tof, bus, CONFIG_SMC_TOF_SHUT_GPIO, CONFIG_SMC_TOF_ROI_SIZE);
    }
    int64_t next_report = 0, next_light = 0, next_retry = 0;
    size_t used = 0;
    bool discard = false;
    while (true) {
        int64_t now = esp_timer_get_time();
        if (pins_ok) {
            smc_tof_update(&tof);
            if (now >= next_light) {
                light_ok = bh1750_read(&light, &lux) == ESP_OK;
                if (light_ok) light_at = esp_timer_get_time();
                next_light = now + 200000;
            }
            if (now >= next_retry) {
                if (!light_ok) {
                    if (light.device) bh1750_start(&light);
                    else bh1750_attach(&light, bus, CONFIG_SMC_BH1750_ADDR);
                }
                /* Retry stuck/no-data sensors, but do not reset merely for a bad range. */
                if (tof.device && (!tof.running || now - (tof.last_sample_us ? tof.last_sample_us : tof.started_us) > 2000000))
                    smc_tof_reset(&tof);
                next_retry = esp_timer_get_time() + 3000000;
            }
        }
        uint8_t bytes[128];
        int count = usb_serial_jtag_read_bytes(bytes, sizeof(bytes), 0);
        for (int i = 0; i < count; ++i) {
            if (bytes[i] == '\n') {
                if (used && !discard) { input_line[used] = 0; command(input_line); }
                used = 0; discard = false;
            } else if (bytes[i] != '\r') {
                if (used + 1 < sizeof(input_line) && !discard) input_line[used++] = bytes[i];
                else discard = true;
            }
        }
        now = esp_timer_get_time();
        bool tof_valid = smc_tof_valid(&tof, now);
        smc_status_led_update(&led, pins_ok, valid_light(now), tof_valid,
                              tof_valid && tof.latest.distance_mm <= 1500, now / 1000);
        if (now >= next_report) { telemetry(); next_report = esp_timer_get_time() + report_ms * 1000; }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}
