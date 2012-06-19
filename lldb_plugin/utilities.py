# utilities for the sublime lldb plugin
import string

import sys


def stderr_msg(str):
    if str is not None and len(str) > 0:
        str = 'err> ' + str.replace('\n', '\nerr> ')

    # Remove the last 'err> '
    if str[-6:] == '\nerr> ':
        str = str[:-5]

    return str


def stdout_msg(str):
    return str


def hex_byte_line(line, grouping):
    hex_line = str(line).encode('hex')

    split_line = []
    while len(hex_line) > 0:
        split_line.append(hex_line[0:grouping * 2])
        hex_line = hex_line[grouping * 2:]

    return ' '.join(split_line)


def print_byte_line(line, grouping):
    def print_or_dot(char):
        c = chr(char)
        return c if c in string.printable else '.'

    split_line = []
    dot_print_line = map(print_or_dot, line)
    while len(dot_print_line) > 0:
        split_line.append(''.join(dot_print_line[0:grouping]))
        dot_print_line = dot_print_line[grouping:]

    return ' '.join(split_line)


def generate_memory_view_for(addr, new_bytes, width=32, grouping=8):
    addresses = []
    hex_bytes = []
    bytes = []

    # Try an heuristic for 64-bit detection. Won't work on the boundary.
    _64bit = addr > 0x100000000

    # We don't want integer division
    n, r = divmod(len(new_bytes), width)
    if r > 0:
        n += 1

    for i in xrange(0, n):
        # Addresses
        curr_addr = addr + i * width
        addresses.append(curr_addr)

        # Hex bytes
        line = new_bytes[i * width:(i + 1) * width]
        hex_bytes.append(hex_byte_line(line, grouping))

        # Bytes
        bytes.append(print_byte_line(line, grouping))

    assert(len(addresses) == len(hex_bytes) == len(bytes))

    result = ''
    addr_fmt = '0x%.16x' if _64bit else '0x%.8x'
    for i in xrange(0, len(addresses)):
        result += (addr_fmt + '     %s          %s\n') % (addresses[i], hex_bytes[i], bytes[i])

    return result


import os
import pty


class PseudoTerminal(object):
    invalid_fd = -1

    def __init__(self):
        self._master = self.invalid_fd
        self._slave = self.invalid_fd
        # raise NotImplementedError("Pseudo-terminal support is only available on Mac OS X")

    def __del__(self):
        self.close_master_file_descriptor()
        self.close_slave_file_descriptor()

    def close_master_file_descriptor(self):
        if self._master > 0:
            os.close(self._master)
            self._master = self.invalid_fd

    def close_slave_file_descriptor(self):
        if self._slave > 0:
            os.close(self._slave)
            self._slave = self.invalid_fd

    @property
    def master(self):
        return self._master

    @property
    def slave(self):
        return self._slave

    def open_first_available_master(self, oflag):
        self._master, self._slave = pty.openpty()

    def release_master_file_descriptor(self):
        fd = self._master
        self._master = self.invalid_fd
        return fd

    def release_slave_file_descriptor(self):
        fd = self._slave
        self._slave = self.invalid_fd
        return fd
