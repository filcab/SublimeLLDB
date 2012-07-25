import re

import sublime

import lldb
import lldbutil

from multiprocessing import Lock

from debug import debug, debugViews, debugSettings
from utilities import SettingsManager
from root_objects import lldb_register_view_name, lldb_disassembly_view_name,   \
                         lldb_variable_view_name, driver_instance, add_lldb_view


class LLDBView(object):
    def __init__(self, view):
        if view.__class__.__name__.startswith("LLDB"):
            assert False

        self.__view = view
        # Keep track of the View's name, so we don't have to call name()
        # on the main thread
        self.__name = view.name()
        # TODO: What happens when a file is renamed?
        self.__file_name = view.file_name()
        add_lldb_view(self)
        debug(debugViews, "Created an LLDBView with (class, view, name, file_name) == %s" %
              str((self.__class__.__name__, self.__view, self.__name, self.__file_name)))

    ##########################################
    # Base view property caching and method forwarding.
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

    ##########################################
    # Update methods.
    def full_update(self):
        """Performs a full update, calling pre_update() on the current thread
            and subsequently calling update() on the main thread."""
        self.pre_update()
        sublime.set_timeout(self.update, 0)

    def pre_update(self):
        """Prepares the view for an update, performing any work that doesn't
            have to be done on the main view."""
        pass

    def update(self):
        """Updates the view. This method will be called on the UI thread and
            its overrides should only contain UI code, if possible. Most of the
            work should be done on the pre_update() method."""
        assert False, "%s.update() wasn't overridden." % self.__class__.__name__

    def stop(self):
        """Stops the update mechanism from updating the view."""
        # FIXME: Implemente this method.
        pass


class LLDBReadOnlyView(LLDBView):
    """Class to abstract read-only views that show the user information about
        the process being debugged. Examples: LLDBThreadDisassemblyView and
        LLDBRegisterView"""
    def __init__(self, view):
        super(LLDBReadOnlyView, self).__init__(view)
        self.__content = ''

    ##########################################
    # Content managing properties and methods.
    def content(self):
        return self.__content

    def updated_content(self):
        assert False, "%s.updated_content() wasn't overridden." % self.__class__.__name__

    ##########################################
    # Update mechanism implementation.
    def pre_update(self):
        self.__content = self.updated_content()

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

    ##########################################
    # API to let subclasses execute code in the UI thread after the update.
    def epilogue(self):
        pass


