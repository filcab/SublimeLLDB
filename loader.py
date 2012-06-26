from plugin.sublime_lldb import *
from plugin import monitors

# If we only import those names, it works too. But we get lint errors.
# So we import everything and export only the command names.

# lldb
# This command opens the input panel for the debugger.
# If it's not initialized, it starts a debugger instance.
LldbCommand = LldbCommand

# lldb_clear_output_view
# This command clears the 'lldb i/o' view if the debugger has already started.
LldbClearOutputView = LldbClearOutputView

# lldb_toggle_output_view
# This command shows/hides the 'lldb i/o' view.
LldbToggleOutputView = LldbToggleOutputView

unload_handler = unload_handler

# UI Listener, for on_load events.
LLDBUIListener = monitors.LLDBUIListener
