# -*- mode: python; coding: utf-8 -*-

import sublime
import sublime_plugin

import os
import sys
import atexit
import datetime
import threading

import lldb
import lldbutil


from debug import debug, debugPlugin, debugVerbose, debugAny


from root_objects import driver_instance, set_driver_instance,          \
                         lldb_out_view, set_lldb_out_view,              \
                         default_lldb_view_name,                        \
                         lldb_view_write, lldb_view_send,               \
                         thread_created, window_ref, set_window_ref,    \
                         get_lldb_output_view, get_lldb_view_for,       \
                         lldb_prompt,                                   \
                         lldb_register_view_name,                       \
                         lldb_disassembly_view_name,                    \
                         disabled_bps, set_disabled_bps,                \
                         InputPanelDelegate,                            \
                         set_ui_updater, ui_updater

from utilities import generate_memory_view_for, SettingsManager

from monitors import LLDBUIUpdater

_initialized = False
_is_debugging = False
_os_not_supported = False
_macosx_is_too_old = False
_did_not_find_debugserver = False
_default_lldb_window_layout = {
                        "cols": [0.0, 1.0],  # start, end
                        "rows": [0.0, 0.75, 1.0],  # start1, start2, end
                        "cells": [[0, 0, 1, 1], [0, 1, 1, 2]]
                       }
_default_basic_window_layout = {  # 1 group
                    "cols": [0.0, 1.0],
                    "rows": [0.0, 1.0],
                    "cells": [[0, 0, 1, 1]]
                 }


def initialize_plugin():
    global _initialized
    if _initialized:
        return

    thread_created('<' + threading.current_thread().name + '>')
    debug(debugAny, 'Loading LLDB Sublime Text 2 plugin')
    debug(debugAny, 'python version: %s' % (sys.version_info,))
    debug(debugAny, 'cwd: %s' % os.getcwd())

    sm = SettingsManager.getSM()
    use_bundled_debugserver = sm.get_default('debugserver.use_bundled', False)
    debugserver_path = sm.get_default('debugerver.path', None)
    global _did_not_find_debugserver
    found = False
    if debugserver_path is not None:
        # TODO: Check that it is a file
        if os.access(debugserver_path, os.X_OK):
            os.environ['LLDB_DEBUGSERVER_PATH'] = debugserver_path
            found = True
        else:
            # FIXME: Warn the user that the debugserver isn't executable
            _did_not_find_debugserver = True
    elif not use_bundled_debugserver:
        debugserver_paths = ['/Applications/Xcode.app/Contents/SharedFrameworks/LLDB.framework/Versions/A/Resources/debugserver',
                             '/System/Library/PrivateFrameworks/LLDB.framework/Versions/A/Resources/debugserver']
        uname = os.uname()
        if uname[0] == 'Darwin':
            if re.match('11\..\..', uname[2]):  # OS X Lion
                found = False
                for path in debugserver_paths:
                    if os.access(path, os.X_OK):
                        os.environ['LLDB_DEBUGSERVER_PATH'] = path
                        found = True
                        break
                if not found:  # XCode has to be installed, signal the plugin.
                    _did_not_find_debugserver = True
            else:  # Snow Leopard, etc...
                # This will only work with XCode 4+ (that includes lldb) which is a paid software for OS X < 10.7
                # I suppose most people with Snow Leopard won't have it.
                # This boolean will be used when trying to initialize lldb.
                global _macosx_is_too_old
                _macosx_is_too_old = True
        else:
            global _os_not_supported
            _os_not_supported = True

    if found:
        debug(debugPlugin, 'debugserver path: %s' % os.environ['LLDB_DEBUGSERVER_PATH'])
    _initialized = True


def debug_prologue(driver):
    """
    Prologue for the debugging session during the development of the plugin.
    Loads a simple program in the debugger and sets a breakpoint in main()
    """
    sm = SettingsManager.getSM()
    prologue = sm.get_default('prologue', [])

    debug(debugPlugin, 'LLDB prologue: %s' % str(prologue))
    for c in prologue:
        lldb_view_write(lldb_prompt() + c + '\n')
        driver.interpret_command(c)


