#!/usr/bin/env python
#
# Copyright (c) 2017, Barnaby <b@zi.is>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Flash via AN945: EFM8 Factory Bootloader HID"""

from __future__ import print_function
import sys
import contextlib
import argparse
import hid
from PyCRC.CRCCCITT import CRCCCITT

SETUP = 0x31
ERASE = 0x32
WRITE = 0x33
VERIFY = 0x34
RUN = 0x36

class Unsupported(IOError):
    """Input file not understood"""
    pass

class BadChecksum(IOError):
    """Checksum mismatch"""
    pass

class BadResponse(IOError):
    """Command not confirmed"""
    pass

def twos_complement(input_value, num_bits=8):
    """Calculates the unsigned int which binary matches the two's complement of the input"""
    mask = 2**(num_bits - 1)
    return ((input_value & mask) - (input_value & ~mask)) & ((2 ** num_bits) - 1)

def toaddr(addr):
    """Split a 16bit address into two bytes (dosn't check it is a 16bit address ;-)"""
    return [addr >> 8, addr & 0xFF]

def crc(data):
    """CITT-16, XModem"""
    buf = "".join(map(chr, data)) if sys.version_info < (3, 0) else bytes(data)
    ret = CRCCCITT().calculate(buf)
    return [ret >> 8, ret & 0xFF]

def create_frame(cmd, data):
    """Bootloader frames start with '$', 1 byte length, 1 byte command, x bytes data"""
    return [
        ord("$"),
        1 + len(data),
        cmd
    ] + data

def read_intel_hex(filename):
    """Read simple Intel format Hex files into byte array"""
    data = []
    address = 0
    with open(filename) as hexfile:
        for line in hexfile.readlines():
            if line[0] != ":":
                continue
            if line.startswith(":020000040000FA"): #Confirms default Extended linear Address
                continue
            if line.startswith(":00000001FF"): #EOF
                break
            if line[7:9] != "00":
                raise Unsupported("We only cope with very simple HEX files")
            if int(line[3:7], 16) != address:
                raise Unsupported("We conly cope with liner HEX files")
            length = 9 + int(line[1:3], 16) * 2 #input chars
            if int(line[length:length + 2], 16) != twos_complement(
                    sum([int(line[x:x + 2], 16) for x in range(1, length, 2)]) & 0xFF
            ):
                raise BadChecksum()
            address += int(line[1:3], 16)
            data += [int(line[x:x + 2], 16) for x in range(9, length, 2)]
    if data == []:
        raise Unsupported("No Intel HEX lines found")
    return data

def to_frames(data, checksum=True, run=True):
    """Convert firmware byte array into sequence of bootloader frames"""
    data_zero = data[0]
    data[0] = 0xFF #Ensure we don't boot a half-written firmware

    frames = [create_frame(SETUP, [0xa5, 0xf1, 0x00])]
    for addr in range(0, len(data), 128):
        frames.append(
            create_frame(
                ERASE if addr % 0x200 == 0 else WRITE,
                toaddr(addr) + data[addr: addr + 128]
            )
        )
    if checksum:
        frames.append(
            create_frame(
                VERIFY,
                [0, 0] + toaddr(len(data)-1) + crc(data)
            )
        )
    frames.append(create_frame(WRITE, [0, 0, data_zero]))
    if run:
        frames.append(create_frame(RUN, [0, 0]))
    return frames

def flash(manufacturer, product, serial, frames):
    """Send bootloader frames over HID, and check confirmations"""
    #pylint: disable-msg=no-member
    with contextlib.closing(hid.device()) as dev:
        if hasattr(serial, "decode"):
            serial = serial.decode("ascii")
        dev.open(manufacturer, product, serial)
        print("Download over port: HID:%X:%X" % (manufacturer, product))
        print()
        for frame in frames:
            print("$", " ".join("{:02X}".format(c) for c in frame[1:9]), end=" > ")
            for off in range(0, len(frame), 64):
                dev.send_feature_report([0] + frame[off:off + 64])
            report = dev.get_feature_report(0, 2)
            print(chr(report[-1]))
            if report[-1] != 64:
                if frame[2] == VERIFY:
                    raise BadChecksum()
                else:
                    raise BadResponse()

def main():
    """Command line"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-s", "--serial", help="Serial number of device to program")
    parser.add_argument("firmware", help="Intel Hex format file to flash")
    args = parser.parse_args()
    flash(
        0x10C4,
        0xEAC9,
        args.serial,
        to_frames(
            read_intel_hex(
                args.firmware
            )
        )
    )

if __name__ == "__main__":
    main()
