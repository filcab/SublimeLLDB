# -*- mode: python; coding: utf-8 -*-

import lldb_wrappers
import sublime

thread_created = lldb_wrappers.thread_created

lldb_ = None
lldb_view = None

pipe_in = None
pipe_out = None
pipe_err = None


def lldb_input_fh():
    return pipe_in


def lldb_output_fh():
    return pipe_out


def lldb_error_fh():
    return pipe_err


def set_lldb_input_fh(input):
    global pipe_in
    pipe_in = input


def set_lldb_output_fh(output):
    global pipe_out
    pipe_out = output


def set_lldb_error_fh(error):
    global pipe_err
    pipe_err = error


def lldb_instance():
    return lldb_


def set_lldb_instance(i):
    global lldb_
    lldb_ = i


def lldb_out_view():
    return lldb_view


def set_lldb_out_view(v):
    global lldb_view
    lldb_view = v


def lldb_view_send(string):
    sublime.set_timeout(lambda: lldb_view_write(string), 0)


def lldb_view_write(string):
    if lldb_view is not None:
        lldb_view.set_read_only(False)
        edit = lldb_view.begin_edit('lldb-panel-write')
        lldb_view.insert(edit, lldb_view.size(), string)
        lldb_view.end_edit(edit)
        lldb_view.set_read_only(True)
        lldb_view.show(lldb_view.size())
