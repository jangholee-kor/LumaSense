#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "vl53l1x_core.h"

static uint8_t registers[512];
static int failing_reg = -1;
static unsigned elapsed, writes;
static int read_reg(void *ctx, uint16_t reg, uint8_t *data, size_t size) {
    (void)ctx;
    if (reg == failing_reg) return -1;
    memcpy(data, registers + reg, size);
    return 0;
}
static int write_reg(void *ctx, uint16_t reg, const uint8_t *data, size_t size) {
    (void)ctx;
    if (reg == failing_reg) return -1;
    /* GPIO status is read-only on the sensor, even in the ST config block. */
    if (reg != 0x31) memcpy(registers + reg, data, size);
    ++writes;
    return 0;
}
static void sleep_ms(void *ctx, unsigned ms) { (void)ctx; elapsed += ms; }
static void reset(void) {
    memset(registers, 0, sizeof(registers));
    registers[0xe5] = 1;
    registers[0x10f] = 0xea; registers[0x110] = 0xcc;
    registers[0xdf] = 100; registers[0x13e] = 199;
    registers[0x31] = 1;
    elapsed = writes = 0; failing_reg = -1;
}
int main(void) {
    smc_tof_io_t io = {NULL, read_reg, write_reg, sleep_ms};
    reset();
    assert(smc_tof_start(&io, 8) == SMC_TOF_OK);
    assert(registers[0x80] == 0x77 && registers[0x87] == 0x40);
    assert(registers[0x2e] == 1 && registers[0x2f] == 1);
    assert(registers[0x5e] == 0 && registers[0x5f] == 0xad);
    registers[0x89] = 9; registers[0x96] = 2; registers[0x97] = 88;
    bool ready; smc_tof_result_t sample;
    assert(smc_tof_poll(&io, &ready, &sample) == 0 && ready && sample.valid && sample.distance_mm == 600);
    registers[0x89] = 4;
    assert(smc_tof_poll(&io, &ready, &sample) == 0 && ready && !sample.valid);
    registers[0x31] = 0;
    assert(smc_tof_poll(&io, &ready, &sample) == 0 && !ready && !sample.valid);
    registers[0x31] = 1; registers[0x89] = 9; failing_reg = 0x86;
    assert(smc_tof_poll(&io, &ready, &sample) == SMC_TOF_IO && !sample.valid);
    reset(); registers[0xe5] = 0;
    assert(smc_tof_start(&io, 8) == SMC_TOF_TIMEOUT && elapsed == 500 && writes == 0);
    reset(); registers[0x31] = 0;
    assert(smc_tof_start(&io, 8) == SMC_TOF_TIMEOUT && elapsed == 1000);
    reset(); failing_reg = 0x2e;
    assert(smc_tof_start(&io, 8) == SMC_TOF_IO && writes == 1);
    reset(); registers[0x10f] = 0;
    assert(smc_tof_start(&io, 8) == SMC_TOF_MODEL && writes == 0);
    assert(smc_tof_start(&io, 3) == SMC_TOF_MODEL);
    puts("VL53L1X initialization, status, timeout and I/O failure tests passed");
    return 0;
}
