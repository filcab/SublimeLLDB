# -*- mode: python; coding: utf-8 -*-

import time

import lldb
import lldbutil
import threading
# import traceback


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


class LldbWrapper(object):
    def __init__(self, source_init_files, log_callback=None):
        debug('Initting LldbWrapper')
        if log_callback is None:
            self.__lldb = lldb.SBDebugger.Create(source_init_files)
        else:
            self.__lldb = lldb.SBDebugger.Create(source_init_files, log_callback)
        self.__listener = LldbListener(
                            lldb.SBListener(
                                self.__lldb.GetListener()), self.__lldb)
        self.__last_cmd = ''

    def breakpoints(self):
        bps = []
        target = self.__lldb.GetSelectedTarget()
        if target:
            n = target.GetNumBreakpoints()
            for i in xrange(n):
                bps.insert(i, BreakpointWrapper(self.__lldb
                                                    .GetSelectedTarget()
                                                    .GetBreakpointAtIndex(i)))

        return bps

    @property
    def frame(self):
        return self.__lldb.GetSelectedTarget().GetProcess() \
                          .GetSelectedThread().GetSelectedFrame()

    @property
    def line_entry(self):
        entry = self.frame.GetLineEntry()
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
            t = self.target.process.thread.SBThread
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

    @property
    def target(self):
        return TargetWrapper(self.__lldb.GetSelectedTarget())

    # @property
    # def symbol_context(self):
    #     return self.frame().GetSymbolContext(0xffffffff)

    def destroy(self):
        self.__listener = None
        lldb.SBDebugger.Destroy(self.__lldb)
        self.__lldb = None

    def interpret_command(self, cmd, add_to_history=False):
        result = LldbCommandReturnWrapper()
        ci = self.__lldb.GetCommandInterpreter()

        r = LldbResultStatusWrapper(ci.HandleCommand(cmd.__str__(),
                                                     result.ReturnObject(),
                                                     add_to_history))

        return (result, r)

    @property
    def listener(self):
        return self.__listener

    @property
    def SBDebugger(self):
        return self.__lldb

    # bridges to SBDebugger methods:
    def set_async(self, async):
        self.__lldb.SetAsync(async)

    # CamelCase methods are simple bridges to the SBDebugger object
    # def GetCommandInterpreter(self):
    #     return self.lldb.GetCommandInterpreter()

    def GetCommandInterpreter(self):
        return self.__lldb.GetCommandInterpreter()

    def SetInputFileHandle(self, fh, transfer_ownership):
        self.__lldb.SetInputFileHandle(fh, transfer_ownership)

    def SetOutputFileHandle(self, fh, transfer_ownership):
        self.__lldb.SetOutputFileHandle(fh, transfer_ownership)

    def SetErrorFileHandle(self, fh, transfer_ownership):
        self.__lldb.SetErrorFileHandle(fh, transfer_ownership)

    def GetInputFileHandle(self):
        return self.__lldb.GetInputFileHandle()

    def GetOutputFileHandle(self):
        return self.__lldb.GetOutputFileHandle()

    def GetErrorFileHandle(self):
        return self.__lldb.GetErrorFileHandle()

    def SetAsync(self, arg):
        return self.__lldb.SetAsync(arg)

    def StateAsCString(self, state):
        return self.__lldb.StateAsCString(state)


class TargetWrapper(object):
    def __init__(self, t):
        self.__t = t

    @property
    def process(self):
        return ProcessWrapper(self.__t.GetProcess())


class ProcessWrapper(object):
    def __init__(self, p=None):
        self.__p = p

    @property
    def num_threads(self):
        return self.__p.GetNumThreads()

    @property
    def thread(self):
        return ThreadWrapper(self.__p.GetSelectedThread())

    @property
    def valid(self):
        return self.__p.IsValid()

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
        self.__p.SetSelectedThread(t.SBThread)

    def GetThreadAtIndex(self, i):
        return ThreadWrapper(self.__p.GetThreadAtIndex(i))


class ThreadWrapper(object):
    def __init__(self, t=None):
        self.__t = t

    @property
    def stop_reason(self):
        return self.__t.GetStopReason()

    @property
    def valid(self):
        return self.__t.IsValid()

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


