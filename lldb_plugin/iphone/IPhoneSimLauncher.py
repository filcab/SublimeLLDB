class DebugHelperTool(object):
    """
    Skeleton of a helper dev tool for debugging with lldb.

    Example: iPhone simulator, iPhone helper, remote debugging helper, etc...
    """

    def will_launch_helper(self, *args):
        pass

    def do_launch_helper(self, *args):
        pass

    def did_launch_helper(self):
        pass

    def launch_helper(self):
        self.will_launch_helper()
        self.do_launch_helper()
        self.did_launch_helper()


import os
import sys
import subprocess


class IPhoneSimLauncher(DebugHelperTool):
    """
    iPhone simulator helper implementation
    """
    # Static vars
    __simulator_path = ''
    __initialized = False

    private_frameworks_relative_path =  \
      '/Platforms/iPhoneSimulator.platform/Developer/Library/PrivateFrameworks'

    # Instance vars
    __iphone_version = '5.1'
    __app = None
    __process = None

    @staticmethod
    def set_simulator_path(path):
        IPhoneSimLauncher.__simulator_path = path

    @staticmethod
    def set_home_dir(path):
        IPhoneSimLauncher.__home_dir = path

    @staticmethod
    def initialize():
        if IPhoneSimLauncher.__initialized:
            return

        IPhoneSimLauncher.__initialized = True
        IPhoneSimLauncher.add_xcode_private_frameworks_to_DYLD_PATH()

    @staticmethod
    def add_xcode_private_frameworks_to_DYLD_PATH():
        xcodeselectpath = os.popen("/usr/bin/xcode-select -print-path")     \
                            .readline().rstrip('\n')
        iphoneprivateframeworkspath = xcodeselectpath                       \
            + IPhoneSimLauncher.private_frameworks_relative_path
        os.putenv('DYLD_FRAMEWORK_PATH', iphoneprivateframeworkspath)

    def __init__(self, app, family='', retina=False):
        IPhoneSimLauncher.initialize()
        self.__app = app
        self.__family = family
        self.__retina = retina

    def do_launch_helper(self):
        if self.__family == 'ipad':
            self.__retina = False  # We don't support the retina iPad yet

        if self.__family:
            command = '"%s" launch "%s" --sdk %s --family %s%s' % \
                (self.__simulator_path, self.__app, self.__iphone_version,
                 self.__family, ' --retina' if self.__retina else '')
        else:
            command = '"%s" launch "%s" --sdk %s' %  \
                (self.__simulator_path, self.__app, self.__iphone_version)

        self.__process =    \
            subprocess.Popen(command, shell=True, cwd=self.__home_dir)

    def did_launch_helper(self):
        os.system('osascript -e \'tell application "iPhone Simulator" to activate\'')


template_dir = os.path.abspath(os.path.dirname(sys._getframe(0).f_code.co_filename))
iPhone_sim = os.path.abspath(os.path.join(template_dir, 'ios-sim'))

# Setup plugin on load
IPhoneSimLauncher.set_home_dir(template_dir)
IPhoneSimLauncher.set_simulator_path(iPhone_sim)


# # Testing stuff
# if __name__ == '__main__':
#     sim = IPhoneSimLauncher('/Users/filcab/Library/Developer/Xcode/'        \
#                           + 'DerivedData/'                                  \
#                           + 'Hagreve_Mobile-aiyzriucpbokxgdqqvnjgshmwloy/'  \
#                           + 'Build/Products/Testflight-iphonesimulator/'    \
#                           + 'Hagreve Mobile.app')
#     sim.launch_helper()
