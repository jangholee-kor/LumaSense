#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sdkconfig.h"
#include "cJSON.h"
#include "bh1750.h"
#include "ld2412.h"
#include "status_led.h"
#include "driver/gpio.h"
#include "driver/usb_serial_jtag.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "soc/soc_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define USB_LINE_CAPACITY 2048
_Static_assert(CONFIG_ESP_MAIN_TASK_STACK_SIZE >= 8192, "Set ESP main task stack size to at least 8192 bytes");
/* This single-task command buffer must not consume the telemetry/printf stack. */
static char usb_line[USB_LINE_CAPACITY];
static bh1750_t light;
static ld2412_t radar;
static smc_status_led_t status_led;
static bool pins_ok;
static bool light_ok;
static float lux;
static int report_ms = CONFIG_SMC_REPORT_MS;
static uint32_t sequence;
static uint32_t usb_dropped;
static esp_err_t light_error = ESP_ERR_INVALID_STATE;
static esp_err_t radar_error = ESP_ERR_INVALID_STATE;
static int64_t last_light_us;
static bool radar_calibration_pending;
static bool radar_calibration_seen_active;

static void send_json(cJSON *root) {
    if (!root) return;
    char *text = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!text) return;
    size_t length = strlen(text), sent = 0;
    int64_t deadline = esp_timer_get_time() + 100000;
    while (sent < length && esp_timer_get_time() < deadline) {
        int written = usb_serial_jtag_write_bytes(text + sent, length - sent, pdMS_TO_TICKS(10));
        if (written > 0) sent += written;
    }
    if (sent != length) ++usb_dropped;
    /* A dropped/partial line remains visibly invalid, not silently fabricated. */
    usb_serial_jtag_write_bytes("\n", 1, pdMS_TO_TICKS(10));
    free(text);
}

static void nullable_bool(cJSON *root, const char *name, bool valid, bool value) {
    if (valid) cJSON_AddBoolToObject(root, name, value);
    else cJSON_AddNullToObject(root, name);
}

static bool radar_valid(int64_t now) {
    return !radar_calibration_pending && radar.installed && radar.last_data_us > 0 && radar.latest.sensor_ok &&
           now - radar.last_data_us <= (int64_t)CONFIG_SMC_RADAR_STALE_MS * 1000;
}

static bool light_valid(int64_t now) {
    return light_ok && now - last_light_us < 1000000;
}

static void led_diagnostics(cJSON *root) {
    cJSON *led = cJSON_AddObjectToObject(root, "status_led");
    cJSON_AddBoolToObject(led, "enabled", status_led.enabled);
    cJSON_AddNumberToObject(led, "gpio", status_led.gpio);
    cJSON_AddNumberToObject(led, "brightness", status_led.brightness);
    cJSON_AddBoolToObject(led, "driver_ok", status_led.error == ESP_OK);
    cJSON_AddStringToObject(led, "error", esp_err_to_name(status_led.error));
    cJSON_AddStringToObject(led, "state", smc_led_state_name(status_led.frame.state));
    cJSON_AddNumberToObject(led, "updates", status_led.updates);
    cJSON *rgb = cJSON_AddArrayToObject(led, "requested_rgb");
    cJSON_AddItemToArray(rgb, cJSON_CreateNumber(status_led.frame.red));
    cJSON_AddItemToArray(rgb, cJSON_CreateNumber(status_led.frame.green));
    cJSON_AddItemToArray(rgb, cJSON_CreateNumber(status_led.frame.blue));
}

