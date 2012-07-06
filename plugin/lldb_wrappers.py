# -*- mode: python; coding: utf-8 -*-

# import time

import os
import lldb
import lldbutil
import sublime
import threading
import utilities

BIG_TIMEOUT = 42000000
START_LLDB_TIMEOUT = 5

from debug import debug, debugDriver


def version():
    return lldb.SBDebugger.GetVersionString()


def thread_created(string):
    lldb.SBHostOS.ThreadCreated(string)


class LldbDriver(threading.Thread):
    eBroadcastBitThreadShouldExit = 1 << 0
    eBroadcastBitThreadDidStart = 1 << 1
    eBroadcastBitReadyForInput = 1 << 2

    __is_done = False
    __io_channel = None
    __debug_mode = False
    __broadcaster = None
    __input_reader = None
    __waiting_for_command = False

    # FIXME: This should be configurable
    __max_instructions = 200

    def __init__(self, window, log_callback=None, process_stopped_callback=None, on_exit_callback=None):
        super(LldbDriver, self).__init__(name='sublime.lldb.driver')
        self.__window = window
        lldb.SBDebugger.Initialize()
        self.__broadcaster = lldb.SBBroadcaster('Driver')
        self.__process_stopped_callback = process_stopped_callback
        self.__on_exit_callback = on_exit_callback

        # if log_callback:
            # self._debugger = lldb.SBDebugger.Create(False, log_callback)
        # else:
        self._debugger = lldb.SBDebugger.Create(False)
        self.__listener = self._debugger.GetListener()
        set_driver_instance(self)
        r, w = os.pipe()
        self.__io_channel_r_fh = os.fdopen(r, 'r', 0)
        self.__io_channel_w_fh = os.fdopen(w, 'w', 0)
        self.__io_channel = IOChannel(self, self.__io_channel_r_fh, lldb_view_send)
        # self._debugger.SetCloseInputOnEOF(False)
        self.__input_reader = lldb.SBInputReader()
        self.__input_pty = utilities.PseudoTerminal()
        self.__output_pty = utilities.PseudoTerminal()

    def __del__(self):
        # del self.__io_channel
        # del self.__broadcaster
        # del self._debugger
        lldb.SBDebugger.Terminate()

    def __input_reader_callback(self, input_reader, notification, bytes):
        if (notification == lldb.eInputReaderReactivate):
            self.ready_for_command()
        elif (notification == lldb.eInputReaderGotToken):
            # We're using a Line granularity. We don't receive the \n
            self.__io_channel_w_fh.write(bytes + '\n')
            self.__io_channel_w_fh.flush()
        elif (notification == lldb.eInputReaderAsynchronousOutputWritten):
            io_channel = self.io_channel
            if io_channel:
                pass
                # io_channel.refresh_prompt()
        elif (notification == lldb.eInputReaderInterrupt):
            io_channel = self.io_channel
            if io_channel:
                io_channel.out_write('^C\n', io_channel.NO_ASYNC)
                # io_channel.refresh_prompt()
        elif (notification == lldb.eInputReaderEndOfFile):
            io_channel = self.io_channel
            if io_channel:
                io_channel.out_write('^D\n', io_channel.NO_ASYNC)
                # io_channel.refresh_prompt()
            self.__io_channel_w_fh.write(b'quit\n')
        elif (notification == lldb.eInputReaderActivate):
            pass
        elif (notification == lldb.eInputReaderDeactivate):
            # Another input reader got pushed onto the stack
            # Let's open an input prompt for it.
            LldbInputDelegate.get_input(self.__window, '?')
        elif (notification == lldb.eInputReaderDone):
            pass

        def notif_str():
            return [
                    "eInputReaderActivate,   // reader is newly pushed onto the reader stack ",
                    "eInputReaderAsynchronousOutputWritten, // an async output event occurred; the reader may want to do something",
                    "eInputReaderReactivate, // reader is on top of the stack again after another reader was popped off ",
                    "eInputReaderDeactivate, // another reader was pushed on the stack",
                    "eInputReaderGotToken,   // reader got one of its tokens (granularity)",
                    "eInputReaderInterrupt,  // reader received an interrupt signal (probably from a control-c)",
                    "eInputReaderEndOfFile,  // reader received an EOF char (probably from a control-d)",
                    "eInputReaderDone        // reader was just popped off the stack and is done"][notification]
        return len(bytes)

    def maybe_get_input(self):
        if self.is_ready_for_command() and self.debugger.InputReaderIsTopReader(self.__input_reader):
            LldbInputDelegate.get_input(self.__window, 'lldb (driver)')
            return True
        elif self.is_ready_for_command():
            LldbInputDelegate.get_input(self.__window, '?')
            return True
        return False

    def master_thread_bytes_received(self, string):
        self.io_channel.out_write(string, IOChannel.ASYNC)

    def stop(self):
        self.broadcaster.BroadcastEventByType(LldbDriver.eBroadcastBitThreadShouldExit)

    def process_is_running(self, proc=None):
        if proc is None:
            proc = self.current_process()
        if proc:
            return proc.GetState() == lldb.eStateRunning
        return False

    def process_has_exited(self, proc=None):
        if proc is None:
            proc = self.current_process()
        if proc:
            return proc.GetState() == lldb.eStateExited
        return False

    def process_is_stopped(self, proc=None):
        if proc is None:
            proc = self.current_process()
        if proc:
            return proc.GetState() == lldb.eStateStopped
        return False

    def get_PC(self):
        frame = self.current_frame()
        if not frame:
            return False
        target = frame.GetThread().GetProcess().GetTarget()
        return frame.GetPCAddress().GetLoadAddress(target)

    def current_target(self):
        target = self.debugger.GetSelectedTarget()
        return target

    def current_process(self):
        target = self.current_target()
        if not target:
            return None
        process = target.GetProcess()
        return process

    def current_thread(self):
        process = self.current_process()
        if not process:
            return False
        thread = process.GetSelectedThread()
        return thread

    def current_frame(self):
        thread = self.current_thread()
        if not thread:
            return None
        frame = thread.GetSelectedFrame()
        return frame

    def disassemble_selected_frame(self):
        frame = self.current_frame()
        return self.disassemble_frame(frame)

    def disassemble_frame(self, frame):
        if not frame:
            debug(debugDriver, 'Driver.disassemble_frame: not frame == True')
            return None

        target = frame.GetThread().GetProcess().GetTarget()
        pc = frame.GetPCAddress()
        function = pc.GetFunction()
        symbol = pc.GetSymbol()

        if function.IsValid():
            code = function.GetInstructions(target)
        elif symbol.IsValid():
            code = symbol.GetInstructions(target)
        else:
            code = target.ReadInstructions(pc, self.__max_instructions)
        result = []

        for i in code:
            comment = i.GetComment(target)
            # data = i.GetData(target)
            # data_str = ''
            # if data.GetByteSize() > 0:
            #     stream = lldb.SBStream()
            #     error = lldb.SBError()
            #     data.GetDescription(stream, data.GetAddress(error, 0))
            #     if error.Success():
            #         data_str = " (data: %s)" % stream.GetData()

            if len(comment) > 0:
                result.append((i.GetAddress().GetLoadAddress(target), i.GetMnemonic(target), i.GetOperands(target), comment))
            else:
                result.append((i.GetAddress().GetLoadAddress(target), i.GetMnemonic(target), i.GetOperands(target)))

        return result

    def get_breakpoint_locations_for_file(self, filename):
        bp_iter = self.current_target().breakpoint_iter()

        def filter(bp_loc):
            addr = bp_loc.GetAddress()
            if addr:
                line_entry = addr.GetLineEntry()
                if line_entry:
                    filespec = line_entry.GetFileSpec()
                    if filespec:
                        filespec_path = filespec.GetDirectory() + '/' + filespec.GetFilename()
                        return filespec_path == filename

        lst = [bp_loc for bp in bp_iter for bp_loc in bp if filter(bp_loc)]
        return lst

    @property
    def debugger(self):
        """The low-level SBDebugger for this driver."""
        return self._debugger

    @property
    def broadcaster(self):
        return self.__broadcaster

    @property
    def listener(self):
        return self.__listener

    @property
    def debug_mode(self):
        """True if the driver is in debug mode."""
        return self.__debug_mode

    @debug_mode.setter
    def debug_mode(self, value):
        self.__debug_mode = value

    @property
    def io_channel(self):
        """The IO channel for this driver."""
        return self.__io_channel

    @io_channel.deleter
    def io_channel(self):
        del self.__io_channel

    @property
    def is_done(self):
        """True if the debugger has finished its work."""
        return self.__is_done

    @is_done.setter
    def is_done(self, done):
        self.__is_done = done

    def send_input(self, cmd):
        """Send a command asynchronously to the IO channel."""
        self.__to_debugger_fh_w.write(bytes(cmd) + '\n')
        self.__to_debugger_fh_w.flush()
        # event = lldb.SBEvent(IOChannel.eBroadcastBitHasUserInput, str(cmd))
        # self.io_channel.broadcaster.BroadcastEvent(event)

    def is_ready_for_command(self):
        return self.__waiting_for_command

    def ready_for_command(self):
        """Send an eBroadcastBitReadyForInput if the debugger wasn't ready before this call."""
        debug(debugDriver, 'ready for command. was waiting: ' + str(self.__waiting_for_command))
        if not self.__waiting_for_command:
            self.__waiting_for_command = True
            self.broadcaster.BroadcastEventByType(LldbDriver.eBroadcastBitReadyForInput, False)

    @property
    def line_entry(self):
        frame = self.current_frame()
        if not frame:
            return None
        entry = frame.GetLineEntry()
        filespec = entry.GetFileSpec()

        if filespec:
            return (filespec.GetDirectory(), filespec.GetFilename(), \
                    entry.GetLine())
        else:
            return None

    def run(self):
        thread_created('<' + self.name + '>')

        sb_interpreter = self._debugger.GetCommandInterpreter()
        #listener = self._debugger.GetListener()
        listener = self.__listener
        listener.StartListeningForEventClass(self._debugger,
                     lldb.SBTarget.GetBroadcasterClassName(),
                     lldb.SBTarget.eBroadcastBitBreakpointChanged)
        # This isn't in Driver.cpp. Check why it listens to those events (because it uses SBDebugger's listener?)
        # listener.StartListeningForEventClass(self._debugger,
        #              lldb.SBProcess.GetBroadcasterClassName(),
        #              lldb.SBProcess.eBroadcastBitStateChanged |     \
        #              lldb.SBProcess.eBroadcastBitInterrupt |        \
        #              lldb.SBProcess.eBroadcastBitSTDOUT |           \
        #              lldb.SBProcess.eBroadcastBitSTDERR)

        # Warn whoever started us that we can start working
        self.broadcaster.BroadcastEventByType(LldbDriver.eBroadcastBitThreadDidStart)

        # in_pty = self.__input_pty
        # in_pty.open_first_available_master(os.O_RDWR | os.O_NOCTTY)

        # out_pty = self.__output_pty
        # out_pty.open_first_available_master(os.O_RDWR | os.O_NOCTTY)

        # Create pipes for communicating with the debugger
        in_pipe_fd, out_pipe_fd = os.pipe()
        self.__from_debugger_fh_r = os.fdopen(in_pipe_fd, 'r', 0)
        self.__from_debugger_fh_w = os.fdopen(out_pipe_fd, 'w', 0)
        in_pipe_fd, out_pipe_fd = os.pipe()
        self.__to_debugger_fh_r = os.fdopen(in_pipe_fd, 'r', 0)
        self.__to_debugger_fh_w = os.fdopen(out_pipe_fd, 'w', 0)

        self.__file_monitor = FileMonitor(self.master_thread_bytes_received, self.__from_debugger_fh_r)
        self.debugger.SetOutputFileHandle(self.__from_debugger_fh_w, False)
        self.debugger.SetErrorFileHandle(self.__from_debugger_fh_w, False)
        self.debugger.SetInputFileHandle(self.__to_debugger_fh_r, False)

        # m_debugger.SetUseExternalEditor(m_option_data.m_use_external_editor);

        error = lldb.SBError(self.__input_reader.Initialize(self.debugger,
                                                            self.__input_reader_callback,
                                                            lldb.eInputReaderGranularityLine,
                                                            None,  # end token (NULL == never done)
                                                            None,  # Prompt (NULL == taken care of elsewhere)
                                                            False))  # echo input (we'll take care of this elsewhere)

        if error.Fail():
            # Fail now... We can't have any input reader
            sublime.error_message('error: ' + error.GetCString())
            return

        self.debugger.PushInputReader(self.__input_reader)

        if listener.IsValid():
            iochannel_thread_exited = False
            listener.StartListeningForEvents(self.io_channel.broadcaster,
                        IOChannel.eBroadcastBitHasUserInput |      \
                        IOChannel.eBroadcastBitUserInterrupt |     \
                        IOChannel.eBroadcastBitThreadShouldExit |  \
                        IOChannel.eBroadcastBitThreadDidStart |    \
                        IOChannel.eBroadcastBitThreadDidExit)

            self.io_channel.start()
            if self.io_channel.is_alive():
                listener.StartListeningForEvents(sb_interpreter.GetBroadcaster(),
                            lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived |    \
                            lldb.SBCommandInterpreter.eBroadcastBitAsynchronousOutputData | \
                            lldb.SBCommandInterpreter.eBroadcastBitAsynchronousErrorData)

                result = lldb.SBCommandReturnObject()
                sb_interpreter.SourceInitFileInHomeDirectory(result)
                if self.debug_mode:
                    result.PutError(self.debugger.GetErrorFileHandle())
                    result.PutOutput(self.debugger.GetOutputFileHandle())

                sb_interpreter.SourceInitFileInCurrentWorkingDirectory(result)
                if self.debug_mode:
                    result.PutError(self.debugger.GetErrorFileHandle())
                    result.PutOutput(self.debugger.GetOutputFileHandle())

                event = lldb.SBEvent()
                listener.WaitForEventForBroadcasterWithType(BIG_TIMEOUT,
                            self.io_channel.broadcaster,
                            IOChannel.eBroadcastBitThreadDidStart,
                            event)

                self.ready_for_command()
                while not self.is_done:
                    listener.WaitForEvent(BIG_TIMEOUT, event)
                    if event:
                        if event.GetBroadcaster():
                            ev_type = event.GetType()
                            if (event.BroadcasterMatchesRef(self.io_channel.broadcaster)):
                                if ev_type & IOChannel.eBroadcastBitHasUserInput:
                                    command_string = lldb.SBEvent.GetCStringFromEvent(event)
                                    if command_string is None:
                                        command_string = ''
                                    result = lldb.SBCommandReturnObject()

                                    self.debugger.GetCommandInterpreter().HandleCommand(command_string, result, True)
                                    if result.GetOutputSize() > 0:
                                        self.io_channel.out_write(result.GetOutput(), IOChannel.NO_ASYNC)

                                    if result.GetErrorSize() > 0:
                                        self.io_channel.err_write(result.GetError(), IOChannel.NO_ASYNC)

                                    debug(debugDriver, 'waiting_for_command = False')
                                    self.__waiting_for_command = False
                                    if self.__input_reader.IsActive():
                                        self.ready_for_command()

                                elif ev_type & IOChannel.eBroadcastBitThreadShouldExit \
                                    or ev_type & IOChannel.eBroadcastBitThreadDidExit:
                                    self.is_done = True
                                    if ev_type & IOChannel.eBroadcastBitThreadDidExit:
                                        iochannel_thread_exited = True
                                    else:
                                        # TODO: __handle_io_event is not implemented
                                        if self.__handle_io_event(event):
                                            self.is_done = True
                            elif lldb.SBProcess.EventIsProcessEvent(event):
                                self.__handle_process_event(event)
                            elif lldb.SBBreakpoint.EventIsBreakpointEvent(event):
                                self.__handle_breakpoint_event(event)
                            elif event.BroadcasterMatchesRef(sb_interpreter.GetBroadcaster()):
                                # This first one should be replaced with a CommandOverrideCallback function
                                if ev_type & lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived:
                                    self.is_done = True
                                elif ev_type & lldb.SBCommandInterpreter.eBroadcastBitAsynchronousErrorData:
                                    data = lldb.SBEvent.GetCStringFromEvent(event)
                                    self.io_channel.err_write(data, IOChannel.ASYNC)
                                    lldb_view_send(stderr_msg(data))
                                elif ev_type & lldb.SBCommandInterpreter.eBroadcastBitAsynchronousOutputData:
                                    data = lldb.SBEvent.GetCStringFromEvent(event)
                                    self.io_channel.out_write(data, IOChannel.ASYNC)
                                    lldb_view_send(stdout_msg(data))

                if not iochannel_thread_exited:
                    event.Clear()
                    listener.GetNextEventForBroadcasterWithType(self.io_channel.broadcaster,
                                                                IOChannel.eBroadcastBitThreadDidExit,
                                                                event)
                    if not event:
                        self.io_channel.stop()

                self.__file_monitor.setDone()
                # Ensure the listener (and everything else, really) is destroyed BEFORE the SBDebugger
                # Otherwise lldb will try to lock a destroyed mutex.
                # TODO: Track that bug!
                listener = None
                lldb.SBDebugger.Destroy(self.debugger)

        debug(debugDriver, 'leaving')
        set_driver_instance(None)
        if self.__on_exit_callback:
            self.__on_exit_callback()

    def __handle_breakpoint_event(self, ev):
        type = lldb.SBBreakpoint.GetBreakpointEventTypeFromEvent(ev)

        # TODO: Remove duplicate code for adding/deleting BP
        if type & lldb.eBreakpointEventTypeCommandChanged       \
            or type & lldb.eBreakpointEventTypeIgnoreChanged    \
            or type & lldb.eBreakpointEventTypeConditionChanged \
            or type & lldb.eBreakpointEventTypeLocationsResolved:
            None
        elif type & lldb.eBreakpointEventTypeAdded:
            # TODO: show disabled bps
            bp = lldb.SBBreakpoint.GetBreakpointFromEvent(ev)
            for loc in bp:
                entry = None
                if loc and loc.GetAddress():
                    line_entry = loc.GetAddress().GetLineEntry()
                    if line_entry:
                        filespec = line_entry.GetFileSpec()

                        if filespec:
                            entry = (filespec.GetDirectory() + '/' + filespec.GetFilename(), \
                                     line_entry.GetLine())
                        else:
                            return None
                if entry:
                    ui_updater().breakpoint_added(entry[0], entry[1], loc.IsEnabled())

        elif type & lldb.eBreakpointEventTypeEnabled    \
              or type & lldb.eBreakpointEventTypeDisabled:
            bp = lldb.SBBreakpoint.GetBreakpointFromEvent(ev)
            for loc in bp:
                entry = None
                if loc and loc.GetAddress():
                    line_entry = loc.GetAddress().GetLineEntry()
                    if line_entry:
                        filespec = line_entry.GetFileSpec()

                        if filespec:
                            entry = (filespec.GetDirectory() + '/' + filespec.GetFilename(), \
                                     line_entry.GetLine())
                        else:
                            return None
                if entry:
                    ui_updater().breakpoint_changed(entry[0], entry[1], loc.IsEnabled())

        elif type & lldb.eBreakpointEventTypeRemoved:
            bp = lldb.SBBreakpoint.GetBreakpointFromEvent(ev)
            for loc in bp:
                entry = None
                if loc and loc.GetAddress():
                    line_entry = loc.GetAddress().GetLineEntry()
                    if line_entry:
                        filespec = line_entry.GetFileSpec()

                        if filespec:
                            entry = (filespec.GetDirectory() + '/' + filespec.GetFilename(), \
                                     line_entry.GetLine())
                        else:
                            return None
                if entry:
                    ui_updater().breakpoint_removed(entry[0], entry[1], loc.IsEnabled())
        elif type & lldb.eBreakpointEventTypeLocationsAdded:
            new_locs = lldb.SBBreakpoint.GetNumBreakpointLocationsFromEvent(ev)
            if new_locs > 0:
                bp = lldb.SBBreakpoint.GetBreakpointFromEvent(ev)
                lldb_view_send("%d locations added to breakpoint %d\n" %
                    (new_locs, bp.GetID()))
        elif type & lldb.eBreakpointEventTypeLocationsRemoved:
            None

    def __handle_process_event(self, ev):
        type = ev.GetType()

        if type & lldb.SBProcess.eBroadcastBitSTDOUT:
            self.get_process_stdout()
        elif type & lldb.SBProcess.eBroadcastBitSTDOUT:
            self.get_process_stderr()
        elif type & lldb.SBProcess.eBroadcastBitInterrupt:
            debug(debugDriver, 'Got a process interrupt event!')
            lldbutil.get_description(ev)
            if self.__process_stopped_callback:
                self.__process_stopped_callback(self, lldb.SBProcess.GetProcessFromEvent(ev))
        elif type & lldb.SBProcess.eBroadcastBitStateChanged:
            self.get_process_stdout()
            self.get_process_stderr()

            # only after printing the std* can we print our prompts
            state = lldb.SBProcess.GetStateFromEvent(ev)
            if state == lldb.eStateInvalid:
                return

            process = lldb.SBProcess.GetProcessFromEvent(ev)
            assert process.IsValid()

            if state == lldb.eStateInvalid       \
                or state == lldb.eStateUnloaded  \
                or state == lldb.eStateConnected \
                or state == lldb.eStateAttaching \
                or state == lldb.eStateLaunching \
                or state == lldb.eStateStepping  \
                or state == lldb.eStateDetached:
                lldb_view_send("Process %llu %s\n", process.GetProcessID(),
                    self.debugger.StateAsCString(state))

            elif state == lldb.eStateRunning:
                None  # Don't be too chatty
            elif state == lldb.eStateExited:
                debug(debugDriver, 'process state: ' + lldbutil.state_type_to_str(state))
                r = self.interpret_command('process status')
                lldb_view_send(stdout_msg(r[0].GetOutput()))
                lldb_view_send(stderr_msg(r[0].GetError()))
                # Remove program counter markers
                if self.__process_stopped_callback:
                    self.__process_stopped_callback(self, process, state)
            elif state == lldb.eStateStopped     \
                or state == lldb.eStateCrashed   \
                or state == lldb.eStateSuspended:
                debug(debugDriver, 'process state: ' + lldbutil.state_type_to_str(state)) if state != lldb.eStateStopped else None

                if lldb.SBProcess.GetRestartedFromEvent(ev):
                    lldb_view_send('Process %llu stopped and was programmatically restarted.' %
                        process.GetProcessID())
                else:
                    self.update_selected_thread()
                    if self.__process_stopped_callback:
                        self.__process_stopped_callback(self, process, state)

    def interpret_command(self, cmd, add_to_history=False):
        result = lldb.SBCommandReturnObject()
        ci = self.debugger.GetCommandInterpreter()

        r = ci.HandleCommand(str(cmd), result, add_to_history)

        return (result, r)

    def update_selected_thread(self):
        debugger = self.debugger
        proc = debugger.GetSelectedTarget().GetProcess()
        if proc.IsValid():
            curr_thread = proc.GetSelectedThread()
            current_thread_stop_reason = curr_thread.GetStopReason()

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
                        debug(debugDriver, 'thread stop reason: ' + lldbutil.stop_reason_to_str(current_thread_stop_reason))
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

    def get_process_stdout(self):
        string = stdout_msg(self.debugger.GetSelectedTarget(). \
            GetProcess().GetSTDOUT(1024))
        while len(string) > 0:
            lldb_view_send(string)
            string = stdout_msg(self.debugger.GetSelectedTarget(). \
                GetProcess().GetSTDOUT(1024))

    def get_process_stderr(self):
        string = stderr_msg(self.debugger.GetSelectedTarget(). \
            GetProcess().GetSTDOUT(1024))
        while len(string) > 0:
            lldb_view_send(string)
            string = stderr_msg(self.debugger.GetSelectedTarget(). \
                GetProcess().GetSTDOUT(1024))


