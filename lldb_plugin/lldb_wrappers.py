# -*- mode: python; coding: utf-8 -*-

import lldb
import threading


def debug(str):
    print str


debug('Loading LLDB wrappers for Sublime Text 2 plugin')


def initialize():
    lldb.SBDebugger.Initialize()


def terminate():
    lldb.SBDebugger.Terminate()


def thread_created(string):
    lldb.SBHostOS.ThreadCreated(string)


class LldbWrapper(object):
    def __init__(self):
        debug('Initting LldbWrapper')
        self.__lldb = lldb.SBDebugger.Create()
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

    def current_frame(self):
        return self.__lldb.GetSelectedTarget().GetProcess() \
                          .GetSelectedThread().GetSelectedFrame()

    def current_line_entry(self):
        entry = self.current_frame().GetLineEntry()
        filespec = entry.GetFileSpec()

        if filespec:
            return (filespec.GetDirectory(), filespec.GetFilename(), \
                    entry.GetLine(), entry.GetColumn())
        else:
            return None

    # def current_sc(self):
    #     return self.current_frame().GetSymbolContext(0xffffffff)

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

    def error(self):
        return self.__ret.GetError()

    def output(self):
        return self.__ret.GetOutput()


# Listeners and broadcasters
class LldbListener(object):
    def __init__(self, listener, debugger):
        self.__listener = listener
        self.__debugger = debugger

    @property
    def valid(self):
        return self.__listener.IsValid()

    def start_listening_for_events(self, timeout, events):
        self.__listener.StartListeningForEvents(timeout, events)

    def start_listening_for_breakpoint_changes(self):
        self.__listener.StartListeningForEventClass(        \
            self.__debugger,                                \
            lldb.SBTarget.GetBroadcasterClassName(),        \
            lldb.SBTarget.eBroadcastBitBreakpointChanged)

    def wait_for_event(self, n_secs):
        event = lldb.SBEvent()
        self.__listener.WaitForEvent(n_secs, event)
        return LldbEvent(event)


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

    eBroadcastBitHasCommandInput = 1 << 0
    eBroadcastBitShouldExit = 1 << 1
    eBroadcastBitDidExit = 1 << 2
    eBroadcastBitsSTDOUT = 1 << 3
    eBroadcastBitsSTDERR = 1 << 4
    eBroadcastBitsSTDIN = 1 << 5
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
        event = LldbEvent(SublimeBroadcaster.eBroadcastBitHasCommandInput, str(cmd))
        self.BroadcastEvent(event.SBEvent)

    def run(self):
        listener = LldbListener(lldb.SBListener('SublimeBroadcaster'), self.__debugger)
        interpreter_broadcaster = self.__debugger.GetCommandInterpreter() \
                                                 .GetBroadcaster()
        listener.start_listening_for_events(interpreter_broadcaster,
                                            lldb.SBCommandInterpreter.eBroadcastBitThreadShouldExit |
                                            lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived)
        listener.start_listening_for_events(self,
                                            SublimeBroadcaster.eBroadcastBitHasCommandInput |
                                            SublimeBroadcaster.eBroadcastBitShouldExit)
        # listener.start_listening_for_events(self,
        #                                     Driver.eBroadcastBitReadyForInput |
        #                                     Driver.eBroadcastBitThreadShouldExit)
        done = False
        while not done:
            event = listener.wait_for_event(10)
            if not event.valid:  # timeout
                continue

            debug('SublimeBroadcaster: event:')
            debug(event)
            if event.broadcaster.valid:
                if event.broadcaster_matches_ref(interpreter_broadcaster):
                    if event.type & lldb.SBCommandInterpreter.eBroadcastBitThreadShouldExit \
                        or event.type & lldb.SBCommandInterpreter.eBroadcastBitQuitCommandReceived:
                        done = True
                        continue
                elif event.broadcaster_matches_ref(self):
                    if event.type & SublimeBroadcaster.eBroadcastBitShouldExit:
                        done = True
                        continue
                    if event.type & SublimeBroadcaster.eBroadcastBitHasCommandInput:
                        result, r = self.__debugger.interpret_command(event.string, True)
                        err_str = result.error()
                        out_str = result.output()

                        self.__output_fun(out_str)

                        if len(err_str) != 0:
                            err_str.replace('\n', '\nerr> ')
                            err_str = 'err> ' + err_str
                            self.__output_fun(err_str)
                        continue
                else:  # event.broadcaster_matches_ref(driver):
                    # if event.type & driver.…readyForInput:
                    None

        self.BroadcastEventByType(SublimeBroadcaster.eBroadcastBitShouldExit)
        del self.__debugger




                # if event.broadcaster_matches_ref(driver):
