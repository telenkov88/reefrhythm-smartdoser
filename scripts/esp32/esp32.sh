#!/bin/bash

#  This file is part of the micropython-builder project,
#  https://github.com/v923z/micropython-builder
#  The MIT License (MIT)
#  Copyright (c) 2022 Zoltán Vörös
#                2023 Zach Moshe

source ./scripts/init.sh

build_esp32() {
    source esp-idf/export.sh
    make ${MAKEOPTS} -C micropython/ports/esp32 BOARD=$1  BOARD_VARIANT=SPIRAM_OCT USER_C_MODULES=../../../../ulab/code/micropython.cmake CFLAGS_EXTRA=-DULAB_HASH=$ulab_hash
    #copy_files esp32/build-$1-SPIRAM_OCT/bootloader.bin $1
    mkdir -p ./artifacts
    rm -rf ./artifacts/*
    cp -rf micropython/ports/esp32/build-ESP32_GENERIC_S3_16MiB_OTA-SPIRAM_OCT/*.bin ./artifacts/
    clean_up esp32 build-ESP32_GENERIC_S3_16MiB_OTA-SPIRAM_OCT
}