static void telemetry(void) {
    int64_t now = esp_timer_get_time();
    bool radar_ok = radar_valid(now);
    bool lux_ok = light_valid(now);
    cJSON *root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "ver", 1);
    cJSON_AddStringToObject(root, "type", "telemetry");
    cJSON_AddStringToObject(root, "device", "smart-monitor-s3");
    cJSON_AddStringToObject(root, "firmware", "0.2.5");
    cJSON_AddBoolToObject(root, "radar_calibration_pending", radar_calibration_pending);
    cJSON_AddNumberToObject(root, "seq", sequence++);
    cJSON_AddNumberToObject(root, "uptime_ms", (double)(now / 1000));
    if (lux_ok) cJSON_AddNumberToObject(root, "lux", lux); else cJSON_AddNullToObject(root, "lux");
    cJSON_AddBoolToObject(root, "light_ok", lux_ok);
    cJSON_AddBoolToObject(root, "radar_ok", radar_ok);
    cJSON_AddBoolToObject(root, "sensor_ok", lux_ok && radar_ok);
    nullable_bool(root, "presence", radar_ok, radar.latest.state != 0);
    nullable_bool(root, "moving", radar_ok, (radar.latest.state & 1) != 0);
    nullable_bool(root, "stationary", radar_ok, (radar.latest.state & 2) != 0);
    if (radar_ok) {
        cJSON_AddNumberToObject(root, "radar_state", radar.latest.state);
        cJSON_AddNumberToObject(root, "radar_reserved", radar.latest.reserved);
        cJSON_AddNumberToObject(root, "moving_distance_cm", radar.latest.moving_cm);
        cJSON_AddNumberToObject(root, "stationary_distance_cm", radar.latest.stationary_cm);
        cJSON_AddNumberToObject(root, "moving_energy", radar.latest.moving_energy);
        cJSON_AddNumberToObject(root, "stationary_energy", radar.latest.stationary_energy);
        int distance = 0;
        if ((radar.latest.state & 1) && radar.latest.moving_cm) distance = radar.latest.moving_cm;
        if ((radar.latest.state & 2) && radar.latest.stationary_cm &&
            (!distance || radar.latest.stationary_cm < distance)) distance = radar.latest.stationary_cm;
        if (distance) cJSON_AddNumberToObject(root, "distance_cm", distance);
        else cJSON_AddNullToObject(root, "distance_cm");
        cJSON_AddBoolToObject(root, "engineering", radar.latest.engineering);
        if (radar.latest.engineering) {
            cJSON *moving = cJSON_AddArrayToObject(root, "moving_gate_energy");
            cJSON *stationary = cJSON_AddArrayToObject(root, "stationary_gate_energy");
            for (int i = 0; i < radar.latest.moving_gate_count; ++i)
                cJSON_AddItemToArray(moving, cJSON_CreateNumber(radar.latest.moving_gates[i]));
            for (int i = 0; i < radar.latest.stationary_gate_count; ++i)
                cJSON_AddItemToArray(stationary, cJSON_CreateNumber(radar.latest.stationary_gates[i]));
        }
    } else cJSON_AddNullToObject(root, "distance_cm");
    cJSON *errors = cJSON_AddArrayToObject(root, "errors");
    if (!pins_ok) cJSON_AddItemToArray(errors, cJSON_CreateString("invalid_gpio_configuration"));
    if (!lux_ok) cJSON_AddItemToArray(errors, cJSON_CreateString("bh1750_unavailable"));
    if (!radar_ok) cJSON_AddItemToArray(errors, cJSON_CreateString("ld2412_unavailable_or_calibrating"));
    cJSON_AddNumberToObject(root, "radar_rejected_frames", radar.parser.rejected);
    cJSON_AddNumberToObject(root, "usb_dropped_lines", usb_dropped);
    cJSON_AddStringToObject(root, "light_error", esp_err_to_name(light_error));
    cJSON_AddStringToObject(root, "radar_init_error", esp_err_to_name(radar_error));
    cJSON_AddNumberToObject(root, "free_heap", esp_get_free_heap_size());
    cJSON_AddNumberToObject(root, "main_stack_min_free_bytes", uxTaskGetStackHighWaterMark(NULL));
    led_diagnostics(root);
    send_json(root);
}

