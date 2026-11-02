#include "ld2412.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include <string.h>

static void receive_event(const ld2412_event_t *event, void *context) {
    ld2412_t *radar = context;
    if (event->kind == LD2412_DATA) {
        radar->latest = event->data;
        radar->last_data_us = esp_timer_get_time();
    } else {
        ++radar->ack_sequence;
        radar->ack_command = event->command;
        radar->ack_status = event->status;
    }
}

esp_err_t ld2412_init(ld2412_t *radar, int rx_pin, int tx_pin, int baud) {
    memset(radar, 0, sizeof(*radar));
    ld2412_parser_init(&radar->parser);
    uart_config_t config = {.baud_rate = baud, .data_bits = UART_DATA_8_BITS, .parity = UART_PARITY_DISABLE,
                            .stop_bits = UART_STOP_BITS_1, .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
                            .source_clk = UART_SCLK_DEFAULT};
    esp_err_t err = uart_param_config(UART_NUM_1, &config);
    if (err == ESP_OK) err = uart_set_pin(UART_NUM_1, tx_pin, rx_pin, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    if (err == ESP_OK) err = uart_driver_install(UART_NUM_1, 4096, 0, 0, NULL, 0);
    radar->installed = err == ESP_OK;
    return err;
}

void ld2412_poll(ld2412_t *radar, uint32_t wait_ms) {
    if (!radar->installed) return;
    uint8_t bytes[256];
    int count = uart_read_bytes(UART_NUM_1, bytes, sizeof(bytes), pdMS_TO_TICKS(wait_ms));
    if (count > 0) ld2412_parser_feed(&radar->parser, bytes, count, receive_event, radar);
}

esp_err_t ld2412_command(ld2412_t *radar, uint16_t command, const uint8_t *payload, size_t length) {
    if (!radar->installed) return ESP_ERR_INVALID_STATE;
    uint8_t frame[LD2412_FRAME_CAPACITY];
    size_t count = ld2412_encode_command(command, payload, length, frame, sizeof(frame));
    if (!count) return ESP_ERR_INVALID_ARG;
    uint32_t previous = radar->ack_sequence;
    if (uart_write_bytes(UART_NUM_1, frame, count) != (int)count) return ESP_FAIL;
    int64_t deadline = esp_timer_get_time() + 1000000;
    while (esp_timer_get_time() < deadline) {
        ld2412_poll(radar, 20);
        if (radar->ack_sequence != previous && radar->ack_command == (command | 0x0100))
            return radar->ack_status == 0 ? ESP_OK : ESP_FAIL;
    }
    return ESP_ERR_TIMEOUT;
}