def lldb_greeting():
    return str(datetime.date.today()) +                             \
           '\nWelcome to the LLDB plugin for Sublime Text 2\n' +    \
           lldb_wrappers.version() + '\n'


def good_lldb_layout(window=window_ref()):
    # if the user already has two groups, it's a good layout
    sm = SettingsManager.getSM()
    lldb_window_layout = sm.get_default('layout', _default_lldb_window_layout)
    return window.num_groups() == len(lldb_window_layout['cells'])


def set_lldb_window_layout(window=window_ref()):
    sm = SettingsManager.getSM()
    lldb_window_layout = sm.get_default('layout', _default_lldb_window_layout)
    if lldb_out_view() != None and window.num_groups() != len(lldb_window_layout['cells']):
        window.run_command('set_layout', lldb_window_layout)


def set_regular_window_layout(window=window_ref()):
    sm = SettingsManager.getSM()
    basic_layout = sm.get_default('layout.basic', _default_basic_window_layout)
    window.run_command('set_layout', basic_layout)


def lldb_toggle_output_view(window, show=False, hide=False):
    """ Toggles the lldb output view visibility.

            if show=True: force showing the view;
            if hide=True: force hiding the view;
            Otherwise: Toggle view visibility.
    """
    # TODO: Set the input_panel syntax to 'lldb command'

    # Just show the window.
    v = lldb_out_view()
    if v:
        if show:
            if not good_lldb_layout(window=window):
                set_lldb_window_layout(window=window)
                window.set_view_index(v, 1, 0)
        elif hide:
            set_regular_window_layout(window=window)
        elif not good_lldb_layout(window=window):
            set_lldb_window_layout(window=window)
            window.set_view_index(v, 1, 0)
        else:
            set_regular_window_layout(window=window)


def clear_view(v):
    v.set_read_only(False)
    edit = v.begin_edit('lldb-view-clear')
    v.erase(edit, sublime.Region(0, v.size()))
    v.end_edit(edit)
    v.set_read_only(True)
    v.show(v.size())


def cleanup(w=None):
    global _is_debugging
    _is_debugging = False

    set_disabled_bps([])
    ui_updater().stop()
    driver = driver_instance()
    if driver:
        driver.stop()
        set_driver_instance(None)
    lldb_view_send('\nDebugging session ended.\n')


@atexit.register
def atexit_function():
    debug(debugPlugin, 'running atexit_function')
    cleanup(window_ref())


def unload_handler():
    debug(debugPlugin, 'unloading lldb plugin')
    cleanup(window_ref())


def process_stopped(driver, process, state=None):
    ui_updater().process_stopped(state, lambda: driver.maybe_get_input())

    # Open a new view on source code/disassembly, if needed.
    if process and driver.process_is_stopped(process):
        filespec = None
        line_entry = process.GetSelectedThread().GetSelectedFrame().GetLineEntry()
        if line_entry:
            # We don't need to run 'process status' like Driver.cpp
            # Since we open the file and show the source line.
            r = driver.interpret_command('thread list')
            lldb_view_send(stdout_msg(r[0].GetOutput()))
            lldb_view_send(stderr_msg(r[0].GetError()))
            r = driver.interpret_command('frame info')
            lldb_view_send(stdout_msg(r[0].GetOutput()))
            lldb_view_send(stderr_msg(r[0].GetError()))

            filespec = line_entry.GetFileSpec()
        else:
            # Give us some assembly to check the crash/stop
            r = driver.interpret_command('process status')
            lldb_view_send(stdout_msg(r[0].GetOutput()))
            lldb_view_send(stderr_msg(r[0].GetError()))
            if not line_entry:
                # Get ALL the SBFrames
                t = process.GetSelectedThread()
                n = t.GetNumFrames()
                for i in xrange(0, n):
                    f = t.GetFrameAtIndex(i)
                    if f:
                        line_entry = f.GetLineEntry()
                        if line_entry and line_entry.GetFileSpec():
                            filespec = line_entry.GetFileSpec()

        if filespec:
            filename = filespec.GetDirectory() + '/' + filespec.GetFilename()
            # Maybe we don't need to focus the first group. The user knows
            # what he/she wants.

            def to_ui_thread():
                window_ref().focus_group(0)
                v = window_ref().open_file(filename)
                lldb_view = get_lldb_view_for(v)
                if lldb_view is None:
                    lldb_view = LLDBCodeView(v, driver)
                # TODO: Maybe bring the view to the front?
            sublime.set_timeout(to_ui_thread, 0)
        else:
            # TODO: If we don't have a filespec, we can try to disassemble
            # around the thread's PC.
            sublime.set_timeout(lambda:
                window_ref().run_command('lldb_disassemble_frame', {'thread': process.GetSelectedThread()}), 0)


