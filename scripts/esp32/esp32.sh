#!/bin/bash

#  This file is part of the micropython-builder project,
#  https://github.com/v923z/micropython-builder
#  The MIT License (MIT)
#  Copyright (c) 2022 Zoltán Vörös
#                2023 Zach Moshe

source ./scripts/init.sh

build_esp32() {
    source esp-idf/export.sh
    VERSION_NAME=$(cat version.txt)
    make ${MAKEOPTS} -C micropython/ports/esp32 BOARD=$1  BOARD_VARIANT=SPIRAM_OCT USER_C_MODULES=../../../../ulab/code/micropython.cmake CFLAGS_EXTRA=-DULAB_HASH=$ulab_hash
    mkdir -p ./artifacts
    rm -rf ./artifacts/*
    cp -rf micropython/ports/esp32/build-ESP32_GENERIC_S3_16MiB_OTA-SPIRAM_OCT/micropython.bin ./artifacts/
    cp -rf micropython/ports/esp32/build-ESP32_GENERIC_S3_16MiB_OTA-SPIRAM_OCT/bootloader/bootloader.bin ./artifacts/
    cp -rf micropython/ports/esp32/build-ESP32_GENERIC_S3_16MiB_OTA-SPIRAM_OCT/partition_table/partition-table.bin ./artifacts/

    cd ./artifacts

    # Add json file with firmware info
    # Specify the filename
    FILENAME="micropython.bin"
    # Calculate the SHA-256 checksum of the file
    SHA=$(sha256sum "$FILENAME" | awk '{ print $1 }')
    # Calculate the length of the file in bytes
    LENGTH=$(wc -c < "$FILENAME")
    # Create the artifacts.json file with the calculated values
    echo "{\"firmware\": \"$FILENAME\", \"version\": \"$RELEASE_TAG\", \"sha\": \"$SHA\", \"length\": $LENGTH}" > micropython.json
    cd ..

    clean_up esp32 build-ESP32_GENERIC_S3_16MiB_OTA-SPIRAM_OCT
}
