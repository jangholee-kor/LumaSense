/**
 ******************************************************************************
 * @file    vl53l0x_class.cpp
 * @author  IMG
 * @version V0.0.1
 * @date    14-December-2018
 * @brief   Implementation file for the VL53L1X driver class
 ******************************************************************************
 * @attention
 *
 * <h2><center>&copy; COPYRIGHT(c) 2018 STMicroelectronics</center></h2>
 *
 * Redistribution and use in source and binary forms, with or without modification,
 * are permitted provided that the following conditions are met:
 *   1. Redistributions of source code must retain the above copyright notice,
 *      this list of conditions and the following disclaimer.
 *   2. Redistributions in binary form must reproduce the above copyright notice,
 *      this list of conditions and the following disclaimer in the documentation
 *      and/or other materials provided with the distribution.
 *   3. Neither the name of STMicroelectronics nor the names of its contributors
 *      may be used to endorse or promote products derived from this software
 *      without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 * DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
 * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
 * SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
 * CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 ******************************************************************************
*/


/* Adapted from stm32duino/VL53L1X 5aa46e743913186c448aaf86dd0f12071fddc0a2.
 * Retains the ST ULD configuration; adds bounded waits and first-error handling. */
#include "vl53l1x_core.h"

#define TRY(call) do { if ((call) != 0) return SMC_TOF_IO; } while (0)

static int byte(const smc_tof_io_t *io, uint16_t reg, uint8_t value) {
    return io->write(io->context, reg, &value, 1);
}

static int word(const smc_tof_io_t *io, uint16_t reg, uint16_t value) {
    uint8_t bytes[] = {value >> 8, value & 255};
    return io->write(io->context, reg, bytes, 2);
}

static int ready_state(const smc_tof_io_t *io, bool *ready) {
    uint8_t polarity, state;
    TRY(io->read(io->context, 0x0030, &polarity, 1));
    TRY(io->read(io->context, 0x0031, &state, 1));
    *ready = (state & 1) == !(polarity & 0x10);
    return SMC_TOF_OK;
}