static bool integer_field(cJSON *root, const char *name, int low, int high, int *value) {
    cJSON *item = cJSON_GetObjectItemCaseSensitive(root, name);
    if (!cJSON_IsNumber(item) || !isfinite(item->valuedouble) || floor(item->valuedouble) != item->valuedouble ||
        item->valuedouble < low || item->valuedouble > high) return false;
    *value = item->valueint;
    return true;
}

static esp_err_t radar_configure(cJSON *request) {
    if (radar_calibration_pending) return ESP_ERR_INVALID_STATE;
    cJSON *engineering = cJSON_GetObjectItemCaseSensitive(request, "engineering");
    cJSON *minimum = cJSON_GetObjectItemCaseSensitive(request, "min_gate");
    cJSON *moving = cJSON_GetObjectItemCaseSensitive(request, "moving_thresholds");
    cJSON *stationary = cJSON_GetObjectItemCaseSensitive(request, "stationary_thresholds");
    cJSON *resolution = cJSON_GetObjectItemCaseSensitive(request, "resolution_cm");
    bool basic = minimum || cJSON_HasObjectItem(request, "max_gate") || cJSON_HasObjectItem(request, "absence_seconds");
    int min_gate = 0, max_gate = 0, absence = 0;
    int resolution_cm = 0;
    uint8_t move_values[14], still_values[14];
    if (engineering && !cJSON_IsBool(engineering)) return ESP_ERR_INVALID_ARG;
    if (resolution && (!integer_field(request, "resolution_cm", 20, 75, &resolution_cm) ||
                       (resolution_cm != 20 && resolution_cm != 50 && resolution_cm != 75)))
        return ESP_ERR_INVALID_ARG;
    /* A resolution restart can reset the module's basic/threshold settings.
       Require separate commands so the host can read back before proceeding. */
    if (resolution && (engineering || basic || moving || stationary)) return ESP_ERR_INVALID_ARG;
    if (basic && (!integer_field(request, "min_gate", 0, 13, &min_gate) ||
                  !integer_field(request, "max_gate", min_gate, 13, &max_gate) ||
                  !integer_field(request, "absence_seconds", 5, 65535, &absence))) return ESP_ERR_INVALID_ARG;
    cJSON *arrays[] = {moving, stationary};
    uint8_t *values[] = {move_values, still_values};
    for (int j = 0; j < 2; ++j) {
        if (!arrays[j]) continue;
        if (!cJSON_IsArray(arrays[j]) || cJSON_GetArraySize(arrays[j]) != 14) return ESP_ERR_INVALID_ARG;
        for (int i = 0; i < 14; ++i) {
            cJSON *v = cJSON_GetArrayItem(arrays[j], i);
            if (!cJSON_IsNumber(v) || !isfinite(v->valuedouble) || v->valuedouble != floor(v->valuedouble) ||
                v->valuedouble < 0 || v->valuedouble > 100) return ESP_ERR_INVALID_ARG;
            values[j][i] = v->valueint;
        }
    }
    if (!engineering && !basic && !moving && !stationary && !resolution) return ESP_ERR_INVALID_ARG;
    /* Only explicit host commands alter persistent radar settings; never at boot. */
    const uint8_t enable[] = {1, 0};
    esp_err_t result = ld2412_command(&radar, 0x00ff, enable, sizeof(enable));
    if (result != ESP_OK) {
        ld2412_command(&radar, 0x00fe, NULL, 0);
        return result;
    }
    if (engineering) result = ld2412_command(&radar, cJSON_IsTrue(engineering) ? 0x62 : 0x63, NULL, 0);
    if (resolution && result == ESP_OK) {
        uint8_t payload[] = {resolution_cm == 20 ? 3 : resolution_cm == 50 ? 1 : 0, 0, 0, 0, 0, 0};
        result = ld2412_command(&radar, 0x0001, payload, sizeof(payload));
    }
    if (basic && result == ESP_OK) {
        uint8_t payload[] = {min_gate, max_gate, absence & 0xff, absence >> 8, 0};
        result = ld2412_command(&radar, 0x0002, payload, sizeof(payload));
    }
    if (moving && result == ESP_OK) result = ld2412_command(&radar, 0x0003, move_values, 14);
    if (stationary && result == ESP_OK) result = ld2412_command(&radar, 0x0004, still_values, 14);
    esp_err_t end = ld2412_command(&radar, 0x00fe, NULL, 0);
    if (result == ESP_OK) result = end;
    if (resolution && result == ESP_OK) {
        /* V1.06: resolution takes effect only after the radar restarts. */
        vTaskDelay(pdMS_TO_TICKS(200));
        result = ld2412_command(&radar, 0x00ff, enable, sizeof(enable));
        if (result == ESP_OK) result = ld2412_command(&radar, 0x00a3, NULL, 0);
        if (result != ESP_OK) ld2412_command(&radar, 0x00fe, NULL, 0);
        /* Do not publish a pre-restart observation as the new configuration. */
        radar.last_data_us = 0;
        radar.latest.sensor_ok = false;
    }
    return result;
}

