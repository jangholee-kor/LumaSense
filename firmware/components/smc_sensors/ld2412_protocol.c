/* HI-LINK LD2412 protocol V1.06: report and ACK frames have no checksum field. */
#include "ld2412_protocol.h"
#include <string.h>

static const uint8_t report_header[] = {0xf4, 0xf3, 0xf2, 0xf1};
static const uint8_t ack_header[] = {0xfd, 0xfc, 0xfb, 0xfa};
static const uint8_t report_footer[] = {0xf8, 0xf7, 0xf6, 0xf5};
static const uint8_t ack_footer[] = {4, 3, 2, 1};
static uint16_t le16(const uint8_t *p) { return (uint16_t)p[0] | ((uint16_t)p[1] << 8); }
static void discard(ld2412_parser_t *p, size_t n) {
    memmove(p->buffer, p->buffer + n, p->used - n);
    p->used -= n;
}

void ld2412_parser_init(ld2412_parser_t *p) { memset(p, 0, sizeof(*p)); }

static bool decode_data(const uint8_t *b, size_t n, ld2412_data_t *out) {
    if (n < 11 || (b[0] != 1 && b[0] != 2) || b[1] != 0xaa || b[n - 2] != 0x55)
        return false;
    if (b[0] == 2 && n != 11) return false;
    if (b[2] > 6) return false;
    memset(out, 0, sizeof(*out));
    out->engineering = b[0] == 1;
    out->state = b[2];
    /* V1.06 table 11 calls the last byte reserved, without a fixed value. */
    out->reserved = b[n - 1];
    /* Calibration/status states 4..6 are not an absence observation. */
    out->sensor_ok = b[2] <= 3;
    out->moving_cm = le16(b + 3);
    out->moving_energy = b[5];
    out->stationary_cm = le16(b + 6);
    out->stationary_energy = b[8];
    if (out->engineering) {
        if (n < 15 || b[9] >= LD2412_GATE_COUNT || b[10] >= LD2412_GATE_COUNT) return false;
        size_t moving_count = (size_t)b[9] + 1, stationary_count = (size_t)b[10] + 1;
        if (n != 11 + moving_count + stationary_count + 4) return false;
        out->moving_gate_count = moving_count;
        out->stationary_gate_count = stationary_count;
        memcpy(out->moving_gates, b + 11, moving_count);
        memcpy(out->stationary_gates, b + 11 + moving_count, stationary_count);
        out->light = b[11 + moving_count + stationary_count];
    }
    return true;
}

void ld2412_parser_feed(ld2412_parser_t *p, const uint8_t *bytes, size_t size,
                        ld2412_callback_t callback, void *context) {
    for (size_t i = 0; i < size; ++i) {
        if (p->used == sizeof(p->buffer)) { discard(p, 1); ++p->rejected; }
        p->buffer[p->used++] = bytes[i];
        while (p->used >= 4) {
            bool ack = memcmp(p->buffer, ack_header, 4) == 0;
            if (!ack && memcmp(p->buffer, report_header, 4) != 0) { discard(p, 1); continue; }
            if (p->used < 6) break;
            size_t length = le16(p->buffer + 4), total = length + 10;
            if (length < (ack ? 4u : 11u) || total > sizeof(p->buffer)) {
                ++p->rejected; discard(p, 1); continue;
            }
            if (p->used < total) break;
            ld2412_event_t event = {0};
            bool valid = memcmp(p->buffer + 6 + length, ack ? ack_footer : report_footer, 4) == 0;
            if (valid && ack) {
                event.kind = LD2412_ACK;
                event.command = le16(p->buffer + 6);
                event.status = le16(p->buffer + 8);
                event.ack_data_length = length - 4;
                memcpy(event.ack_data, p->buffer + 10, event.ack_data_length);
                valid = (event.command & 0x0100) != 0;
            } else if (valid) {
                event.kind = LD2412_DATA;
                valid = decode_data(p->buffer + 6, length, &event.data);
            }
            if (!valid) { ++p->rejected; discard(p, 1); continue; }
            ++p->frames;
            if (callback) callback(&event, context);
            discard(p, total);
        }
    }
}

size_t ld2412_encode_command(uint16_t command, const uint8_t *payload, size_t length,
                             uint8_t *out, size_t capacity) {
    if (!out || length > LD2412_FRAME_CAPACITY - 12 || capacity < length + 12 || (length && !payload)) return 0;
    memcpy(out, ack_header, 4);
    out[4] = (uint8_t)(length + 2); out[5] = 0;
    out[6] = (uint8_t)command; out[7] = (uint8_t)(command >> 8);
    if (length) memcpy(out + 8, payload, length);
    memcpy(out + 8 + length, ack_footer, 4);
    return length + 12;
}
