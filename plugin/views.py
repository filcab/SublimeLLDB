import re
import lldb
import lldbutil

from multiprocessing import Lock

import sublime
# import sublime_plugin

from root_objects import lldb_register_view_name, lldb_disassembly_view_name,   \
                         driver_instance, add_lldb_view

from utilities import SettingsManager


import sys
import threading

from debug import debug as _debug
from debug import debugViews

def debug(thing):
    _debug(debugViews, thing)


class LLDBView(object):
    def __init__(self, view):
        self.__view = view
        # Keep track of the View's name, so we don't have to call name()
        # on the main thread
        self.__name = view.name()
        # TODO: What happens when a file is renamed?
        self.__file_name = view.file_name()
        add_lldb_view(self)
        debug("Created an LLDBView with (class, view, name, file_name) == %s" %
              str((self.__class__.__name__, self.__view, self.__name, self.__file_name)))

    def base_view(self):
        return self.__view

    def name(self):
        return self.__name

    def set_name(self, name):
        self.base_view().set_name(name)
        self.__name = name

    def file_name(self):
        return self.__file_name

    def set_read_only(self, is_ro=True):
        self.__view.set_read_only(is_ro)

    def set_scratch(self, is_scratch=True):
        self.__view.set_scratch(is_scratch)

    def show(self, point_or_region_or_region_set, show_surrounds=True):
        self.__view.show(point_or_region_or_region_set, show_surrounds)

    def full_update(self):
        """This method calls pre_update and then makes the main thread
call update().
    It should only be used when there is only one view to update."""
        self.pre_update()
        sublime.set_timeout(self.update, 0)

    # Method that can be overridden, if need be
    def pre_update(self):
        """This method will do what's needed to prepare for the view
update. It won't necessarily be called from the main thread."""
        pass

    # Method that has to be overridden by each subclass
    def update(self):
        """This method will update the view. Ideally, only UI code will be
run here. It will be called from the main (UI) thread."""
        assert False, "%s.update() wasn't overridden." % self.__class__.__name__

    def stop(self):
        pass


class LLDBReadOnlyView(LLDBView):
    # Put here the stuff only for read-only views
    def __init__(self, view):
        super(LLDBReadOnlyView, self).__init__(view)
        self.__content = ''

    def content(self):
        return self.__content

    def pre_update(self):
        self.updated_content()

    def updated_content(self):
        assert False, "%s.updated_content() wasn't overridden." % self.__class__.__name__

    def update_content(self):
        self.__content = self.updated_content()

    # Method that is run in the end of an update
    def epilogue(self):
        pass

    def update(self):
        string = self.content()
        view = self.base_view()

        view.set_read_only(False)
        edit = view.begin_edit(view.name())
        region = sublime.Region(0, view.size())
        view.erase(edit, region)
        view.insert(edit, 0, string)
        view.end_edit(edit)
        view.set_read_only(True)
        self.epilogue()


