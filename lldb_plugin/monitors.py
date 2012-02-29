# -*- mode: python; coding: utf-8 -*-

import sublime

# FIXME: Use lldb_wrappers
from lldb_wrappers import LldbListener, SublimeBroadcaster
import lldb
import lldbutil

import errno
import Queue
import select
import threading

from root_objects import lldb_instance, lldb_view_write, \
                         lldb_output_fh, lldb_error_fh,  \
                         thread_created


def debug_thr():
    print ('thread id: ' + threading.current_thread().name)
    # traceback.print_stack()


def debug(str):
    print threading.current_thread().name + ' ' + str


def debugif(b, str):
    if b:
        debug(str)


lldb_i_o_thread = None
lldb_event_monitor_thread = None
lldb_markers_thread = None
lldb_last_location_view = None
lldb_file_markers_queue = Queue.Queue()


def kill_monitors():
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
    t.daemon = True
    t.start()


def launch_i_o_monitor(*args):
    global lldb_i_o_thread
    if lldb_i_o_thread and not lldb_i_o_thread.is_alive():
        lldb_i_o_thread.join()

    lldb_i_o_thread = launch_monitor(lldb_i_o_monitor,
                                     name='<lldb i/o monitor>',
                                     args=args)


def launch_markers_monitor(*args):
    global lldb_markers_thread
    if lldb_markers_thread and not lldb_markers_thread.is_alive():
        lldb_markers_thread.join()

    lldb_markers_thread = launch_monitor(lldb_markers_monitor,
                                         name='<lldb file markers monitor>',
                                         args=args)


def launch_event_monitor(*args):
    global lldb_event_monitor_thread
    if lldb_event_monitor_thread is not None and \
        lldb_event_monitor_thread.is_alive():
        lldb_event_monitor_thread.join()

    lldb_event_monitor_thread = launch_monitor(lldb_event_monitor,
                                               name='<lldb event monitor>',
                                               args=args)


def lldb_i_o_monitor(broadcaster):
    thread_created(threading.current_thread().name)
    debug_thr()
    debug('started')

    listener = LldbListener(lldb.SBListener('i/o listener'), lldb_instance())
    listener.start_listening_for_events(broadcaster,
                                    SublimeBroadcaster.eBroadcastBitsSTDOUT |
                                    SublimeBroadcaster.eBroadcastBitsSTDERR |
                                    SublimeBroadcaster.eBroadcastBitDidExit |
                                    SublimeBroadcaster.eBroadcastBitShouldExit)

    if listener.valid:
        done = False
        while not done:
            ev = listener.wait_for_event(100)
            if ev.valid:
                debug('Got event: ' + lldbutil.get_description(ev.SBEvent))
                if ev.broadcaster.valid:
                    if ev.type & SublimeBroadcaster.eBroadcastBitShouldExit \
                        or ev.type & SublimeBroadcaster.eBroadcastBitDidExit:
                        done = True
                        continue
                    elif ev.type & SublimeBroadcaster.eBroadcastBitsSTDOUT:
                        lldb_view_send(ev.string)
                    elif ev.type & SublimeBroadcaster.eBroadcastBitsSTDERR:
                        string = 'err> ' + ev.string
                        string.replace('\n', '\nerr> ')
                        lldb_view_send(string)


# def lldb_i_o_monitor():
#     thread_created(threading.current_thread().name)
#     debug_thr()
#     debug('started')

#     while lldb_instance() != None:
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
#                 # if fh == lldbout:
#                 #     sublime.set_timeout(lambda: lldb_view_write(string), 0)
#                 if fh == lldberr:
#                     # We're sure we read something
#                     string.replace('\n', '\nerr> ')
#                     string = 'err> ' + string

#                 sublime.set_timeout(lambda: lldb_view_write(string), 0)

#     debug('stopped')


def lldb_markers_monitor():
    thread_created(threading.current_thread().name)
    debug_thr()
    debug('started')
    # In the future, use lldb events to know what to update
    while True:
        v = lldb_file_markers_queue.get(True)
        m = v['marks']
        w = v['window']
        f = v['after']

        debug('got: ' + str(v))
        if 'pc' == m:
            update_code_view(w)
        elif 'bp' == m:
            update_breakpoints(w)
        elif 'all' == m:
            update_breakpoints(w)
            update_code_view(w)
        elif 'quit' == m:
            update_breakpoints(w)
            update_code_view(w)
            if f is not None:
                sublime.set_timeout(f, 0)
            return

        if f is not None:
                sublime.set_timeout(f, 0)

    debug('stopped')


def update_code_view(window):
    global lldb_last_location_view
    if lldb_last_location_view is not None:
        # WARNING!! Fix this! (erase_regions noton the main thread)
        sublime.set_timeout(
            lambda: lldb_last_location_view.erase_regions("lldb-location"), 0)

    if lldb_instance():
        entry = lldb_instance().current_line_entry()

        if entry:
                (directory, file, line, column) = entry
                filename = directory + '/' + file

                loc = filename + ':' + str(line) + ':' + str(column)

                def temp_function():
                    window.focus_group(0)
                    view = window.open_file(loc, sublime.ENCODED_POSITION)
                    window.focus_view(view)

                    global lldb_last_location_view
                    lldb_last_location_view = view
                    debug('marking loc at: ' + str(view))
                    region = [view.full_line(
                                view.text_point(line - 1, column - 1))]
                    sublime.set_timeout(lambda:
                        view.add_regions("lldb-location",
                                         region,
                                         "entity.name.class", "bookmark",
                                         sublime.HIDDEN), 100)

                sublime.set_timeout(temp_function, 0)
                return

    debug("No location info available")


