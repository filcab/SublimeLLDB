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


# class LldbWrapper(lldb.SBDebugger):
#     @property
#     def frame(self):
#         return self.GetSelectedTarget().GetProcess() \
#                    .GetSelectedThread().GetSelectedFrame()

#     @property
#     def target(self):
#         return TargetWrapper(self.GetSelectedTarget())

#     # @property
#     # def symbol_context(self):
#     #     return self.frame().GetSymbolContext(0xffffffff)

#     def destroy(self):
#         lldb.SBDebugger.Destroy(self.lldb)
#         self.lldb = None

#     @property
#     def SBDebugger(self):
#         return self

#     # # bridges to SBDebugger methods:
#     # def set_async(self, async):
#     #     self.__lldb.SetAsync(async)

#     # CamelCase methods are simple bridges to the SBDebugger object
#     # def GetCommandInterpreter(self):
#     #     return self.lldb.GetCommandInterpreter()

#     # def GetCommandInterpreter(self):
#     #     return self.__lldb.GetCommandInterpreter()

#     # def SetInputFileHandle(self, fh, transfer_ownership):
#     #     self.__lldb.SetInputFileHandle(fh, transfer_ownership)

#     # def SetOutputFileHandle(self, fh, transfer_ownership):
#     #     self.__lldb.SetOutputFileHandle(fh, transfer_ownership)

#     # def SetErrorFileHandle(self, fh, transfer_ownership):
#     #     self.__lldb.SetErrorFileHandle(fh, transfer_ownership)

#     # def GetInputFileHandle(self):
#     #     return self.__lldb.GetInputFileHandle()

#     # def GetOutputFileHandle(self):
#     #     return self.__lldb.GetOutputFileHandle()

#     # def GetErrorFileHandle(self):
#     #     return self.__lldb.GetErrorFileHandle()

#     # def SetAsync(self, arg):
#     #     return self.__lldb.SetAsync(arg)

#     # def StateAsCString(self, state):
#     #     return self.__lldb.StateAsCString(state)


# class TargetWrapper(lldb.SBTarget):
#     def __init__(self, t):
#         self.__t = t

#     @property
#     def process(self):
#         return ProcessWrapper(self.GetProcess())

#     # def __getattr__(self, name):
#     #     return self.__t.__getattr__(name)

#     # def __setattr__(self, name, value):
#     #     self.__t.__setattr__(name, value)


# class ProcessWrapper(lldb.SBProcess):
#     def __init__(self, p=None):
#         self.__p = p

#     @property
#     def num_threads(self):
#         return self.GetNumThreads()

#     @property
#     def thread(self):
#         return ThreadWrapper(self.GetSelectedThread())

#     @property
#     def valid(self):
#         return self.IsValid()

#     def __iter__(self):
#         for t in self.__p:
#             debug(t)
#             yield ThreadWrapper(t)

#     def __nonzero__(self):
#         if self.__p:
#             return True
#         else:
#             return False

#     def SetSelectedThread(self, t):
#         self.SetSelectedThread(t.SBThread)

#     def GetThreadAtIndex(self, i):
#         return ThreadWrapper(self.__p.GetThreadAtIndex(i))

#     # def __getattr__(self, name):
#     #     return self.__p.__getattr__(name)

#     # def __setattr__(self, name, value):
#     #     self.__p.__setattr__(name, value)


# class ThreadWrapper(lldb.SBThread):
#     def __init__(self, t=None):
#         self.__t = t

#     @property
#     def stop_reason(self):
#         return self.GetStopReason()

#     @property
#     def valid(self):
#         return self.IsValid()

#     def __nonzero__(self):
#         if self.__t:
#             return True
#         else:
#             return False

#     def __iter__(self):
#         for f in self.__t:
#             yield FrameWrapper(f)

#     @property
#     def SBThread(self):
#         return self.__t

#     # def __getattr__(self, name):
#     #     return self.__t.__getattr__(name)