class LLDBCodeView(LLDBView):
    eRegionPC = 1 << 0
    eRegionBreakpointEnabled = 1 << 1
    eRegionBreakpointDisabled = 1 << 2

    __pc_line = None
    __bp_lock = Lock()

    # Settings for the whole class
    settings_keys = ['markers.current_line.region_name',
                     'markers.current_line.scope',
                     'markers.current_line.scope.crashed',
                     'markers.current_line.icon',
                     'markers.breakpoint.enabled.region_name',
                     'markers.breakpoint.enabled.scope',
                     'markers.breakpoint.enabled.type',
                     'markers.breakpoint.disabled.region_name',
                     'markers.breakpoint.disabled.scope',
                     'markers.breakpoint.disabled.type']

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

    def __init__(self, view, driver):
        # FIXME: Split stuff that doesn't have to run on the UI thread.
        super(LLDBCodeView, self).__init__(view)

        self.__needs_update = False
        self.__driver = driver
        self.__enabled_bps = {}
        self.__disabled_bps = {}
        # Get info on current breakpoints for this file
        self.__populate_breakpoint_lists()
        if not view.is_loading():
            self.__update_bps()
            self.pre_update()
        else:
            debug(debugViews, 'Skipped LLDBCodeView.__update_bps() because view.is_loading is True')
            self.pre_update()
            self.__needs_update = 'full'  # Horrible hack to update the bp
                                        # markers as well as the pc marker when the on_load
                                        # method calls update on this object

        # FIXME: Just make every LLDBCodeView observe the settings.
        #        Another way to do it would be for the class to observe and
        #        then call the appropriate method on all the instances.
        for k in self.settings_keys:
            self.__sm.add_observer(k, self.setting_updated)

    def __del__(self):
        # FIXME: This method won't get called since our observers dict holds a
        # reference to this object.
        self.__sm.del_observer(self.settings_updated)

    def __repr__(self):
        return '<%s: file_name: %s, needs_update: %s, pc_line: %s, enabled_bps: %s, disable_bps: %s>' % \
            (self.__class__.__name__, self.file_name(), str(self._needs_update),
             str(self.__pc_line), str(self.__enabled_bps), str(self.__disabled_bps))

    ##########################################
    # Settings observer method.
    def setting_updated(self, key, old, new):
        debug(debugSettings | debugViews, 'Updating setting %s from %s to %s. instance: %s' % (key, old, new, self))
        if key.startswith('markers.current_line'):
            # Update all the PC settings.
            self.__mark_pc(None)
            self.__class__.eMarkerPCName = self.__sm.get_default('markers.current_line.region_name', 'lldb.location')
            self.__class__.eMarkerPCScope = self.__sm.get_default('markers.current_line.scope', 'bookmark')
            self.__class__.eMarkerPCScopeCrashed = self.__sm.get_default('markers.current_line.scope.crashed', 'invalid')
            self.__class__.eMarkerPCIcon = self.__sm.get_default('markers.current_line.icon', 'bookmark')
            self.__mark_pc(self.__pc_line - 1, False)

        elif key.startswith('markers.breakpoint.enabled'):
            # Update all the enabled bp settings.
            self.__mark_regions([], self.eRegionBreakpointEnabled)
            self.__class__.eMarkerBreakpointEnabledName = self.__sm.get_default('markers.breakpoint.enabled.region_name',
                                                                           'lldb.breakpoint.enabled')
            self.__class__.eMarkerBreakpointEnabledScope = self.__sm.get_default('markers.breakpoint.enabled.scope', 'string')
            self.__class__.eMarkerBreakpointEnabledIcon = self.__sm.get_default('markers.breakpoint.enabled.type', 'circle')
            # TODO: Check if the settings' on_change method is always called in
            # the main thread. If not, we'll have to guard the regions
            # definition
            v = self.base_view()
            regions = map(lambda line: v.line(v.text_point(line - 1, 0)), self.__enabled_bps.keys())
            self.__mark_regions(regions, self.eRegionBreakpointEnabled)

        elif key.startswith('markers.breakpoint.disabled'):
            # Update all the disabled bp settings.
            self.__mark_regions([], self.eRegionBreakpointDisabled)
            self.__class__.eMarkerBreakpointDisabledName = self.__sm.get_default('markers.breakpoint.disabled.region_name',
                                                                                 'lldb.breakpoint.disabled')
            self.__class__.eMarkerBreakpointDisabledScope = self.__sm.get_default('markers.breakpoint.disabled.scope', 'bookmark')
            self.__class__.eMarkerBreakpointDisabledIcon = self.__sm.get_default('markers.breakpoint.disabled.type', 'circle')
            # TODO: Check if the settings' on_change method is always called in
            # the main thread. If not, we'll have to guard the regions
            # definition
            v = self.base_view()
            regions = map(lambda line: v.line(v.text_point(line - 1, 0)), self.__disabled_bps.keys())
            self.__mark_regions(regions, self.eRegionBreakpointDisabled)

        else:
            raise Exception('Weird key to be updated for LLDBCodeView: %s' % key)

    ##########################################
    # View properties.
    @property
    def __needs_update(self):
        return self._needs_update

    @__needs_update.setter
    def __needs_update(self, value):
        self._needs_update = value

    ##########################################
    # Breakpoint markers' methods.
    def mark_bp(self, line, is_enabled=True):
        # {mark,change,unmark}_bp don't update __needs_update because they
        # immediately update the breakpoint markers
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

    ##########################################
    # Update mechanism implementation.
    def pre_update(self):
        """pre_update will perform lldb-related work and get our PC line"""
        # FIXME: We can't use base_view().is_loading() because Sublime
        # Text 2 won't even let us query views on another thread (even
        # read-only properties!!).
        # This 'full' hack is here to make us wait for the on_load() call
        # on the LLDBUIListener.
        # This variable will make us keep __needs_update == 'full' if it was
        # like that before we ran this function.
        old_needs_update = self.__needs_update
        self.__needs_update = False

        old_pc_line = self.__pc_line
        self.__pc_line = None
        debug(debugViews, 'old pc_line: %s' % str(old_pc_line))

        thread = self.__driver.current_thread()
        if not thread:
            debug(debugViews, 'new pc_line: %s' % str(self.__pc_line))
            if self.__pc_line != old_pc_line:
                self.__needs_update = old_needs_update or True
            return False

        for frame in thread:
            line_entry = frame.GetLineEntry()
            filespec = line_entry.GetFileSpec()
            if filespec:
                filename = filespec.GetDirectory() + '/' + filespec.GetFilename()
                if filename == self.file_name():
                    self.__pc_line = line_entry.GetLine()
                    debug(debugViews, 'new pc_line: %s' % str(self.__pc_line))
                    if self.__pc_line != old_pc_line or old_needs_update == 'full':
                        self.__needs_update = old_needs_update or True
                    return True

        debug(debugViews, 'new pc_line: %s' % str(self.__pc_line))
        if self.__pc_line != old_pc_line or old_needs_update == 'full':
            self.__needs_update = old_needs_update or True
        return False

    def update(self):
        debug(debugViews, 'Updating LLDBCodeView. needs_update: %s' % str(self.__needs_update))
        if self.__needs_update and not self.base_view().is_loading():
            # Hack so we update the bps when updating the view for the first time.
            if self.__needs_update == 'full':
                self.__update_bps()

            if self.__pc_line is not None:
                self.__mark_pc(self.__pc_line - 1, True)
            else:
                self.__mark_pc(None)
            # For now, bp-marking functions will immediately update the
            # view. We don't need to update it when the view is dirty.
            # self.__update_bps()
            self.__needs_update = False
        else:
            debug(debugViews, 'LLDBCodeView: didn\'t need an update (or view was loading): %s' % repr(self))

    def stop(self):
        self.pre_update()  # This will set pc_line to None
        self.__enabled_bps = {}
        self.__disabled_bps = {}

        def to_ui():
            debug(debugViews, 'executing UI code for LLDBCodeView.stop()')
            self.update()
            self.__update_bps()
        sublime.set_timeout(to_ui, 0)

    ##########################################
    # Private LLDBCodeView methods
    def __mark_regions(self, regions, type):
        if type == self.eRegionPC:
            self.__mark_or_delete_regions(self.eMarkerPCName, regions, self.eMarkerPCScope,
                                          self.eMarkerPCIcon, sublime.HIDDEN)
        elif type == self.eRegionBreakpointEnabled:
            self.__mark_or_delete_regions(self.eMarkerBreakpointEnabledName, regions, self.eMarkerBreakpointEnabledScope,
                                          self.eMarkerBreakpointEnabledIcon, sublime.HIDDEN)
        elif type == self.eRegionBreakpointDisabled:
            self.__mark_or_delete_regions(self.eMarkerBreakpointDisabledName, regions, self.eMarkerBreakpointDisabledScope,
                                          self.eMarkerBreakpointDisabledIcon, sublime.HIDDEN)

    def __mark_or_delete_regions(self, name, regions, scope, icon, options):
        if len(regions) > 0:
            debug(debugViews, '(%s) adding regions: %s' % (self.file_name(), (name, regions, scope, icon, options)))
            self.base_view().add_regions(name, regions, scope, icon, options)
        else:
            debug(debugViews, 'erasing regions: %s' % name)
            self.base_view().erase_regions(name)

    def __mark_pc(self, line, show=False):
        debug(debugViews, 'Marking PC for LLDBCodeView: %s' % repr(self))
        v = self.base_view()
        if line is None:
            to_mark = []
        else:
            to_mark = [v.line(v.text_point(line, 0))]
        self.__mark_regions(to_mark, self.eRegionPC)
        if show and to_mark:
            self.show(to_mark[0], True)

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

    def __add_bps(self, lines, are_enabled=True):
        """Adds breakpoints (enabled or disabled) to the view.
            __update_bps() must be called afterwards to refresh the UI."""
        if len(lines) > 0:
            self.__needs_update = True

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
            self.__needs_update = True

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

    def __update_bps(self):
        v = self.base_view()
        regions = map(lambda line: v.line(v.text_point(line - 1, 0)), self.__enabled_bps.keys())
        self.__mark_regions(regions, self.eRegionBreakpointEnabled)
        regions = map(lambda line: v.line(v.text_point(line - 1, 0)), self.__disabled_bps.keys())
        self.__mark_regions(regions, self.eRegionBreakpointDisabled)


