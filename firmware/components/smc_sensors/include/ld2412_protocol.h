#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define LD2412_FRAME_CAPACITY 256
#define LD2412_ACK_DATA_CAPACITY (LD2412_FRAME_CAPACITY - 14)
#define LD2412_GATE_COUNT 14

typedef struct {
    bool engineering;
    bool sensor_ok;
    uint8_t state;
    uint16_t moving_cm;
    uint16_t stationary_cm;
    uint8_t moving_energy;
    uint8_t stationary_energy;
    uint8_t moving_gate_count;
    uint8_t stationary_gate_count;
    uint8_t moving_gates[LD2412_GATE_COUNT];
    uint8_t stationary_gates[LD2412_GATE_COUNT];
    uint8_t light;
    uint8_t reserved;
} ld2412_data_t;

typedef enum { LD2412_DATA, LD2412_ACK } ld2412_kind_t;
typedef struct {
    ld2412_kind_t kind;
    ld2412_data_t data;
    uint16_t command;
    uint16_t status;
    uint16_t ack_data_length;
    uint8_t ack_data[LD2412_ACK_DATA_CAPACITY];
} ld2412_event_t;
typedef void (*ld2412_callback_t)(const ld2412_event_t *, void *);
typedef struct {
    uint8_t buffer[LD2412_FRAME_CAPACITY];
    size_t used;
    uint32_t rejected;
    uint32_t frames;
} ld2412_parser_t;

void ld2412_parser_init(ld2412_parser_t *parser);
void ld2412_parser_feed(ld2412_parser_t *parser, const uint8_t *bytes, size_t size,
                        ld2412_callback_t callback, void *context);
size_t ld2412_encode_command(uint16_t command, const uint8_t *payload, size_t length,
                             uint8_t *out, size_t capacity);
