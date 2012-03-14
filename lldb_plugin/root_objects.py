# -*- mode: python; coding: utf-8 -*-

import sublime

lldb_view_name = 'lldb i/o'
lldb_prompt = '(lldb) '

__driver = None
__out_view = None
__got_input_function = None
__window_ref = None
__breakpoint_dict = {}

__input_fh = None
__output_fh = None
__error_fh = None


def debug(string):
    print string


def set_lldb_view_name(name):
    global lldb_view_name
    lldb_view_name = name


def breakpoint_dict():
    return __breakpoint_dict


def reset_breakpoint_dict():
    global __breakpoint_dict
    __breakpoint_dict = {}


def add_bp_loc(filename, line):
    debug('add_bp_loc filename="%s", line=%d"' % (filename, line))
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
    debug('Error: asked to remove a non-existing breakpoint?')
    debug('filename: %s, line: %d' % (filename, line))
    debug(__breakpoint_dict)
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


def show_lldb_panel(w=None):
    if not w:
        w = window_ref()
    # last args: on_done, on_change, on_cancel.
    # On change we could try to complete the input using a quick_panel.
    if w:
        w.show_input_panel('lldb', '',
                            __got_input_function, None, None),


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
        __out_view = get_lldb_output_view(__window_ref, lldb_view_name)
        if not __window_ref:
            # Bail out and just set the first window
            __window_ref = sublime.windows()[0]

        __window_ref.set_view_index(__out_view, 1, 0)

    __out_view.set_read_only(False)
    edit = __out_view.begin_edit('lldb-panel-write')
    __out_view.insert(edit, __out_view.size(), string)
    __out_view.end_edit(edit)
    __out_view.set_read_only(True)
    __out_view.show(__out_view.size())


def get_lldb_output_view(window, name=None):
    # Search for the lldb_view view first.
    if not name:
        name = lldb_view_name

    f = None
    for v in window.views():
        if v.name() == name:
            f = v
            break

    if f is None:
        f = window.new_file()
        f.set_name(name)

    f.set_scratch(True)
    f.set_read_only(True)
    # f.set_syntax_file('…')  # lldb output syntax
    return f

__settings_keys = ["lldb.prologue",
                   "lldb.use_bundled_debugserver"
                   "lldb.i/o.view.name"
                   "lldb.i/o.view.clear_on_startup"
                   "lldb.layout"
                   "lldb.layout.basic"
                   "lldb.layout.group.source_file"
                   "lldb.layout.group.i/o"
                   "lldb.markers.current_line.region_name"
                   "lldb.markers.current_line.scope"
                   "lldb.markers.current_line.scope.crashed"
                   "lldb.markers.current_line.type"
                   "lldb.markers.breakpoint.region_name"
                   "lldb.markers.breakpoint.scope"
                   "lldb.markers.breakpoint.type"]


def get_settings_keys():
    return __settings_keys


import lldb_wrappers

thread_created = lldb_wrappers.thread_created
