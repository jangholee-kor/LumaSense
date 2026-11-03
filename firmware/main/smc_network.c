#include "smc_network.h"
#include "smc_network_guard.h"
#include "smc_wifi_radio.h"
#include "sdkconfig.h"
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lwip/sockets.h"

typedef struct { char ssid[33], password[64], token[65]; } credentials_t;
static QueueHandle_t config_queue, telemetry_queue, command_queue, reply_queue;
static char boot[17];
static volatile uint32_t generation;
static volatile bool authenticated, configured, connected;
static esp_netif_t *netif;
static esp_err_t network_error = ESP_ERR_INVALID_STATE;
#ifdef CONFIG_SMC_WIFI_TX_POWER_LIMIT
static const int tx_power_requested_qdbm = CONFIG_SMC_WIFI_MAX_TX_POWER_QDBM;
#else
static const int tx_power_requested_qdbm = 0;
#endif

static bool text_valid(cJSON *item, size_t minimum, size_t maximum) {
    return cJSON_IsString(item) && strlen(item->valuestring) >= minimum && strlen(item->valuestring) <= maximum;
}

static bool token_valid(const char *token) {
    if (strlen(token) != 64) return false;
    for (int i = 0; i < 64; ++i)
        if (!((token[i] >= '0' && token[i] <= '9') || (token[i] >= 'a' && token[i] <= 'f'))) return false;
    return true;
}

static bool matches(const char *expected, const char *actual) {
    if (strlen(actual) != 64) return false;
    unsigned difference = 0;
    for (int i = 0; i < 64; ++i) difference |= expected[i] ^ actual[i];
    return difference == 0;
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t event, void *data) {
    (void)arg; (void)data;
    if (base == IP_EVENT && event == IP_EVENT_STA_GOT_IP) { connected = true; network_error = ESP_OK; }
    if (base == WIFI_EVENT && event == WIFI_EVENT_STA_DISCONNECTED) connected = false;
}

esp_err_t smc_network_configure(cJSON *request) {
    if (!config_queue) return ESP_ERR_INVALID_STATE;
    cJSON *ssid = cJSON_GetObjectItemCaseSensitive(request, "ssid");
    cJSON *password = cJSON_GetObjectItemCaseSensitive(request, "password");
    cJSON *token = cJSON_GetObjectItemCaseSensitive(request, "token");
    if (!text_valid(ssid, 1, 32) || !text_valid(password, 8, 63) || !text_valid(token, 64, 64) ||
        !token_valid(token->valuestring)) return ESP_ERR_INVALID_ARG;
    credentials_t config = {0};
    strcpy(config.ssid, ssid->valuestring);
    strcpy(config.password, password->valuestring);
    strcpy(config.token, token->valuestring);
    nvs_handle_t handle;
    esp_err_t error = nvs_open("smc_wifi", NVS_READWRITE, &handle);
    if (error != ESP_OK) return error;
    error = nvs_set_blob(handle, "credentials", &config, sizeof(config));
    if (error == ESP_OK) error = nvs_commit(handle);
    nvs_close(handle);
    if (error == ESP_OK) xQueueOverwrite(config_queue, &config);
    memset(&config, 0, sizeof(config));
    return error;
}

void smc_network_status(cJSON *reply) {
    cJSON *network = cJSON_AddObjectToObject(reply, "network");
    cJSON_AddBoolToObject(network, "configured", configured);
    cJSON_AddBoolToObject(network, "connected", connected);
    cJSON_AddStringToObject(network, "error", esp_err_to_name(network_error));
    cJSON_AddNumberToObject(network, "port", 47653);
    if (tx_power_requested_qdbm)
        cJSON_AddNumberToObject(network, "tx_power_requested_dbm", tx_power_requested_qdbm / 4.0);
    else cJSON_AddNullToObject(network, "tx_power_requested_dbm");
    int8_t tx_power = 0;
    esp_err_t power_error = esp_wifi_get_max_tx_power(&tx_power);
    cJSON_AddStringToObject(network, "tx_power_read_error", esp_err_to_name(power_error));
    if (power_error == ESP_OK) cJSON_AddNumberToObject(network, "tx_power_max_dbm", tx_power / 4.0);
    else cJSON_AddNullToObject(network, "tx_power_max_dbm");
    esp_netif_ip_info_t ip = {0};
    char address[16] = "";
    if (netif && connected && esp_netif_get_ip_info(netif, &ip) == ESP_OK)
        snprintf(address, sizeof(address), IPSTR, IP2STR(&ip.ip));
    cJSON_AddStringToObject(network, "address", address);
}

