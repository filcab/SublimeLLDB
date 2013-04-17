# -*- mode: python; coding: utf-8 -*-

import sublime

from debug import debug, debugRoot
from utilities import SettingsManager

default_lldb_view_name = 'lldb i/o'
__lldb_prompt = '(lldb) '
__lldb_register_view_fmt = 'registers for thread #%d'
__lldb_variable_view_fmt = 'variables for thread #%d'
__lldb_disassembly_view__unkown_addr_fmt = 'disassembly at 0x%x'
__lldb_disassembly_view_fmt = 'disassembly at %s@0x%x'
__lldb_thread_disassembly_view_fmt = 'disassembly of TID 0x%x'

__driver = None
__ui_updater = None
__out_view = None
__got_input_function = None
__window_ref = None
__breakpoint_dict = {}
_disabled_bps = []
__lldb_views = []

__input_fh = None
__output_fh = None
__error_fh = None


def ui_updater():
    return __ui_updater


def set_ui_updater(ui_updater):
    global __ui_updater
    __ui_updater = ui_updater


def lldb_prompt():
    return __lldb_prompt


def lldb_register_view_name(thread):
    return __lldb_register_view_fmt % thread.GetThreadID()


def lldb_variable_view_name(thread):
    return __lldb_variable_view_fmt % thread.GetThreadID()


def lldb_disassembly_view_name(arg):
    if type(arg) is int:
        # We have a thread ID
        return __lldb_thread_disassembly_view_fmt % (arg,)

    frame = arg
    if not frame:
        return ''

    target = frame.GetThread().GetProcess().GetTarget()
    pc = frame.GetPCAddress()
    function = pc.GetFunction()
    symbol = function.GetName()
    start_addr = function.GetStartAddress()
    if start_addr.IsValid():
        addr = start_addr.GetLoadAddress(target)
    else:
        addr = pc.GetLoadAddress(target)
        return __lldb_disassembly_view__unkown_addr_fmt % (addr,)
    return __lldb_disassembly_view_fmt % (symbol, addr)


def breakpoint_dict():
    return __breakpoint_dict


def reset_breakpoint_dict():
    global __breakpoint_dict
    __breakpoint_dict = {}


def add_bp_loc(filename, line):
    bps = __breakpoint_dict
    if not filename in bps:
        bps[filename] = []

    bps_file = bps[filename]

    for (l, n) in bps_file:
        if l == line:
            bps_file.remove((l, n))
            bps_file.append((l, n + 1))
            return False

    bps_file.append((line, 1))
    return True


def del_bp_loc(filename, line):
    bps = __breakpoint_dict
    if not filename in bps:
        bps[filename] = []

    bps_file = bps[filename]
    for (l, n) in bps_file:
        if l == line:
            bps_file.remove((l, n))
            if n == 1:
                if len(bps_file) == 0:
                    del bps[filename]
                return True
            else:
                bps_file.append((l, n - 1))
                return False
    debug(debugRoot, 'Error: asked to remove a non-existing breakpoint?')
    debug(debugRoot, 'filename: %s, line: %d' % (filename, line))
    debug(debugRoot, __breakpoint_dict)
    return False


def bps_for_file(filename):
    if filename in __breakpoint_dict:
        return map(lambda (x, y): x, __breakpoint_dict[filename])
    else:
        return []


def window_ref():
    return __window_ref


def set_window_ref(w):
    global __window_ref
    __window_ref = w


def set_got_input_function(f):
    global __got_input_function
    __got_input_function = f


def got_input_function():
    return __got_input_function


def lldb_input_fh():
    return __input_fh


def lldb_output_fh():
    return __output_fh


def lldb_error_fh():
    return __error_fh


def set_lldb_input_fh(input):
    global __input_fh
    __input_fh = input


def set_lldb_output_fh(output):
    global __output_fh
    __output_fh = output


def set_lldb_error_fh(error):
    global __error_fh
    __error_fh = error


def driver_instance():
    return __driver


def set_driver_instance(d):
    global __driver
    __driver = d


def lldb_out_view():
    return __out_view


def set_lldb_out_view(v):
    global __out_view
    __out_view = v


def lldb_view_send(string):
    sublime.set_timeout(lambda: lldb_view_write(string), 0)


def lldb_view_write(string):
    global __out_view, __window_ref
    if not (__out_view and __window_ref and __out_view.window()):
        sm = SettingsManager.getSM()
        name = sm.get_default('i/o.view.name', default_lldb_view_name)

        __out_view = get_lldb_output_view(__window_ref, name)
        if not __window_ref:
            # Bail out and just set the first window
            __window_ref = sublime.windows()[0]

        # __window_ref.set_view_index(__out_view, 1, 0)

    __out_view.set_read_only(False)
    edit = __out_view.begin_edit('lldb-panel-write')
    __out_view.insert(edit, __out_view.size(), string)
    __out_view.end_edit(edit)
    __out_view.set_read_only(True)
    __out_view.show(__out_view.size())


