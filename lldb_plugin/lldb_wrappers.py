# -*- mode: python; coding: utf-8 -*-

# import time

import lldb
# import lldbutil
import threading
from root_objects import set_driver_instance, lldb_view_send, lldb_view_write
from utilities import stderr_msg, stdout_msg
# import traceback

BIG_TIMEOUT = 42000000


def debug(str):
    print str


debug('Loading LLDB wrappers for Sublime Text 2 plugin')


def version():
    return lldb.SBDebugger.GetVersionString()


def initialize():
    lldb.SBDebugger.Initialize()


def terminate():
    lldb.SBDebugger.Terminate()


def thread_created(string):
    lldb.SBHostOS.ThreadCreated(string)


class LldbDriver(threading.Thread):
    eBroadcastBitThreadShouldExit = 1 << 0

    __is_done = False
    __io_channel = None
    __broadcaster = None
    __debug_mode = False
    __waiting_for_command = False

    def __init__(self):
        debug('Initting LldbDriver')
        self.__broadcaster = lldb.SBBroadcaster('Driver')
        self._debugger = lldb.SBDebugger.Create(False)
        set_driver_instance(self)
        # self._debugger.SetCloseInputOnEOF(False)

    @property
    def debugger(self):
        return self._debugger

    @property
    def broadcaster(self):
        return self.__broadcaster

    @property
    def debug_mode(self):
        """True if the driver is in debug mode"""
        return self.__debug_mode

    @debug_mode.setter
    def debug_mode(self, value):
        self.__debug_mode = value

    @debug_mode.deleter
    def debug_mode(self):
        del self.__debug_mode

    @property
    def io_channel(self):
        return self.__io_channel

    @io_channel.deleter
    def io_channel(self):
        del self.__io_channel

    @property
    def is_done(self):
        return self.__is_done

    @is_done.setter
    def is_done(self, done):
        self.__is_done = done

    def send_command(self, cmd):
        event = lldb.SBEvent(IOChannel.eBroadcastBitHasUserInput, str(cmd))
        self.io_channel.broadcaster.BroadcastEvent(event)

    def ready_for_command(self):
        if not self.__waiting_for_command:
            self.__ready_for_command = True
            self.broadcaster.BroadcastEventByType(LldbDriver.eBroadcastBitReadyForInput, True)

    # @property
    # def line_entry(self):
    #     frame = self.debugger.GetSelectedTarget().GetProcess().GetSelectedThread().GetSelectedFrame()
    #     entry = frame.GetLineEntry()
    #     filespec = entry.GetFileSpec()

    #     if filespec:
    #         return (filespec.GetDirectory(), filespec.GetFilename(), \
    #                 entry.GetLine(), entry.GetColumn())
    #     else:
    #         return None

    # @property
    # def first_line_entry_with_source(self):
    #     entry = self.line_entry
    #     if entry:
    #         return entry
    #     else:
    #         # Get ALL the SBStackFrames
    #         debug('going through stackframes')
    #         t = self.debugger.GetSelectedTarget().GetProcess().GetSelectedThread()
    #         n = t.GetNumFrames()
    #         for i in xrange(0, n):
    #             f = t.GetFrameAtIndex(i)
    #             if f:
    #                 entry = f.line_entry
    #                 if entry and entry.GetFileSpec():
    #                     filespec = entry.GetFileSpec()

    #                     if filespec:
    #                         return (filespec.GetDirectory(), filespec.GetFilename(), \
    #                                 entry.GetLine(), entry.GetColumn())
    #                     else:
    #                         return None
    #         debug('not touching stackframes any more')

    #         return None

    def run(self):
        thread_created(threading.current_thread().name)

        # bool quit_success = sb_interpreter.SetCommandOverrideCallback ("quit", QuitCommandOverrideCallback, this);
        # assert quit_success
        self.__io_channel = IOChannel(self, lldb_view_write)

        sb_interpreter = self._debugger.GetCommandInterpreter()
        listener = lldb.SBListener(self._debugger.GetListener())
        listener.StartListeningForEventClass(self._debugger,
                     lldb.SBTarget.GetBroadcasterClassName(),
                     lldb.SBTarget.eBroadcastBitBreakpointChanged)

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

                sb_interpreter.SourceInitFileInCurrentWorkingDirectory()
                if self.debug_mode:
                    result.PutError(self.debugger.GetErrorFileHandle())
                    result.PutOutput(self.debugger.GetOutputFileHandle())

                event = lldb.SBEvent()
                listener.WaitForEventForBroadcasterWithType(BIG_TIMEOUT,
                            self.io_channel.broadcaster,
                            IOChannel.eBroadcastBitThreadDidStart,
                            event)

                self.ready_for_command = True

                while not self.is_done:
                    listener.WaitForEvent(BIG_TIMEOUT, event)
                    if event:
                        if event.GetBroadcaster():
                            ev_type = event.GetType()
                            if (event.BroadcasterMatchesRef(self.io_channel.broadcaster)):
                                if ev_type & IOChannel.eBroadcastBitHasUserInput:
                                    command_string = lldb.SBEvent.GetCStringFromEvent(event)
                                    if (command_string == NULL)
                                        command_string = ''
                                    result = lldb.SBCommandReturnObject()

                                    self.debugger.GetCommandInterpreter().HandleCommand(command_string, result, True)
                                    if result.GetOutputSize() > 0:
                                        self.io_channel.out_write(result.GetOutput(), result.GetOutputSize(), IOChannel.NO_ASYNC)

                                    if result.GetErrorSize() > 0:
                                        self.io_channel.err_write(result.GetError(), result.GetErrorSize(), IOChannel.NO_ASYNC)

                                elif ev_type & IOChannel.eBroadcastBitThreadShouldExit \
                                    or ev_type & IOChannel.eBroadcastBitThreadDidExit:
                                    self.is_done = True
                                    if ev_type & IOChannel.eBroadcastBitThreadDidExit:
                                        iochannel_thread_exited = True
                                    else:
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

                if not iochannel_thread_exited:
                    event.Clear()
                    listener.GetNextEventForBroadcasterWithType(self.io_channel.broadcaster,
                                                                IOChannel.eBroadcastBitThreadDidExit,
                                                                event)
                    if not event:
                        self.io_channel.stop()

                lldb.SBDebugger.Destroy(self.debugger)


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

    SYNC = 0
    ASYNC = 1

    __driver = None
    __err_write = None
    __out_write = None
    __broadcaster = None

    def __init__(self, driver, out_write, err_write=None):
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

    def run(self):
        listener = lldb.SBListener('IOChannel.run')
        interpreter_broadcaster = self.driver.debugger.GetCommandInterpreter().GetBroadcaster()

        listener.StartListeningForEvents(interpreter_broadcaster,
                    lldb.SBCommandInterpreter.eBroadcastBitThreadShouldExit |   \
                    lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived)

        listener.StartListeningForEvents(self.broadcaster,
                    IOChannel.eBroadcastBitThreadShouldExit)

        listener.StartListeningForEvents(self.driver.broadcaster,
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
                if event.BroadcasterMatchesPtr(self.driver.broadcaster):
                    # if event_type & LldbDriver.eBroadcastBitReadyForInput
                    if event_type & LldbDriver.eBroadcastBitThreadShouldExit:
                        done = True
                        continue
                elif event.BroadcasterMatchesRef(interpreter_broadcaster):
                    if event_type == lldb.SBCommandInterpreter.eBroadcastBitThreadShouldExit \
                        or event_type == lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived:
                        done = True
                elif event.BroadcasterMatchesPtr(self.broadcaster):
                    if event_type & IOChannel.eBroadcastBitThreadShouldExit:
                        done = True
                        continue

        self.broadcaster.BroadcastEventByType(IOChannel.eBroadcastBitThreadDidExit)
        self.__driver = None


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
