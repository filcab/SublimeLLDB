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
                         show_lldb_panel, set_got_input_function
                         # lldb_input_fh,  set_lldb_input_fh,     \
                         # lldb_output_fh, set_lldb_output_fh,    \
                         # lldb_error_fh,  set_lldb_error_fh,     \

# from monitors import cleanup


# import this specific name without the prefix
from lldb_wrappers import LldbDriver, interpret_command, START_LLDB_TIMEOUT
import lldb_wrappers


# import traceback
def debug_thr(string=None):
    if string:
        print ('thread id: ' + threading.current_thread().name + ' ' + string)
    else:
        print ('thread id: ' + threading.current_thread().name)


def debug(str):
    print str


def debugif(b, str):
    if b:
        debug(str)


def initialize_plugin():
    thread_created('<' + threading.current_thread().name + '>')
    debug('Loading LLDB Sublime Text 2 plugin')
    debug('python version: %s' % (sys.version_info,))
    debug('cwd: %s' % os.getcwd())


def debug_prologue(driver):
    """
    Prologue for the debugging session during the development of the plugin.
    Loads a simple program in the debugger and sets a breakpoint in main()
    """
    debug('lldb prologue')
    debugger = driver.debugger
    lldb_view_write('(lldb) log enable -v lldb thread unwind\n')
    interpret_command(debugger, 'log enable lldb thread unwind')
    lldb_view_write('(lldb) log enable -v gdb-remote thread\n')
    interpret_command(debugger, 'log enable gdb-remote thread')
    lldb_view_write('(lldb) target create ~/dev/softek/lldb-plugin/tests\n')
    interpret_command(debugger, 'target create ~/dev/softek/lldb-plugin/tests')
    lldb_view_write('(lldb) b main\n')
    interpret_command(debugger, 'b main')
    debug('ended lldb prologue')


def lldb_greeting():
    return datetime.date.today().__str__() + \
           '\nWelcome to the LLDB plugin for Sublime Text 2\n' + \
           lldb_wrappers.version() + '\n'


lldb_view_name = 'lldb i/o'
lldb_prog_view_name = 'program i/o'
lldb_prompt = '(lldb) '

# driver_instance = None
# lldb_out_view = None

# To hold on to the pipes. Otherwise GC takes them
# pipe_in = None
# pipe_out = None
# pipe_err = None

broadcaster = None

lldb_prog_view = None
lldb_prog_input = None
lldb_prog_output = None
lldb_prog_error = None
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
# backup_layout = None


def good_lldb_layout(window=window_ref()):
    # if the user already has two groups, it's a good layout
    return window.num_groups() == 2


def set_lldb_window_layout(window=window_ref()):
    if lldb_out_view() != None and window.num_groups() != 2:
        window.run_command('set_layout', lldb_window_layout)


def set_regular_window_layout(window=window_ref()):
    window.run_command("set_layout", basic_layout)


def get_lldb_output_view(window, name):
    # Search for the lldb_view view first.
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
    debug('clearing view: ' + repr(v))
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

    driver = LldbDriver()
    driver.start()

    # ESPERAR QUE ESTEJA TUDO INICIALIZADO!
    event = lldb.SBEvent()
    listener = lldb.SBListener('Wait for lldb initialization')
    listener.WaitForEventForBroadcasterWithType(START_LLDB_TIMEOUT,
                driver.broadcaster,
                LldbDriver.eBroadcastBitThreadDidStart,
                event)

    if not event:
        lldb_view_write("oops... the event isn't valid")

    # Warn whoever started us that we can start working
    driver.broadcaster.BroadcastEventByType(LldbDriver.eBroadcastBitThreadDidStart)
    return driver


def start_debugging():
    cleanup(window_ref())

    # Really start the debugger
    initialize_lldb()
    debug('setting file handles')
    # lldb_.SetInputFileHandle(sys.__stdin__, False)
    # lldb_.SetErrorFileHandle(sys.__stderr__, False)
    # lldb_.SetOutputFileHandle(sys.__stdout__, False)

    # launch_i_o_monitor(broadcaster)

    # We may also need to change the width upon window resize
    # debugger.SetTerminalWidth()

    # Setup the input, output, and error file descriptors
    # for the debugger
    # global pipe_in, pipe_out, pipe_err

    # pipe_in, lldb_debugger_pipe_in = os.pipe()
    # lldb_debugger_pipe_out, pipe_out = os.pipe()
    # lldb_debugger_pipe_err, pipe_err = os.pipe()
    # debug('in: %d, %d' % (pipe_in, lldb_debugger_pipe_in))
    # debug('out: %d, %d' % (lldb_debugger_pipe_out, pipe_out))
    # debug('err: %d, %d' % (lldb_debugger_pipe_err, pipe_err))

    # pipe_in = os.fdopen(pipe_in, 'r', 0)
    # set_lldb_input_fh(os.fdopen(lldb_debugger_pipe_in, 'w', 0))
    # set_lldb_output_fh(os.fdopen(lldb_debugger_pipe_out, 'r', 0))
    # pipe_out = os.fdopen(pipe_out, 'w', 0)
    # set_lldb_error_fh(os.fdopen(lldb_debugger_pipe_err, 'r', 0))
    # pipe_err = os.fdopen(pipe_err, 'w', 0)

    # debug('in: %s, %s' % (str(pipe_in), str(lldb_debugger_pipe_in)))
    # debug('out: %s, %s' % (str(lldb_debugger_pipe_out), str(pipe_out)))
    # debug('err: %s, %s' % (str(lldb_debugger_pipe_err), str(pipe_err)))

    # driver_instance().SetInputFileHandle(pipe_in, True)
    # driver_instance().SetOutputFileHandle(pipe_out, True)
    # driver_instance().SetErrorFileHandle(pipe_err, True)


class WindowCommand(sublime_plugin.WindowCommand):
    def setup(self):
        debug_thr('starting')

        # global lldb_out_view
        if lldb_out_view() is None:
            set_lldb_out_view(get_lldb_output_view(self.window, lldb_view_name))  # for lldb output


class LldbCommand(WindowCommand):
    def run(self):
        self.setup()

        global lldb_view_name

        if driver_instance() is None:
            # if should_clear_lldb_view:
            clear_lldb_out_view()
            set_window_ref(self.window)

            start_debugging()
            debug('Creating an SBDebugger instance.')

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

        debug('layout: ' + str(good_lldb_layout(window=self.window)))
        if good_lldb_layout(window=self.window) and basic_layout != None:
            # restore backup_layout (groups and views)
            lldb_toggle_output_view(self.window, hide=True)
        else:
            lldb_toggle_output_view(self.window, show=True)


class LldbClearOutputView(WindowCommand):
    def run(self):
        self.setup()
        debug('clearing lldb view')

        clear_lldb_out_view()

# class LldbNext(sublime_plugin.WindowCommand):
#     def run(self):
#         debugger.

initialize_plugin()