def update_breakpoints(window):
    debug_thr()

    if lldb_instance():
        breakpoints = lldb_instance().breakpoints()
    else:
        # Just erase the current bp markers
        breakpoints = []

    def bulk_update():
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

    sublime.set_timeout(bulk_update, 0)


def lldb_event_monitor(listener):
    thread_created(threading.current_thread().name)
    debug_thr()
    debug('started')

    if listener.valid:
        done = False
        while not done:
            ev = listener.wait_for_event(10)
            if ev.valid:
                debug('Got event: ' + lldbutil.get_description(ev.SBEvent))
                if ev.broadcaster.valid:
                    if ev.is_process_event():
                        handle_process_event(ev)
                    elif ev.is_breakpoint_event():
                        handle_breakpoint_event(ev)
                    elif True:  # (just assume, for now) ev.broadcaster_matches_ref(interpreter.broadcaster):
                        if ev.type & lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived:
                            done = True
                            debug('quit received')
                        elif ev.type & lldb.SBCommandInterpreter.eBroadcastBitAsynchronousErrorData:
                            debug('got error data')
                            string = ev.string
                            string = 'err> ' + string
                            string.replace('\n', '\nerr> ')
                            lldb_view_send(string)
                        elif ev.type & lldb.SBCommandInterpreter.eBroadcastBitAsynchronousOutputData:
                            debug('got output data')
                            lldb_view_send(ev.string)
            # else:
                # debug('Event is not valid (timeout)')
    debug('exiting')


def handle_process_event(ev):
    debug('process event: ' + str(ev))
    if ev.type & lldb.SBProcess.eBroadcastBitSTDOUT:
        get_process_stdout()
    elif ev.type & lldb.SBProcess.eBroadcastBitSTDOUT:
        get_process_stderr()
    elif ev.type & lldb.SBProcess.eBroadcastBitStateChanged:
        get_process_stdout()
        get_process_stderr()

        # only after printing the std* can we print our prompts
        state = lldb.SBProcess.GetStateFromEvent(ev.SBEvent)
        if state == lldb.eStateInvalid:
            debug('invalid process state')
            return

        process = lldb.SBProcess.GetProcessFromEvent(ev.SBEvent)
        assert process.IsValid()

        if state == lldb.eStateInvalid       \
            or state == lldb.eStateUnloaded  \
            or state == lldb.eStateConnected \
            or state == lldb.eStateAttaching \
            or state == lldb.eStateLaunching \
            or state == lldb.eStateStepping  \
            or state == lldb.eStateDetached:
            debug("Process %llu %s\n", process.GetProcessID(),
                lldb_instance().StateAsCString(state))

        elif state == lldb.eStateRunning:
            None  # Don't be too chatty
        elif state == lldb.eStateExited:
            None  # FIXME:
            # r = lldb_instance().interpret_command('process status')
            # debug(r[0].output())
            # debug(r[0].error())
        elif state == lldb.eStateStopped     \
            or state == lldb.eStateCrashed   \
            or state == lldb.eStateSuspended:
            if lldb.SBProcess.GetRestartedFromEvent(ev.SBEvent):
                debug('Process %llu stopped and was programmatically restarted.' %
                    process.GetProcessID())
            else:
                # FIXME:
                # update_selected_thread()
                r = lldb_instance().interpret_command('process status')
                debug(r[0].output())
                debug(r[0].error())


def get_process_stdout():
    string = lldb_instance().SBDebugger.GetSelectedTarget(). \
        GetProcess().GetSTDOUT(1024)
    while len(string) > 0:
        debug('program stdout')
        debug(string)
        string = lldb_instance().SBDebugger.GetSelectedTarget(). \
            GetProcess().GetSTDOUT(1024)


def get_process_stderr():
    string = lldb_instance().SBDebugger.GetSelectedTarget(). \
        GetProcess().GetSTDOUT(1024)
    while len(string) > 0:
        string.replace('\n', '\nerr> ')
        string = 'err> ' + string
        debug('program stderr')
        debug(string)
        string = lldb_instance().SBDebugger.GetSelectedTarget(). \
            GetProcess().GetSTDOUT(1024)


def handle_breakpoint_event(ev):
    type = lldb.SBBreakpoint.GetBreakpointEventTypeFromEvent(ev.SBEvent)
    debug('breakpoint event: ' + str(type))

    if type & lldb.eBreakpointEventTypeAdded                \
        or type & lldb.eBreakpointEventTypeRemoved          \
        or type & lldb.eBreakpointEventTypeEnabled          \
        or type & lldb.eBreakpointEventTypeDisabled         \
        or type & lldb.eBreakpointEventTypeCommandChanged   \
        or type & lldb.eBreakpointEventTypeConditionChanged \
        or type & lldb.eBreakpointEventTypeIgnoreChanged    \
        or type & lldb.eBreakpointEventTypeLocationsResolved:
        None
    elif type & lldb.eBreakpointEventTypeLocationsAdded:
        new_locs = lldb.SBBreakpoint.GetNumBreakpointLocationsFromEvent(ev.SBEvent)
        if new_locs > 0:
            bp = lldb.SBBreakpoint.GetBreakpointFromEvent(ev.SBEvent)
            debug("%d locations added to breakpoint %d\n" %
                (new_locs, breakpoint.GetID()))
    elif type & lldb.eBreakpointEventTypeLocationsRemoved:
        None
