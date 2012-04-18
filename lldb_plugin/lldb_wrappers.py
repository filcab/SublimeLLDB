# -*- mode: python; coding: utf-8 -*-

# import time

import lldb
import lldbutil
import sublime
import threading
# import traceback

BIG_TIMEOUT = 42000000
START_LLDB_TIMEOUT = 5


def debug(string):
    print threading.current_thread().name + ' ' + str(string)


debug('Loading LLDB wrappers for Sublime Text 2 plugin')


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

    def __init__(self, log_callback=None):
        super(LldbDriver, self).__init__()  # name='Driver')
        self.name = 'sublime.lldb.driver'
        lldb.SBDebugger.Initialize()
        self.__broadcaster = lldb.SBBroadcaster('Driver')

        # if log_callback:
            # self._debugger = lldb.SBDebugger.Create(False, log_callback)
        # else:
        self._debugger = lldb.SBDebugger.Create(False)
        set_driver_instance(self)
        self.__io_channel = IOChannel(self, lldb_view_send)
        # self._debugger.SetCloseInputOnEOF(False)
        self.__input_reader = lldb.SBInputReader()

    def __del__(self):
        del self.__io_channel
        del self.__broadcaster
        del self._debugger
        lldb.SBDebugger.Terminate()

    def input_reader_callback(self, *args, **kwargs):
        import pdb
        pdb.set_trace()
        debug('yaaay, input reader callback' + str(*args) + ', ' + str(**kwargs))

    def stop(self):
        self.broadcaster.BroadcastEventByType(LldbDriver.eBroadcastBitThreadShouldExit)

    @property
    def debugger(self):
        """The low-level SBDebugger for this driver."""
        return self._debugger

    @property
    def broadcaster(self):
        return self.__broadcaster

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

    def send_command(self, cmd):
        """Send a command asynchronously to the IO channel."""
        event = lldb.SBEvent(IOChannel.eBroadcastBitHasUserInput, str(cmd))
        self.io_channel.broadcaster.BroadcastEvent(event)

    def process_is_stopped(self):
        target = self.debugger.GetSelectedTarget()
        if target:
            process = target.GetProcess()
            if process:
                state = process.GetState()
                if lldb.SBDebugger.StateIsRunningState(state):
                    return False
        return True

    def is_ready_for_command(self):
        return self.process_is_stopped()

    def ready_for_command(self):
        """Send an eBroadcastBitReadyForInput if the debugger wasn't ready before this call."""
        if not self.__waiting_for_command:
            # self.__waiting_for_command = True
            self.broadcaster.BroadcastEventByType(LldbDriver.eBroadcastBitReadyForInput, False)

    @property
    def line_entry(self):
        frame = self.debugger.GetSelectedTarget().GetProcess().GetSelectedThread().GetSelectedFrame()
        entry = frame.GetLineEntry()
        filespec = entry.GetFileSpec()

        if filespec:
            return (filespec.GetDirectory(), filespec.GetFilename(), \
                    entry.GetLine())
        else:
            return None

    def run(self):
        thread_created('<' + self.name + '>')

        # bool quit_success = sb_interpreter.SetCommandOverrideCallback ("quit", QuitCommandOverrideCallback, this);
        # assert quit_success

        # Warn whoever started us that we can start working
        self.broadcaster.BroadcastEventByType(LldbDriver.eBroadcastBitThreadDidStart)

        error = lldb.SBError(self.__input_reader.Initialize(self.debugger,
                                                            self.input_reader_callback,
                                                            lldb.eInputReaderGranularityByte,
                                                            None,  # end token (NULL == never done)
                                                            None,  # Prompt (NULL == taken care of elsewhere)
                                                            False))  # echo input (we'll take care of this elsewhere)

        if error.Fail():
            # Fail now... We can't have any input reader
            sublime.error_message('error: ' + error.GetCString())
            return

        self.debugger.PushInputReader(self.__input_reader)

        sb_interpreter = self._debugger.GetCommandInterpreter()
        listener = lldb.SBListener('driver')  # self._debugger.GetListener())
        listener.StartListeningForEventClass(self._debugger,
                     lldb.SBTarget.GetBroadcasterClassName(),
                     lldb.SBTarget.eBroadcastBitBreakpointChanged)
        # This isn't in Driver.cpp. Check why it listens to those events (it uses SBDebugger's listener)
        listener.StartListeningForEventClass(self._debugger,
                     lldb.SBProcess.GetBroadcasterClassName(),
                     lldb.SBProcess.eBroadcastBitStateChanged |     \
                     lldb.SBProcess.eBroadcastBitInterrupt |        \
                     lldb.SBProcess.eBroadcastBitSTDOUT |           \
                     lldb.SBProcess.eBroadcastBitSTDERR)

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

                                elif ev_type & IOChannel.eBroadcastBitThreadShouldExit \
                                    or ev_type & IOChannel.eBroadcastBitThreadDidExit:
                                    self.is_done = True
                                    if ev_type & IOChannel.eBroadcastBitThreadDidExit:
                                        iochannel_thread_exited = True
                                    else:
                                        # TODO: handle_io_event is not implemented
                                        if self.handle_io_event(event):
                                            self.is_done = True
                            elif lldb.SBProcess.EventIsProcessEvent(event):
                                self.handle_process_event(event)
                            elif lldb.SBBreakpoint.EventIsBreakpointEvent(event):
                                self.handle_breakpoint_event(event)
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
                    if self.process_is_stopped():
                        self.ready_for_command()

                if not iochannel_thread_exited:
                    event.Clear()
                    listener.GetNextEventForBroadcasterWithType(self.io_channel.broadcaster,
                                                                IOChannel.eBroadcastBitThreadDidExit,
                                                                event)
                    if not event:
                        self.io_channel.stop()

                # Ensure the listener (and everything else, really) is destroyed BEFORE the SBDebugger
                # Otherwise lldb will try to lock a destroyed mutex.
                # TODO: Track that bug!
                listener = None
                lldb.SBDebugger.Destroy(self.debugger)

        debug('leaving')
        set_driver_instance(None)

    def handle_breakpoint_event(self, ev):
        type = lldb.SBBreakpoint.GetBreakpointEventTypeFromEvent(ev)
        # debug('breakpoint event: ' + lldbutil.get_description(ev))

        if type & lldb.eBreakpointEventTypeCommandChanged       \
            or type & lldb.eBreakpointEventTypeConditionChanged:
            None
        if type & lldb.eBreakpointEventTypeAdded                \
            or type & lldb.eBreakpointEventTypeEnabled          \
            or type & lldb.eBreakpointEventTypeLocationsResolved:
            # TODO: show disabled bps
            bp = lldb.SBBreakpoint.GetBreakpointFromEvent(ev)
            # debug('bp: ' + lldbutil.get_description(bp))
            for loc in bp:
                entry = None
                if loc and loc.GetAddress():
                    line_entry = loc.GetAddress().GetLineEntry()
                    if line_entry:
                        filespec = line_entry.GetFileSpec()

                        if filespec:
                            entry = (filespec.GetDirectory(), filespec.GetFilename(), \
                                     line_entry.GetLine())
                        else:
                            return None
                if entry:
                    marker_update('bp', (entry,))

        elif type & lldb.eBreakpointEventTypeDisabled         \
            or type & lldb.eBreakpointEventTypeIgnoreChanged:
            # We don't need the eBreakpointEventTypeRemoved type
            # Because breakpoints are first disabled and then removed.
            # or type & lldb.eBreakpointEventTypeRemoved            \
            # TODO: show disabled bps
            bp = lldb.SBBreakpoint.GetBreakpointFromEvent(ev)
            for loc in bp:
                entry = None
                if loc and loc.GetAddress():
                    line_entry = loc.GetAddress().GetLineEntry()
                    if line_entry:
                        filespec = line_entry.GetFileSpec()

                        if filespec:
                            entry = (filespec.GetDirectory(), filespec.GetFilename(), \
                                     line_entry.GetLine())
                        else:
                            return None
                if entry:
                    marker_update('bp', (entry, True))
        elif type & lldb.eBreakpointEventTypeLocationsAdded:
            new_locs = lldb.SBBreakpoint.GetNumBreakpointLocationsFromEvent(ev)
            if new_locs > 0:
                bp = lldb.SBBreakpoint.GetBreakpointFromEvent(ev)
                lldb_view_send("%d locations added to breakpoint %d\n" %
                    (new_locs, bp.GetID()))
        elif type & lldb.eBreakpointEventTypeLocationsRemoved:
            None

    def handle_process_event(self, ev):
        type = ev.GetType()
        # debug('process event: ' + lldbutil.get_description(ev))

        if type & lldb.SBProcess.eBroadcastBitSTDOUT:
            self.get_process_stdout()
        elif type & lldb.SBProcess.eBroadcastBitSTDOUT:
            self.get_process_stderr()
        elif type & lldb.SBProcess.eBroadcastBitInterrupt:
            debug('Got a process interrupt event!')
            lldbutil.get_description(ev)
        elif type & lldb.SBProcess.eBroadcastBitStateChanged:
            self.get_process_stdout()
            self.get_process_stderr()

            # only after printing the std* can we print our prompts
            state = lldb.SBProcess.GetStateFromEvent(ev)
            set_process_state(state)
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
                debug('process state: ' + lldbutil.state_type_to_str(state))
                r = interpret_command(self.debugger, 'process status')
                lldb_view_send(stdout_msg(r[0].GetOutput()))
                lldb_view_send(stderr_msg(r[0].GetError()))
                # Remove program counter markers
                marker_update('pc', (None,))
            elif state == lldb.eStateStopped     \
                or state == lldb.eStateCrashed   \
                or state == lldb.eStateSuspended:
                debug('process state: ' + lldbutil.state_type_to_str(state)) if state != lldb.eStateStopped else None

                if lldb.SBProcess.GetRestartedFromEvent(ev):
                    lldb_view_send('Process %llu stopped and was programmatically restarted.' %
                        process.GetProcessID())
                else:
                    self.update_selected_thread()
                    debugger = self.debugger
                    entry = None
                    line_entry = self.debugger.GetSelectedTarget().GetProcess().GetSelectedThread().GetSelectedFrame().GetLineEntry()
                    if line_entry:
                        # We don't need to run 'process status' like Driver.cpp
                        # Since we open the file and show the source line.
                        r = interpret_command(debugger, 'thread list')
                        lldb_view_send(stdout_msg(r[0].GetOutput()))
                        lldb_view_send(stderr_msg(r[0].GetError()))
                        r = interpret_command(debugger, 'frame info')
                        lldb_view_send(stdout_msg(r[0].GetOutput()))
                        lldb_view_send(stderr_msg(r[0].GetError()))

                        filespec = line_entry.GetFileSpec()

                        if filespec:
                            entry = (filespec.GetDirectory(), filespec.GetFilename(), \
                                     line_entry.GetLine())
                    else:
                        # Give us some assembly to check the crash/stop
                        r = interpret_command(debugger, 'process status')
                        lldb_view_send(stdout_msg(r[0].GetOutput()))
                        lldb_view_send(stderr_msg(r[0].GetError()))
                        if not line_entry:
                            # Get ALL the SBFrames
                            t = self.debugger.GetSelectedTarget().GetProcess().GetSelectedThread()
                            n = t.GetNumFrames()
                            for i in xrange(0, n):
                                f = t.GetFrameAtIndex(i)
                                if f:
                                    line_entry = f.GetLineEntry()
                                    if line_entry and line_entry.GetFileSpec():
                                        filespec = line_entry.GetFileSpec()

                                        if filespec:
                                            entry = (filespec.GetDirectory(), filespec.GetFilename(), \
                                                     line_entry.GetLine())
                                            break

                    scope = 'bookmark'
                    if state == lldb.eStateCrashed:
                        scope = 'invalid'
                    marker_update('pc', (entry, scope))

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
                        debug('thread stop reason: ' + lldbutil.stop_reason_to_str(current_thread_stop_reason))
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