class LLDBCodeView(LLDBView):
    eRegionPC = 1 << 0
    eRegionBreakpointEnabled = 1 << 1
    eRegionBreakpointDisabled = 1 << 2

    __pc_line = None
    __bp_lock = Lock()

    # Settings for the whole class
    __sm = SettingsManager.getSM()
    eMarkerPCName = __sm.get_default('markers.current_line.region_name', 'lldb.location')
    eMarkerPCScope = __sm.get_default('markers.current_line.scope', 'bookmark')
    eMarkerPCScopeCrashed = __sm.get_default('markers.current_line.scope.crashed', 'invalid')
    eMarkerPCIcon = __sm.get_default('markers.current_line.icon', 'bookmark')
    eMarkerBreakpointEnabledName = __sm.get_default('markers.breakpoint.enabled.region_name',
                                                  'lldb.breakpoint.enabled')
    eMarkerBreakpointEnabledScope = __sm.get_default('markers.breakpoint.enabled.scope', 'string')
    eMarkerBreakpointEnabledIcon = __sm.get_default('markers.breakpoint.enabled.type', 'circle')
    eMarkerBreakpointDisabledName = __sm.get_default('markers.breakpoint.disabled.region_name',
                                                   'lldb.breakpoint.disabled')
    eMarkerBreakpointDisabledScope = __sm.get_default('markers.breakpoint.disabled.scope', 'bookmark')
    eMarkerBreakpointDisabledIcon = __sm.get_default('markers.breakpoint.disabled.type', 'circle')

    # FIXME: Split stuff that doesn't have to run on the UI thread.
    def __init__(self, view, driver):
        super(LLDBCodeView, self).__init__(view)

        self._needs_update = False
        self.__driver = driver
        self.__enabled_bps = {}
        self.__disabled_bps = {}
        # Get info on current breakpoints for this file
        self.__populate_breakpoint_lists()
        if not view.is_loading():
            self.__update_bps()
        else:
            debug('Skipped LLDBCodeView.__update_bps() because view.is_loading is True')
        self.pre_update()

    def __repr__(self):
        return 'file_name: %s, needs_update: %s, pc_line: %s, enabled_bps: %s, disable_bps: %s' % \
            (self.file_name(), str(self._needs_update), str(self.__pc_line), str(self.__enabled_bps), str(self.__disabled_bps))

    @property
    def needs_update(self):
        return self._needs_update

    @needs_update.setter
    def needs_update(self, value):
        self._needs_update = value

    # {mark,change,unmark}_bp don't update needs_update because they
    # immediately update what was touched.
    def mark_bp(self, line, is_enabled=True):
        """Mark a new breakpoint as enabled/disabled and immediately mark
its region."""
        self.__add_bps([line], is_enabled)
        v = self.base_view()

        if is_enabled:
            regions = map(lambda line: v.line(v.text_point(line - 1, 0)), self.__enabled_bps.keys())
            self.__mark_regions(regions, self.eRegionBreakpointEnabled)
        else:
            regions = map(lambda line: v.line(v.text_point(line - 1, 0)), self.__disabled_bps.keys())
            self.__mark_regions(regions, self.eRegionBreakpointDisabled)

    def change_bp(self, line, is_enabled):
        if is_enabled:
            remove_from = self.__disabled_bps
            add_to = self.__enabled_bps
        else:
            remove_from = self.__enabled_bps
            add_to = self.__disabled_bps

        with self.__bp_lock:
            # The breakpoint must exist in remove_from
            existing = remove_from[line]
            if existing == 1:
                del remove_from[line]
            else:
                remove_from[line] = existing - 1

            if line in add_to:
                existing = add_to[line]
            else:
                existing = 0
            add_to[line] = existing + 1

        v = self.base_view()
        regions = map(lambda line: v.line(v.text_point(line - 1, 0)), self.__enabled_bps.keys())
        self.__mark_regions(regions, self.eRegionBreakpointEnabled)
        regions = map(lambda line: v.line(v.text_point(line - 1, 0)), self.__disabled_bps.keys())
        self.__mark_regions(regions, self.eRegionBreakpointDisabled)

    def unmark_bp(self, line, is_enabled=True):
        """Remove merkings for a breakpoint and update the UI
afterwards."""
        self.__remove_bps([line], is_enabled)
        v = self.base_view()

        if is_enabled:
            regions = map(lambda line: v.line(v.text_point(line - 1, 0)), self.__enabled_bps.keys())
            self.__mark_regions(regions, self.eRegionBreakpointEnabled)
        else:
            regions = map(lambda line: v.line(v.text_point(line - 1, 0)), self.__disabled_bps.keys())
            self.__mark_regions(regions, self.eRegionBreakpointDisabled)

    def pre_update(self):
        """pre_update will perform lldb-related work and get our PC line"""
        old_pc_line = self.__pc_line
        self.__pc_line = None
        _debug(debugViews, 'old pc_line: %s' % str(old_pc_line))

        thread = self.__driver.current_thread()
        if not thread:
            _debug(debugViews, 'new pc_line: %s' % str(self.__pc_line))
            if self.__pc_line != old_pc_line:
                self.needs_update = True
            return False

        for frame in thread:
            line_entry = frame.GetLineEntry()
            filespec = line_entry.GetFileSpec()
            if filespec:
                filename = filespec.GetDirectory() + '/' + filespec.GetFilename()
                if filename == self.file_name():
                    self.__pc_line = line_entry.GetLine()
                    _debug(debugViews, 'new pc_line: %s' % str(self.__pc_line))
                    if self.__pc_line != old_pc_line:
                        self.needs_update = True
                    return True

        _debug(debugViews, 'new pc_line: %s' % str(self.__pc_line))
        if self.__pc_line != old_pc_line:
            self.needs_update = True
        return False

    def update(self):
        if self.needs_update:
            if self.__pc_line is not None:
                self.__mark_pc(self.__pc_line - 1, True)
            else:
                self.__mark_pc(None)
            # For now, bp-marking functions will immediately update the
            # view. We don't need to update it when the view is dirty.
            # self.__update_bps()
            self.needs_update = False
        else:
            _debug(debugViews, 'LLDBCodeView: didn\'t need an update: %s' % repr(self))

    def stop(self):
        self.pre_update()  # This will set pc_line to None
        self.__enabled_bps = {}
        self.__disabled_bps = {}

        def to_ui():
            _debug(debugViews, 'executing UI code for LLDBCodeView.stop()')
            self.update()
            self.__update_bps()
        sublime.set_timeout(to_ui, 0)

    # Private LLDBCodeView methods
    def __populate_breakpoint_lists(self):
        file_bp_locs = self.__driver.get_breakpoint_locations_for_file(self.file_name())

        def line_from_bp_loc(bp_loc):
            line_entry = bp_loc.GetAddress().GetLineEntry()
            return line_entry.GetLine()

        enabled_bp_lines = []
        disabled_bp_lines = []
        for bp_loc in file_bp_locs:
            if bp_loc.IsEnabled():
                enabled_bp_lines.append(line_from_bp_loc(bp_loc))
            else:
                disabled_bp_lines.append(line_from_bp_loc(bp_loc))

        self.__add_bps(enabled_bp_lines, True)
        self.__add_bps(disabled_bp_lines, False)


    def __mark_regions(self, regions, type):
        if type == self.eRegionPC:
            if len(regions) > 0:
                debug('(' + self.file_name() + ') adding regions: ' + str((self.eMarkerPCName, regions,
                      self.eMarkerPCScope, self.eMarkerPCIcon, sublime.HIDDEN)))
                self.base_view().add_regions(self.eMarkerPCName, regions,
                                             self.eMarkerPCScope, self.eMarkerPCIcon, sublime.HIDDEN)
            else:
                _debug(debugViews, 'erasing region: %s' % self.eMarkerPCName)
                self.base_view().erase_regions(self.eMarkerPCName)
        elif type == self.eRegionBreakpointEnabled:
            if len(regions) > 0:
                debug('(' + self.file_name() + ') adding regions: ' + str((self.eMarkerBreakpointEnabledName, regions,
                      self.eMarkerBreakpointEnabledScope, self.eMarkerBreakpointEnabledIcon, sublime.HIDDEN)))
                self.base_view().add_regions(self.eMarkerBreakpointEnabledName, regions, self.eMarkerBreakpointEnabledScope,
                              self.eMarkerBreakpointEnabledIcon, sublime.HIDDEN)
            else:
                _debug(debugViews, 'erasing regions: %s' % self.eMarkerBreakpointEnabledName)
                self.base_view().erase_regions(self.eMarkerBreakpointEnabledName)
        elif type == self.eRegionBreakpointDisabled:
            if len(regions) > 0:
                debug('(' + self.file_name() + ') adding regions: ' + str((self.eMarkerBreakpointDisabledName, regions,
                      self.eMarkerBreakpointDisabledScope, self.eMarkerBreakpointDisabledIcon, sublime.HIDDEN)))
                self.base_view().add_regions(self.eMarkerBreakpointDisabledName, regions, self.eMarkerBreakpointDisabledScope,
                              self.eMarkerBreakpointDisabledIcon, sublime.HIDDEN)
            else:
                _debug(debugViews, 'erasing regions: %s' % self.eMarkerBreakpointDisabledName)
                self.base_view().erase_regions(self.eMarkerBreakpointDisabledName)

    def __mark_pc(self, line, show=False):
        v = self.base_view()
        if line is None:
            to_mark = []
        else:
            to_mark = [v.line(v.text_point(line, 0))]
        self.__mark_regions(to_mark, self.eRegionPC)
        if show and to_mark:
            self.show(to_mark[0], True)

    def __update_bps(self):
        v = self.base_view()
        regions = map(lambda line: v.line(v.text_point(line - 1, 0)), self.__enabled_bps.keys())
        self.__mark_regions(regions, self.eRegionBreakpointEnabled)
        regions = map(lambda line: v.line(v.text_point(line - 1, 0)), self.__disabled_bps.keys())
        self.__mark_regions(regions, self.eRegionBreakpointDisabled)

    def __add_bps(self, lines, are_enabled=True):
        """Adds breakpoints (enabled or disabled) to the view.
__update_bps() must be called afterwards to refresh the UI."""
        if len(lines) > 0:
            self.needs_update = True

        if are_enabled:
            add_to = self.__enabled_bps
        else:
            add_to = self.__disabled_bps

        with self.__bp_lock:
            # We shouldn't have that many breakpoints for this to be a
            # problem. If the lock becomes a problem, we can lock for each
            # breakpoint.
            for line in lines:
                if line in add_to:
                    existing = add_to[line]
                else:
                    existing = 0

                add_to[line] = existing + 1

    def __remove_bps(self, lines, are_enabled=True):
        """Removes breakpoints (enabled or disabled) from the view.
__update_bps() must be called afterwards to refresh the UI."""
        if len(lines) > 0:
            self.needs_update = True

        if are_enabled:
            remove_from = self.__enabled_bps
        else:
            remove_from = self.__disabled_bps

        with self.__bp_lock:
            for line in lines:
                existing = remove_from[line]
                if existing == 1:
                    del remove_from[line]
                else:
                    remove_from[line] = existing - 1


