import re
import lldb
import lldbutil

import sublime
# import sublime_plugin

from root_objects import lldb_register_view_name, lldb_disassembly_view_name, \
                         driver_instance


import sys
import threading


def debug(thing):
    print >> sys.__stdout__, threading.current_thread().name, str(thing)


class LLDBView(sublime.View):
    def __init__(self, view):
        self.__view = view

    def base_view(self):
        return self.__view

    def name(self):
        return self.base_view().name()

    def set_name(self, name):
        self.__view.set_name(name)

    def set_read_only(self, is_ro=True):
        self.__view.set_read_only(is_ro)

    def set_scratch(self, is_scratch=True):
        self.__view.set_scratch(is_scratch)

    def show(self, point_or_region_or_region_set, show_surrounds=True):
        self.__view.show(point_or_region_or_region_set, show_surrounds)

    # Method that is run in the end of an update
    def epilogue(self):
        pass

    def updated_content(self):
        assert False, "%s.updated_content() wasn't overridden." % self.__class__.__name__

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
            self.epilogue()
        sublime.set_timeout(updater, 0)


class LLDBRegisterView(LLDBView):
    def __init__(self, view, thread):
        self.__thread = thread
        super(LLDBRegisterView, self).__init__(view)
        self.set_name(lldb_register_view_name(thread))
        self.set_scratch()
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
        super(LLDBDisassemblyView, self).__init__(view)

        self.set_name(lldb_disassembly_view_name(frame))
        self.set_scratch()
        debug('LLDBDisassemblyView.name == ' + view.name())

    @property
    def frame(self):
        return self.__frame

    @property
    def pc_line(self):
        return self.__pc_line

    def epilogue(self):
        r = self.base_view.text_point(self.pc_line, 0)
        self.show(r, True)
        
    def updated_content(self):
        frame = self.__frame
        if not frame.IsValid():
            return 'Invalid frame. Has it finished its work?'

        target = frame.GetThread().GetProcess().GetTarget()
        pc = frame.GetPCAddress()
        function = pc.GetFunction()
        symbol = function.GetName()
        start_addr = function.GetStartAddress().GetLoadAddress(target)

        instrs = driver_instance().disassemble_frame(frame)
        if not instrs:
            return False
        pc = driver_instance().get_PC()

        def get_max_sizes(accum, next):
            debug('accum: ' + str(accum))
            debug(next)
            return (max(accum[0], len(next[1])), max(accum[1], len(next[2])))
        (max_mnemonic, max_operands) = reduce(get_max_sizes, instrs, (0, 0))
        # format_str = '%%2.2s%%10.10s: %%%d.%ds %%%d.%ds%%s\n' % (max_mnemonic, max_operands)
        format_str = '%2.2s%.10s: %*s %*s%s\n'
        debug('%s, %s' % (str(max_mnemonic), str(max_operands)))
        max_mnemonic, max_operands = (int(max_mnemonic), int(max_operands))

        result = '%s @ 0x%s:\n' % (symbol, start_addr)
        for i in instrs:
            if len(i) == 3:
                (addr, mnemonic, ops) = i
                comment_str = ''
            elif len(i) == 4:
                (addr, mnemonic, ops, comment) = i
                comment_str = '\t; ' + comment
            else:
                assert False

            pc_str = ''
            if pc == addr:
                pc_str = '=>'

            result += format_str % (pc_str, hex(addr), max_mnemonic, mnemonic, max_operands, ops, comment_str)

        self.__pc_line = pc - start_addr
        return result