# def get_breakpoints(debugger):
#     bps = []
#     target = debugger.GetSelectedTarget()
#     if target:
#         n = target.GetNumBreakpoints()
#         for i in xrange(n):
#             bps.insert(i, BreakpointWrapper(debugger.GetSelectedTarget()
#                                                     .GetBreakpointAtIndex(i)))

#     return bps


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

    def __init__(self, driver, out_write, err_write=None):
        super(IOChannel, self).__init__()
        self.name = 'sublime.lldb.io-channel'

        if err_write is None:
            err_write = out_write

        self.__driver = driver
        self.__err_write = err_write
        self.__out_write = out_write
        self.__broadcaster = lldb.SBBroadcaster('IOChannel')

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
                        LldbInputDelegate.get_input()
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
        debug('leaving')


def interpret_command(debugger, cmd, add_to_history=False):
    result = lldb.SBCommandReturnObject()
    ci = debugger.GetCommandInterpreter()

    r = ci.HandleCommand(cmd.__str__(), result, add_to_history)

    return (result, r)


_success_returns = [lldb.eReturnStatusSuccessFinishNoResult,        \
                    lldb.eReturnStatusSuccessFinishResult,          \
                    lldb.eReturnStatusSuccessContinuingNoResult,    \
                    lldb.eReturnStatusSuccessContinuingResult]
                    # lldb.eReturnStatusStarted]
_finished_returns = [lldb.eReturnStatusSuccessFinishNoResult,       \
                     lldb.eReturnStatusSuccessFinishResult]

_continuing_returns = [lldb.eReturnStatusSuccessContinuingNoResult, \
                       lldb.eReturnStatusSuccessContinuingResult]


def is_return_success(r):
    return r in _success_returns


def is_return_finished(r):
    return r in _finished_returns


def is_return_continuing(r):
    return r in _continuing_returns


def is_return_started(r):
    return r == lldb.eReturnStatusStarted


def is_return_quit(r):
    return r == lldb.eReturnStatusQuit


def is_return_failed(r):
    return r == lldb.eReturnStatusFailed


def is_return_invalid(r):
    return r == lldb.eReturnStatusInvalid


from root_objects import set_driver_instance, lldb_view_send, set_process_state, LldbInputDelegate
from monitors import marker_update
from utilities import stderr_msg, stdout_msg
