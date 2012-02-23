# -*- mode: python; coding: utf-8 -*-

import lldb


def debug(str):
    print str


debug('Loading LLDB wrappers for Sublime Text 2 plugin')


def terminate():
    lldb.SBDebugger.Terminate()


class LldbWrapper(object):
    def __init__(self):
        debug('Initting LldbWrapper')
        self.__lldb = lldb.SBDebugger.Create()
        self.__last_cmd = ''

    def breakpoints(self):
        #         uint32_t    GetNumBreakpoints () const
        # lldb::SBBreakpoint  GetBreakpointAtIndex (uint32_t idx) const
        bps = []
        target = self.__lldb.GetSelectedTarget()
        if target:
            n = target.GetNumBreakpoints()
            for i in xrange(n):
                bps.insert(i, BreakpointWrapper(self.__lldb                  \
                                                    .GetSelectedTarget()     \
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

    def interpret_command(self, cmd):
        # if cmd == '':
        #     cmd = self.__last_cmd

        result = LldbCommandReturnWrapper()
        ci = self.__lldb.GetCommandInterpreter()

        r = LldbResultStatusWrapper(ci.HandleCommand(cmd.__str__(),
                                                     result.ReturnObject(),
                                                     True))

        # if r.is_success():
        #     self.__last_cmd = cmd

        return (result, r)

    # bridges to SBDebugger methods
    def set_async(self, async):
        self.__lldb.SetAsync(async)

    # CamelCase methods are simple bridges to the SBDebugger object
    # def GetCommandInterpreter(self):
    #     return self.lldb.GetCommandInterpreter()

    def __GetErrorFileHandle(self):
        return self.__lldb.GetErrorFileHandle()

    def __GetOutputFileHandle(self):
        return self.__lldb.GetOutputFileHandle()

    def __SetAsync(self, arg):
        return self.__lldb.SetAsync(arg)


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

# eReturnStatusInvalid = _lldb.eReturnStatusInvalid
# eReturnStatusSuccessFinishNoResult = _lldb.eReturnStatusSuccessFinishNoResult
# eReturnStatusSuccessFinishResult = _lldb.eReturnStatusSuccessFinishResult
# eReturnStatusSuccessContinuingNoResult = _lldb.eReturnStatusSuccessContinuingNoResult
# eReturnStatusSuccessContinuingResult = _lldb.eReturnStatusSuccessContinuingResult
# eReturnStatusStarted = _lldb.eReturnStatusStarted
# eReturnStatusFailed = _lldb.eReturnStatusFailed
# eReturnStatusQuit = _lldb.eReturnStatusQuit


class LldbCommandReturnWrapper(object):
    def __init__(self):
        self.__ret = lldb.SBCommandReturnObject()

    def ReturnObject(self):
        return self.__ret

    def error(self):
        return self.__ret.GetError()

    def output(self):
        return self.__ret.GetOutput()