static esp_err_t radar_query(uint16_t cmd, size_t expected_length) {
    esp_err_t result = ld2412_command(&radar, cmd, NULL, 0);
    if (result == ESP_OK && radar.ack_data_length != expected_length) return ESP_ERR_INVALID_SIZE;
    return result;
}

static esp_err_t radar_get_config(cJSON *reply) {
    cJSON *config = cJSON_AddObjectToObject(reply, "radar");
    const uint8_t enable[] = {1, 0};
    esp_err_t result = ld2412_command(&radar, 0x00ff, enable, sizeof(enable));
    if (result == ESP_OK) result = radar_query(0x0011, 6);
    if (result == ESP_OK) {
        uint8_t resolution = radar.ack_data[0];
        int width_cm = resolution == 0 ? 75 : resolution == 1 ? 50 : resolution == 3 ? 20 : 0;
        cJSON_AddNumberToObject(config, "resolution_code", resolution);
        cJSON_AddNumberToObject(config, "gate_width_cm", width_cm);
        if (!width_cm) result = ESP_ERR_INVALID_RESPONSE;
    }
    if (result == ESP_OK) result = radar_query(0x0012, 5);
    if (result == ESP_OK) {
        cJSON_AddNumberToObject(config, "min_gate", radar.ack_data[0]);
        cJSON_AddNumberToObject(config, "max_gate", radar.ack_data[1]);
        cJSON_AddNumberToObject(config, "absence_seconds", radar.ack_data[2] | ((uint16_t)radar.ack_data[3] << 8));
        cJSON_AddNumberToObject(config, "out_polarity", radar.ack_data[4]);
    }
    const uint16_t commands[] = {0x0013, 0x0014};
    const char *names[] = {"moving_thresholds", "stationary_thresholds"};
    for (int i = 0; i < 2 && result == ESP_OK; ++i) {
        result = radar_query(commands[i], 14);
        if (result == ESP_OK) {
            cJSON *values = cJSON_AddArrayToObject(config, names[i]);
            for (int j = 0; j < 14; ++j) cJSON_AddItemToArray(values, cJSON_CreateNumber(radar.ack_data[j]));
        }
    }
    /* Exit configuration even on failed reads; never alter persistent values. */
    esp_err_t end = ld2412_command(&radar, 0x00fe, NULL, 0);
    if (result == ESP_OK) result = end;
    cJSON_AddBoolToObject(config, "complete", result == ESP_OK);
    return result;
}

