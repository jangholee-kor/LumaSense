#pragma once
#include "ld2412_protocol.h"
#include "driver/uart.h"
#include "esp_err.h"

typedef struct {
    ld2412_parser_t parser;
    ld2412_data_t latest;
    int64_t last_data_us;
    uint32_t ack_sequence;
    uint16_t ack_command;
    uint16_t ack_status;
    uint16_t ack_data_length;
    uint8_t ack_data[LD2412_ACK_DATA_CAPACITY];
    bool installed;
} ld2412_t;

esp_err_t ld2412_init(ld2412_t *radar, int rx_pin, int tx_pin, int baud);
void ld2412_poll(ld2412_t *radar, uint32_t wait_ms);
esp_err_t ld2412_command(ld2412_t *radar, uint16_t command, const uint8_t *payload, size_t length);