def initialize_lldb(w):
    # set_got_input_function(lldb_in_panel_on_done)

    driver = LldbDriver(w, lldb_view_send, process_stopped, on_exit_callback=cleanup)
    event = lldb.SBEvent()
    listener = lldb.SBListener('Wait for lldb initialization')
    listener.StartListeningForEvents(driver.broadcaster,
            LldbDriver.eBroadcastBitThreadDidStart)

    driver.start()
    listener.WaitForEvent(START_LLDB_TIMEOUT, event)
    listener.Clear()

    if not event:
        lldb_view_write("oops... the event isn't valid")

    return driver


def start_debugging(w):
    global _is_debugging
    if _is_debugging:
        cleanup(window_ref())

    initialize_plugin()

    # Check for error conditions before starting the debugger
    global _did_not_find_debugserver, _macosx_is_too_old, _os_not_supported
    if _did_not_find_debugserver:
        sublime.error_message("Couldn't find the debugserver binary.\n" +  \
                    'Is XCode.app or the command line tools installed?')
        return False
    if _macosx_is_too_old:
        sublime.error_message('Your Mac OS X version is not supported.\n' +  \
                    'Supported versions: Lion and more recent\n\n' +        \
                    'If you think it should be supported, please contact the author.')
        return False
    if _os_not_supported:
        sublime.error_message('Your operating system is not supported by this plugin yet.\n' +          \
                    'If there is a stable version of lldb for your operating system and you would ' +   \
                    'like to have the plugin support it, please contact the author.')
        return False

    _is_debugging = True

    # Really start the debugger
    initialize_lldb(w)

    driver_instance().debugger.SetInputFileHandle(sys.__stdin__, False)

    # We may also need to change the width upon window resize
    # debugger.SetTerminalWidth()
    return True


# TODO: Search current directory for an executable
def search_for_executable():
    sm = SettingsManager.getSM()
    exe = sm.get_default('exe', None)
    return exe


def ensure_lldb_is_running(w=None):
    """Returns True if lldb was started. False if it was already running"""
    # Ensure we reflect any changes to saved settings (including project settings)
    # reload_settings()

    if not w and window_ref():
        w = window_ref()
    else:
        # We're redefining the default window.
        set_window_ref(w)

    if driver_instance() is None:
        sm = SettingsManager.getSM()
        clear_view_on_startup = sm.get_default('i/o.view.clear_on_startup', True)
        if clear_view_on_startup:
            clear_view(lldb_out_view())

        if not start_debugging(w):
            return

        set_ui_updater(LLDBUIUpdater())
        g = lldb_greeting()
        if lldb_out_view().size() > 0:
            g = '\n\n' + lldb_greeting()
        lldb_view_write(g)
        lldb_view_write('cwd: ' + os.getcwd() + '\n')
        w.set_view_index(lldb_out_view(), 1, 0)

        debug_prologue(driver_instance())
        return True

    return False


import re
bp_re_file_line = re.compile('^(.*\S)\s*:\s*(\d+)\s*$')
bp_re_address = re.compile('^(0x[0-9A-Fa-f]+)\s*$')
# bp_re_abbrev = re.compile('^(-.*)$')
bp_re_name = re.compile('^(.*\S)\s*$')


