# -*- mode: python; coding: utf-8 -*-

import sublime
import sublime_plugin

import os
import sys
import select
import atexit
import datetime
import threading

import lldb

def debug(str):
    print str


debug('LLDB Sublime Text 2 plugin')
debug('python version: %s' % (sys.version_info,))
debug('cwd: %s' % os.getcwd())


def lldb_greeting():
    return datetime.date.today().__str__() + \
           '\nWelcome to the LLDB plugin for Sublime Text 2\n'


 # # Create a new debugger instance
lldb_instance = None   # SBDebugger.Create()
lldb_view_name = 'lldb i/o'
lldb_prog_view_name = 'program i/o'
lldb_out_view = None
lldb_prog_view = None
lldb_last_location_view = None
lldb_prog_input = None
lldb_prog_output = None
lldb_prog_error = None
lldb_prompt = '(lldb) '
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
    if lldb_out_view != None and window.num_groups() != 2:
        window.run_command('set_layout', lldb_window_layout)


def set_regular_window_layout(window=window_ref):
    window.run_command("set_layout", basic_layout)


def lldb_toggle_output_view(window, show=False, hide=False):
    """ Toggles the lldb output view visibility.

            if show=True: force showing the view;
            if hide=True: force hiding the view;
            Otherwise: Toggle view visibility.
    """
    global lldb_out_view_name
    # TODO: Set the input_panel syntax to 'lldb command'

    # Just show the window.
    if lldb_out_view:
        if show:
            debug('showing, show=true')
            set_lldb_window_layout(window=window)
            window.set_view_index(lldb_out_view, 1, 0)
        elif hide:
            debug('hiding, hide=true')
            set_regular_window_layout(window=window)
        elif not good_lldb_layout(window=window):
            debug('showing, not good layout')
            set_lldb_window_layout(window=window)
            window.set_view_index(lldb_out_view, 1, 0)
        else:
            debug('hiding, good layout')
            set_regular_window_layout(window=window)


def lldb_i_o_monitor():
    debug('monitor: started')
    while lldb_instance != None:
        lldberr = lldb_instance.GetErrorFileHandle()
        lldbout = lldb_instance.GetOutputFileHandle()

        debug('lldberr: ' + lldberr.__str__())
        debug('lldbout: ' + lldbout.__str__())

        debug('monitor: waiting for select')

        input = []
        if lldbout:
            input.append(lldbout)
        if lldberr:
            input.append(lldberr)

        if len(input) > 0:
            input, output, x = select.select(input, [], [])
        else:
            # We're not waiting for input, set a timeout
            input, output, x = select.select(input, [], [], 1000)

        for h in input:
            str = h.read()
            if h == lldbout:
                sublime.set_timeout(lambda: lldb_view_write(str), 0.01)
            if h == lldberr:
                # We're sure we read something
                str.replace('\n', '\nerr> ')
                str = 'err> ' + str
                sublime.set_timeout(lambda: lldb_view_write(str), 0.01)

    debug('monitor: stopped')


def lldb_in_panel_on_done(cmd):
    global lldb_instance
    global prompt

    lldb_view_write(lldb_prompt + cmd + '\n')
    if cmd == 'q' or cmd == 'quit':
        lldb.SBDebugger.Terminate()
        lldb_instance = None
        return

    result = lldb_instance.interpret_command(cmd)
    err_str = result.GetError()
    out_str = result.GetOutput()

    lldb_view_write(out_str)

    if len(err_str) != 0:
        err_str.replace('\n', '\nerr> ')
        err_str = 'err> ' + err_str
        lldb_view_write(err_str)

    # We don't have a window, so let's re-use the one active on lldb launch
    lldb_toggle_output_view(window_ref, show=True)
    lldb_out_view.show(lldb_out_view.size(), True)

    update_code_view(window_ref)
    window_ref.show_input_panel('lldb', '',
                                lldb_in_panel_on_done, None, None)


def lldb_view_write(string):
    lldb_out_view.set_read_only(False)
    edit = lldb_out_view.begin_edit('lldb-panel-write')
    lldb_out_view.insert(edit, lldb_out_view.size(), string)
    lldb_out_view.end_edit(edit)
    lldb_out_view.set_read_only(True)
    lldb_out_view.show(lldb_out_view.size())


def update_code_view(window):
    line_entry = lldb_instance.current_line_entry()

    if line_entry:
        filespec = line_entry.GetFileSpec()
        if filespec:
            filename = filespec.GetDirectory() + '/' + filespec.GetFilename()

            line = line_entry.GetLine()
            column = line_entry.GetColumn()

            loc = filename + ':' + str(line) + ':' + str(column)
            debug("Location: " + loc)

            window.focus_group(0)
            view = window.open_file(loc, sublime.ENCODED_POSITION)
            window.focus_view(view)

            global lldb_last_location_view
            if lldb_last_location_view:
                lldb_last_location_view.erase_regions("lldb.location")
            lldb_last_location_view = view
            view.add_regions("lldb.location", \
                             [view.full_line(view.text_point(line - 1, column - 1))], \
                             "entity.name.class", "bookmark", \
                             sublime.HIDDEN)
            return

    debug("No location info available")