class IOChannel(threading.Thread):
    eBroadcastBitHasUserInput = 1 << 0
    eBroadcastBitUserInterrupt = 1 << 1
    eBroadcastBitThreadShouldExit = 1 << 2
    eBroadcastBitThreadDidStart = 1 << 3
    eBroadcastBitThreadDidExit = 1 << 4
    eAllEventBits = 0xffffffff

    NO_ASYNC = False
    ASYNC = True

    __driver = None
    __err_write = None
    __out_write = None
    __broadcaster = None

    def __init__(self, driver, pipe, out_write, err_write=None):
        super(IOChannel, self).__init__(name='sublime.lldb.io-channel')

        if err_write is None:
            err_write = out_write

        self.__driver = driver
        self.__err_write = err_write
        self.__out_write = out_write
        self.__broadcaster = lldb.SBBroadcaster('IOChannel')
        self.__io_channel_pipe = pipe

    @property
    def driver(self):
        return self.__driver

    @property
    def broadcaster(self):
        return self.__broadcaster

    def stop(self):
        if self.is_alive():
            self.broadcaster.BroadcastEventByType(IOChannel.eBroadcastBitThreadShouldExit)

        self.join()

    def out_write(self, string, async):
        self.__out_write(string)
        # if (asynchronous)
        #     m_driver->GetDebugger().NotifyTopInputReader (eInputReaderAsynchronousOutputWritten)

    def err_write(self, string, async):
        self.__err_write(string)
        # if (asynchronous)
        #     m_driver->GetDebugger().NotifyTopInputReader (eInputReaderAsynchronousErrorWritten)

    def run(self):
        thread_created('<' + self.name + '>')

        listener = lldb.SBListener('IOChannel.run')
        interpreter_broadcaster = self.driver.debugger.GetCommandInterpreter().GetBroadcaster()

        listener.StartListeningForEvents(interpreter_broadcaster,
                    lldb.SBCommandInterpreter.eBroadcastBitThreadShouldExit |   \
                    lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived)

        listener.StartListeningForEvents(self.broadcaster,
                    IOChannel.eBroadcastBitThreadShouldExit)

        listener.StartListeningForEvents(self.driver.broadcaster,
                    LldbDriver.eBroadcastBitReadyForInput |     \
                    LldbDriver.eBroadcastBitThreadShouldExit)

        self.broadcaster.BroadcastEventByType(IOChannel.eBroadcastBitThreadDidStart)

        done = False
        while not done:
            event = lldb.SBEvent()
            listener.WaitForEvent(BIG_TIMEOUT, event)
            if not event:
                continue

            event_type = event.GetType()
            if event.GetBroadcaster():
                if event.BroadcasterMatchesRef(self.driver.broadcaster):
                    if event_type & LldbDriver.eBroadcastBitReadyForInput:
                        self.driver.maybe_get_input()
                        line = self.__io_channel_pipe.readline()
                        if line == '':
                            done = True
                            continue
                        if line[-1] == '\n':
                            line = line[:-1]
                        event = lldb.SBEvent(self.eBroadcastBitHasUserInput, line)
                        self.broadcaster.BroadcastEvent(event)
                    if event_type & LldbDriver.eBroadcastBitThreadShouldExit:
                        done = True
                        continue
                elif event.BroadcasterMatchesRef(interpreter_broadcaster):
                    if event_type == lldb.SBCommandInterpreter.eBroadcastBitThreadShouldExit \
                        or event_type == lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived:
                        done = True
                elif event.BroadcasterMatchesRef(self.broadcaster):
                    if event_type & IOChannel.eBroadcastBitThreadShouldExit:
                        done = True
                        continue

        self.broadcaster.BroadcastEventByType(IOChannel.eBroadcastBitThreadDidExit)
        self.__driver = None
        debug(debugDriver, 'leaving')


from root_objects import set_driver_instance, lldb_view_send, LldbInputDelegate, ui_updater
from monitors import FileMonitor
from utilities import stderr_msg, stdout_msg
