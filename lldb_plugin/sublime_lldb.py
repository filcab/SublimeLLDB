# -*- mode: python; coding: utf-8 -*-

import sublime
import sublime_plugin

import os
import sys
import atexit
import datetime
import threading

import lldb

from root_objects import driver_instance, set_driver_instance,          \
                         lldb_out_view, set_lldb_out_view,              \
                         lldb_view_write, lldb_view_send,               \
                         thread_created, window_ref, set_window_ref,    \
                         show_lldb_panel, set_got_input_function,       \
                         get_lldb_output_view, lldb_prompt,             \
                         lldb_view_name, set_lldb_view_name,            \
                         get_settings_keys

from monitors import start_markers_monitor, stop_markers_monitor


# import this specific names without the prefix
from lldb_wrappers import LldbDriver, interpret_command, START_LLDB_TIMEOUT
import lldb_wrappers

_settings = None
# _setting_prefix = 'lldb.'
_setting_prefix = ''
_initialized = False
_is_debugging = False
_os_not_supported = False
_macosx_is_too_old = False
_use_bundled_debugserver = False
_did_not_find_debugserver = False
_clear_view_on_startup = True
_lldb_window_layout = {
                        "cols": [0.0, 1.0],  # start, end
                        "rows": [0.0, 0.75, 1.0],  # start1, start2, end
                        "cells": [[0, 0, 1, 1], [0, 1, 1, 2]]
                       }
_basic_layout = {  # 1 group
                    "cols": [0.0, 1.0],
                    "rows": [0.0, 1.0],
                    "cells": [[0, 0, 1, 1]]
                 }
_default_exe = None
_default_bps = []
_default_args = []
_default_arch = lldb.LLDB_ARCH_DEFAULT
_prologue = []


def debug_thr(string=None):
    if string:
        print ('thread id: ' + threading.current_thread().name + ' ' + string)
    else:
        print ('thread id: ' + threading.current_thread().name)


def debug(str):
    print str


def setup_settings():
    global _settings
    _settings = sublime.load_settings('lldb.sublime-settings')
    for k in get_settings_keys():
        _settings.add_on_change(k, reload_settings)

    # reload_settings()


def get_setting(name):
    setting_name = _setting_prefix + name
    if not _settings:
        setup_settings()

    setting = None
    if sublime.active_window() and sublime.active_window().active_view():
        setting = sublime.active_window().active_view().settings().get(setting_name)

    return setting or _settings.get(setting_name)


def reload_settings():
    debug('reloading settings')

    global _use_bundled_debugserver, _lldb_window_layout, _basic_layout
    global _clear_view_on_startup, _prologue
    global _default_exe, _default_bps, _default_args, _default_arch
    _use_bundled_debugserver = get_setting('lldb.use_bundled_debugserver')
    _lldb_window_layout = get_setting('lldb.layout')
    _basic_layout = get_setting('lldb.layout.basic')
    _clear_view_on_startup = get_setting('lldb.i/o.view.clear_on_startup')
    set_lldb_view_name(get_setting('lldb.i/o.view.name'))
    _prologue = get_setting('lldb.prologue')

    _default_exe = get_setting('lldb.exe')
    _default_args = get_setting('lldb.arch') or []
    _default_arch = get_setting('lldb.arch') or lldb.LLDB_ARCH_DEFAULT
    _default_bps = get_setting('lldb.breakpoints') or []


def initialize_plugin():
    global _initialized
    if _initialized:
        return

    thread_created('<' + threading.current_thread().name + '>')
    debug('Loading LLDB Sublime Text 2 plugin')
    debug('python version: %s' % (sys.version_info,))
    debug('cwd: %s' % os.getcwd())

    setup_settings()
    reload_settings()

    global _use_bundled_debugserver
    if not _use_bundled_debugserver:
        debugserver_paths = ['/Applications/Xcode.app/Contents/SharedFrameworks/LLDB.framework/Versions/A/Resources/debugserver',
                             '/System/Library/PrivateFrameworks/LLDB.framework/Versions/A/Resources/debugserver']
        uname = os.uname()
        if uname[0] == 'Darwin':
            if uname[2] == '11.3.0':  # OS X Lion
                found = False
                for path in debugserver_paths:
                    if os.access(path, os.X_OK):
                        os.environ['LLDB_DEBUGSERVER_PATH'] = path
                        found = True
                        break
                if not found:  # XCode has to be installed
                    global _did_not_find_debugserver
                    _did_not_find_debugserver = True
            else:  # Snow Leopard, etc...
                # This will only work with XCode 4+ (that includes lldb) which is a paid software for OS X < 10.7
                # I suppose most people with Snow Leopard won't have it.
                # This boolean will be used when trying to initialize lldb.
                global _macosx_is_too_old
                _macosx_is_too_old = True
        else:
            global _os_not_supported
            _os_not_supported = True

    _initialized = True


