# -*- mode: python; coding: utf-8 -*-

import sublime
import sublime_plugin

import Queue
import threading


from lldb_wrappers import thread_created
from root_objects import show_lldb_panel, breakpoint_dict, reset_breakpoint_dict,   \
                         bps_for_file, add_bp_loc, del_bp_loc


def debug_thr():
    print ('thread id: ' + threading.current_thread().name)
    # traceback.print_stack()


def debug(string):
    print threading.current_thread().name + ' ' + str(string)


lldb_i_o_thread = None
lldb_event_monitor_thread = None
lldb_markers_thread = None
lldb_last_location_view = None
lldb_current_location = None
lldb_file_markers_queue = Queue.Queue()


def marker_update(marks, args=(), after=None):
    dict = {'marks': marks, 'args': args, 'after': after}
    lldb_file_markers_queue.put(dict)


def launch_monitor(fun, name='<monitor thread>', args=()):
    t = threading.Thread(target=fun, name=name, args=args)
    # t.daemon = True
    t.start()


def start_markers_monitor(*args):
    global lldb_markers_thread
    if lldb_markers_thread and not lldb_markers_thread.is_alive():
        lldb_markers_thread.join()

    lldb_markers_thread = launch_monitor(lldb_markers_monitor,
                                         name='<sublime.lldb.monitor.markers>',
                                         args=args)


def stop_markers_monitor():
    reset_breakpoint_dict()
    marker_update('quit')


def lldb_markers_monitor(w, driver):
    thread_created(threading.current_thread().name)
    # debug_thr()
    debug('started')

    done = False
    while not done:
        # Create a new scope, so the 'f' variable isn't changed before running
        # the function, when the timeout expires.
        def aaaa():
            global done
            v = lldb_file_markers_queue.get(True)
            m = v['marks']

            # debug('got: ' + str(v))
            if 'pc' == m:
                args = v['args']
                f = lambda: update_code_view(w, *args)
            elif 'bp' == m:
                args = v['args']
                f = lambda: update_breakpoints(w, *args)
            # elif 'all' == m:
            #     args = v['args']
            #     f = lambda: (update_breakpoints(w, *args), update_code_view(w, *args))
            elif 'quit' == m:
                done = True
                args = v['args']
                f = lambda: (update_code_view(w, *args), remove_all_bps())

            after = v['after']
            if after:
                sublime.set_timeout(lambda: (f[0](), after()), 0)
            else:
                sublime.set_timeout(f, 0)
        aaaa()

    debug('stopped')


def remove_all_bps():
    for w in sublime.windows():
        for v in w.views():
            v.erase_regions("lldb-breakpoint")


def update_code_view(window, entry=None, scope='entity.name.class'):
    global lldb_last_location_view
    if lldb_last_location_view is not None:
        lldb_last_location_view.erase_regions("lldb-location")

    global lldb_current_location
    lldb_current_location = None

    if entry:
        (directory, file, line) = entry
        filename = directory + '/' + file
        lldb_current_location = (filename, line, scope)

        loc = filename + ':' + str(line)

        window.focus_group(0)
        view = window.open_file(loc, sublime.ENCODED_POSITION)
        window.set_view_index(view, 0, 0)

        # If the view is already loaded:
        # (Otherwise, let the listener do the work)
        if not view.is_loading():
            lldb_last_location_view = view
            mark_code_loc(view, True, lldb_current_location)


def update_breakpoints(w, entry=None, remove=False):
    if entry:
        (directory, file, line) = entry
        filename = directory + '/' + file

        if remove:
            f = del_bp_loc
        else:
            f = add_bp_loc

        if not f(filename, line):
            return

        for w in sublime.windows():
            for v in w.views():
                if v.file_name() == filename:
                    v.erase_regions("lldb-breakpoint")
                    regions = map(lambda line: v.full_line(v.text_point(line - 1, 0)), bps_for_file(filename))
                    v.add_regions("lldb-breakpoint", regions,   \
                                     "string", "circle",        \
                                     sublime.HIDDEN)
                    return


def mark_code_loc(view, show_panel, loc):
    line = loc[1]
    scope = loc[2]

    # debug('marking loc at: ' + str(view))
    region = [view.full_line(
                view.text_point(line - 1, 0))]
    view.add_regions("lldb-location",
                     region,
                     scope, "bookmark",
                     sublime.HIDDEN)

    if show_panel:
        show_lldb_panel()


class MarkersListener(sublime_plugin.EventListener):
    def on_load(self, v):
        bps = breakpoint_dict()
        if v.file_name() in bps:
            regions = map(lambda line: v.full_line(v.text_point(line - 1, 0)), bps_for_file(v.file_name()))
            v.add_regions("lldb-breakpoint", regions,
                             "string", "circle",
                             sublime.HIDDEN)

        global lldb_last_location_view
        if lldb_current_location and v.file_name() == lldb_current_location[0]:
            lldb_last_location_view = v
            mark_code_loc(v, True, lldb_current_location)
