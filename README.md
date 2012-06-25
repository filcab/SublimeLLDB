Sublime Text 2 LLDB plugin
==========================

(last updated: long ago)

This is a plugin that allows users to debug programs in Sublime Text 2
using lldb.

Usage
-----
* Menu items in Tools->LLDB
* Quick access commands using Sublime Text 2's Command Pallette (all commands
  start with “LLDB: ”)


Useful Keybound Commands
------------------------

* super+shift+l: (LldbCommand) Open lldb prompt (maybe starting lldb)

* super+shift+k: (LldbToggleOutputView) Show/hide the lldb i/o view
* super+shift+alt+k: (LldbClearOutputView) Clear the lldb i/o view

* Xcode-like commands (Mac OS X):
 * super+ctrl+y: (LldbContinue) Continue executing the program
 * F6: (LldbStepOver) Step over
 * F7: (LldbStepInto) Step into
 * F8: (LldbStepOut) Step out
 * ctrl+F6: (LldbStepOverInstruction) Step over instruction
 * ctrl+shift+F6: (LldbStepOverThread) Step over thread
 * ctrl+F7: (LldbStepIntoInstruction) Step into instruction
 * ctrl+shift+F7: (LldbStepIntoThread) Step into thread
 * super+shift+m: (LldbViewMemory) View process memory


Other Useful Commands
---------------------

* LldbDebugProgram
* LldbAttachProcess
* LldbConnectDebugserver

* LldbStopDebugging
* LldbSendSignal

* LldbListBreakpoints
* LldbBreakAt{Line,Symbol}
* LldbToggleEnableBreakpoints

* LldbViewSharedLibraries
* LldbRegisterView
* LldbDisassembleFrame


Features
--------
* Command-line interface like the lldb tool
* Line-level markers for the program counter and breakpoints
* Event-driven to avoid any editing slow-downs due to the plugin

Installation
------------
* Clone github repository to Sublime Text 2's “Packages” directory
* Restart Sublime Text 2

Known bugs
----------
* `stdin` to the debugged program (or debugger queries) has to be passed using
  the console (yes, to use `stdin` in your program, you have to either redirect
  it using the debugger or start Sublime Text 2 using the console). Executing
  the `process launch` command while the program is running will hang lldb
  until you reply with `y` or `n` to the `stdin` (usually the Terminal).
* The plugin is very new and doesn't export a lot of functionality. But simple
  usage shold be fine.
* The input reader thread is named (for Python) Dummy-N (N=1, ...). This
  is a Python problem (the LLDB library uses `pthread_setname_np` to name
  the thread).
* ...

Please feel free to ask for additional functionalities either in the
forums or through github.

`debugserver` binary
--------------------
The default `debugserver` binary that is used is the system one (when XCode
or the command line tools are installed).
If the bundled `debugserver` is to be used (e.g: newer `debugserver` with
protocol enhancements), change the variable `__use_bundled_debugserver` in
`sublime_lldb.py` to `True` and sign the
`<plugin folder>/lldb_plugin/LLDB.framework/Resources/debugserver` binary
as instructed in the `docs/code-signing.txt` file in lldb's sources.

