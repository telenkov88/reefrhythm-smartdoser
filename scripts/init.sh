#!/bin/bash

#  This file is part of the micropython-builder project,
#  https://github.com/v923z/micropython-builder
#  The MIT License (MIT)
#  Copyright (c) 2022 Zoltán Vörös


# set-up and housekeeping utilities

# get the number of processors, so that this might be passed to make
if which nproc > /dev/null; then
    MAKEOPTS="-j$(nproc)"
else
    MAKEOPTS="-j$(sysctl -n hw.ncpu)"
fi


# only check out ulab, if is not availble locally, otherwise, pull
git clone https://github.com/v923z/micropython-ulab ulab || git -C ulab pull


# only check out micropython, if it is not available locally, otherwise, pull
git clone https://github.com/micropython/micropython micropython || git -C micropython pull
cd micropython
git checkout v1.22.2
git submodule update --init
cd ..


# Lib for OTA update:
git clone https://github.com/glenn20/micropython-esp32-ota.git
cd micropython-esp32-ota
git checkout main
mkdir -p ../micropython/ports/esp32/modules/ota/
cp -r mip/ota/*.py ../micropython/ports/esp32/modules/ota/
cd ..

# Prepare App source code
pip3 install numpy
cd src
# Precalculate RPM table for Stepper motor
rm -rf *.npy; rm -rf *.npy.crc; rm -rf constants.crc
python3 -c 'from lib.stepper_doser_math import *;make_rpm_table()'

# Copy APP as frozen module
rm -rf frozen_app.py
python3 -m freezefs ./ frozen_app.py --on-import=extract --overwrite always --compress
mv frozen_app.py ../micropython/ports/esp32/modules
cd ..

# copy ESP32 custom board to micropython
rm -rfp micropython/ports/esp32/boards/ESP32_GENERIC_S3_16MiB_OTA
cp -rf ./boards/ESP32_GENERIC_S3_16MiB_OTA micropython/ports/esp32/boards/ESP32_GENERIC_S3_16MiB_OTA
cp -rf ./boards/ESP32_GENERIC_S3_16MiB_OTA/partitions-16MiB-4MiB_ota.csv micropython/ports/esp32/
VERSION_NAME=$(cat version.txt)
sed -i "/MICROPY_HW_BOARD_NAME/c\        MICROPY_HW_BOARD_NAME=\"$VERSION_NAME\"" micropython/ports/esp32/boards/ESP32_GENERIC_S3_16MiB_OTA/mpconfigboard.cmake

# replace initsetup.py
cp -r initsetup.py micropython/ports/esp32/modules/inisetup.py


# only check out micropython-lib, if it is not available locally, otherwise, pull
git clone https://github.com/micropython/micropython-lib || git -C micropython-lib pull


# create hashes, which will be appended to the output file names
ulab_hash=`cd ulab; git describe --abbrev=8 --always; cd ..`
upython_hash=`cd micropython; git describe --abbrev=8 --always; cd ..`

# the cross-compiler is required for each build, so we might as well get it over with
make ${MAKEOPTS} -C micropython/mpy-cross

# choose a delimiter that is not probable to turn up in the description of the file
write_platforms_list() {
    if [ -f "platforms.md" ]; then
        echo $1"| "$1-$upython_hash-$ulab_hash$ext"| " $2 >> ./platforms.list
    echo
    fi
}

# helper function to move the binary file from the build directory a temporary folder (./artifacts)
copy_files() {
    if [ -d "./artifacts" ]; then
        echo "copying firmware"
        stem=`basename $1`
        ext=$([[ "$stem" = *.* ]] && echo ".${stem##*.}" || echo '')
        mv micropython/ports/$1 ./artifacts/$2$ext
    fi
}

# clean up the build directory, in case another piece of firmware is produced for the same port
# note that the clean-up routine is run only, if the ./artifacts directory exists
clean_up() {
    # only remove the artifacts, if they can be saved in the ./artifacts folder
    if [ -d "./artifacts" ]; then
        echo "running make clean"
        make clean -C ./micropython/ports/$1

        # remove the directory explicitly, if make clean didn't get rid of it
        echo "removing compilation folder"
        rm ./micropython/ports/$1/$2 -rf
    fi
}