def debug_prologue(driver):
    """
    Prologue for the debugging session during the development of the plugin.
    Loads a simple program in the debugger and sets a breakpoint in main()
    """
    debugger = driver.debugger
    global _prologue
    for c in _prologue:
        lldb_view_write(lldb_prompt() + c + '\n')
        interpret_command(debugger, c)
    # lldb_view_write('(lldb) target create ~/dev/softek/lldb-plugin/tests\n')
    # interpret_command(debugger, 'target create ~/dev/softek/lldb-plugin/tests')
    # lldb_view_write('(lldb) b main\n')
    # interpret_command(debugger, 'b main')


def lldb_greeting():
    return str(datetime.date.today()) +                             \
           '\nWelcome to the LLDB plugin for Sublime Text 2\n' +    \
           lldb_wrappers.version() + '\n'


def good_lldb_layout(window=window_ref()):
    # if the user already has two groups, it's a good layout
    return window.num_groups() == len(_lldb_window_layout['cells'])


def set_lldb_window_layout(window=window_ref()):
    global _lldb_window_layout
    if lldb_out_view() != None and window.num_groups() != len(_lldb_window_layout['cells']):
        window.run_command('set_layout', _lldb_window_layout)


def set_regular_window_layout(window=window_ref()):
    global _basic_layout
    window.run_command('set_layout', _basic_layout)


def lldb_toggle_output_view(window, show=False, hide=False):
    """ Toggles the lldb output view visibility.

            if show=True: force showing the view;
            if hide=True: force hiding the view;
            Otherwise: Toggle view visibility.
    """
    # global lldb_out_view_name
    # TODO: Set the input_panel syntax to 'lldb command'

    # Just show the window.
    v = lldb_out_view()
    if v:
        if show and not good_lldb_layout(window=window):
            set_lldb_window_layout(window=window)
            window.set_view_index(v, 1, 0)
        elif hide:
            set_regular_window_layout(window=window)
        elif not good_lldb_layout(window=window):
            set_lldb_window_layout(window=window)
            window.set_view_index(v, 1, 0)
        else:
            set_regular_window_layout(window=window)


def clear_lldb_out_view():
    v = lldb_out_view()

    v.set_read_only(False)
    edit = v.begin_edit('lldb-view-clear')
    v.erase(edit, sublime.Region(0, v.size()))
    v.end_edit(edit)
    v.set_read_only(True)
    v.show(v.size())


def lldb_in_panel_on_done(cmd):
    debug_thr()

    # global prompt
    if cmd is None:
        cmd = ''

    if driver_instance():
        lldb_view_write(lldb_prompt() + cmd + '\n')
        driver_instance().send_command(cmd)

        # We don't have a window, so let's re-use the one active on lldb launch
        lldb_toggle_output_view(window_ref(), show=True)

        v = lldb_out_view()
        v.show_at_center(v.size() + 1)

        show_lldb_panel()


def cleanup(w=None):
    global _is_debugging
    _is_debugging = False

    stop_markers_monitor()
    driver = driver_instance()
    if driver:
        driver.stop()
        set_driver_instance(None)


@atexit.register
def atexit_function():
    debug('running atexit_function')
    cleanup(window_ref())


def unload_handler():
    debug('unloading lldb plugin')
    cleanup(window_ref())


def initialize_lldb():
    set_got_input_function(lldb_in_panel_on_done)

    driver = LldbDriver(lldb_view_send)
    event = lldb.SBEvent()
    listener = lldb.SBListener('Wait for lldb initialization')
    listener.StartListeningForEvents(driver.broadcaster,
            LldbDriver.eBroadcastBitThreadDidStart)

    driver.start()
    listener.WaitForEvent(START_LLDB_TIMEOUT, event)
    listener.Clear()

    if not event:
        lldb_view_write("oops... the event isn't valid")

    return driver


def start_debugging():
    global _is_debugging
    if _is_debugging:
        cleanup(window_ref())

    initialize_plugin()

    # Check for error conditions before starting the debugger
    global _did_not_find_debugserver, _macosx_is_too_old, _os_not_supported
    if _did_not_find_debugserver:
        sublime.error_message("Couldn't find the debugserver binary.\n" +  \
                    'Is XCode.app or the command line tools installed?')
        return False
    if _macosx_is_too_old:
        sublime.error_message('Your Mac OS X version is not supported.\n' +  \
                    'Supported versions: Lion and more recent\n\n' +        \
                    'If you think it should be supported, please contact the author.')
        return False
    if _os_not_supported:
        sublime.error_message('Your operating system is not supported by this plugin yet.\n' +          \
                    'If there is a stable version of lldb for your operating system and you would ' +   \
                    'like to have the plugin support it, please contact the author.')
        return False

    _is_debugging = True

    # Really start the debugger
    initialize_lldb()

    driver_instance().debugger.SetInputFileHandle(sys.__stdin__, False)
    start_markers_monitor(window_ref(), driver_instance())

    # We may also need to change the width upon window resize
    # debugger.SetTerminalWidth()
    return True


