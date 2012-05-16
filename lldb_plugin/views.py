import lldbutil

import sublime
import sublime_plugin

class LLDBView(sublimg_plugin.SublimeView):
  pass


class LLDBRegisterView(LLDBView):
  def __init__(self, frame):
    self.__thread = thread
    self.set_name(lldbutil.get_description(thread))
    debug('LLDBRegisterView.name == ' + self.name())

  def __nonzero__(self):
    return self.valid

  @property
  def valid(self):
    return self.frame.IsValid()

  @property
  def thread(self):
    return self.__thread

  def update(self):
    string = self.make_register_info_string()
    region = sublime.Region(0, self.size()))
    def updater(self):
      self.set_read_only(False)
      edit = self.begin_edit(self.name)
      self.erase(edit, region)
      self.insert(edit, 0, string)
      self.end_edit(edit)
      self.set_read_only(True)
    sublime.set_timeout(updater, 0)

  def make_register_info_string(self):
    if not thread.IsValid():
      return 'Invalid thread. Has it finished its work?'

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
                    desc = ', ' + desc
                result = result + ('%10.10s = %.18s%s\n' % (child.GetName(), child.GetValue(), desc))

    return result