class FrameWrapper(object):
    def __init__(self, f):
        self.__f = f

    @property
    def line_entry(self):
        entry = self.__f.GetLineEntry()
        debug('entry: ' + str(entry))
        filespec = entry.GetFileSpec()
        debug('filespec: ' + str(filespec))

        if filespec:
            return (filespec.GetDirectory(), filespec.GetFilename(), \
                    entry.GetLine(), entry.GetColumn())
        else:
            return None


class BreakpointWrapper(object):
    def __init__(self, b):
        self.__b = b

    def enabled(self):
        return self.__b.IsEnabled()
    # def set_enabled(self, e):
    #     self.__b.SetEnabled(e)

    def line_entries(self):
        entries = []

        n = self.__b.GetNumLocations()
        for i in xrange(n):
            bp_loc = self.__b.GetLocationAtIndex(i)
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


class LldbResultStatusWrapper(object):
    _success_returns = [lldb.eReturnStatusSuccessFinishNoResult,        \
                        lldb.eReturnStatusSuccessFinishResult,          \
                        lldb.eReturnStatusSuccessContinuingNoResult,    \
                        lldb.eReturnStatusSuccessContinuingResult]
                        # lldb.eReturnStatusStarted]
    _finished_returns = [lldb.eReturnStatusSuccessFinishNoResult,       \
                         lldb.eReturnStatusSuccessFinishResult]

    _continuing_returns = [lldb.eReturnStatusSuccessContinuingNoResult, \
                           lldb.eReturnStatusSuccessContinuingResult]

    def __init__(self, r):
        self.__r = r

    def is_success(self):
        return self.__r in self._success_returns

    def is_finished(self):
        return self.__r in self._finished_returns

    def is_started(self):
        return self.__r == lldb.eReturnStatusStarted

    def is_quit(self):
        return self.__r == lldb.eReturnStatusQuit

    def is_failed(self):
        return self.__r == lldb.eReturnStatusFailed

    def is_invalid(self):
        return self.__r == lldb.eReturnStatusInvalid


class LldbCommandReturnWrapper(object):
    def __init__(self):
        self.__ret = lldb.SBCommandReturnObject()

    def ReturnObject(self):
        return self.__ret

    @property
    def error(self):
        return self.__ret.GetError()

    @property
    def output(self):
        return self.__ret.GetOutput()


# Listeners and broadcasters
class LldbListener(object):
    def __init__(self, listener, debugger):
        self.__listener = listener
        self.__debugger = debugger

    @property
    def SBListener(self):
        return self.__listener

    @property
    def debugger(self):
        return self.__debugger

    @property
    def valid(self):
        return self.__listener.IsValid()

    def start_listening_for_events(self, broadcaster, events):
        b = broadcaster
        if isinstance(b, LldbBroadcaster):
            b = b.SBBroadcaster

        self.__listener.StartListeningForEvents(b, events)

    def start_listening_for_process_events(self):
        self.__listener.StartListeningForEventClass(        \
            self.__debugger.SBDebugger,                     \
            lldb.SBProcess.GetBroadcasterClassName(),       \
            lldb.SBProcess.eBroadcastBitStateChanged |      \
            lldb.SBProcess.eBroadcastBitInterrupt |         \
            lldb.SBProcess.eBroadcastBitSTDOUT |            \
            lldb.SBProcess.eBroadcastBitSTDERR)

    def start_listening_for_breakpoint_changes(self):
        self.__listener.StartListeningForEventClass(        \
            self.__debugger.SBDebugger,                     \
            lldb.SBTarget.GetBroadcasterClassName(),        \
            lldb.SBTarget.eBroadcastBitBreakpointChanged)

    def wait_for_event(self, timeout=None):
        if timeout is None:
            timeout = 4000000
        event = lldb.SBEvent()
        self.__listener.WaitForEvent(timeout, event)
        return LldbEvent(event)

    def wait_for_event_for_broadcaster_with_type(self, timeout, broadcaster, mask):
        b = broadcaster
        if isinstance(b, LldbBroadcaster):
            b = b.SBBroadcaster
        if timeout is None:
            timeout = 4000000

        event = lldb.SBEvent()
        self.__listener.WaitForEventForBroadcasterWithType(timeout,
                                             broadcaster,
                                             mask,
                                             event)
        return event