# TODO: Search current directory for a project file or an executable
def search_for_executable():
    return _default_exe


def ensure_lldb_is_running(w=None):
    # Ensure we reflect any changes to saved settings (including project settings)
    reload_settings()

    if not w and window_ref():
        w = window_ref()
    else:
        # We're redefining the default window.
        set_window_ref(w)

    if driver_instance() is None:
        global _clear_view_on_startup
        if _clear_view_on_startup:
            clear_lldb_out_view()

        if not start_debugging():
            return

        g = lldb_greeting()
        if lldb_out_view().size() > 0:
            g = '\n\n' + lldb_greeting()
        lldb_view_write(g)
        lldb_view_write('cwd: ' + os.getcwd() + '\n')
        w.set_view_index(lldb_out_view(), 1, 0)

        debug_prologue(driver_instance())

import re
bp_re_file_line = re.compile('^(.*\S)\s*:\s*(\d+)\s*$')
bp_re_address = re.compile('^(0x[0-9A-Fa-f]+)\s*$')
# bp_re_abbrev = re.compile('^(-.*)$')
bp_re_name = re.compile('^(.*\S)\s*$')
# break_regex_cmd_ap->AddRegexCommand("^(.*\S)`(.*\S)\s*$", "breakpoint set --name '%2' --shlib '%1'") &&


def create_default_bps_for_target(target):
    n = 0
    for bp in _default_bps:
        if type(bp) is str or type(bp) is unicode:
            bp = str(bp)
            m = bp_re_file_line.match(bp)
            if m:
                # debug('breaking at: %s:%d' % (m.group(1), m.group(2)))
                target.BreakpointCreateByLocation(m.group(1), m.group(2))
                ++n
                continue

            m = bp_re_address.match(bp)
            if m:
                # debug('breaking at: %x' % m.group(1))
                target.BreakpointCreateByAddress(m.group(1))
                ++n
                continue

            m = bp_re_name.match(bp)
            if m:
                # debug('breaking at: %s' % m.group(1))
                target.BreakpointCreateByName(m.group(1))
                ++n
                continue

            debug("couldn't tell where the bp spec '" + bp + "' should break.")

        # bp isn't an str. It should be a dict
        elif 'file' in bp and 'line' in bp:
            # debug('breaking at: %s:%d' % (str(bp['file']), bp['line']))
            target.BreakpointCreateByLocation(str(bp['file']), bp['line'])
            ++n
        elif 'address' in bp:
            # debug('breaking at: %x' % bp['address'])
            target.BreakpointCreateByAddress(bp['address'])
            ++n
        else:
            debug('unrecognized breakpoint type: ' + str(bp))
    # debug('%d breakpoints created' % n)


class WindowCommand(sublime_plugin.WindowCommand):
    def setup(self):
        debug_thr('starting command')

        # global lldb_out_view
        if lldb_out_view() is None:
            set_lldb_out_view(get_lldb_output_view(self.window, lldb_view_name()))  # for lldb output


class LldbCommand(WindowCommand):
    def run(self):
        self.setup()
        ensure_lldb_is_running(self.window)
        lldb_toggle_output_view(self.window, show=True)
        show_lldb_panel(self.window)


class LldbDebugProgram(WindowCommand):
    def run(self):
        self.setup()
        ensure_lldb_is_running(self.window)
        lldb_toggle_output_view(self.window, show=True)

        exe = search_for_executable()
        global _default_arch
        arch = _default_arch

        debug('os.getcwd(): ' + os.getcwd())
        if exe:
            debug('Launching program: ' + exe + ' (' + arch + '), with args: ' + str(_default_args))
            t = driver_instance().debugger.CreateTargetWithFileAndArch(str(exe), str(arch))
            debug('got a target: ' + str(t))
            driver_instance().debugger.SetSelectedTarget(t)
            create_default_bps_for_target(t)
            # main_bp = t.BreakpointCreateByName('main', t.GetExecutable().GetFilename())
            # debug('main bp: ' + str(main_bp))
            p = t.LaunchSimple(_default_args, [], os.getcwd())
            debug('got a process: ' + str(p))


class LldbToggleOutputView(WindowCommand):
    def run(self):
        self.setup()

        # debug('layout: ' + str(good_lldb_layout(window=self.window)))
        global _basic_layout
        if good_lldb_layout(window=self.window) and _basic_layout != None:
            # restore backup_layout (groups and views)
            lldb_toggle_output_view(self.window, hide=True)
        else:
            lldb_toggle_output_view(self.window, show=True)


class LldbClearOutputView(WindowCommand):
    def run(self):
        self.setup()
        # debug('clearing lldb view')
        # TODO: Test variable to know if we should clear the view when starting a debug session

        clear_lldb_out_view()