class LLDBRegisterView(LLDBReadOnlyView):
    def __init__(self, view, thread):
        self.__thread = thread
        super(LLDBRegisterView, self).__init__(view)
        self.set_name(lldb_register_view_name(thread))
        self.set_scratch()

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


class LLDBDisassemblyView(LLDBReadOnlyView):
    __pc_line = 0

    def __init__(self, view, frame):
        self.__frame = frame
        super(LLDBDisassemblyView, self).__init__(view)

        self.set_name(lldb_disassembly_view_name(frame))
        self.set_scratch()

    @property
    def frame(self):
        return self.__frame

    @property
    def pc_line(self):
        return self.__pc_line

    def epilogue(self):
        r = self.base_view().text_point(self.pc_line, 0)
        self.show(r, True)

    def updated_content(self):
        frame = self.__frame
        if not frame.IsValid():
            return 'Invalid frame. Has it finished its work?'

        target = frame.GetThread().GetProcess().GetTarget()
        pc = frame.GetPCAddress()
        function = pc.GetFunction()
        symbol = pc.GetSymbol()
        if function.IsValid():
            name = function.GetName()
            start_addr = function.GetStartAddress().GetLoadAddress(target)
        elif symbol.IsValid():
            name = symbol.GetName()
            start_addr = symbol.GetStartAddress().GetLoadAddress(target)
        else:
            name = pc.GetModule().GetFileSpec().GetFilename()
            start_addr = pc.GetLoadAddress(target)
            # assert False, "Neither symbol nor the function are valid!"

        instrs = driver_instance().disassemble_frame(frame)
        if not instrs:
            return 'Error getting instructions for frame ' + str(frame)

        pc = driver_instance().get_PC()

        def get_max_sizes(accum, next):
            return (max(accum[0], len(next[1])), max(accum[1], len(next[2])))
        (max_mnemonic, max_operands) = reduce(get_max_sizes, instrs, (0, 0))
        format_str = '%2.2s%.10s: %*s %*s%s\n'
        max_mnemonic, max_operands = (int(max_mnemonic), int(max_operands))

        result = '%s @ 0x%s:\n' % (name, start_addr)
        n_instrs = 0
        for i in instrs:
            n_instrs += 1
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
                self.__pc_line = n_instrs
                pc_str = '=>'

            result += format_str % (pc_str, hex(addr), max_mnemonic, mnemonic, max_operands, ops, comment_str)

        return result


