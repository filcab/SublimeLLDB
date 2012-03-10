# -*- mode: python; coding: utf-8 -*-

import sublime
import sublime_plugin

# FIXME: Use lldb_wrappers
from lldb_wrappers import BIG_TIMEOUT, interpret_command
import lldb_wrappers
import lldb
import lldbutil

import Queue
import threading

from root_objects import driver_instance, set_driver_instance, \
                         lldb_view_send,  \
                         thread_created, show_lldb_panel,  \
                         window_ref

from utilities import stdout_msg, stderr_msg


def debug_thr():
    print ('thread id: ' + threading.current_thread().name)
    # traceback.print_stack()


def debug(string):
    print threading.current_thread().name + ' ' + str(string)


def debugif(b, str):
    if b:
        debug(str)


lldb_i_o_thread = None
lldb_event_monitor_thread = None
lldb_markers_thread = None
lldb_last_location_view = None
lldb_current_location = None
lldb_file_markers_queue = Queue.Queue()


def marker_update(marks, args=(), after=None):
    dict = {'marks': marks, 'args': args, 'after': after}
    lldb_file_markers_queue.put(dict)


def cleanup(window, full=True):
    debug('cleaning up the lldb plugin')

    sublime.set_timeout(lambda: update_code_view(window, None), 0)
    if driver_instance() is not None:
        driver_instance().destroy()
        lldb_wrappers.terminate()
        set_driver_instance(None)

    # close the pipes
    # if broadcaster is not None:
    #     broadcaster.end()
    # broadcaster = None


def kill_monitors():
    global lldb_i_o_thread, lldb_event_monitor_thread, lldb_markers_thread

    cleanup(window_ref())
    if lldb_i_o_thread is not None and lldb_i_o_thread.is_alive():
        lldb_i_o_thread.kill()
        lldb_i_o_thread = None
    if lldb_event_monitor_thread is not None and lldb_event_monitor_thread.is_alive():
        lldb_event_monitor_thread.kill()
        lldb_event_monitor_thread = None
    if lldb_markers_thread is not None and lldb_markers_thread.is_alive():
        lldb_markers_thread.kill()
        lldb_markers_thread = None


def launch_monitor(fun, name='<monitor thread>', args=()):
    t = threading.Thread(target=fun, name=name, args=args)
    # t.daemon = True
    t.start()


def launch_i_o_monitor(*args):
    global lldb_i_o_thread
    if lldb_i_o_thread and not lldb_i_o_thread.is_alive():
        lldb_i_o_thread.join()

    lldb_i_o_thread = launch_monitor(lldb_i_o_monitor,
                                     name='<sublime-lldb i/o monitor>',
                                     args=args)


def launch_markers_monitor(*args):
    global lldb_markers_thread
    if lldb_markers_thread and not lldb_markers_thread.is_alive():
        lldb_markers_thread.join()

    lldb_markers_thread = launch_monitor(lldb_markers_monitor,
                                         name='<sublime-lldb file markers monitor>',
                                         args=args)


def launch_event_monitor(*args):
    global lldb_event_monitor_thread
    if lldb_event_monitor_thread is not None and \
        lldb_event_monitor_thread.is_alive():
        lldb_event_monitor_thread.join()

    lldb_event_monitor_thread = launch_monitor(lldb_event_monitor,
                                               name='<sublime-lldb event monitor>',
                                               args=args)