def create_default_bps_for_target(target):
    n = 0
    sm = SettingsManager.getSM()
    bps = sm.get_default('breakpoints', [])
    for bp in bps:
        if not bp:
            continue

        if type(bp) is str or type(bp) is unicode:
            bp = str(bp)
            m = bp_re_file_line.match(bp)
            if m:
                target.BreakpointCreateByLocation(m.group(1), m.group(2))
                ++n
                continue

            m = bp_re_address.match(bp)
            if m:
                target.BreakpointCreateByAddress(m.group(1))
                ++n
                continue

            m = bp_re_name.match(bp)
            if m:
                target.BreakpointCreateByName(m.group(1))
                ++n
                continue

            debug(debugPlugin, "couldn't tell where the bp spec '" + bp + "' should break.")

        # bp isn't an str. It should be a dict
        elif 'file' in bp and 'line' in bp:
            target.BreakpointCreateByLocation(str(bp['file']), bp['line'])
            ++n
        elif 'address' in bp:
            target.BreakpointCreateByAddress(bp['address'])
            ++n
        else:
            debug(debugPlugin, 'unrecognized breakpoint type: ' + str(bp))


# TODO: Check when each command should be enabled.
class WindowCommand(sublime_plugin.WindowCommand):
    def setup(self):
        debug(debugPlugin, 'Command: %s, identity: %x' % (self.__class__.__name__, id(self)))
        # global lldb_out_view
        if lldb_out_view() is None:
            sm = SettingsManager.getSM()
            view_name = sm.get_default('i/o.view.name', default_lldb_view_name)
            set_lldb_out_view(get_lldb_output_view(self.window, view_name))  # for lldb output

    def status_message(self, string):
        sublime.status_message(string)


class LldbCommand(WindowCommand):
    # This command is always enabled.
    def run(self):
        self.setup()
        lldb_toggle_output_view(self.window, show=True)
        if not ensure_lldb_is_running(self.window):
            # lldb wasn't started by us. show the input panel if possible
            if not driver_instance().maybe_get_input():
                sublime.status_message('Unable to send commands to the debugger')


class LldbDebugProgram(WindowCommand):
    # Only enabled when we have a default program to run.
    def is_enabled(self):
        exe = search_for_executable()
        return exe is not None

    def run(self):
        self.setup()
        ensure_lldb_is_running(self.window)
        lldb_toggle_output_view(self.window, show=True)

        exe = search_for_executable()
        sm = SettingsManager.getSM()
        arch = sm.get_default('arch', lldb.LLDB_ARCH_DEFAULT)

        if exe:
            args = sm.get_default('args', [])

            debug(debugPlugin, 'Launching program: ' + exe + ' (' + arch + '), with args: ' + str(args))
            t = driver_instance().debugger.CreateTargetWithFileAndArch(str(exe), str(arch))
            driver_instance().debugger.SetSelectedTarget(t)
            create_default_bps_for_target(t)
            t.LaunchSimple(args, [], os.getcwd())


class LldbAttachProcess(WindowCommand):
    # Always enabled, since we want to start lldb if it's not running.
    class AttachProcessDelegate(InputPanelDelegate):
        def __init__(self, owner):
            self.__owner = owner

        def on_done(self, string):
            ensure_lldb_is_running(self.__owner.window)
            lldb_toggle_output_view(self.__owner.window, show=True)

            driver = driver_instance()
            if driver:
                # Check if we have a previously running program
                target = driver.debugger.GetSelectedTarget()

                if not target:
                    target = driver.debugger.CreateTarget('')
                    if not target:
                        sublime.error_message('Error attaching to process')
                    driver.debugger.SetSelectedTarget(target)

                old_exec_module = target.GetExecutable()
                old_triple = target.GetTriple()

                # attach_info = lldb.SBAttachInfo()
                # If the user didn't specify anything, attach to the program from
                # the current target, if it exists
                # if string is '':
                #     if old_exec_module:
                #         attach_info.SetExecutable(old_exec_module)
                #     else:
                #         # Bail out
                #         sublime.error_message('No process name/ID specified and no current target.')
                #         return
                # else:
                error = lldb.SBError()
                sm = SettingsManager.getSM()
                wait_for_launch = sm.get_default('attach.wait_for_launch', False)

                try:
                    pid = int(string)
                    # attach_info.SetProcessID(pid)
                    debug(debugPlugin, 'Attaching to pid: %d' % pid)
                    process = target.AttachToProcessWithID(lldb.SBListener(), pid, error)
                except ValueError:
                    # We have a process name, not a pid.
                    # pid = lldb.LLDB_INVALID_PROCESS_ID
                    # attach_info.SetExecutable(str(string))
                    name = str(string) if string != '' else old_exec_module
                    debug(debugPlugin, 'Attaching to process: %s (wait=%s)' % (name, str(wait_for_launch)))
                    process = target.AttachToProcessWithName(lldb.SBListener(), name, wait_for_launch, error)

                # attach_info.SetWaitForLaunch(wait_for_launch)

                # error = lldb.SBError()
                # debug(debugPlugin, attach_info)
                # process = target.Attach(attach_info, error)

                debug(debugPlugin, process)
                if error.Fail():
                    sublime.error_message("Attach failed: %s" % error.GetCString())

                new_exec_module = target.GetExecutable()
                if new_exec_module != old_exec_module:
                    debug(debugPlugin, 'Executable module changed from "%s" to "%s".' % \
                        (old_exec_module, new_exec_module))

                new_triple = target.GetTriple()
                if new_triple != old_triple:
                    debug(debugPlugin, 'Target triple changed from "%s" to "%s".' % (old_triple, new_triple))

                # How can we setup the default breakpoints?
                # We *could* start a new thread with a listener, just for that...

    def run(self):
        self.setup()

        delegate = self.AttachProcessDelegate(self)
        delegate.show_on_window(self.window, 'Process ID')