class LldbEvent(object):
    def __init__(self, *args):
        self.__ev = lldb.SBEvent(*args)

    @property
    def broadcaster(self):
        return LldbBroadcaster(self.__ev.GetBroadcaster())

    def broadcaster_matches_ref(self, bb):
        b = bb
        if isinstance(b, LldbBroadcaster):
            b = b.SBBroadcaster

        return self.__ev.BroadcasterMatchesRef(b)

    @property
    def string(self):
        return lldb.SBEvent.GetCStringFromEvent(self.__ev)

    def is_breakpoint_event(self):
        return lldb.SBBreakpoint.EventIsBreakpointEvent(self.__ev)

    def is_process_event(self):
        return lldb.SBProcess.EventIsProcessEvent(self.__ev)

    @property
    def valid(self):
        return self.__ev.IsValid()

    @property
    def SBEvent(self):
        return self.__ev

    @property
    def type(self):
        return self.__ev.GetType()

    def __str__(self):
        stream = lldb.SBStream()
        self.__ev.GetDescription(stream)
        return stream.GetData()


class LldbBroadcaster(object):
    def __init__(self, broadcaster):
        self.__broadcaster = broadcaster

    @property
    def SBBroadcaster(self):
        return self.__broadcaster

    @property
    def valid(self):
        return self.__broadcaster.IsValid()


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

    def start(self):
        debug('creating thread: <' + self.GetName() + '>')
        self.__t = threading.Thread(name='<' + self.GetName() + '>', target=self.run)
        self.__t.start()

    def send_command(self, cmd):
        event = LldbEvent(SublimeBroadcaster.eBroadcastBitHasInput, str(cmd))
        self.BroadcastEvent(event.SBEvent)

    def run(self):
        thread_created(threading.current_thread().name)

        time.sleep(1)

        def debug(object):
            print threading.current_thread().name + ' ' + str(object)

        listener = LldbListener(lldb.SBListener('SublimeListener'), self.__debugger)
        interpreter_broadcaster = self.__debugger.SBDebugger.GetCommandInterpreter().GetBroadcaster()
        listener.start_listening_for_events(interpreter_broadcaster,
                                            lldb.SBCommandInterpreter.eBroadcastBitThreadShouldExit | \
                                            lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived)

        listener.start_listening_for_events(self, SublimeBroadcaster.eBroadcastBitShouldExit | \
                                                  SublimeBroadcaster.eBroadcastBitHasInput)

        debug('broadcasting DidStart')
        self.BroadcastEventByType(SublimeBroadcaster.eBroadcastBitDidStart)

        done = False
        while not done:
            debug('listening at: ' + str(listener.SBListener))
            event = listener.wait_for_event()
            if not event.valid:  # timeout
                continue

            debug('SublimeBroadcaster: got event: ' + lldbutil.get_description(event.SBEvent))
            if event.broadcaster.valid:
                if event.broadcaster_matches_ref(interpreter_broadcaster):
                    if event.type & lldb.SBCommandInterpreter.eBroadcastBitThreadShouldExit \
                        or event.type & lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived:
                        debug('exiting from broadcaster due to interpreter')
                        done = True
                        continue
                elif event.broadcaster_matches_ref(self):
                    if event.type & SublimeBroadcaster.eBroadcastBitShouldExit:
                        debug('exiting from broadcaster due to self')
                        done = True
                        continue
                    if event.type & SublimeBroadcaster.eBroadcastBitHasInput:
                        cmd = event.string
                        # TODO: This shouldn't happen!
                        # GetCStringFromEvent() is returning None when the string is empty.
                        if cmd is None:
                            cmd = ''

                        event = LldbEvent(SublimeBroadcaster.eBroadcastBitHasCommandInput, str(cmd))
                        self.BroadcastEvent(event.SBEvent)
                        continue

        self.BroadcastEventByType(SublimeBroadcaster.eBroadcastBitShouldExit)
        debug('leaving...')
        del self.__debugger
        self.BroadcastEventByType(SublimeBroadcaster.eBroadcastBitDidExit)




                # if event.broadcaster_matches_ref(driver):
