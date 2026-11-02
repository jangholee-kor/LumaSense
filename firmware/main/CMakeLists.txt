idf_component_register(SRCS "main.c" INCLUDE_DIRS "." REQUIRES smc_sensors smc_status json esp_driver_usb_serial_jtag esp_driver_gpio esp_timer)
