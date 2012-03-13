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
                         get_lldb_output_view, lldb_view_name, lldb_prompt

from monitors import start_markers_monitor, stop_markers_monitor


# import this specific names without the prefix
from lldb_wrappers import LldbDriver, interpret_command, START_LLDB_TIMEOUT
import lldb_wrappers

__is_debugging = False
__os_not_supported = False
__macosx_is_too_old = False
__use_bundled_debugserver = False
__did_not_find_debugserver = False


def debug_thr(string=None):
    if string:
        print ('thread id: ' + threading.current_thread().name + ' ' + string)
    else:
        print ('thread id: ' + threading.current_thread().name)


def debug(str):
    print str


def initialize_plugin():
    thread_created('<' + threading.current_thread().name + '>')
    debug('Loading LLDB Sublime Text 2 plugin')
    debug('python version: %s' % (sys.version_info,))
    debug('cwd: %s' % os.getcwd())

    if not __use_bundled_debugserver:
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
                    global __did_not_find_debugserver
                    __did_not_find_debugserver = True
            else:  # Snow Leopard, etc...
                # This will only work with XCode 4+ (that includes lldb) which is a paid software for OS X < 10.7
                # I suppose most people with Snow Leopard won't have it.
                # This boolean will be used when trying to initialize lldb.
                global __macosx_is_too_old
                __macosx_is_too_old = True
        else:
            global __os_not_supported
            __os_not_supported = True


def debug_prologue(driver):
    """
    Prologue for the debugging session during the development of the plugin.
    Loads a simple program in the debugger and sets a breakpoint in main()
    """
    debugger = driver.debugger
    lldb_view_write('(lldb) target create ~/dev/softek/lldb-plugin/tests\n')
    interpret_command(debugger, 'target create ~/dev/softek/lldb-plugin/tests')
    lldb_view_write('(lldb) b main\n')
    interpret_command(debugger, 'b main')


def lldb_greeting():
    return datetime.date.today().__str__() +                        \
           '\nWelcome to the LLDB plugin for Sublime Text 2\n' +    \
           lldb_wrappers.version() + '\n'


lldb_window_layout = {
                        "cols": [0.0, 1.0],  # start, end
                        "rows": [0.0, 0.75, 1.0],  # start1, start2, end
                        "cells": [[0, 0, 1, 1], [0, 1, 1, 2]]
                     }
basic_layout = {  # 1 group
                    "cols": [0.0, 1.0],
                    "rows": [0.0, 1.0],
                    "cells": [[0, 0, 1, 1]]
               }


def good_lldb_layout(window=window_ref()):
    # if the user already has two groups, it's a good layout
    return window.num_groups() == 2


def set_lldb_window_layout(window=window_ref()):
    if lldb_out_view() != None and window.num_groups() != 2:
        window.run_command('set_layout', lldb_window_layout)


def set_regular_window_layout(window=window_ref()):
    window.run_command("set_layout", basic_layout)


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
        if show:
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
        lldb_view_write(lldb_prompt + cmd + '\n')
        driver_instance().send_command(cmd)

        # We don't have a window, so let's re-use the one active on lldb launch
        lldb_toggle_output_view(window_ref(), show=True)

        v = lldb_out_view()
        v.show_at_center(v.size() + 1)

        show_lldb_panel()


def cleanup(w=None):
    global __is_debugging
    __is_debugging = False

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
    global __is_debugging
    if __is_debugging:
        cleanup(window_ref())

    # Check for error conditions before starting the debugger
    if __did_not_find_debugserver:
        sublime.error_message("Couldn't find the debugserver binary.\n" +  \
                    'Is XCode.app or the command line tools installed?')
        return False
    if __macosx_is_too_old:
        sublime.error_message('Your Mac OS X version is not supported.\n' +  \
                    'Supported versions: Lion and more recent\n\n' +        \
                    'If you think it should be supported, please contact the author.')
        return False
    if __os_not_supported:
        sublime.error_message('Your operating system is not supported by this plugin yet.\n' +          \
                    'If there is a stable version of lldb for your operating system and you would ' +   \
                    'like to have the plugin support it, please contact the author.')
        return False

    __is_debugging = True

    # Really start the debugger
    initialize_lldb()

    driver_instance().debugger.SetInputFileHandle(sys.__stdin__, False)
    start_markers_monitor(window_ref(), driver_instance())

    # We may also need to change the width upon window resize
    # debugger.SetTerminalWidth()
    return True


class WindowCommand(sublime_plugin.WindowCommand):
    def setup(self):
        debug_thr('starting command')

        # global lldb_out_view
        if lldb_out_view() is None:
            set_lldb_out_view(get_lldb_output_view(self.window, lldb_view_name))  # for lldb output


class LldbCommand(WindowCommand):
    def run(self):
        self.setup()

        if driver_instance() is None:
            # if should_clear_lldb_view:
            clear_lldb_out_view()
            set_window_ref(self.window)

            if not start_debugging():
                return

            g = lldb_greeting()
            if lldb_out_view().size() > 0:
                g = '\n\n' + lldb_greeting()
            lldb_view_write(g)
            lldb_view_write('cwd: ' + os.getcwd() + '\n')
            self.window.set_view_index(lldb_out_view(), 1, 0)

            debug_prologue(driver_instance())

        show_lldb_panel(self.window)


class LldbToggleOutputView(WindowCommand):
    def run(self):
        self.setup()

        # debug('layout: ' + str(good_lldb_layout(window=self.window)))
        if good_lldb_layout(window=self.window) and basic_layout != None:
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


initialize_plugin()
