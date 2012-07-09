# Utilities for the sublime lldb plugin
import string
import sublime

from debug import debug, debugSettings, debugAny


class SettingsManager(object):
    # This class is not thread-safe, but has everything we need for our
    # settings' management, and we can guarantee that we won't have any race
    # condition when creating the instance.
    __sm = None
    __prefix = 'lldb.'

    @classmethod
    def getSM(cls):
        if cls.__sm is None:
            cls.__sm = SettingsManager()
        return cls.__sm

    def __init__(self):
        self.__settings = sublime.load_settings('lldb.sublime-settings')
        self.__settings_keys = []
        # self.__settings_keys = root_objects.get_settings_keys()
        self.__values = {}
        self.__observers = {}

    def create_listener(self, key):
        return self.Listener(self, key)

    # Listener class, to work around Sublime Text 2's lack of decent
    # on_change functionality (it doesn't even tell you what setting was
    # changed!)
    class Listener(object):
        def __init__(self, owner, key):
            self.__owner = owner
            self.__key = key

        @property
        def key(self):
            return self.__key

        def on_change(self):
            self.__owner.on_change(self.key)

        # TODO: If this doesn't work, just create a destroy method that
        # does the same.
        def __del__(self):
            self.__owner.clear_on_change(self.__key)

    def add_observer(self, key, observer):
        """Observer is a function of two arguments: key and new value. It
            will be called whenever the key is changed."""
        key = self.__prefix + key
        if key in self.__observers:
            self.__observers[key].append(observer)
        else:
            self.__observers[key] = [observer]

    def del_observer(self, observer, key=None):
        if key is None:
            new_observers = {}
            for k, obs in self.__observers:
                # FIXME: call Settings.clean_on_change() if we go down to 0
                # observers on a key.
                obs.remove(observer)
                if len(obs) > 0:
                    new_observers[k] = obs
            self.__observers = new_observers
        else:
            if k in self.__observers:
                obs = self.__observers[k]
                obs.remove(observer)
                if len(obs) > 0:
                    self.__observers[k] = obs
                else:
                    # FIXME: call Settings.clean_on_change() if we go down to 0
                    # observers on a key.
                    del self.__observers[k]

    # def get(self, *args, **dargs):  # name, default=None, error=True, force=False):
    #     if len(args) > 1:
    #         return self.get_default(*args, **dargs)
    #
    #     # Temporary name fix for when we're given a setting name with the prefix
    #     if args[0].startswith(self.__prefix):
    #         name = args[0]
    #         debug(debugSettings, 'Setting name has lldb prefix: %s' % name)
    #         import traceback
    #         traceback.print_stack()
    #     else:
    #         # Final code should be:
    #         name = self.__prefix + args[0]
    #
    #     if not ('force' in dargs and dargs[force]) and name in self.__values:
    #         return self.__values[name]
    #
    #     setting = None
    #     # Is this test needed or do we always have an active window and view
    #     if sublime.active_window() and sublime.active_window().active_view():
    #         setting = sublime.active_window().active_view().settings().get(name)
    #     setting = setting or self.__settings.get(name)
    #
    #     self.__values[name] = setting
    #     if name not in self.__settings_keys:
    #         self.__settings_keys.append(name)
    #         listener = self.create_listener(name)
    #         self.__settings.add_on_change(name, listener.on_change)
    #
    #     debug(debugSettings, 'setting %s: %s' % (name, repr(setting)))
    #     return setting

    def get_default(self, name, default, force=False):
        # Temporary name fix for when we're given a setting name with the prefix
        # In the future, this test will be gone and no setting will have
        # the 'lldb.' prefix
        if not name.startswith(self.__prefix):
            # Final code should be:
            name = self.__prefix + name
        else:
            debug(debugAny, 'Setting name has lldb prefix: %s' % name)
            import traceback
            traceback.print_stack()

        if not force and name in self.__values:
            return self.__values[name]

        setting = default

        if sublime.active_window() and sublime.active_window().active_view():
            setting = sublime.active_window().active_view().settings().get(name, default)

        if setting is default:
            setting = self.__settings.get(name, default)

        # Cache the setting value and setup a listener
        self.__values[name] = setting
        if name not in self.__settings_keys:
            self.__settings_keys.append(name)
            listener = self.create_listener(name)
            self.__settings.add_on_change(name, listener.on_change)

        debug(debugSettings, 'setting %s: %s' % (name, repr(setting)))
        return setting

    def on_change(self, key):
        if key in self.__settings_keys and key in self.__observers:
            # if key in self.__settings_keys => key in self.__values
            old_value = self.__values[key]
            obs = self.__observers[key]

            key = key[len(self.__prefix):]
            new_value = self.get_default(key, old_value, force=True)

            if old_value != new_value:
                debug(debugSettings, 'Triggering on_change observers for: ' + key)
                for o in obs:
                    o(key, old_value, new_value)


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