class LldbConnectDebugserver(WindowCommand):
    # Always enabled, since we want to start lldb if it's not running.
    class ConnectDebugserverDelegate(InputPanelDelegate):
        def __init__(self, owner):
            self.__owner = owner

        def on_done(self, string):
            ensure_lldb_is_running(self.__owner.window)
            lldb_toggle_output_view(self.__owner.window, show=True)

            driver = driver_instance()
            if driver:
                invalidListener = lldb.SBListener()
                error = lldb.SBError()
                target = driver.debugger.CreateTargetWithFileAndArch(None, None)
                process = target.ConnectRemote(invalidListener, str(string), None, error)
                debug(debugPlugin, process)
                if error.Fail():
                    sublime.error_message("Connect failed: %s" % error.GetCString())
                else:
                    driver.debugger.SetSelectedTarget(target)

            # How can we setup the default breakpoints?
            # We *could* start a new thread with a listener, just for that...

    def run(self):
        self.setup()

        delegate = self.ConnectDebugserverDelegate(self)
        delegate.show_on_window(self.window, 'URL', 'connect://localhost:12345')


class LldbStopDebugging(WindowCommand):
    def is_enabled(self):
        driver = driver_instance()
        return driver is not None

    def run(self):
        self.setup()
        driver = driver_instance()
        if driver:
            cleanup(self.window)


class LldbContinue(WindowCommand):
    def is_enabled(self):
        driver = driver_instance()
        if driver:
            return driver.process_is_stopped()
        return False

    def run(self, process=None):
        self.setup()
        driver = driver_instance()
        if driver:
            if process is None:
                target = driver.debugger.GetSelectedTarget()
                if target:
                    process = target.GetProcess()

            if process:
                process.Continue()
        # TODO: Decide what to do in case of errors.
        # e.g: Warn about no running program, etc.


class LldbSendSignal(WindowCommand):
    class SendSignalDelegate(InputPanelDelegate):
        def __init__(self, owner, process):
            self.__owner = owner
            self.__process = process

        def on_done(self, string):
            if self.__process:  # Check if it's still valid
                # TODO: Allow specification of signals by name.
                error = self.__process.Signal(int(string))
                if error.Fail():
                    sublime.error_message(error.GetCString())

    def is_enabled(self):
        driver = driver_instance()
        if driver:
            target = driver.debugger.GetSelectedTarget()
            return target and target.GetProcess()

    def run(self, process=None):
        self.setup()
        driver = driver_instance()
        if driver:
            if process is None:
                target = driver.debugger.GetSelectedTarget()
                if target:
                    process = target.GetProcess()

            if process:
                delegate = self.SendSignalDelegate(self, process)
                delegate.show_on_window(self.window, 'Signal number')
                # TODO: check what happens. From our standpoint, it seems the process terminated successfully.
                #       on the lldb CLI interface, we see the signal.


