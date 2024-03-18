#!/bin/bash

#  This file is part of the micropython-builder project,
#  https://github.com/v923z/micropython-builder
#  The MIT License (MIT)
#  Copyright (c) 2022-2023 Zoltán Vörös
#                2023 Zach Moshe

source ./scripts/esp32/esp32.sh
# Read the new version name from version.txt
VERSION_NAME=$(cat version.txt)
# Use sed to replace the line containing MICROPY_HW_BOARD_NAME
sed -i "/MICROPY_HW_BOARD_NAME/c\        MICROPY_HW_BOARD_NAME=\"$VERSION_NAME\"" micropython/ports/esp32/boards/ESP32_GENERIC_S3_16MiB_OTA/mpconfigboard.cmake

build_esp32 "ESP32_GENERIC_S3_16MiB_OTA"