#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Transport-independent, bounded ST ULD adaptation. Nonzero means I/O failure. */
typedef struct {
    void *context;
    int (*read)(void *, uint16_t, uint8_t *, size_t);
    int (*write)(void *, uint16_t, const uint8_t *, size_t);
    void (*sleep_ms)(void *, unsigned);
} smc_tof_io_t;

typedef struct {
    uint16_t distance_mm;
    uint8_t raw_status;
    bool valid;
} smc_tof_result_t;

enum { SMC_TOF_OK = 0, SMC_TOF_IO = -1, SMC_TOF_TIMEOUT = -2, SMC_TOF_MODEL = -3 };
int smc_tof_start(const smc_tof_io_t *io, unsigned roi_size);
/* A successful poll can report ready=false; it must not refresh sample age. */
int smc_tof_poll(const smc_tof_io_t *io, bool *ready, smc_tof_result_t *result);