#     # def __setattr__(self, name, value):
#     #     self.__t.__setattr__(name, value)


# class FrameWrapper(lldb.SBFrame):
#     def __init__(self, f):
#         self.__f = f

#     @property
#     def line_entry(self):
#         entry = self.GetLineEntry()
#         debug('entry: ' + str(entry))
#         filespec = entry.GetFileSpec()
#         debug('filespec: ' + str(filespec))

#         if filespec:
#             return (filespec.GetDirectory(), filespec.GetFilename(), \
#                     entry.GetLine(), entry.GetColumn())
#         else:
#             return None

#     # def __getattr__(self, name):
#     #     return self.__f.__getattr__(name)

#     # def __setattr__(self, name, value):
#     #     self.__f.__setattr__(name, value)


# class BreakpointWrapper(lldb.SBBreakpoint):
#     def __init__(self, b):
#         self.__b = b

#     def enabled(self):
#         return self.IsEnabled()

#     def line_entries(self):
#         entries = []

#         n = self.GetNumLocations()
#         for i in xrange(n):
#             bp_loc = self.GetLocationAtIndex(i)
#             addr = bp_loc.GetAddress()
#             entry = addr.GetLineEntry()
#             filespec = entry.GetFileSpec()

#             if filespec:
#                 entries.insert(i, (filespec.GetDirectory(), \
#                                    filespec.GetFilename(),  \
#                                    entry.GetLine(),         \
#                                    entry.GetColumn()))
#             else:
#                 entries.insert(i, None)

#         return entries

#     # def __getattr__(self, name):
#     #     return self.__b.__getattr__(name)

#     # def __setattr__(self, name, value):
#     #     self.__b.__setattr__(name, value)


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


# class LldbCommandReturnWrapper(lldb.SBCommandReturnObject):
#     def ReturnObject(self):
#         return self

#     @property
#     def error(self):
#         return self.GetError()

#     @property
#     def output(self):
#         return self.GetOutput()


# Listeners and broadcasters
def start_listening_for_process_events(listener, debugger):
    listener.StartListeningForEventClass(debugger,
        lldb.SBProcess.GetBroadcasterClassName(),
        lldb.SBProcess.eBroadcastBitStateChanged |      \
        lldb.SBProcess.eBroadcastBitInterrupt |         \
        lldb.SBProcess.eBroadcastBitSTDOUT |            \
        lldb.SBProcess.eBroadcastBitSTDERR)


def start_listening_for_breakpoint_changes(listener, debugger):
    listener.StartListeningForEventClass(debugger,
        lldb.SBTarget.GetBroadcasterClassName(),
        lldb.SBTarget.eBroadcastBitBreakpointChanged)


# class LldbListener(lldb.SBListener):
#     @property
#     def SBListener(self):
#         return self

#     @property
#     def valid(self):
#         return self.IsValid()

#     def start_listening_for_events(self, broadcaster, events):
#         b = broadcaster
#         if isinstance(b, LldbBroadcaster):
#             b = b.SBBroadcaster

#         self.StartListeningForEvents(b, events)


#     # def __getattr__(self, name):
#     #     return self.__listener.__getattr__(name)

#     # def __setattr__(self, name, value):
#     #     self.__listener.__setattr__(name, value)


# class LldbBroadcaster(lldb.SBBroadcaster):
#     def __init__(self, broadcaster):
#         self.__broadcaster = broadcaster

#     @property
#     def SBBroadcaster(self):
#         return self.__broadcaster

#     @property
#     def valid(self):
#         return self.__broadcaster.IsValid()

#     # def __getattr__(self, name):
#     #     return self.__broadcaster.__getattr__(name)

#     # def __setattr__(self, name, value):
#     #     self.__broadcaster.__setattr__(name, value)