static esp_err_t radar_calibration(cJSON *request, cJSON *reply, bool start) {
    if (start && (!cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(request, "empty_confirmed")) ||
                  radar_calibration_pending)) return ESP_ERR_INVALID_STATE;
    const uint8_t enable[] = {1, 0};
    esp_err_t result = ld2412_command(&radar, 0x00ff, enable, sizeof(enable));
    if (result == ESP_OK && start) {
        /* An ACK timeout can still mean the module received the start command. */
        radar_calibration_pending = true;
        radar_calibration_seen_active = false;
        radar.last_data_us = 0;
        result = ld2412_command(&radar, 0x000b, NULL, 0);
    } else if (result == ESP_OK) {
        result = radar_query(0x001b, 2);
        if (result == ESP_OK) {
            bool active = radar.ack_data[0] != 0;
            cJSON_AddBoolToObject(reply, "active", active);
            if (active) radar_calibration_seen_active = true;
            if (!active && radar_calibration_pending && radar_calibration_seen_active) {
                radar_calibration_pending = false;
                radar.last_data_us = 0;
            }
        }
    }
    esp_err_t end = ld2412_command(&radar, 0x00fe, NULL, 0);
    cJSON_AddBoolToObject(reply, "calibration_pending", radar_calibration_pending);
    return result == ESP_OK ? end : result;
}

static void command(const char *line) {
    cJSON *request = cJSON_ParseWithOpts(line, NULL, true);
    cJSON *reply = cJSON_CreateObject();
    cJSON_AddNumberToObject(reply, "ver", 1);
    cJSON_AddStringToObject(reply, "type", "ack");
    if (request) {
        cJSON *id = cJSON_GetObjectItemCaseSensitive(request, "id");
        if (cJSON_IsString(id) || cJSON_IsNumber(id)) cJSON_AddItemToObject(reply, "id", cJSON_Duplicate(id, true));
    }
    cJSON *name = cJSON_GetObjectItemCaseSensitive(request, "cmd");
    int version = 0;
    esp_err_t result = ESP_ERR_INVALID_ARG;
    if (request && integer_field(request, "ver", 1, 1, &version) && cJSON_IsString(name)) {
        cJSON_AddStringToObject(reply, "cmd", name->valuestring);
        if (!strcmp(name->valuestring, "ping")) result = ESP_OK;
        else if (!strcmp(name->valuestring, "get_status")) {
            result = ESP_OK;
            cJSON_AddStringToObject(reply, "device", "smart-monitor-s3");
            cJSON_AddStringToObject(reply, "firmware", "0.2.5");
            cJSON_AddNumberToObject(reply, "report_ms", report_ms);
            cJSON_AddNumberToObject(reply, "sda_gpio", CONFIG_SMC_I2C_SDA);
            cJSON_AddNumberToObject(reply, "scl_gpio", CONFIG_SMC_I2C_SCL);
            cJSON_AddNumberToObject(reply, "radar_rx_gpio", CONFIG_SMC_RADAR_RX);
            cJSON_AddNumberToObject(reply, "radar_tx_gpio", CONFIG_SMC_RADAR_TX);
            led_diagnostics(reply);
        } else if (!strcmp(name->valuestring, "set_reporting")) {
            int interval;
            if (integer_field(request, "interval_ms", 100, 5000, &interval)) {
                report_ms = interval;
                result = ESP_OK;
            }
        } else if (!strcmp(name->valuestring, "radar_config")) result = radar_configure(request);
        else if (!strcmp(name->valuestring, "radar_get_config")) result = radar_get_config(reply);
        else if (!strcmp(name->valuestring, "radar_calibrate_background")) result = radar_calibration(request, reply, true);
        else if (!strcmp(name->valuestring, "radar_calibration_status")) result = radar_calibration(request, reply, false);
    }
    cJSON_AddBoolToObject(reply, "ok", result == ESP_OK);
    cJSON_AddStringToObject(reply, "error", esp_err_to_name(result));
    if (cJSON_IsString(name) && (!strcmp(name->valuestring, "radar_config") ||
        !strcmp(name->valuestring, "radar_calibrate_background")) && result != ESP_OK)
        cJSON_AddBoolToObject(reply, "configuration_may_be_partial", true);
    send_json(reply);
    cJSON_Delete(request);
}