class LldbStepOver(WindowCommand):
    def is_enabled(self):
        driver = driver_instance()
        if driver:
            return driver.process_is_stopped()
        return False

    def run(self, thread=None):
        self.setup()
        if thread is None:
            thread = driver_instance().current_thread()

        if thread:
            thread.StepOver()


class LldbStepInto(WindowCommand):
    def is_enabled(self):
        driver = driver_instance()
        if driver:
            return driver.process_is_stopped()
        return False

    def run(self, thread=None):
        self.setup()
        if thread is None:
            thread = driver_instance().current_thread()

        if thread:
            thread.StepInto()


class LldbStepOut(WindowCommand):
    def is_enabled(self):
        driver = driver_instance()
        if driver:
            return driver.process_is_stopped()
        return False

    def run(self, thread=None):
        self.setup()
        if thread is None:
            thread = driver_instance().current_thread()

        if thread:
            thread.StepOut()


class LldbStepOverInstruction(WindowCommand):
    def is_enabled(self):
        driver = driver_instance()
        if driver:
            return driver.process_is_stopped()
        return False

    def run(self, thread=None):
        self.setup()
        if thread is None:
            thread = driver_instance().current_thread()

        if thread:
            thread.StepInstruction(True)


class LldbStepOverThread(WindowCommand):
    def is_enabled(self):
        driver = driver_instance()
        if driver:
            return driver.process_is_stopped()
        return False

    def run(self, thread=None):
        self.setup()
        if thread is None:
            thread = driver_instance().current_thread()

        if thread:
            thread.StepOver(lldb.eOnlyThisThread)


class LldbStepIntoInstruction(WindowCommand):
    def is_enabled(self):
        driver = driver_instance()
        if driver:
            return driver.process_is_stopped()
        return False

    def run(self, thread=None):
        self.setup()
        if thread is None:
            thread = driver_instance().current_thread()

        if thread:
            thread.StepInstruction(False)


class LldbStepIntoThread(WindowCommand):
    def is_enabled(self):
        driver = driver_instance()
        if driver:
            return driver.process_is_stopped()
        return False

    def run(self, thread=None):
        self.setup()
        if thread is None:
            thread = driver_instance().current_thread()

        if thread:
            thread.StepInto(lldb.eOnlyThisThread)


# Breakpoint related commands
class LldbListBreakpoints(WindowCommand):
    bp_desc_re_addr = re.compile('address = ([^,]+)')
    bp_desc_re_name = re.compile("name = '(([^'\\\\]|\\\\.)+)'")
    bp_desc_re_file_line = re.compile("file =\\s*'(([^'\\\\]|\\\\.)+)', line = (\\d+)")
    bp_desc_re_regex = re.compile('source regex = "(([^"\\\\]|\\\\.)*)"')

    def is_enabled(self):
        driver = driver_instance()
        return driver is not None and driver.debugger.GetSelectedTarget()

    def parse_description(self, bp_desc):
        """
        Parse breakpoint descriptions from lldb, outputting JSON for putting in the lldb.breakpoints setting.
        TODO: Support breakpoint conditions (and maybe callbacks/commands)

        Example descriptions:

        Current breakpoints:
        1: name = 'main', locations = 1
          1.1: where = tests`main + 36 at tests.c:15, address = tests[0x0000000100000824], unresolved, hit count = 0

        2: name = 'atoi', locations = 2
          2.1: where = tests`atoi + 13 at atoi.c:10, address = tests[0x000000010000154d], unresolved, hit count = 0
          2.2: where = libsystem_c.dylib`atoi, address = libsystem_c.dylib[0x0000000000080bba], unresolved, hit count = 0

        3: name = 'itoa', locations = 1
          3.1: where = tests`itoa + 11 at atoi.c:56, address = tests[0x000000010000175b], unresolved, hit count = 0

        4: file ='tests.c', line = 42, locations = 1
          4.1: where = tests`main + 1786 at tests.c:43, address = tests[0x0000000100000efa], unresolved, hit count = 0

        """
        m = self.bp_desc_re_addr.search(bp_desc)
        if m:
            json = '{ "address": %s }' % m.group(1)
            return json

        m = self.bp_desc_re_name.search(bp_desc)
        if m:
            json = '{ "name": "%s" }' % m.group(1)
            return json

        m = self.bp_desc_re_file_line.search(bp_desc)
        if m:
            json = '{ "file": "%s", "line": %s }' % (m.group(1), m.group(2))
            return json

        m = self.bp_desc_re_regex.search(bp_desc)
        if m:
            json = '{ "regex": "%s" }' % m.group(1)
            return json

    def run(self, target=None):
        self.setup()

        if target is None:
            target = driver_instance().debugger.GetSelectedTarget()

        if not target:
            return

        bp_list = []
        for bp in target.breakpoint_iter():
            # We're going to have to parse the description to know which kind
            # of breakpoint we have, since lldb doesn't reify that information.
            bp_list.append(self.parse_description(lldbutil.get_description(bp)))

        string = ', '.join(bp_list)
        v = self.window.get_output_panel('breakpoint list')

        clear_view(v)
        v.set_read_only(False)
        edit = v.begin_edit('bp-list-view-clear')
        v.replace(edit, sublime.Region(0, v.size()), string)
        v.end_edit(edit)
        v.set_read_only(True)

        self.window.run_command('show_panel', {"panel": 'output.breakpoint list'})


