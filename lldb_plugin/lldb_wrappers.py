# -*- mode: python; coding: utf-8 -*-

import time

import lldb
import lldbutil
import threading
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


class LldbDriver(object):
    def __init__(self, source_init_files, log_writer):
        debug('Initting LldbDriver')
        if log_writer is None:
            self._debugger = lldb.SBDebugger.Create(source_init_files)
        else:
            self._debugger = lldb.SBDebugger.Create(source_init_files, log_writer)

    @property
    def debugger(self):
        return self._debugger

    @property
    def line_entry(self):
        frame = self.debugger.GetSelectedTarget().GetProcess().GetSelectedThread().GetSelectedFrame()
        entry = frame.GetLineEntry()
        filespec = entry.GetFileSpec()

        if filespec:
            return (filespec.GetDirectory(), filespec.GetFilename(), \
                    entry.GetLine(), entry.GetColumn())
        else:
            return None

    @property
    def first_line_entry_with_source(self):
        entry = self.line_entry
        if entry:
            return entry
        else:
            # Get ALL the SBStackFrames
            debug('going through stackframes')
            t = self.debugger.GetSelectedTarget().GetProcess().GetSelectedThread()
            n = t.GetNumFrames()
            for i in xrange(0, n):
                f = t.GetFrameAtIndex(i)
                if f:
                    entry = f.line_entry
                    if entry and entry.GetFileSpec():
                        filespec = entry.GetFileSpec()

                        if filespec:
                            return (filespec.GetDirectory(), filespec.GetFilename(), \
                                    entry.GetLine(), entry.GetColumn())
                        else:
                            return None
            debug('not touching stackframes any more')

            return None


def get_breakpoints(debugger):
    bps = []
    target = debugger.GetSelectedTarget()
    if target:
        n = target.GetNumBreakpoints()
        for i in xrange(n):
            bps.insert(i, BreakpointWrapper(debugger.GetSelectedTarget()
                                                    .GetBreakpointAtIndex(i)))

    return bps


def interpret_command(debugger, cmd, add_to_history=False):
    result = lldb.SBCommandReturnObject()
    ci = debugger.GetCommandInterpreter()

    r = ci.HandleCommand(cmd.__str__(), result, add_to_history)

    return (result, r)


class LldbWrapper(lldb.SBDebugger):
    @property
    def frame(self):
        return self.GetSelectedTarget().GetProcess() \
                   .GetSelectedThread().GetSelectedFrame()

    @property
    def target(self):
        return TargetWrapper(self.GetSelectedTarget())

    # @property
    # def symbol_context(self):
    #     return self.frame().GetSymbolContext(0xffffffff)

    def destroy(self):
        lldb.SBDebugger.Destroy(self.lldb)
        self.lldb = None

    @property
    def SBDebugger(self):
        return self

    # # bridges to SBDebugger methods:
    # def set_async(self, async):
    #     self.__lldb.SetAsync(async)

    # CamelCase methods are simple bridges to the SBDebugger object
    # def GetCommandInterpreter(self):
    #     return self.lldb.GetCommandInterpreter()

    # def GetCommandInterpreter(self):
    #     return self.__lldb.GetCommandInterpreter()

    # def SetInputFileHandle(self, fh, transfer_ownership):
    #     self.__lldb.SetInputFileHandle(fh, transfer_ownership)

    # def SetOutputFileHandle(self, fh, transfer_ownership):
    #     self.__lldb.SetOutputFileHandle(fh, transfer_ownership)

    # def SetErrorFileHandle(self, fh, transfer_ownership):
    #     self.__lldb.SetErrorFileHandle(fh, transfer_ownership)

    # def GetInputFileHandle(self):
    #     return self.__lldb.GetInputFileHandle()

    # def GetOutputFileHandle(self):
    #     return self.__lldb.GetOutputFileHandle()

    # def GetErrorFileHandle(self):
    #     return self.__lldb.GetErrorFileHandle()

    # def SetAsync(self, arg):
    #     return self.__lldb.SetAsync(arg)

    # def StateAsCString(self, state):
    #     return self.__lldb.StateAsCString(state)


class TargetWrapper(lldb.SBTarget):
    def __init__(self, t):
        self.__t = t

    @property
    def process(self):
        return ProcessWrapper(self.GetProcess())

    # def __getattr__(self, name):
    #     return self.__t.__getattr__(name)

    # def __setattr__(self, name, value):
    #     self.__t.__setattr__(name, value)


class ProcessWrapper(lldb.SBProcess):
    def __init__(self, p=None):
        self.__p = p

    @property
    def num_threads(self):
        return self.GetNumThreads()

    @property
    def thread(self):
        return ThreadWrapper(self.GetSelectedThread())

    @property
    def valid(self):
        return self.IsValid()

    def __iter__(self):
        for t in self.__p:
            debug(t)
            yield ThreadWrapper(t)

    def __nonzero__(self):
        if self.__p:
            return True
        else:
            return False

    def SetSelectedThread(self, t):
        self.SetSelectedThread(t.SBThread)

    def GetThreadAtIndex(self, i):
        return ThreadWrapper(self.__p.GetThreadAtIndex(i))

    # def __getattr__(self, name):
    #     return self.__p.__getattr__(name)

    # def __setattr__(self, name, value):
    #     self.__p.__setattr__(name, value)