@atexit.register
def atexit_function():
    debug('running atexit_function')
    cleanup()


def unload_handler():
    debug('unloading lldb plugin')
    cleanup()


def cleanup():
    global lldb_instance
    debug('cleaning up the lldb plugin')

    if lldb_last_location_view:
        lldb_last_location_view.erase_regions("lldb.location")
    lldb.SBDebugger.Terminate()
    lldb_instance = None


def initialize_lldb():
    lldb = LldbWrapper()
    # For now, we'll use sync mode
    lldb.SetAsync(False)

    return lldb


class LldbWrapper(object):
    last_cmd = None
    lldb = None

    def __init__(self):
        self.lldb = lldb.SBDebugger.Create()

    def current_frame(self):
        return self.lldb.GetSelectedTarget().GetProcess() \
                        .GetSelectedThread().GetSelectedFrame()

    def current_line_entry(self):
        return self.current_frame().GetLineEntry()

    def current_sc(self):
        return self.current_frame().GetSymbolContext(0xffffffff)

    def interpret_command(self, cmd):
        if cmd == '':
            cmd = last_cmd
        last_cmd = cmd

        valid_returns = [lldb.eReturnStatusSuccessFinishNoResult,     \
                         lldb.eReturnStatusSuccessFinishResult,       \
                         lldb.eReturnStatusSuccessContinuingNoResult, \
                         lldb.eReturnStatusSuccessContinuingResult,   \
                         lldb.eReturnStatusStarted]

        result = lldb.SBCommandReturnObject()
        ci = self.lldb.GetCommandInterpreter()

        r = ci.HandleCommand(cmd.__str__(), result)
        if r in valid_returns:
            last_cmd = cmd

        return result

    # CamelCase methods are simple bridges to the SBDebugger object
    # def GetCommandInterpreter(self):
    #     return self.lldb.GetCommandInterpreter()

    def GetErrorFileHandle(self):
        return self.lldb.GetErrorFileHandle()

    def GetOutputFileHandle(self):
        return self.lldb.GetOutputFileHandle()

    def SetAsync(self, arg):
        return self.lldb.SetAsync(arg)


class LldbCommand(sublime_plugin.WindowCommand):
    def run(self):
        global lldb_instance
        global lldb_out_view
        global lldb_view_name
        global window_ref
        global lldb_debugger_pipe_in
        global lldb_debugger_pipe_out
        global lldb_debugger_pipe_err

        if not lldb_instance:
            debug('Creating an SBDebugger instance.')
            lldb_instance = initialize_lldb()
            window_ref = self.window

            lldb_out_view = self.get_lldb_output_view(lldb_view_name)  # for lldb output

            g = lldb_greeting()
            if lldb_out_view.size() > 0:
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

            debug('lldb: starting monitor thread')
            t = threading.Thread(target=lldb_i_o_monitor,
                                 name='lldb i/o monitor')
            t.start()

        # last args: on_done, on_change, on_cancel.
        # On change we could try to complete the input using a quick_panel.
        self.window.show_input_panel('lldb', '',
                                     lldb_in_panel_on_done, None, None)

        update_code_view(self.window)

    def get_lldb_output_view(self, name):
            # Search for the lldb_view view first.
            f = None
            found = False
            for v in self.window.views():
                if v.name() == name:
                    found = True
                    f = v
                    break

            if not found:
                f = sublime.windows()[0].new_file()
                f.set_name(name)

            f.set_scratch(True)
            # f.set_syntax_file('…')  # lldb output syntax
            self.window.set_view_index(f, 1, 0)
            # Maybe set read_only and only unprotect when needed.
            return f


class LldbToggleOutputView(sublime_plugin.WindowCommand):
    def run(self):
        debug(lldb_out_view.layout_extent())
        if good_lldb_layout(window=self.window) and basic_layout != None:
            # restore backup_layout (groups and views)
            lldb_toggle_output_view(self.window, hide=True)
        else:
            lldb_toggle_output_view(self.window, show=True)


class LldbClearOutputView(sublime_plugin.WindowCommand):
    def run(self):
        lldb_out_view.set_read_only(False)
        edit = lldb_out_view.begin_edit('lldb-view-clear')
        lldb_out_view.erase(edit, sublime.Region(0, lldb_out_view.size()))
        lldb_out_view.end_edit(edit)
        lldb_out_view.set_read_only(True)
        lldb_out_view.show(lldb_out_view.size())


# class LldbNext(sublime_plugin.WindowCommand):
#     def run(self):
#         debugger.