class LldbBreakAtLine(WindowCommand):
    def is_enabled(self):
        driver = driver_instance()
        return driver is not None and driver.debugger.GetSelectedTarget()

    def run(self, target=None):
        self.setup()

        if target is None:
            target = driver_instance().current_target()

        v = self.window.active_view()
        if target and v:
            file = v.file_name()
            (line, col) = v.rowcol(v.sel()[0].begin())
            target.BreakpointCreateByLocation(str(file), line + 1)


class LldbBreakAtSymbol(WindowCommand):
    class BreakAtSymbolDelegate(InputPanelDelegate):
        def __init__(self, owner, target):
            # TODO: Default text should be the current symbol, if any
            self.__owner = owner
            self.__target = target

        def on_done(self, string):
            if self.__target:  # Check if it's still valid
                self.__target.BreakpointCreateByName(str(string))

    def is_enabled(self):
        driver = driver_instance()
        return driver is not None and driver.debugger.GetSelectedTarget()

    def run(self, target=None):
        self.setup()

        if target is None:
            target = driver_instance().current_target()

        if target:
            delegate = self.BreakAtSymbolDelegate(self, target)
            delegate.show_on_window(self.window, 'Symbol to break at')


class LldbToggleEnableBreakpoints(WindowCommand):
    def is_enabled(self):
        driver = driver_instance()
        return driver is not None and driver.debugger.GetSelectedTarget()

    def run(self, target=None):
        self.setup()

        if len(disabled_bps()) > 0:
            for bp in disabled_bps():
                if bp:
                    bp.SetEnabled(True)

            set_disabled_bps([])

        else:
            # bps are enabled. Disable them
            if target is None:
                target = driver_instance().current_target()

            if target:
                assert(len(disabled_bps()) == 0)
                for bp in target.breakpoint_iter():
                    if bp and bp.IsEnabled():
                        disabled_bps().append(bp)
                        bp.SetEnabled(False)

        if len(disabled_bps()) == 0:
            msg = 'Breakpoints disabled.'
        else:
            msg = 'Breakpoints enabled.'

        self.status_message(msg)


# Miscellaneous commands
class LldbViewSharedLibraries(WindowCommand):
    _shared_libraries_view_name = 'Shared libraries'

    def is_enabled(self):
        driver = driver_instance()
        return driver is not None and driver.current_target()

    def run(self, target=None):
        self.setup()

        if target is None:
            target = driver_instance().current_target()

        result = ''

        if target:
            for i in xrange(0, target.GetNumModules()):
                debug(debugPlugin | debugVerbose, lldbutil.get_description(target.GetModuleAtIndex(i)))
                result += lldbutil.get_description(target.GetModuleAtIndex(i)) + '\n'

            # Re-use a view, if we already have one.
            v = None
            for _v in self.window.views():
                if _v.name() == self._shared_libraries_view_name:
                    v = _v
                    break

            if v is None:
                v = self.window.new_file()
                v.set_name(self._shared_libraries_view_name)

            clear_view(v)
            v.set_scratch(True)
            v.set_read_only(False)

            edit = v.begin_edit('lldb-shared-libraries-list')
            v.insert(edit, 0, result)
            v.end_edit(edit)
            v.set_read_only(True)