def maybe_get_lldb_output_view(window, name):
    f = None

    for v in __lldb_views:
        if v.name() == name or v.file_name() == name:
            return v

    if window:
        for v in window.views():
            if v.name() == name:
                return v

    return f


def add_lldb_view(v):
    # This is leaking. Check if Sublime Text 2 tells us when our window is
    # closed.
    __lldb_views.append(v)


def del_lldb_view(v):
    debug(debugRoot, 'Removing %s from lldb_views.' % str(v))
    __lldb_views.remove(v)


def lldb_views():
    # Return a copy of the list
    return list(__lldb_views)


def lldb_views_update(epilogue):
    debug(debugRoot, 'lldb_views_update')
    for v in __lldb_views:
        v.pre_update()

    def updater():
        for v in __lldb_views:
            v.update()
        epilogue()
    sublime.set_timeout(updater, 0)


def lldb_views_destroy():
    global __lldb_views
    views = __lldb_views
    __lldb_views = []

    def stop_visitor(thing):
        thing.stop()
    map(stop_visitor, views)


def get_lldb_view_for(v):
    debug(debugRoot, 'lldb_views: %s' % repr(__lldb_views))
    name = v.name()
    file_name = v.file_name()
    for lldb_view in __lldb_views:
        if (name is not None and len(name) > 0 and name == lldb_view.name()) \
            or (file_name is not None and len(file_name) > 0 and file_name == lldb_view.file_name()):
            return lldb_view
    return None


def get_lldb_output_view(window, name=None):
    # Search for the lldb_view view first.
    if not name:
        sm = SettingsManager.getSM()
        name = sm.get_default('i/o.view.name', default_lldb_view_name)

    f = maybe_get_lldb_output_view(window, name)
    if f is None:
        f = window.new_file()
        f.set_name(name)

    f.set_scratch(True)
    f.set_read_only(True)
    # f.set_syntax_file('…')  # lldb output syntax
    return f


def disabled_bps():
    return _disabled_bps


def set_disabled_bps(bps):
    global _disabled_bps
    _disabled_bps = bps


__settings_keys = ['lldb.prologue',
                   'lldb.use_bundled_debugserver',
                   'lldb.i/o.view.name',
                   'lldb.i/o.view.clear_on_startup',
                   'lldb.layout',
                   'lldb.layout.basic',
                   'lldb.layout.group.source_file',
                   'lldb.layout.group.i/o',
                   'lldb.markers.current_line.region_name',
                   'lldb.markers.current_line.scope',
                   'lldb.markers.current_line.scope.crashed',
                   'lldb.markers.current_line.type',
                   'lldb.markers.breakpoint.enabled.region_name',
                   'lldb.markers.breakpoint.enabled.scope',
                   'lldb.markers.breakpoint.enabled.type',
                   'lldb.markers.breakpoint.disabled.region_name',
                   'lldb.markers.breakpoint.disabled.scope',
                   'lldb.markers.breakpoint.disabled.type',
                   'lldb.exe',
                   'lldb.args',
                   'lldb.arch',
                   'lldb.breakpoints',
                   'lldb.view.memory.size',
                   'lldb.view.memory.width',
                   'lldb.view.memory.grouping',
                   'lldb.layout.group.source_file',
                   'lldb.attach.wait_for_launch']


def get_settings_keys():
    return __settings_keys


class InputPanelDelegate(object):
    def show_on_window(self, window, title='', initial_text=''):
        # Make sure we save the window we're passed.
        self.window = window
        sublime.set_timeout(lambda: window.show_input_panel(title, initial_text,
            self.on_done, self.on_change, self.on_cancel), 0)

    def on_done(self, string):
        pass

    def on_change(self, string):
        pass

    def on_cancel(self):
        pass


class LldbInputDelegate(InputPanelDelegate):
    _lldb_input_panel_is_active = False

    @staticmethod
    def get_input(window=None, title='lldb', *args):
        if window is None:
            window = window_ref()

        # Don't show the panel if we're running a process
        # if not LldbInputDelegate._lldb_input_panel_is_active:
        LldbInputDelegate().show_on_window(window, title, *args)

    def show_on_window(self, window, *args):
        LldbInputDelegate._lldb_input_panel_is_active = True
        super(LldbInputDelegate, self).show_on_window(window, *args)

    def on_done(self, cmd):
        LldbInputDelegate._lldb_input_panel_is_active = False
        # global prompt
        if cmd is None:
            cmd = ''

        if driver_instance():
            lldb_view_write(lldb_prompt() + cmd + '\n')
            driver_instance().send_input(cmd)

            # We don't have a window, so let's re-use the one active on lldb launch
            # lldb_toggle_output_view(window_ref(), show=True)

            v = lldb_out_view()
            v.show_at_center(v.size() + 1)

    def on_cancel(self):
        LldbInputDelegate._lldb_input_panel_is_active = False
        debug(debugRoot, 'canceled input panel')