static const uint8_t default_configuration[] =
{
   0x00, /* 0x2d : set bit 2 and 5 to 1 for fast plus mode (1MHz I2C), else don't touch */
   0x00, /* 0x2e : bit 0 if I2C pulled up at 1.8V, else set bit 0 to 1 (pull up at AVDD) */
   0x00, /* 0x2f : bit 0 if GPIO pulled up at 1.8V, else set bit 0 to 1 (pull up at AVDD) */
   0x01, /* 0x30 : set bit 4 to 0 for active high interrupt and 1 for active low (bits 3:0 must be 0x1), use SetInterruptPolarity() */
   0x02, /* 0x31 : bit 1 = interrupt depending on the polarity, use CheckForDataReady() */
   0x00, /* 0x32 : not user-modifiable */
   0x02, /* 0x33 : not user-modifiable */
   0x08, /* 0x34 : not user-modifiable */
   0x00, /* 0x35 : not user-modifiable */
   0x08, /* 0x36 : not user-modifiable */
   0x10, /* 0x37 : not user-modifiable */
   0x01, /* 0x38 : not user-modifiable */
   0x01, /* 0x39 : not user-modifiable */
   0x00, /* 0x3a : not user-modifiable */
   0x00, /* 0x3b : not user-modifiable */
   0x00, /* 0x3c : not user-modifiable */
   0x00, /* 0x3d : not user-modifiable */
   0xff, /* 0x3e : not user-modifiable */
   0x00, /* 0x3f : not user-modifiable */
   0x0F, /* 0x40 : not user-modifiable */
   0x00, /* 0x41 : not user-modifiable */
   0x00, /* 0x42 : not user-modifiable */
   0x00, /* 0x43 : not user-modifiable */
   0x00, /* 0x44 : not user-modifiable */
   0x00, /* 0x45 : not user-modifiable */
   0x20, /* 0x46 : interrupt configuration 0->level low detection, 1-> level high, 2-> Out of window, 3->In window, 0x20-> New sample ready , TBC */
   0x0b, /* 0x47 : not user-modifiable */
   0x00, /* 0x48 : not user-modifiable */
   0x00, /* 0x49 : not user-modifiable */
   0x02, /* 0x4a : not user-modifiable */
   0x0a, /* 0x4b : not user-modifiable */
   0x21, /* 0x4c : not user-modifiable */
   0x00, /* 0x4d : not user-modifiable */
   0x00, /* 0x4e : not user-modifiable */
   0x05, /* 0x4f : not user-modifiable */
   0x00, /* 0x50 : not user-modifiable */
   0x00, /* 0x51 : not user-modifiable */
   0x00, /* 0x52 : not user-modifiable */
   0x00, /* 0x53 : not user-modifiable */
   0xc8, /* 0x54 : not user-modifiable */
   0x00, /* 0x55 : not user-modifiable */
   0x00, /* 0x56 : not user-modifiable */
   0x38, /* 0x57 : not user-modifiable */
   0xff, /* 0x58 : not user-modifiable */
   0x01, /* 0x59 : not user-modifiable */
   0x00, /* 0x5a : not user-modifiable */
   0x08, /* 0x5b : not user-modifiable */
   0x00, /* 0x5c : not user-modifiable */
   0x00, /* 0x5d : not user-modifiable */
   0x01, /* 0x5e : not user-modifiable */
   0xcc, /* 0x5f : not user-modifiable */
   0x0f, /* 0x60 : not user-modifiable */
   0x01, /* 0x61 : not user-modifiable */
   0xf1, /* 0x62 : not user-modifiable */
   0x0d, /* 0x63 : not user-modifiable */
   0x01, /* 0x64 : Sigma threshold MSB (mm in 14.2 format for MSB+LSB), use SetSigmaThreshold(), default value 90 mm  */
   0x68, /* 0x65 : Sigma threshold LSB */
   0x00, /* 0x66 : Min count Rate MSB (MCPS in 9.7 format for MSB+LSB), use SetSignalThreshold() */
   0x80, /* 0x67 : Min count Rate LSB */
   0x08, /* 0x68 : not user-modifiable */
   0xb8, /* 0x69 : not user-modifiable */
   0x00, /* 0x6a : not user-modifiable */
   0x00, /* 0x6b : not user-modifiable */
   0x00, /* 0x6c : Intermeasurement period MSB, 32 bits register, use SetIntermeasurementInMs() */
   0x00, /* 0x6d : Intermeasurement period */
   0x0f, /* 0x6e : Intermeasurement period */
   0x89, /* 0x6f : Intermeasurement period LSB */
   0x00, /* 0x70 : not user-modifiable */
   0x00, /* 0x71 : not user-modifiable */
   0x00, /* 0x72 : distance threshold high MSB (in mm, MSB+LSB), use SetD:tanceThreshold() */
   0x00, /* 0x73 : distance threshold high LSB */
   0x00, /* 0x74 : distance threshold low MSB ( in mm, MSB+LSB), use SetD:tanceThreshold() */
   0x00, /* 0x75 : distance threshold low LSB */
   0x00, /* 0x76 : not user-modifiable */
   0x01, /* 0x77 : not user-modifiable */
   0x0f, /* 0x78 : not user-modifiable */
   0x0d, /* 0x79 : not user-modifiable */
   0x0e, /* 0x7a : not user-modifiable */
   0x0e, /* 0x7b : not user-modifiable */
   0x00, /* 0x7c : not user-modifiable */
   0x00, /* 0x7d : not user-modifiable */
   0x02, /* 0x7e : not user-modifiable */
   0xc7, /* 0x7f : ROI center, use SetROI() */
   0xff, /* 0x80 : XY ROI (X=Width, Y=Height), use SetROI() */
   0x9B, /* 0x81 : not user-modifiable */
   0x00, /* 0x82 : not user-modifiable */
   0x00, /* 0x83 : not user-modifiable */
   0x00, /* 0x84 : not user-modifiable */
   0x01, /* 0x85 : not user-modifiable */
   0x00, /* 0x86 : clear interrupt, use ClearInterrupt() */
   0x00  /* 0x87 : start ranging, use StartRanging() or StopRanging(), If you want an automatic start after VL53L1X_init() call, put 0x40 in location 0x87 */
};