void smc_network_publish(const char *json) {
    if (!telemetry_queue || strlen(json) >= SMC_NET_LINE) return;
    char line[SMC_NET_LINE] = {0};
    strcpy(line, json);
    xQueueOverwrite(telemetry_queue, line);
}

bool smc_network_command(smc_net_message_t *message) {
    if (!command_queue || xQueueReceive(command_queue, message, 0) != pdTRUE) return false;
    return authenticated && message->generation == generation;
}

void smc_network_reply(uint32_t target, const char *json) {
    if (!reply_queue || !authenticated || target != generation || strlen(json) >= SMC_NET_LINE) return;
    smc_net_message_t reply = {.generation = target};
    strcpy(reply.line, json);
    /* A full queue drops the ACK; the host reports failure and never retries mutations. */
    xQueueSend(reply_queue, &reply, 0);
}

static bool send_line(int socket, const char *line) {
    size_t size = strlen(line), sent = 0;
    int64_t deadline = esp_timer_get_time() + 300000;
    while (sent < size && esp_timer_get_time() < deadline) {
        int count = send(socket, line + sent, size - sent, 0);
        if (count <= 0) return false;
        sent += count;
    }
    return sent == size && send(socket, "\n", 1, 0) == 1;
}

static bool authorize(int socket, const char *line, const credentials_t *config) {
    cJSON *request = cJSON_ParseWithOpts(line, NULL, true);
    cJSON *cmd = cJSON_GetObjectItemCaseSensitive(request, "cmd");
    cJSON *id = cJSON_GetObjectItemCaseSensitive(request, "id");
    cJSON *token = cJSON_GetObjectItemCaseSensitive(request, "token");
    cJSON *version = cJSON_GetObjectItemCaseSensitive(request, "ver");
    bool valid = cJSON_IsNumber(version) && version->valuedouble == 1 &&
        text_valid(cmd, 4, 4) && !strcmp(cmd->valuestring, "auth") && text_valid(id, 1, 64) &&
        text_valid(token, 64, 64) && matches(config->token, token->valuestring);
    if (valid) {
        cJSON *ack = cJSON_CreateObject();
        cJSON_AddNumberToObject(ack, "ver", 1);
        cJSON_AddStringToObject(ack, "type", "ack");
        cJSON_AddStringToObject(ack, "cmd", "auth");
        cJSON_AddStringToObject(ack, "id", id->valuestring);
        cJSON_AddBoolToObject(ack, "ok", true);
        cJSON_AddStringToObject(ack, "boot_id", boot);
        cJSON_AddNumberToObject(ack, "uptime_ms", (double)(esp_timer_get_time() / 1000));
        char *json = cJSON_PrintUnformatted(ack);
        valid = json && send_line(socket, json);
        free(json);
        cJSON_Delete(ack);
    }
    cJSON_Delete(request);
    return valid;
}

