idf_component_register(SRCS "ld2412_protocol.c" "ld2412.c" "bh1750.c" INCLUDE_DIRS "include"
                       REQUIRES esp_driver_i2c esp_driver_uart esp_timer)
