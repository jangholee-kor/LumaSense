#include "ld2412_protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static ld2412_event_t events[32];
static unsigned count;
static void received(const ld2412_event_t *event, void *unused) {
    (void)unused;
    assert(count < 32);
    events[count++] = *event;
}
static const uint8_t normal[] = {
    0xf4,0xf3,0xf2,0xf1,0x0b,0, 2,0xaa,2,0x51,0,0,0,0,0x3b,0x55,0, 0xf8,0xf7,0xf6,0xf5
};
static void reset(ld2412_parser_t *p) { ld2412_parser_init(p); count = 0; }
static void feed(ld2412_parser_t *p, const uint8_t *b, size_t n) { ld2412_parser_feed(p,b,n,received,NULL); }

int main(void) {
    ld2412_parser_t parser;
    reset(&parser);
    for (size_t i = 0; i < sizeof(normal); ++i) feed(&parser, normal + i, 1);
    assert(count == 1 && events[0].kind == LD2412_DATA);
    assert(events[0].data.sensor_ok && events[0].data.state == 2);
    assert(events[0].data.moving_cm == 81 && events[0].data.stationary_energy == 59);

    reset(&parser);
    const uint8_t engineering[] = {
        0xf4,0xf3,0xf2,0xf1,0x2b,0, 1,0xaa,2,0,0,0,0,0,0,13,13,
        0,3,2,1,0,0,0,0,2,2,2,0,0,0,
        0,0,4,0x7e,0x61,13,15,5,5,4,2,1,2,1, 0xe3,0,0x55,0, 0xf8,0xf7,0xf6,0xf5
    };
    feed(&parser, engineering, sizeof(engineering));
    assert(count == 1 && events[0].data.engineering);
    assert(events[0].data.moving_gate_count == 14 && events[0].data.light == 0xe3);
    assert(events[0].data.stationary_gates[3] == 0x7e);

    /* The final byte is reserved, not a zero marker/checksum (V1.06 table 11). */
    for (unsigned reserved = 0; reserved <= 255; ++reserved) {
        uint8_t frame[sizeof(normal)]; memcpy(frame, normal, sizeof(frame));
        frame[sizeof(frame) - 5] = reserved;
        reset(&parser); feed(&parser, frame, sizeof(frame));
        assert(count == 1 && events[0].data.reserved == reserved && !parser.rejected);
    }
    uint8_t varied_engineering[sizeof(engineering)];
    memcpy(varied_engineering, engineering, sizeof(engineering));
    varied_engineering[sizeof(varied_engineering) - 5] = 0xa5;
    reset(&parser); feed(&parser, varied_engineering, sizeof(varied_engineering));
    assert(count == 1 && events[0].data.engineering && events[0].data.reserved == 0xa5);

    /* Every split point, noise prefix, and consecutive frames. */
    for (size_t split = 0; split <= sizeof(normal); ++split) {
        reset(&parser);
        const uint8_t noise[] = {0x55,0xf4,0xf3,0,0xf4,0xf3,0xf2};
        feed(&parser, noise, sizeof(noise));
        feed(&parser, normal, split);
        feed(&parser, normal + split, sizeof(normal) - split);
        feed(&parser, normal, sizeof(normal));
        assert(count == 2);
    }

    /* Calibration states remain invalid sensor observations, never absence. */
    for (uint8_t state = 0; state <= 6; ++state) {
        uint8_t frame[sizeof(normal)]; memcpy(frame, normal, sizeof(frame)); frame[8] = state;
        reset(&parser); feed(&parser, frame, sizeof(frame));
        assert(count == 1 && events[0].data.sensor_ok == (state <= 3));
    }
    /* Corrupt headers, bounds, marker, state, and footer must resynchronize. */
    const size_t corrupt_offsets[] = {0,4,7,8,15,20};
    for (size_t i = 0; i < sizeof(corrupt_offsets)/sizeof(corrupt_offsets[0]); ++i) {
        uint8_t frame[sizeof(normal)]; memcpy(frame, normal, sizeof(frame));
        frame[corrupt_offsets[i]] = 0xff;
        reset(&parser); feed(&parser, frame, sizeof(frame)); feed(&parser, normal, sizeof(normal));
        assert(count == 1);
    }
    reset(&parser);
    const uint8_t ack[] = {0xfd,0xfc,0xfb,0xfa,8,0,0xff,1,0,0,1,0,0,0,4,3,2,1};
    feed(&parser, ack, sizeof(ack)); feed(&parser, normal, sizeof(normal));
    assert(count == 2 && events[0].kind == LD2412_ACK && events[0].command == 0x1ff);
    assert(events[0].status == 0);
    uint8_t out[256]; const uint8_t payload[] = {1,0};
    assert(ld2412_encode_command(0xff,payload,2,out,sizeof(out)) == 14);
    const uint8_t expected[] = {0xfd,0xfc,0xfb,0xfa,4,0,0xff,0,1,0,4,3,2,1};
    assert(!memcmp(out,expected,sizeof(expected)));
    assert(ld2412_encode_command(0xff,payload,2,out,13) == 0);
    assert(ld2412_encode_command(0xff,NULL,2,out,sizeof(out)) == 0);
    assert(ld2412_encode_command(0xff,payload,245,out,sizeof(out)) == 0);
    assert(ld2412_encode_command(0xff,payload,2,NULL,sizeof(out)) == 0);

    reset(&parser);
    uint8_t noise[8192]; memset(noise,0xff,sizeof(noise)); feed(&parser,noise,sizeof(noise));
    feed(&parser,normal,sizeof(normal)); assert(count == 1 && parser.used < 256);
    puts("LD2412 native tests PASS: reference frames, fragmentation, bounds, corruption, ACK, calibration, all reserved byte values");
    return 0;
}