class LldbViewMemory(WindowCommand):
    _view_memory_view_prefix = 'View memory @ '

    class ViewMemoryDelegate(InputPanelDelegate):
        def __init__(self, owner, process):
            self.__owner = owner
            self.__process = process

        def on_done(self, string):
            if self.__process:  # Check if it's still valid
                addr = int(string, 0)
                error = lldb.SBError()
                sm = SettingsManager.getSM()
                view_mem_size = sm.get_default('view.memory.size', 512)
                view_mem_width = sm.get_default('view.memory.width', 32)
                view_mem_grouping = sm.get_default('view.memory.grouping', 8)

                content = self.__process.ReadMemory(addr, view_mem_size, error)
                if error.Fail():
                    sublime.error_message(error.GetCString())
                    return None

                # Use 'ascii' encoding as each byte of 'content' is within [0..255].
                new_bytes = bytearray(content, 'latin1')

                result = generate_memory_view_for(addr, new_bytes, view_mem_width, view_mem_grouping)
                # Re-use a view, if we already have one.
                v = None
                name = self.__owner._view_memory_view_prefix + hex(addr)
                for _v in self.__owner.window.views():
                    if _v.name() == name:
                        v = _v
                        break

                if v is None:
                    layout_group_source_file = sm.get_default('layout.group.source_file', 0)
                    self.__owner.window.focus_group(layout_group_source_file)
                    v = self.__owner.window.new_file()
                    v.set_name(name)

                clear_view(v)
                v.set_scratch(True)
                v.set_read_only(False)

                edit = v.begin_edit('lldb-view-memory-' + hex(addr))
                v.insert(edit, 0, result)
                v.end_edit(edit)
                v.set_read_only(True)

    def is_enabled(self):
        driver = driver_instance()
        if driver and driver.current_target():
            return driver.process_is_stopped()
        return False

    def run(self, process=None):
        if process is None:
            process = driver_instance().current_process()

        if process:
            delegate = self.ViewMemoryDelegate(self, process)
            delegate.show_on_window(self.window, 'Address to inspect')


# Output view related commands
class LldbToggleOutputView(WindowCommand):
    def run(self):
        self.setup()

        sm = SettingsManager.getSM()
        basic_layout = sm.get_default('layout.basic', _default_basic_window_layout)
        if good_lldb_layout(window=self.window) and basic_layout != None:
            # restore backup_layout (groups and views)
            lldb_toggle_output_view(self.window, hide=True)
        else:
            lldb_toggle_output_view(self.window, show=True)


class LldbClearOutputView(WindowCommand):
    def run(self):
        self.setup()

        clear_view(lldb_out_view())


class LldbRegisterView(WindowCommand):
    def run(self, thread=None):
        self.setup()
        ensure_lldb_is_running(self.window)
        if thread is None:
            thread = driver_instance().current_thread()

        if not thread:
            return False

        base_reg_view = get_lldb_output_view(self.window, lldb_register_view_name(thread))
        if isinstance(base_reg_view, LldbRegisterView):
            reg_view = base_reg_view
        else:
            reg_view = LLDBRegisterView(base_reg_view, thread)
        reg_view.full_update()
        self.window.focus_view(reg_view.base_view())


class LldbDisassembleFrame(WindowCommand):
    def run(self, thread=None):
        self.setup()
        ensure_lldb_is_running(self.window)
        if thread is None:
            thread = driver_instance().current_thread()

        if not thread:
            return False

        base_disasm_view = get_lldb_output_view(self.window, lldb_disassembly_view_name(thread.GetThreadID()))
        if isinstance(base_disasm_view, LLDBThreadDisassemblyView):
            disasm_view = base_disasm_view
        else:
            disasm_view = LLDBThreadDisassemblyView(base_disasm_view, thread)
        disasm_view.full_update()
        self.window.focus_view(disasm_view.base_view())


# import this specific names without the prefix
from lldb_wrappers import LldbDriver, START_LLDB_TIMEOUT
from utilities import stderr_msg, stdout_msg
from views import LLDBRegisterView, LLDBThreadDisassemblyView, LLDBCodeView
import lldb_wrappers