class LLDBThreadDisassemblyView(LLDBReadOnlyView):
    __pc_line = 0
    # __frame = lldb.SBFrame()

    def __init__(self, view, thread):
        self.__thread = thread
        super(LLDBThreadDisassemblyView, self).__init__(view)

        self.set_name(lldb_disassembly_view_name(thread.GetThreadID()))
        self.set_scratch()

    @property
    def thread(self):
        return self.__thread

    @property
    def pc_line(self):
        return self.__pc_line

    def epilogue(self):
        r = self.base_view().text_point(self.pc_line, 0)
        self.show(r, True)

    def updated_content(self):
        thread = self.__thread
        if not thread.IsValid():
            return 'Invalid thread. Has it finished its work?'

        target = thread.GetProcess().GetTarget()
        pc = thread.GetSelectedFrame().GetPCAddress()
        function = pc.GetFunction()
        symbol = pc.GetSymbol()
        if function.IsValid():
            name = function.GetName()
            start_addr = function.GetStartAddress().GetLoadAddress(target)
        elif symbol.IsValid():
            name = symbol.GetName()
            start_addr = symbol.GetStartAddress().GetLoadAddress(target)
        else:
            name = pc.GetModule().GetFileSpec().GetFilename()
            start_addr = pc.GetLoadAddress(target)
            # assert False, "Neither symbol nor the function are valid!"

        instrs = driver_instance().disassemble_frame(thread.GetSelectedFrame())
        if not instrs:
            return 'Error getting instructions for thread ' + str(thread)

        pc = driver_instance().get_PC()

        def get_max_sizes(accum, next):
            return (max(accum[0], len(next[1])), max(accum[1], len(next[2])))
        (max_mnemonic, max_operands) = reduce(get_max_sizes, instrs, (0, 0))
        format_str = '%2.2s%.10s: %*s %*s%s\n'
        max_mnemonic, max_operands = (int(max_mnemonic), int(max_operands))

        result = '%s @ 0x%s:\n' % (name, start_addr)
        n_instrs = 0
        for i in instrs:
            n_instrs += 1
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
                self.__pc_line = n_instrs
                pc_str = '=>'

            result += format_str % (pc_str, hex(addr), max_mnemonic, mnemonic, max_operands, ops, comment_str)

        return result