int smc_tof_start(const smc_tof_io_t *io, unsigned roi_size) {
    if (roi_size < 4 || roi_size > 16) return SMC_TOF_MODEL;
    uint8_t boot = 0, id[2];
    for (unsigned attempt = 0; attempt < 50; ++attempt) {
        TRY(io->read(io->context, 0x00e5, &boot, 1));
        if (boot & 1) break;
        io->sleep_ms(io->context, 10);
    }
    if (!(boot & 1)) return SMC_TOF_TIMEOUT;
    TRY(io->read(io->context, 0x010f, id, 2));
    if (id[0] != 0xea || id[1] != 0xcc) return SMC_TOF_MODEL;
    for (unsigned i = 0; i < sizeof(default_configuration); ++i) {
        uint8_t value = default_configuration[i];
        /* AVDD-level I/O, rather than the ULD's 1.8 V defaults. */
        if (i == 1 || i == 2) value |= 1;
        TRY(byte(io, 0x002d + i, value));
    }
    TRY(byte(io, 0x0087, 0x40));
    bool ready = false;
    for (unsigned attempt = 0; attempt < 100; ++attempt) {
        int error = ready_state(io, &ready);
        if (error) return error;
        if (ready) break;
        io->sleep_ms(io->context, 10);
    }
    if (!ready) return SMC_TOF_TIMEOUT;
    TRY(byte(io, 0x0086, 1));
    TRY(byte(io, 0x0087, 0));
    TRY(byte(io, 0x0008, 9));
    TRY(byte(io, 0x000b, 0));
    /* ST ULD long mode, 50 ms timing budget, 100 ms intermeasurement. */
    TRY(byte(io, 0x004b, 0x0a));
    TRY(byte(io, 0x0060, 0x0f));
    TRY(byte(io, 0x0063, 0x0d));
    TRY(byte(io, 0x0069, 0xb8));
    TRY(word(io, 0x0078, 0x0f0d));
    TRY(word(io, 0x007a, 0x0e0e));
    TRY(word(io, 0x005e, 0x00ad));
    TRY(word(io, 0x0061, 0x00c6));
    uint8_t clock_bytes[2];
    TRY(io->read(io->context, 0x00de, clock_bytes, 2));
    uint16_t clock = ((clock_bytes[0] << 8) | clock_bytes[1]) & 0x03ff;
    if (!clock) return SMC_TOF_MODEL;
    uint32_t period = (uint32_t)(clock * 100 * 1.075);
    uint8_t period_bytes[] = {period >> 24, period >> 16, period >> 8, period};
    TRY(io->write(io->context, 0x006c, period_bytes, 4));
    uint8_t center;
    TRY(io->read(io->context, 0x013e, &center, 1));
    if (roi_size > 10) center = 199;
    TRY(byte(io, 0x007f, center));
    TRY(byte(io, 0x0080, ((roi_size - 1) << 4) | (roi_size - 1)));
    TRY(byte(io, 0x0086, 1));
    TRY(byte(io, 0x0087, 0x40));
    return SMC_TOF_OK;
}

int smc_tof_poll(const smc_tof_io_t *io, bool *ready, smc_tof_result_t *result) {
    *ready = false;
    result->valid = false;
    int error = ready_state(io, ready);
    if (error || !*ready) return error;
    uint8_t raw[17];
    TRY(io->read(io->context, 0x0089, raw, sizeof(raw)));
    result->raw_status = raw[0] & 0x1f;
    result->distance_mm = ((uint16_t)raw[13] << 8) | raw[14];
    /* ST ULD maps raw status 9 to RangeValid (0). All other codes are invalid. */
    result->valid = result->raw_status == 9 && result->distance_mm >= 40 && result->distance_mm <= 4000;
    int cleared = byte(io, 0x0086, 1);
    if (cleared) { result->valid = false; return SMC_TOF_IO; }
    return SMC_TOF_OK;
}