class SublimeBroadcaster(lldb.SBBroadcaster):

    eBroadcastBitHasInput = 1 << 0
    eBroadcastBitHasCommandInput = 1 << 1
    eBroadcastBitDidStart = 1 << 2
    eBroadcastBitShouldExit = 1 << 3
    eBroadcastBitDidExit = 1 << 4
    eBroadcastBitsSTDIN = 1 << 5
    eBroadcastBitsSTDOUT = 1 << 6
    eBroadcastBitsSTDERR = 1 << 7
    eAllEventBits = 0xffffffff

    def __init__(self, debugger):
        super(SublimeBroadcaster, self).__init__('SublimeBroadcaster')
        self.__debugger = debugger
        self.__output_fun = debug

    def set_output_fun(self, fun):
        self.__output_fun = fun

    @property
    def SBBroadcaster(self):
        return self

    def end(self):
        self.broadcaster.BroadcastEventByType(self.eBroadcastBitThreadShouldExit)
        if self.__t:
            self.__t.kill()
        del self.__t

    def start(self, debugger):
        debug('creating thread: <' + self.GetName() + '>')
        self.__t = threading.Thread(name='<' + self.GetName() + '>', target=self.run, args=(debugger,))
        self.__t.start()

    def send_command(self, cmd):
        event = lldb.SBEvent(SublimeBroadcaster.eBroadcastBitHasInput, str(cmd))
        self.BroadcastEvent(event)

    # def run(self, debugger):
    #     thread_created(threading.current_thread().name)

    #     time.sleep(1)

    #     def debug(object):
    #         print threading.current_thread().name + ' ' + str(object)

    #     listener = LldbListener('SublimeListener')
    #     interpreter_broadcaster = debugger.debugger.GetCommandInterpreter().GetBroadcaster()
    #     listener.StartListeningForEvents(interpreter_broadcaster,
    #                                      lldb.SBCommandInterpreter.eBroadcastBitThreadShouldExit | \
    #                                      lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived)

    #     listener.StartListeningForEvents(self, SublimeBroadcaster.eBroadcastBitShouldExit | \
    #                                            SublimeBroadcaster.eBroadcastBitHasInput)

    #     debug('broadcasting DidStart')
    #     self.BroadcastEventByType(SublimeBroadcaster.eBroadcastBitDidStart)

    #     done = False
    #     while not done:
    #         debug('listening at: ' + str(listener.SBListener))
    #         event = lldb.SBEvent()
    #         listener.WaitForEvent(BIG_TIMEOUT, event)
    #         if not event.IsValid():  # timeout
    #             continue

    #         debug('SublimeBroadcaster: got event: ' + lldbutil.get_description(event))
    #         if event.GetBroadcaster().IsValid():
    #             type = event.GetType()
    #             if event.BroadcasterMatchesRef(interpreter_broadcaster):
    #                 if type & lldb.SBCommandInterpreter.eBroadcastBitThreadShouldExit \
    #                     or type & lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived:
    #                     debug('exiting from broadcaster due to interpreter')
    #                     done = True
    #                     continue
    #             elif event.BroadcasterMatchesRef(self):
    #                 if type & SublimeBroadcaster.eBroadcastBitShouldExit:
    #                     debug('exiting from broadcaster due to self')
    #                     done = True
    #                     continue
    #                 if type & SublimeBroadcaster.eBroadcastBitHasInput:
    #                     cmd = lldb.SBEvent.GetCStringFromEvent(event)
    #                     # TODO: This shouldn't happen!
    #                     # GetCStringFromEvent() is returning None when the string is empty.
    #                     if cmd is None:
    #                         cmd = ''

    #                     event = lldb.SBEvent(SublimeBroadcaster.eBroadcastBitHasCommandInput, str(cmd))
    #                     self.BroadcastEvent(event)
    #                     continue

    #     self.BroadcastEventByType(SublimeBroadcaster.eBroadcastBitShouldExit)
    #     debug('leaving...')
    #     del self.__debugger
    #     self.BroadcastEventByType(SublimeBroadcaster.eBroadcastBitDidExit)
