#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "cJSON.h"
#include "esp_err.h"

#define SMC_NET_LINE 2048
typedef struct { uint32_t generation; char line[SMC_NET_LINE]; } smc_net_message_t;
esp_err_t smc_network_init(const char *boot_id);
esp_err_t smc_network_configure(cJSON *request);
void smc_network_status(cJSON *reply);
void smc_network_publish(const char *json);
bool smc_network_command(smc_net_message_t *message);
void smc_network_reply(uint32_t generation, const char *json);
