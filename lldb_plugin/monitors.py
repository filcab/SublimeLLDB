# -*- mode: python; coding: utf-8 -*-

import sublime

import Queue
import select
import threading

from root_objects import lldb_instance, lldb_view_write, \
                         lldb_output_fh, lldb_error_fh


def debug_thr():
    print ('thread id: ' + threading.current_thread().name)
    # traceback.print_stack()


def debug(str):
    print str


def debugif(b, str):
    if b:
        debug(str)


lldb_i_o_thread = None
lldb_markers_thread = None
lldb_last_location_view = None
lldb_file_markers_queue = Queue.Queue()


def launch_monitor(fun, name='monitor thread'):
    t = threading.Thread(target=fun, name=name)
    t.daemon = True
    t.start()


def launch_i_o_monitor():
    global lldb_i_o_thread
    if lldb_i_o_thread and not lldb_i_o_thread.is_alive():
        lldb_i_o_thread.join()

    lldb_i_o_thread = launch_monitor(lldb_i_o_monitor,
                                     name='lldb i/o monitor')


def launch_markers_monitor():
    global lldb_markers_thread
    if lldb_markers_thread and not lldb_markers_thread.is_alive():
        lldb_markers_thread.join()

    lldb_markers_thread = launch_monitor(lldb_markers_monitor,
                                         name='lldb file markers monitor')


def lldb_i_o_monitor():
    debug_thr()
    debug('i/o monitor: started')

    while lldb_instance() != None:
        lldberr = lldb_output_fh()
        lldbout = lldb_error_fh()

        debug('i/o monitor: lldberr: ' + lldberr.__str__())
        debug('i/o monitor: lldbout: ' + lldbout.__str__())

        input = []
        if lldbout:
            input.append(lldbout.fileno())
        if lldberr:
            input.append(lldberr.fileno())

        if len(input) > 0:
            debug('i/o monitor: waiting for select')
            input, output, x = select.select(input, [], [])
        else:
            debug('i/o monitor: waiting for select (timeout)')
            # We're not waiting for input, set a timeout
            input, output, x = select.select(input, [], [], 1000)

        for h in input:
            debug('for h in input')
            debug('i/o: ' + str(h))
            fh = None
            if h == lldbout.fileno():
                fh = lldbout
            elif h == lldberr.fileno():
                fh = lldberr

            debug('i/o: ' + fh.closed)
            if not fh.closed:
                string = fh.read(40)
                debug(string)
                # if fh == lldbout:
                #     sublime.set_timeout(lambda: lldb_view_write(string), 0)
                if fh == lldberr:
                    # We're sure we read something
                    string.replace('\n', '\nerr> ')
                    string = 'err> ' + string

                sublime.set_timeout(lambda: lldb_view_write(string), 0)

    debug('i/o monitor: stopped')


def lldb_markers_monitor():
    debug_thr()
    debug('markers monitor: started')
    # In the future, use lldb events to know what to update
    while True:
        v = lldb_file_markers_queue.get(True)
        m = v['marks']
        w = v['window']
        f = v['after']
        debug('markers mon: ' + str(lldb_file_markers_queue.qsize()))

        debug('markers monitor, got: ' + str(v))
        if 'pc' == m:
            update_code_view(w)
        elif 'bp' == m:
            update_breakpoints(w)
        elif 'all' == m:
            update_code_view(w)
            update_breakpoints(w)
        elif 'quit' == m:
            update_code_view(w)
            if f is not None:
                sublime.set_timeout(f, 0)
            return

        if f is not None:
                sublime.set_timeout(f, 0)

    debug('markers monitor: stopped')


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
                        view.add_regions("lldb-location", \
                                         region, \
                                         "entity.name.class", "bookmark", \
                                         sublime.HIDDEN), 100)

                sublime.set_timeout(temp_function, 0)
                return

    debug("No location info available")


def update_breakpoints(window):
    debug_thr()

    if lldb_instance():
        breakpoints = lldb_instance().breakpoints()
    else:
        # Just erase the current markers
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

                regions = []
                v.erase_regions("lldb-breakpoint")
                for bp in breakpoints:
                    for bp_loc in bp.line_entries():
                        debug('bp entries: ' + str(bp.line_entries()))
                        if bp_loc and v.file_name() == bp_loc[0] + '/' + bp_loc[1]:
                            debug('marking: ' + str(bp_loc) + ' at: ' + v.file_name() + ' (' + v.name() + ')')
                            debug('regions: ' + str(regions))
                            regions.append(  \
                                v.full_line( \
                                  v.text_point(bp_loc[2] - 1, bp_loc[3] - 1)))
                            debug('regions (after): ' + str(regions))

                if len(regions) > 0:
                    debug('marking regions:')
                    debug(regions)
                    v.add_regions("lldb-breakpoint", regions, \
                                 "string", "circle",          \
                                 sublime.HIDDEN)

    sublime.set_timeout(bulk_update, 0)
