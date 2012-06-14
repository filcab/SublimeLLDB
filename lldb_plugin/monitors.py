# -*- mode: python; coding: utf-8 -*-

import sublime
import sublime_plugin

import os
import fcntl

import Queue
import select
import threading


from lldb_wrappers import thread_created
from root_objects import breakpoint_dict, reset_breakpoint_dict,        \
                         bps_for_file, add_bp_loc, del_bp_loc,          \
                         lldb_views_update,                             \
                         get_lldb_view_for, del_lldb_view

import sys


def debug_thr():
    print >> sys.__stdout__, 'thread id:', threading.current_thread().name
    sys.__stdout__.flush()
    # traceback.print_stack()


def debug(string):
    print >> sys.__stdout__, threading.current_thread().name, str(string)


lldb_markers_thread = None
lldb_last_location_view = None
lldb_current_location = None
lldb_file_markers_queue = Queue.Queue()


class UIUpdater(threading.Thread):
    _done = False

    eProcessStopped = 1 << 0
    eBreakpointAdded = 1 << 1
    eBreakpointEnabled = 1 << 2
    eBreakpointRemoved = 1 << 3
    eBreakpointDisabled = 1 << 4

    def __init__(self):
        super(UIUpdater, self).__init__()
        self.daemon = True
        self.__queue = Queue.Queue()
        self.start()

    def process_stopped(self, state):
        self.__queue.put(self.packet(self.eProcessStopped, state))

    def breakpoint_added(self, file, line):
        packet = self.packet(self.eBreakpointAdded, file, line)
        self.__queue.put(packet)

    def breakpoint_removed(self, file, line):
        packet = self.packet(self.eBreakpointRemoved, file, line)
        self.__queue.put(packet)

    def get_next_packet(self):
        packet = self.__queue.get()
        self.__queue.task_done()
        return packet

    def packet(self, *args):
        return args

    def maybe_get_view_for_file(self, filename):
        return maybe_get_lldb_output_view(None, filename)


    def run(self):
        thread_created('<' + self.name + '>')

        packet = self.get_next_packet()
        while packet:
            debug(packet)
            if packet[0] == self.eProcessStopped:
                state = packet[1]
                lldb_views_update()
                # Should we wait or signal ourselves from lldb_views_refresh?
                # We'll have to signal ourselves if we find that the views get marked,
                # instead of the input box

                # Focus the best view
                # Ask for input, if appropriate
            elif packet[0] == self.eBreakpointAdded:
                filename = packet[1]
                line = packet[2]

                v = maybe_get_view_for_file(filename)
                v.mark_bp(line, True)
            elif packet[0] == self.eBreakpointRemoved:
                pass

            packet = self.get_next_packet()

class FileMonitor(threading.Thread):
    TIMEOUT = 10  # Our default select timeout is 10 secs

    def __init__(self, callback, *files):
        self._callback = callback
        self._files = list(files)
        self._done = False
        super(FileMonitor, self).__init__(name='lldb.debugger.out.monitor')

    def isDone(self):
        return self._done

    def setDone(self, done=True):
        self._done = done

    def run(self):
        thread_created('<' + self.name + '>')

        def fun(file):
            # make stdin a non-blocking file
            fd = file.fileno()
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        rlist = self._files
        map(fun, rlist)

        while not self.isDone() and rlist is not []:
            # debug('rlist: ' + str(rlist))
            r, w, x = select.select(rlist, [], [], FileMonitor.TIMEOUT)
            # debug('after select: ' + str(r))
            if len(r) == 0:
                continue
            for f in r:
                data = f.read()
                # debug('file: ' + str(f) + ', data: ' + data)
                if data == '':
                    debug('removing ' + str(f) + ' from FileMonitor')
                    rlist.remove(f)
                self._callback(data)

        self.setDone(True)


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
        # Comented out so the view won't always jump in front of us.
        # TODO: Create a setting for this
        # window.set_view_index(view, 0, 0)

        # If the view is already loaded:
        # (Otherwise, let the listener do the work)
        if not view.is_loading():
            lldb_last_location_view = view
            mark_code_loc(view, True, lldb_current_location)


def update_breakpoints(w, entry=None, remove=False):
    return False
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

    # if show_panel:
    #     show_lldb_panel()


class UIListener(sublime_plugin.EventListener):
    def on_close(self, v):
        lldb_view = get_lldb_view_for(v)
        if lldb_view:
            del_lldb_view(v)

    def on_load(self, v):
        lldb_view = get_lldb_view_for(v)
        if lldb_view:
            # TODO: Instead of updating it here, send a message to the UIUpdater
            lldb_view.full_update()


class MarkersListener(sublime_plugin.EventListener):
    def on_load(self, v):
        return
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