static bool validate_pins(void) {
    const int pins[] = {CONFIG_SMC_I2C_SDA, CONFIG_SMC_I2C_SCL, CONFIG_SMC_RADAR_RX, CONFIG_SMC_RADAR_TX,
#ifdef CONFIG_SMC_STATUS_LED_ENABLE
                        CONFIG_SMC_STATUS_LED_GPIO,
#endif
    };
    return smc_gpio_validate(pins, sizeof(pins) / sizeof(pins[0]), SOC_GPIO_VALID_OUTPUT_GPIO_MASK);
}

void app_main(void) {
    usb_serial_jtag_driver_config_t usb = {.tx_buffer_size = 8192, .rx_buffer_size = 4096};
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb));
    pins_ok = validate_pins();
#ifdef CONFIG_SMC_STATUS_LED_ENABLE
    const int led_pin[] = {CONFIG_SMC_STATUS_LED_GPIO};
    bool led_pin_usable = smc_gpio_validate(led_pin, 1, SOC_GPIO_VALID_OUTPUT_GPIO_MASK) &&
                          led_pin[0] != CONFIG_SMC_I2C_SDA && led_pin[0] != CONFIG_SMC_I2C_SCL &&
                          led_pin[0] != CONFIG_SMC_RADAR_RX && led_pin[0] != CONFIG_SMC_RADAR_TX;
    smc_status_led_init(&status_led, true, led_pin[0], CONFIG_SMC_STATUS_LED_BRIGHTNESS, led_pin_usable);
#else
    smc_status_led_init(&status_led, false, -1, 0, false);
#endif
    smc_status_led_update(&status_led, pins_ok, false, false, false, esp_timer_get_time() / 1000);
    if (pins_ok) {
        light_error = bh1750_init(&light, CONFIG_SMC_I2C_SDA, CONFIG_SMC_I2C_SCL, CONFIG_SMC_BH1750_ADDR);
        radar_error = ld2412_init(&radar, CONFIG_SMC_RADAR_RX, CONFIG_SMC_RADAR_TX, CONFIG_SMC_RADAR_BAUD);
    }
    size_t used = 0;
    bool discard_line = false;
    int64_t next_report = 0, next_read = esp_timer_get_time() + 200000, next_retry = 0;
    while (true) {
        ld2412_poll(&radar, 0);
        int64_t now = esp_timer_get_time();
        if (pins_ok && now >= next_read) {
            light_error = bh1750_read(&light, &lux);
            light_ok = light_error == ESP_OK;
            if (light_ok) last_light_us = now;
            next_read = now + 200000;
        }
        if (pins_ok && now >= next_retry) {
            if (!light_ok) {
                if (light.device) light_error = bh1750_start(&light);
                else light_error = bh1750_init(&light, CONFIG_SMC_I2C_SDA, CONFIG_SMC_I2C_SCL, CONFIG_SMC_BH1750_ADDR);
                next_read = esp_timer_get_time() + 200000;
            }
            if (!radar.installed) radar_error = ld2412_init(&radar, CONFIG_SMC_RADAR_RX, CONFIG_SMC_RADAR_TX, CONFIG_SMC_RADAR_BAUD);
            next_retry = now + 2000000;
        }
        uint8_t bytes[128];
        int count = usb_serial_jtag_read_bytes(bytes, sizeof(bytes), 0);
        for (int i = 0; i < count; ++i) {
            if (bytes[i] == '\n') {
                if (!discard_line && used) { usb_line[used] = 0; command(usb_line); }
                else if (discard_line) command("{}");
                used = 0; discard_line = false;
            } else if (bytes[i] != '\r') {
                if (used + 1 < sizeof(usb_line) && !discard_line) usb_line[used++] = bytes[i];
                else discard_line = true;
            }
        }
        now = esp_timer_get_time();
        smc_status_led_update(&status_led, pins_ok, light_valid(now), radar_valid(now),
                              radar.latest.state != 0, now / 1000);
        if (now >= next_report) { telemetry(); next_report = esp_timer_get_time() + report_ms * 1000; }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}
