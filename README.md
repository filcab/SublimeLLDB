Sublime Text 2 LLDB plugin
==========================

This is a plugin that allows users to debug programs in Sublime Text 2
using lldb.

Usage:
* cmd+shift+l: Open lldb prompt (maybe starting lldb)
* cmd+shift+k: Show/hide the lldb i/o view
* cmd+shift+alt+k: Clear the lldb i/o view

Features:
* Command-line interface like the lldb tool
* Line-level markers for the program counter and breakpoints
* Event-driven to avoid any editing slow-downs due to the plugin

Known bugs:
* stdin to the debugged program has to be passed using the console (yes,
  to use stdin in your program, you have to either redirect it using the
  debugger or start Sublime Text 2 using the console
* ...

Please feel free to ask for additional functionalities either in the
forums or through github.

*** `debugserver` binary

The default `debugserver` binary that is used is the system one (when XCode
or the command line tools are installed).
If the bundled `debugserver` is to be used (e.g: newer `debugserver` with
protocol enhancements), change the variable `__use_bundled_debugserver` in
`sublime_lldb.py` to `True` and sign the
`<plugin folder>/lldb_plugin/LLDB.framework/Resources/debugserver` binary
as instructed in the `docs/code-signing.txt` file in lldb's sources.