static void network_task(void *unused) {
    (void)unused;
    static credentials_t config, updated;
    static char input[SMC_NET_LINE], latest[SMC_NET_LINE];
    static smc_net_message_t message;
    int listener = -1, client = -1;
    size_t used = 0;
    int64_t auth_deadline = 0, next_connect = 0;
    while (true) {
        if (xQueueReceive(config_queue, &updated, 0) == pdTRUE) {
            authenticated = connected = false;
            if (client >= 0) { close(client); client = -1; }
            config = updated;
            memset(&updated, 0, sizeof(updated));
            wifi_config_t wifi = {0};
            memcpy(wifi.sta.ssid, config.ssid, strlen(config.ssid));
            memcpy(wifi.sta.password, config.password, strlen(config.password));
            wifi.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
            esp_wifi_disconnect();
            network_error = esp_wifi_set_config(WIFI_IF_STA, &wifi);
            memset(&wifi, 0, sizeof(wifi));
            configured = network_error == ESP_OK;
            next_connect = 0;
        }
        int64_t now = esp_timer_get_time();
        if (configured && !connected && now >= next_connect) {
            network_error = esp_wifi_connect();
            next_connect = now + 5000000;
        }
        if (!connected) {
            authenticated = false;
            if (client >= 0) { close(client); client = -1; }
        }
        if (connected && listener < 0) {
            listener = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
            if (listener >= 0) {
                int reuse = 1;
                setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
                struct sockaddr_in address = {.sin_family = AF_INET, .sin_port = htons(47653), .sin_addr.s_addr = htonl(INADDR_ANY)};
                if (bind(listener, (struct sockaddr *)&address, sizeof(address)) || listen(listener, 1)) {
                    close(listener); listener = -1;
                } else fcntl(listener, F_SETFL, O_NONBLOCK);
            }
        }
        if (connected && listener >= 0 && client < 0) {
            client = accept(listener, NULL, NULL);
            if (client >= 0) {
                struct timeval timeout = {.tv_sec = 0, .tv_usec = 100000};
                setsockopt(client, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
                setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
                int no_delay = 1;
                setsockopt(client, IPPROTO_TCP, TCP_NODELAY, &no_delay, sizeof(no_delay));
                ++generation; used = 0; authenticated = false;
                xQueueReset(telemetry_queue); xQueueReset(reply_queue); xQueueReset(command_queue);
                auth_deadline = now + 3000000;
            }
        }
        bool healthy = true;
        if (client >= 0) {
            if (!authenticated && now > auth_deadline) healthy = false;
            char bytes[256];
            int count = recv(client, bytes, sizeof(bytes), MSG_DONTWAIT);
            if (!count || (count < 0 && errno != EAGAIN && errno != EWOULDBLOCK)) healthy = false;
            for (int i = 0; healthy && i < count; ++i) {
                if (bytes[i] == '\n') {
                    input[used] = 0;
                    if (!smc_network_line_bounded(input)) { healthy = false; break; }
                    if (!authenticated) authenticated = healthy = authorize(client, input, &config);
                    else {
                        message.generation = generation;
                        memcpy(message.line, input, used + 1);
                        healthy = xQueueSend(command_queue, &message, 0) == pdTRUE;
                    }
                    used = 0;
                } else if (bytes[i] != '\r') {
                    if (bytes[i] == 0 || used + 1 >= sizeof(input)) healthy = false;
                    else input[used++] = bytes[i];
                }
            }
            if (authenticated && healthy) {
                while (healthy && xQueueReceive(reply_queue, &message, 0) == pdTRUE)
                    if (message.generation == generation) healthy = send_line(client, message.line);
                if (healthy && xQueueReceive(telemetry_queue, latest, 0) == pdTRUE) healthy = send_line(client, latest);
            }
            if (!healthy) { authenticated = false; close(client); client = -1; }
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

esp_err_t smc_network_init(const char *boot_id) {
    strncpy(boot, boot_id, sizeof(boot) - 1);
    esp_err_t result = nvs_flash_init();
    if (result != ESP_OK) return network_error = result;
    result = esp_netif_init();
    if (result != ESP_OK) return network_error = result;
    result = esp_event_loop_create_default();
    if (result != ESP_OK) return network_error = result;
    netif = esp_netif_create_default_wifi_sta();
    if (!netif) return network_error = ESP_ERR_NO_MEM;
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    if ((result = esp_wifi_init(&init)) != ESP_OK) return network_error = result;
    if ((result = esp_wifi_set_storage(WIFI_STORAGE_RAM)) != ESP_OK) return network_error = result;
    esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL);
    esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL);
    esp_wifi_set_mode(WIFI_MODE_STA);
    if ((result = smc_wifi_radio_start(tx_power_requested_qdbm)) != ESP_OK) return network_error = result;
    /* Keep receiving latency predictable on monitor USB power. */
    esp_wifi_set_ps(WIFI_PS_NONE);
    config_queue = xQueueCreate(1, sizeof(credentials_t));
    telemetry_queue = xQueueCreate(1, SMC_NET_LINE);
    command_queue = xQueueCreate(4, sizeof(smc_net_message_t));
    reply_queue = xQueueCreate(4, sizeof(smc_net_message_t));
    if (!config_queue || !telemetry_queue || !command_queue || !reply_queue) return network_error = ESP_ERR_NO_MEM;
    credentials_t saved = {0};
    nvs_handle_t handle;
    if (nvs_open("smc_wifi", NVS_READONLY, &handle) == ESP_OK) {
        size_t length = sizeof(saved);
        result = nvs_get_blob(handle, "credentials", &saved, &length);
        nvs_close(handle);
        if (result == ESP_OK && length == sizeof(saved) && saved.ssid[32] == 0 && saved.password[63] == 0 &&
            saved.token[64] == 0 && token_valid(saved.token)) xQueueOverwrite(config_queue, &saved);
    }
    memset(&saved, 0, sizeof(saved));
    if (xTaskCreate(network_task, "smc-network", 8192, NULL, 4, NULL) != pdPASS) return network_error = ESP_ERR_NO_MEM;
    return network_error = ESP_OK;
}
