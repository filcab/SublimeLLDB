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

