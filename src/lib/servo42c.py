import struct


def calc_crc(*args):
    summ = 0
    print(args)
    for register in args:
        print(register.to_bytes(1, 'big'), end=' ')
        summ += register
    crc = summ & 0xFF
    print(f"{crc.to_bytes(1, 'big')}")
    return crc


def calc_steps(mks, rpm, mstep, timeout):
    steps_per_cycle = mks.step_per_rev*mstep
    steps_per_minute = steps_per_cycle * rpm
    steps_per_timeout = steps_per_minute * (timeout/60)
    return int(steps_per_timeout)


class Servo42c:
    def __init__(self, uart, addr: int, speed=1, mstep=255, direction=0, step_per_rev=200):
        self.sec_in_pulse = None
        self.rpm = None
        self.speed_reg = None
        self.addr = 224 + addr  # MKS-Servo42C  UART address 0-8
        self.uart = uart
        self.dir = direction
        self.speed = speed
        self.mstep = mstep
        self.step_per_rev = step_per_rev  # Steps per revolution. Angle 1.8 = 200, 0.9 = 400
        reply_crc = calc_crc(self.addr, 1)
        self.reply_pattern = bytes([self.addr, 1, reply_crc])

        self.set_mstep(mstep, force=True, retry=1)
        self.set_speed(speed, self.dir)
        self.flush()

    def set_mstep(self, mstep, force=False, retry=5):
        print(f"Old mstep: {self.mstep} New mstep: {mstep}")
        if self.mstep != mstep or force:
            for _ in range(5):
                if self.stop():
                    break

            print(f"\nWrite new mstep: {mstep}")
            crc = calc_crc(self.addr, 132, mstep)
            cmd = bytes([self.addr, 132, mstep, crc])
            self.flush()
            self.uart.write(cmd)

            for retry_count in range(1, retry+1):
                reply = self.uart.read()
                print(reply)

                if reply == self.reply_pattern:
                    print("Setting up Mstep success")
                    self.mstep = mstep
                    return True
                else:
                    print(f"Mstep reply invalid, retry No {retry_count}")

            print("Setting up Mstep failed after multiple retries.")
            return False

        else:
            print("Skip setting up mstep")
            return True

    def set_mstep_proxy(self, mstep):
        self.set_mstep(mstep)

    def write(self, register: int):
        self.uart.write(register.to_bytes(1, 'big'))

    def flush(self):
        self.uart.read()

    def read(self, *uart_formats, check_crc=False, debug=False):
        # https://docs.python.org/3/library/struct.html
        data = []

        for size, data_format in uart_formats:
            raw_data = self.uart.read(size)
            if debug:
                print(f"Read {size} bytes: [{raw_data}]")
            try:
                value = struct.unpack('>' + data_format, raw_data)[0]
            except TypeError:
                print(f"Failed to unpack data [{raw_data}] with format {data_format}")
                return False
            print(f"raw_data: {raw_data} value: {value}")
            data.append(value)

        if check_crc and calc_crc(*data[:-1]) == data[-1]:
            return data
        elif check_crc:
            return False
        else:
            return data

    def read_raw(self):
        return self.uart.read()

    def read_encoder(self, debug=False):
        self.flush()
        crc = calc_crc(self.addr, 48)
        cmd = bytes([self.addr, 48, crc]) # 48 = b'\x30' - read encoder
        self.uart.write(cmd)
        address, carry, value, crc = self.read((1, 'B'), (4, 'i'), (2, 'H'), (1, 'B'), debug=debug)
        if address == self.addr:
            return carry, value
        else:
            return False

    def read_pulses(self):
        crc = calc_crc(self.addr, 51)
        self.flush()
        cmd = bytes([self.addr, 51, crc])  # b'\x33' - read number of pulses
        self.uart.write(cmd)
        print("crc", crc)

        address, pulses, crc = self.read((1, 'B'), (4, 'i'), (1, 'B'))
        if address == self.addr:
            return pulses
        else:
            print("crc missmatch")
            return None

    def set_speed(self, speed, direction):
        # Ensure speed is within the valid range (0 to 127)
        self.speed = max(1, min(speed, 127))
        # Ensure direction is either 0 or 1
        self.dir = 1 if direction else 0

        self.rpm = self.calc_rpm(speed)
        self.sec_in_pulse = 60 / (self.mstep * 200 * self.rpm)
        self.speed_reg = self.calc_speed_reg()

    def set_current(self, current: int):
        current = max(200, min(current, 3000))
        crc = calc_crc(self.addr, 131, current//200)
        cmd = bytes([self.addr, 131, current//200, crc])  # b'\x83' -set current
        self.uart.write(cmd)

    def calc_rpm(self, speed):
        return (speed * 30000) / (self.mstep * self.step_per_rev)

    def calc_delay(self, pulses):
        return pulses * self.sec_in_pulse

    def calc_speed_reg(self):
        # Combine direction and speed bits to form the 8-bit register value
        return (self.dir << 7) | self.speed

    def stop(self,):
        self.flush()
        crc = calc_crc(self.addr, 247)
        cmd = bytes([self.addr, 247, crc])
        self.uart.write(cmd)
        status = self.read_raw()
        print("[STOP] got status :", status)
        if status and self.reply_pattern in status:
            return True
        else:
            return False

    def move(self, speed, direction):
        self.set_speed(speed, direction)
        crc = calc_crc(self.addr, 246, self.speed_reg)
        cmd = bytes([self.addr, 246, self.speed_reg, crc])  # b'\xf6' -move forward
        self.uart.write(cmd)

    def make_steps(self, steps, speed, direction, stop=True):
        self.set_speed(speed, direction)
        print(f"Make {steps} steps on speed {speed}, rpm {self.rpm}")

        pulses_reg = [x for x in steps.to_bytes(4, 'big')]
        crc = calc_crc(self.addr, 253, self.speed_reg, *pulses_reg)
        if stop:
            self.stop()

        # Create a list of bytes to be sent
        bytes_to_send = [self.addr, 253, self.speed_reg] + pulses_reg + [crc]

        # Convert the list to a bytes object
        data = bytes(bytes_to_send)

        # Write the entire bytes object in one command
        self.uart.write(data)

        reply = self.read_raw()
        if reply and self.reply_pattern in reply:
            print("Command success")
            worktime = steps * self.sec_in_pulse
            print(f"Run for {worktime}sec")
            return worktime
        else:
            return False