def lldb_i_o_monitor():
    # thread_created(threading.current_thread().name)
    # debug_thr()
    # debug('started')

    # listener = LldbListener(lldb.SBListener('i/o listener'), driver_instance())
    # listener.start_listening_for_events(broadcaster,
    #                                 SublimeBroadcaster.eBroadcastBitsSTDOUT |
    #                                 SublimeBroadcaster.eBroadcastBitsSTDERR |
    #                                 SublimeBroadcaster.eBroadcastBitDidExit |
    #                                 SublimeBroadcaster.eBroadcastBitShouldExit)

    # if listener.valid:
    #     done = False
    #     while not done:
    #         debug('listening at: ' + str(listener.SBListener))
    #         ev = listener.wait_for_event()
    #         if ev.valid:
    #             debug('Got event: ' + lldbutil.get_description(ev.SBEvent))
    #             if ev.broadcaster.valid:
    #                 if ev.type & SublimeBroadcaster.eBroadcastBitShouldExit \
    #                     or ev.type & SublimeBroadcaster.eBroadcastBitDidExit:
    #                     debug('leaving due to SublimeBroadcaster')
    #                     done = True
    #                     continue
    #                 elif ev.type & SublimeBroadcaster.eBroadcastBitsSTDOUT:
    #                     debug('stdout bits')
    #                     lldb_view_send(ev.string)
    #                 elif ev.type & SublimeBroadcaster.eBroadcastBitsSTDERR:
    #                     debug('stderr bits')
    #                     string = 'err> ' + ev.string
    #                     string.replace('\n', '\nerr> ')
    #                     lldb_view_send(string)
    debug('leaving...')


# def lldb_i_o_monitor():
#     thread_created(threading.current_thread().name)
#     debug_thr()
#     debug('started')

#     while driver_instance() != None:
#         lldberr = lldb_output_fh()
#         lldbout = lldb_error_fh()

#         # debug('lldberr: ' + str(lldberr))
#         # debug('lldbout: ' + str(lldbout))

#         input = []
#         if lldbout:
#             input.append(lldbout.fileno())
#         if lldberr:
#             input.append(lldberr.fileno())

#         if len(input) > 0:
#             try:
#                 input, output, x = select.select(input, [], [])
#             except IOError as e:
#                 debug("I/O error({0}): {1}".format(e.errno, e.strerror))
#                 if e.errno == errno.EDABFD:
#                     debug('i/o monitor: ' + \
#                             'I suppose lldb error or output file was closed')
#                     debug('i/o: retrying')
#         else:
#             # debug('waiting for select (timeout)')
#             # We're not waiting for input, set a timeout
#             input, output, x = select.select([], [], [], 3.14)

#         for h in input:
#             debug('for h in input: ' + str(h))
#             fh = None
#             if h == lldbout.fileno():
#                 fh = lldbout
#             elif h == lldberr.fileno():
#                 fh = lldberr

#             debug('  ' + str(fh.closed))
#             if not fh.closed:
#                 string = fh.read()
#                 debug(string)
#                 if fh == lldbout:
#                     sublime.set_timeout(lambda: lldb_view_write(string), 0)
#                 if fh == lldberr:
#                     # We're sure we read something
#                     string.replace('\n', '\nerr> ')
#                     string = 'err> ' + string

#                 sublime.set_timeout(lambda: lldb_view_write(string), 0)

#     debug('stopped')


def lldb_markers_monitor(w):
    thread_created(threading.current_thread().name)
    debug_thr()
    debug('started')

    done = False
    while not done:
        v = lldb_file_markers_queue.get(True)
        m = v['marks']
        args = v['args']
        after = v['after']

        debug('got: ' + str(v))
        if 'pc' == m:
            f = lambda: update_code_view(w, *args)
        elif 'bp' == m:
            f = lambda: update_breakpoints(w, *args)
        elif 'all' == m:
            f = lambda: (update_breakpoints(w, *args), update_code_view(w, *args))
        elif 'delete' == m:
            done = True
            f = lambda: (update_breakpoints(w, *args), update_code_view(w, *args))

        if after:
            sublime.set_timeout(lambda: (f(), after()), 0)
        else:
            sublime.set_timeout(f, 0)

    debug('stopped')


