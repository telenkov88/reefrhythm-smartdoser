#!/bin/bash

# Instructions from: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/get-started/linux-macos-setup.html
sudo apt-get -y install git wget flex bison gperf python3 python3-venv python3-pip cmake ninja-build ccache libffi-dev libssl-dev dfu-util libusb-1.0-0

pip3 install pyelftools freezefs
git clone https://github.com/espressif/esp-idf.git
git -C esp-idf checkout v5.1.2
./esp-idf/install.sh

cd esp-idf
./install.sh all
cd ..
source esp-idf/export.sh