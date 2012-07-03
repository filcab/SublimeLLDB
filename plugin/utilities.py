# Utilities for the sublime lldb plugin
import sys
import string
import sublime

import root_objects
import debug
from debug import debugSettings

# This class is not thread-safe, but has everything we need for our
# settings' management, and we can guarantee that we won't have any race
# condition when creating the instance.
class SettingsManager(object):
    __sm = None
    __prefix = 'lldb.'

    @classmethod
    def getSM(cls):
        if cls.__sm is None:
            cls.__sm = SettingsManager()
        return cls.__sm

    def __init__(self):
        self.__settings = sublime.load_settings('lldb.sublime-settings')
        self.__settings_keys = root_objects.get_settings_keys()
        for k in self.__settings_keys:
            self.__settings.add_on_change(k, self.on_change)

        self.__observers = {}

    def add_observer(self, key, observer):
        """Observer is a function of two arguments: key and new value. It
will be called whenever the key is changed."""
        if key in self.__observers:
            self.__observers[key].append(observer)

    def del_observer(self, observer, key=None):
        if key is None:
            new_observers = {}
            for k, os in self.__observers:
                os.remove(observer)
                if len(os) > 0:
                    new_observers[k] = os
            self.__observers = new_observers
        else:
            if k in self.__observers:
                os = self.__observers[k]
                os.remove(observer)
                if len(os) > 0:
                    self.__observers[k] = os
                else:
                    del self.__observers[k]

    def get(self, *args):  # name, default=None, error=True):
        if len(args) > 1:
            return self.get_default(*args)

        # Temporary name fix for when we're given a setting name with the prefix
        if args[0].startswith(self.__prefix):
            name = args[0]
        else:
            # Final code should be:
            name = self.__prefix + args[0]

        setting = None
        # Is this test needed or do we always have an active window and view
        if sublime.active_window() and sublime.active_window().active_view():
            setting = sublime.active_window().active_view().settings().get(name)

        setting = setting or self.__settings.get(name)
        debug.debug(debugSettings, 'setting %s: %s' % (name, repr(setting)))
        return setting

    def get_default(self, name, default):
        # Temporary name fix for when we're given a setting name with the prefix
        # In the future, this test will be gone and no setting will have
        # the 'lldb.' prefix
        if not name.startswith(self.__prefix):
            # Final code should be:
            name = self.__prefix + name
        else:
            debug.debug(debugSettings, 'Setting name has lldb prefix: %s' % name)
            import traceback
            traceback.print_stack()

        setting = default

        if sublime.active_window() and sublime.active_window().active_view():
            setting = sublime.active_window().active_view().settings().get(name, default)

        if setting is default:
            setting = self.__settings.get(name, default)

        debug.debug(debugSettings, 'setting %s: %s' % (name, repr(setting)))
        return setting

    def on_change(*args):
        raise Exception('on_change was called. Check backtrace!')
        key= 'lldb'
        value = ''
        if key in self.__observers:
            obs = self.__observers[key]

            for o in obs:
                o(key, value)


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