class LLDBRegisterView(LLDBReadOnlyView):
    def __init__(self, view, thread):
        self.__thread = thread
        super(LLDBRegisterView, self).__init__(view)
        self.set_name(lldb_register_view_name(thread))
        self.set_scratch()

    @property
    def thread(self):
        return self.__thread

    ##########################################
    # Update mechanism implementation.
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


class LLDBThreadDisassemblyView(LLDBReadOnlyView):
    __pc_line = 0

    settings_keys = ['markers.current_line.region_name',
                     'markers.current_line.scope',
                     'markers.current_line.scope.crashed',
                     'markers.current_line.icon']

    __sm = SettingsManager.getSM()
    eMarkerPCName = __sm.get_default('markers.current_line.region_name', 'lldb.location')
    eMarkerPCScope = __sm.get_default('markers.current_line.scope', 'bookmark')
    eMarkerPCScopeCrashed = __sm.get_default('markers.current_line.scope.crashed', 'invalid')
    eMarkerPCIcon = __sm.get_default('markers.current_line.icon', 'bookmark')

    def __init__(self, view, thread):
        self.__thread = thread
        super(LLDBThreadDisassemblyView, self).__init__(view)

        self.set_name(lldb_disassembly_view_name(thread.GetThreadID()))
        self.set_scratch()

        # FIXME: Just make every LLDBCodeView observe the settings.
        #        Another way to do it would be for the class to observe and
        #        then call the appropriate method on all the instances.
        for k in self.settings_keys:
            self.__sm.add_observer(k, self.setting_updated)

    def __repr__(self):
        return '<%s: name: %s, thread %s, pc_line: %d, content size: %d>' % \
            (self.__class__.__name__, self.name(), self.thread, self.pc_line, len(self.content()))

    ##########################################
    # View properties.
    @property
    def thread(self):
        return self.__thread

    @property
    def pc_line(self):
        return self.__pc_line

    ##########################################
    # Settings observer method.
    def setting_updated(self, key, old, new):
        debug(debugSettings | debugViews, 'Updating setting %s from %s to %s. instance: %s' % (key, old, new, self))
        if key.startswith('markers.current_line'):
            # Update all the PC settings.
            self.__mark_pc(None)
            self.__class__.eMarkerPCName = self.__sm.get_default('markers.current_line.region_name', 'lldb.location')
            self.__class__.eMarkerPCScope = self.__sm.get_default('markers.current_line.scope', 'bookmark')
            self.__class__.eMarkerPCScopeCrashed = self.__sm.get_default('markers.current_line.scope.crashed', 'invalid')
            self.__class__.eMarkerPCIcon = self.__sm.get_default('markers.current_line.icon', 'bookmark')
            self.__mark_pc(self.__pc_line - 1, False)

        else:
            raise Exception('Weird key to be updated for LLDBThreadDisassemblyView %s' % key)

    ##########################################
    # Update mechanism implementation.
    def epilogue(self):
        if self.pc_line != 0:
            debug(debugViews, 'Marking PC for LLDBDisassemblyView %s' % repr(self))
            v = self.base_view()
            r = v.text_point(self.pc_line, 0)
            to_mark = [v.line(r)]

            debug(debugViews, '(' + self.name() + ') adding region: ' + str((self.eMarkerPCName, to_mark, self.eMarkerPCScope, self.eMarkerPCIcon, sublime.HIDDEN)))
            self.base_view().add_regions(self.eMarkerPCName, to_mark, self.eMarkerPCScope, self.eMarkerPCIcon, sublime.HIDDEN)
            self.show(to_mark[0], True)
        else:
            debug(debugViews, 'erasing region: %s' % self.eMarkerPCName)
            self.base_view().erase_regions(self.eMarkerPCName)

    def updated_content(self):
        debug(debugViews, 'Updating content for: %s' % repr(self))
        # Reset the PC line number
        self.__pc_line = 0

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

        instrs = driver_instance().disassemble_frame(thread.GetSelectedFrame())
        if not instrs:
            return 'Error getting instructions for thread 0x%x: No instructions available.' % thread.GetThreadID()

        pc = driver_instance().get_PC()

        def get_max_sizes(accum, next):
            return (max(accum[0], len(next[1])), max(accum[1], len(next[2])))
        (max_mnemonic, max_operands) = reduce(get_max_sizes, instrs, (0, 0))
        format_str = '%.10s: %*s %*s%s\n'
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

            if pc == addr:
                self.__pc_line = n_instrs

            result += format_str % (hex(addr), max_mnemonic, mnemonic, max_operands, ops, comment_str)

        return result