def update_code_view(window, entry, scope='entity.name.class'):
    global lldb_last_location_view
    if lldb_last_location_view is not None:
        lldb_last_location_view.erase_regions("lldb-location")

    global lldb_current_location
    lldb_current_location = None

    if entry:
        (directory, file, line, column) = entry
        filename = directory + '/' + file
        lldb_current_location = (filename, line, column, scope)

        loc = filename + ':' + str(line) + ':' + str(column)

        window.focus_group(0)
        view = window.open_file(loc, sublime.ENCODED_POSITION)
        window.set_view_index(view, 0, 0)

        # If the view is already loaded:
        # (Otherwise, let the listener do the work)
        if not view.is_loading():
            lldb_last_location_view = view
            mark_code_loc(view, lldb_current_location)

    else:
        debug("No location info available")


def mark_code_loc(view, loc):
    line = loc[1]
    column = loc[2]
    scope = loc[3]

    debug('marking loc at: ' + str(view))
    region = [view.full_line(
                view.text_point(line - 1, column - 1))]
    view.add_regions("lldb-location",
                     region,
                     scope, "bookmark",
                     sublime.HIDDEN)
    show_lldb_panel()


class MarkersListener(sublime_plugin.EventListener):
    def on_load(self, view):
        global lldb_last_location_view
        if lldb_current_location and view.file_name() == lldb_current_location[0]:
            lldb_last_location_view = view
            mark_code_loc(view, lldb_current_location)


def update_breakpoints(window):
    debug_thr()

    if driver_instance():
        breakpoints = driver_instance().breakpoints()
    else:
        # Just erase the current bp markers
        breakpoints = []

    seen = []
    for w in sublime.windows():
        for v in w.views():
            debug('marking view: ' + str(v.file_name()) + ' (' + str(v.name()) + ')')
            if v in seen:
                continue
            else:
                seen.append(v)

            v.erase_regions("lldb-breakpoint")
            regions = []
            for bp in breakpoints:
                for bp_loc in bp.line_entries():
                    debug('bp entries: ' + str(bp.line_entries()))
                    if bp_loc and v.file_name() == bp_loc[0] + '/' + bp_loc[1]:
                        debug('marking: ' + str(bp_loc) + ' at: ' + v.file_name() + ' (' + v.name() + ')')
                        debug('regions: ' + str(regions))
                        regions.append(
                            v.full_line(
                              v.text_point(bp_loc[2] - 1, bp_loc[3] - 1)))
                        debug('regions (after): ' + str(regions))

            if len(regions) > 0:
                debug('marking regions:')
                debug(regions)
                v.add_regions("lldb-breakpoint", regions, \
                             "string", "circle",          \
                             sublime.HIDDEN)


def update_selected_thread(debugger):
    proc = debugger.GetSelectedTarget().GetProcess()
    if proc.IsValid():
        curr_thread = proc.GetSelectedThread()
        current_thread_stop_reason = curr_thread.GetStopReason()

        debug('thread stop reason: ' + str(current_thread_stop_reason))
        other_thread = lldb.SBThread()
        plan_thread = lldb.SBThread()
        if not curr_thread.IsValid() \
            or current_thread_stop_reason == lldb.eStopReasonInvalid \
            or current_thread_stop_reason == lldb.eStopReasonNone:
            for t in proc:
                t_stop_reason = t.GetStopReason()
                if t_stop_reason == lldb.eStopReasonInvalid \
                    or t_stop_reason == lldb.eStopReasonNone:
                    pass
                elif t_stop_reason == lldb.eStopReasonTrace \
                    or t_stop_reason == lldb.eStopReasonBreakpoint \
                    or t_stop_reason == lldb.eStopReasonWatchpoint \
                    or t_stop_reason == lldb.eStopReasonSignal \
                    or t_stop_reason == lldb.eStopReasonException:
                    if not other_thread:
                        other_thread = t
                    elif t_stop_reason == lldb.eStopReasonPlanComplete:
                        if not plan_thread:
                            plan_thread = t

            if plan_thread:
                proc.SetSelectedThread(plan_thread)
            elif other_thread:
                proc.SetSelectedThread(other_thread)
            else:
                if curr_thread:
                    thread = curr_thread
                else:
                    thread = proc.GetThreadAtIndex(0)

                proc.SetSelectedThread(thread)
