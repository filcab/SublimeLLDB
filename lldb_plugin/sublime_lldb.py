# -*- mode: python; coding: utf-8 -*-

import sublime
import sublime_plugin

import os
import sys
import atexit
import datetime
import threading

from root_objects import lldb_instance, set_lldb_instance, \
                         lldb_out_view, set_lldb_out_view, \
                         lldb_view_write
from monitors import launch_i_o_monitor, \
                     launch_markers_monitor, lldb_file_markers_queue
# import this specific name without the prefix
from lldb_wrappers import LldbWrapper
import lldb_wrappers


# import traceback
def debug_thr():
    1 + 1
    # print ('thread id: ' + threading.current_thread().name)
    # traceback.print_stack()


def debug(str):
    print str


def debugif(b, str):
    if b:
        debug(str)


def initialize_plugin():
    debug('Loading LLDB Sublime Text 2 plugin')
    debug('python version: %s' % (sys.version_info,))
    debug('cwd: %s' % os.getcwd())


def debug_prologue(lldb):
    """
    Prologue for the debugging session during the development of the plugin.
    Loads a simple program in the debugger and sets a breakpoint in main()
    """
    debug('lldb prologue')
    lldb_view_write('(lldb) target create ~/dev/softek/lldb-plugin/tests\n')
    lldb.interpret_command('target create ~/dev/softek/lldb-plugin/tests')
    lldb_view_write('(lldb) b main\n')
    lldb.interpret_command('b main')
    debug('ended lldb prologue')


def lldb_greeting():
    return datetime.date.today().__str__() + \
           '\nWelcome to the LLDB plugin for Sublime Text 2\n'


lldb_view_name = 'lldb i/o'
lldb_prog_view_name = 'program i/o'
lldb_prompt = '(lldb) '

# lldb_instance = None
# lldb_out_view = None
lldb_prog_view = None
lldb_prog_input = None
lldb_prog_output = None
lldb_prog_error = None
lldb_debugger_pipe_in = None
lldb_debugger_pipe_out = None
lldb_debugger_pipe_err = None
window_ref = None  # For the 'on_done' panel helper
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


def good_lldb_layout(window=window_ref):
    # if the user already has two groups, it's a good layout
    return window.num_groups() == 2


def set_lldb_window_layout(window=window_ref):
    if lldb_out_view() != None and window.num_groups() != 2:
        window.run_command('set_layout', lldb_window_layout)


def set_regular_window_layout(window=window_ref):
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
            debug('showing lldb i/o, show=true')
            set_lldb_window_layout(window=window)
            window.set_view_index(v, 1, 0)
        elif hide:
            debug('hiding lldb i/o, hide=true')
            set_regular_window_layout(window=window)
        elif not good_lldb_layout(window=window):
            debug('showing lldb i/o, not good layout')
            set_lldb_window_layout(window=window)
            window.set_view_index(v, 1, 0)
        else:
            debug('hiding lldb i/o, good layout')
            set_regular_window_layout(window=window)


def lldb_in_panel_on_done(cmd):
    debug_thr()

    # global prompt

    lldb_view_write(lldb_prompt + cmd + '\n')

    result, r = lldb_instance().interpret_command(cmd)
    err_str = result.error()
    out_str = result.output()

    lldb_view_write(out_str)

    if len(err_str) != 0:
        err_str.replace('\n', '\nerr> ')
        err_str = 'err> ' + err_str
        lldb_view_write(err_str)

    # We don't have a window, so let's re-use the one active on lldb launch
    lldb_toggle_output_view(window_ref, show=True)

    v = lldb_out_view()
    v.show_at_center(v.size() + 1)

    if r.is_quit():
        cleanup(window_ref)
    else:
        update_markers(window_ref, after=lambda:
            window_ref.show_input_panel('lldb', '',
                                        lldb_in_panel_on_done, None, None))


def update_markers(window, after=None):
    lldb_file_markers_queue.put({ 'marks': 'all', 'window': window, 'after': after })


@atexit.register
def atexit_function():
    debug('running atexit_function')
    cleanup(window_ref)


def unload_handler():
    debug('unloading lldb plugin')
    cleanup(window_ref)


def cleanup(window):
    debug('cleaning up the lldb plugin')

    update_markers(window)  # markers will be removed
    lldb_wrappers.terminate()
    set_lldb_instance(None)


def initialize_lldb():
    lldb = LldbWrapper()
    # For now, we'll use sync mode
    lldb.set_async(False)

    return lldb


class WindowCommand(sublime_plugin.WindowCommand):
    def setup(self):
        debug_thr()

        # global lldb_out_view
        if lldb_out_view() is None:
            set_lldb_out_view(get_lldb_output_view(self.window, lldb_view_name))  # for lldb output


class LldbCommand(WindowCommand):
    def run(self):
        self.setup()

        global lldb_view_name
        global window_ref
        global lldb_debugger_pipe_in
        global lldb_debugger_pipe_out
        global lldb_debugger_pipe_err

        if lldb_instance() is None:
            debug('Creating an SBDebugger instance.')
            set_lldb_instance(initialize_lldb())
            window_ref = self.window

            g = lldb_greeting()
            if lldb_out_view().size() > 0:
                g = '\n\n' + lldb_greeting()
            lldb_view_write(g)
            lldb_view_write('cwd: ' + os.getcwd() + '\n')

            # We also need to change the width upon window resize
            # debugger.SetTerminalWidth()

            # Setup the input, output, and error file descriptors
            # for the debugger
            # pipe_in, lldb_debugger_pipe_in = os.pipe()
            # lldb_debugger_pipe_out, pipe_out = os.pipe()
            # lldb_debugger_pipe_err, pipe_err = os.pipe()
            # print 'lldb: ended pipes'
            # lldb_debugger_pipe_in = os.fdopen(lldb_debugger_pipe_in, 'w')
            # lldb_debugger_pipe_out = os.fdopen(lldb_debugger_pipe_out, 'r')
            # lldb_debugger_pipe_err = os.fdopen(lldb_debugger_pipe_err, 'r')
            # print 'lldb: setting file handles'
            # lldb_instance.SetInputFileHandle(os.fdopen(pipe_in, 'r'), False)
            # lldb_instance.SetOutputFileHandle(os.fdopen(pipe_out, 'w'), False)
            # lldb_instance.SetErrorFileHandle(os.fdopen(pipe_err, 'w'), False)

            launch_i_o_monitor()
            launch_markers_monitor()

            if lldb_out_view() is None:
                debug('uh oh, starting lldb and the i/o view is not ready!')
            self.window.set_view_index(lldb_out_view(), 1, 0)

            debug_prologue(lldb_instance())

        # last args: on_done, on_change, on_cancel.
        # On change we could try to complete the input using a quick_panel.
        self.window.show_input_panel('lldb', '',
                                     lldb_in_panel_on_done, None, None)


class LldbToggleOutputView(WindowCommand):
    def run(self):
        self.setup()

        if good_lldb_layout(window=self.window) and basic_layout != None:
            # restore backup_layout (groups and views)
            lldb_toggle_output_view(self.window, hide=True)
        else:
            lldb_toggle_output_view(self.window, show=True)


class LldbClearOutputView(WindowCommand):
    def run(self):
        self.setup()

        v = lldb_out_view()
        v.set_read_only(False)
        edit = v.begin_edit('lldb-view-clear')
        v.erase(edit, sublime.Region(0, v.size()))
        v.end_edit(edit)
        v.set_read_only(True)
        v.show(v.size())


# class LldbNext(sublime_plugin.WindowCommand):
#     def run(self):
#         debugger.

initialize_plugin()
