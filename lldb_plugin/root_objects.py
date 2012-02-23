# -*- mode: python; coding: utf-8 -*-

lldb_ = None
lldb_view = None


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


def lldb_view_write(string):
    if lldb_view is not None:
        lldb_view.set_read_only(False)
        edit = lldb_view.begin_edit('lldb-panel-write')
        lldb_view.insert(edit, lldb_view.size(), string)
        lldb_view.end_edit(edit)
        lldb_view.set_read_only(True)
        lldb_view.show(lldb_view.size())
