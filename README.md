# micropython-builder

`micropython` firmware for DIY high-precise stepper motor Dosing pump.
## Contents

1. [Overview](#overview)
1. [Platforms and firmware](#platforms-and-firmware)
1. [Compiling locally](#compiling-locally)
1. [Contributing and issues](#contributing-and-issues)
    1. [Testing the build process on github](#testing-the-build-process-on-github)

## Overview
This project aims to provide a highly precise and stable DIY solution for dosing pumps with a user-friendly interface and extensive IoT integration capabilities.

It's designed to automate and simplify the dosing process, ensuring accurate and consistent dosing without manual calculations. Leveraging advanced stepper motor drivers with G-code control and the Ulab library for high-performance calculations, this project offers a cutting-edge solution for aquarists and hobbyists. Additionally, it features built-in OTA functionality for seamless firmware upgrades, ensuring the system remains up-to-date with the latest improvements and features.

## Features
- **High Precision Dosing**: Utilizes advanced stepper motor drivers to ensure accurate dosing volumes.
- **User-Friendly Interface**: Designed with ease of use in mind, allowing users to manage dosing schedules and volumes effortlessly.
- **IoT Integration**: Offers extensive IoT capabilities for integration with various smart home systems and devices.
- **Automated Calculations**: All dosing calculations are performed by the system, eliminating the need for manual input and reducing the risk of errors.
- **OTA Updates**: Supports Over-The-Air (OTA) firmware updates, making it easy to upgrade to the latest version without physical access to the device.
- **Customizable**: Flexible design accommodates different setups and requirements, making it suitable for a wide range of applications.

## Hardware Requirements
- **Controller**: [ESP32-S3 N16R8](https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf) with 16 MB Flash and 8 MB PSRAM, unless otherwise specified.
- **Stepper Motor Driver**: [BIGTREETECH MKS-Servo42C](https://github.com/makerbase-mks/MKS-SERVO42C) with UART control for precise motor management.
- **Power Supply**: Suitable power source for the ESP-S3 controller and stepper motor driver.
- **Peristaltic Pump**: DIY or commercially available peristaltic pump compatible with the stepper motor.
- **Miscellaneous**: Cables, connectors, and mounting hardware as needed for your specific setup.

## Software & Libraries
- **Firmware**: Custom firmware for the ESP-S3 controller, designed specifically for dosing pump control.
- **[Ulab Library](https://github.com/v923z/micropython-ulab)**: Utilized for high-performance mathematical calculations within the firmware.
- **[Micropython OTA tools for ESP32](https://github.com/glenn20/micropython-esp32-ota)**: Allows for Over-The-Air updates.

## Installation
1. Assemble the hardware according to the provided schematics and connection diagrams.
2. Flash the initial firmware to the ESP-S3 controller.
3. Configure the system settings, including WiFi credentials, through the initial setup interface.
4. Mount and secure the peristaltic pump in the desired location, ensuring proper alignment with the stepper motor.

## Usage
1. Access the device's web interface using its IP address or hostname.
2. Set up dosing schedules, specifying the volume, frequency, and start times for each dosing task.
3. Monitor dosing activity and system status through the interface.
4. Update firmware OTA as new versions become available to access new features and improvements.

[Contents](#contents)

# Flashing the firmware
1. Install [esptool ](https://docs.espressif.com/projects/esptool/en/latest/esp32/installation.html)
2. Download latest [release](https://github.com/telenkov88/reefrhythm-smartdoser/releases/latest)
3. Connect ESP32-S3 N16R8 controller to USB port in boot mode and erase the flash and flash the firmware
```bash
python -m esptool -b 460800 --before default_reset --after hard_reset --chip esp32s3  write_flash --erase-all --flash_mode dio --flash_size 16MB --flash_freq 80m 0x0 bootloader.bin 0x8000 partition-table.bin 0x10000 micropython.bin
```
4. Push reset button on ESP32 controller
## Compiling locally

If you would like to compile (or customise) the firmware on a local machine, all you have to do is clone this repository
with

```bash
git clone https://github.com/telenkov88/reefrhythm-smartdoser.git
```

then

```bash
cd reefrhythm-smartdoser
```

and there run

```bash
./styles/esp32/generic-s3-spiram-16mb-ota.sh
```

The rest is taken care of.

[Contents](#contents)

## Contributing
Contributions to this project are welcome! Whether it's reporting bugs, suggesting features, or submitting pull requests, your input is valuable. Please refer to the contributing guidelines for more information on how to get involved.

## License
This project is licensed under the [MIT License](LICENSE). See the LICENSE file for more details.