class LLDBVariableView(LLDBReadOnlyView):
    def __init__(self, view, thread):
        self.__thread = thread
        super(LLDBVariableView, self).__init__(view)
        self.set_name(lldb_variable_view_name(thread))
        self.set_scratch()

    @property
    def thread(self):
        return self.__thread

    ##########################################
    # Update mechanism implementation.
    def updated_content(self):
        thread = self.__thread
        if not thread.IsValid():
            return 'Invalid thread. Has it finished its work?'

        frame = thread.GetSelectedFrame()
        # TODO: Allow users to configure which variables to get.
        variables = frame.GetVariables(True, True, True, True)
        result = 'Frame variables:\n'
        for var in variables:
            result = result + ('%s = ' % self.__name_for(var))
            if var.GetNumChildren() == 0:
                result = result + self.__value_for(var) + '\n'
            else:
                result = result + '{\n'
                for child in var:
                    typename = self.__typename_for(child)
                    name = self.__name_for(child)
                    value = self.__value_for(child)
                    result = result + ('  (%s) %s = %s,\n' % (typename, name, value))
                result = result + '}\n'

        return result

    ##########################################
    # Private methods
    def __typename_for(self, value):
        if value.IsValid():
            return value.GetTypeName()
        else:
            return "<invalid type>"

    def __name_for(self, value):
        if value.IsValid():
            return value.GetName()
        else:
            return "<no name>"

    def __value_for(self, value):
        if value.IsValid():
            if not value.IsInScope():
                return "out of scope"

            return value.GetValue()
        else:
            return "<no value>"
