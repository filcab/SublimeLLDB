import re
import lldb
import lldbutil

import sublime
# import sublime_plugin

from root_objects import lldb_register_view_name


import sys
import threading


def debug(thing):
    print >> sys.__stdout__, threading.current_thread().name, str(thing)


class LLDBView(sublime.View):
    def __init__(self, view):
        self.__view = view

    def base_view(self):
        return self.__view

    def update(self):
        string = self.updated_content()
        view = self.base_view()
        region = sublime.Region(0, view.size())

        def updater():
            view.set_read_only(False)
            edit = view.begin_edit(view.name())
            view.erase(edit, region)
            view.insert(edit, 0, string)
            view.end_edit(edit)
            view.set_read_only(True)
        sublime.set_timeout(updater, 0)

    def name(self):
        return self.base_view().name()


class LLDBRegisterView(LLDBView):
    def __init__(self, view, thread):
        self.__thread = thread
        super(LLDBRegisterView, self).__init__(view)
        view.set_name(lldb_register_view_name(thread))
        debug('LLDBRegisterView.name == ' + view.name())

    # def __nonzero__(self):
    #     return self.valid

    # @property
    # def valid(self):
    #     return self.__thread.IsValid()

    @property
    def thread(self):
        return self.__thread

    def updated_content(self):
        thread = self.__thread
        if not thread.IsValid():
            return 'Invalid thread. Has it finished its work?'
        target = thread.GetProcess().GetTarget()

        frame = thread.GetSelectedFrame()
        registerList = frame.GetRegisters()
        result = 'Frame registers:'
        for value in registerList:
            #print value
            result = result + ('\n%s (number of registers = %d):\n' % (value.GetName(), value.GetNumChildren()))
            for child in value:
                if child.GetValue() is not None:
                    # Let's assume no register name is bigger than 10 chars, for now.
                    # 18 chars are needed for 64 bit values: 0x0000000000000000
                    addr = lldb.SBAddress(child.GetValueAsUnsigned(), target)
                    desc = lldbutil.get_description(addr)
                    if re.match('0x[0-9A-Fa-f]+|^$', desc):
                        desc = ''
                    else:
                        desc = '; ' + desc
                    result = result + ('%10.10s = %.18s%s\n' % (child.GetName(), child.GetValue(), desc))

        return result


class LLDBDisassemblyView(LLDBView):
    def __init__(self, view, frame):
        self.__frame = frame
        super(LLDBRegisterView, self).__init__(view)

        pc = frame.GetPCAddress()
        function = pc.GetFunction()
        symbol = function.GetName()
        addr = function.GetStartAddress()

        view.set_name(lldb_disassembly_view_name(symbol, addr))
        debug('LLDBDisassemblyView.name == ' + view.name())

    # def __nonzero__(self):
    #     return self.valid

    # @property
    # def valid(self):
    #     return self.__frame.IsValid()

    @property
    def frame(self):
        return self.__frame

    def updated_content(self):
        thread = self.__thread
        if not thread.IsValid():
            return 'Invalid thread. Has it finished its work?'
        target = thread.GetProcess().GetTarget()

        frame = thread.GetSelectedFrame()
        registerList = frame.GetRegisters()
        result = 'Frame registers:'
        for value in registerList:
            #print value
            result = result + ('\n%s (number of registers = %d):\n' % (value.GetName(), value.GetNumChildren()))
            for child in value:
                if child.GetValue() is not None:
                    # Let's assume no register name is bigger than 10 chars, for now.
                    # 18 chars are needed for 64 bit values: 0x0000000000000000
                    addr = lldb.SBAddress(child.GetValueAsUnsigned(), target)
                    desc = lldbutil.get_description(addr)
                    if re.match('0x[0-9A-Fa-f]+|^$', desc):
                        desc = ''
                    else:
                        desc = '; ' + desc
                    result = result + ('%10.10s = %.18s%s\n' % (child.GetName(), child.GetValue(), desc))

        return result