class ThreadWrapper(lldb.SBThread):
    def __init__(self, t=None):
        self.__t = t

    @property
    def stop_reason(self):
        return self.GetStopReason()

    @property
    def valid(self):
        return self.IsValid()

    def __nonzero__(self):
        if self.__t:
            return True
        else:
            return False

    def __iter__(self):
        for f in self.__t:
            yield FrameWrapper(f)

    @property
    def SBThread(self):
        return self.__t

    # def __getattr__(self, name):
    #     return self.__t.__getattr__(name)

    # def __setattr__(self, name, value):
    #     self.__t.__setattr__(name, value)


class FrameWrapper(lldb.SBFrame):
    def __init__(self, f):
        self.__f = f

    @property
    def line_entry(self):
        entry = self.GetLineEntry()
        debug('entry: ' + str(entry))
        filespec = entry.GetFileSpec()
        debug('filespec: ' + str(filespec))

        if filespec:
            return (filespec.GetDirectory(), filespec.GetFilename(), \
                    entry.GetLine(), entry.GetColumn())
        else:
            return None

    # def __getattr__(self, name):
    #     return self.__f.__getattr__(name)

    # def __setattr__(self, name, value):
    #     self.__f.__setattr__(name, value)


class BreakpointWrapper(lldb.SBBreakpoint):
    def __init__(self, b):
        self.__b = b

    def enabled(self):
        return self.IsEnabled()

    def line_entries(self):
        entries = []

        n = self.GetNumLocations()
        for i in xrange(n):
            bp_loc = self.GetLocationAtIndex(i)
            addr = bp_loc.GetAddress()
            entry = addr.GetLineEntry()
            filespec = entry.GetFileSpec()

            if filespec:
                entries.insert(i, (filespec.GetDirectory(), \
                                   filespec.GetFilename(),  \
                                   entry.GetLine(),         \
                                   entry.GetColumn()))
            else:
                entries.insert(i, None)

        return entries

    # def __getattr__(self, name):
    #     return self.__b.__getattr__(name)

    # def __setattr__(self, name, value):
    #     self.__b.__setattr__(name, value)


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


class LldbCommandReturnWrapper(lldb.SBCommandReturnObject):
    def ReturnObject(self):
        return self

    @property
    def error(self):
        return self.GetError()

    @property
    def output(self):
        return self.GetOutput()


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


class LldbListener(lldb.SBListener):
    @property
    def SBListener(self):
        return self

    @property
    def valid(self):
        return self.IsValid()

    def start_listening_for_events(self, broadcaster, events):
        b = broadcaster
        if isinstance(b, LldbBroadcaster):
            b = b.SBBroadcaster

        self.StartListeningForEvents(b, events)


    # def __getattr__(self, name):
    #     return self.__listener.__getattr__(name)

    # def __setattr__(self, name, value):
    #     self.__listener.__setattr__(name, value)


class LldbBroadcaster(lldb.SBBroadcaster):
    def __init__(self, broadcaster):
        self.__broadcaster = broadcaster

    @property
    def SBBroadcaster(self):
        return self.__broadcaster

    @property
    def valid(self):
        return self.__broadcaster.IsValid()

    # def __getattr__(self, name):
    #     return self.__broadcaster.__getattr__(name)

    # def __setattr__(self, name, value):
    #     self.__broadcaster.__setattr__(name, value)


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
        self.BroadcastEventByType(self.eBroadcastBitThreadShouldExit)
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

    def run(self, debugger):
        thread_created(threading.current_thread().name)

        time.sleep(1)

        def debug(object):
            print threading.current_thread().name + ' ' + str(object)

        listener = LldbListener('SublimeListener')
        interpreter_broadcaster = debugger.debugger.GetCommandInterpreter().GetBroadcaster()
        listener.StartListeningForEvents(interpreter_broadcaster,
                                         lldb.SBCommandInterpreter.eBroadcastBitThreadShouldExit | \
                                         lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived)

        listener.StartListeningForEvents(self, SublimeBroadcaster.eBroadcastBitShouldExit | \
                                               SublimeBroadcaster.eBroadcastBitHasInput)

        debug('broadcasting DidStart')
        self.BroadcastEventByType(SublimeBroadcaster.eBroadcastBitDidStart)

        done = False
        while not done:
            debug('listening at: ' + str(listener.SBListener))
            event = lldb.SBEvent()
            listener.WaitForEvent(BIG_TIMEOUT, event)
            if not event.IsValid():  # timeout
                continue

            debug('SublimeBroadcaster: got event: ' + lldbutil.get_description(event))
            if event.GetBroadcaster().IsValid():
                type = event.GetType()
                if event.BroadcasterMatchesRef(interpreter_broadcaster):
                    if type & lldb.SBCommandInterpreter.eBroadcastBitThreadShouldExit \
                        or type & lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived:
                        debug('exiting from broadcaster due to interpreter')
                        done = True
                        continue
                elif event.BroadcasterMatchesRef(self):
                    if type & SublimeBroadcaster.eBroadcastBitShouldExit:
                        debug('exiting from broadcaster due to self')
                        done = True
                        continue
                    if type & SublimeBroadcaster.eBroadcastBitHasInput:
                        cmd = lldb.SBEvent.GetCStringFromEvent(event)
                        # TODO: This shouldn't happen!
                        # GetCStringFromEvent() is returning None when the string is empty.
                        if cmd is None:
                            cmd = ''

                        event = lldb.SBEvent(SublimeBroadcaster.eBroadcastBitHasCommandInput, str(cmd))
                        self.BroadcastEvent(event)
                        continue

        self.BroadcastEventByType(SublimeBroadcaster.eBroadcastBitShouldExit)
        debug('leaving...')
        del self.__debugger
        self.BroadcastEventByType(SublimeBroadcaster.eBroadcastBitDidExit)




                # if event.broadcaster_matches_ref(driver):
