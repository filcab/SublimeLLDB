#!/usr/bin/env zsh

Verb=

local default_sysroots='/'
local default_sdks_prefix="/Applications/Xcode45-DP2.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs"

for i in {9..6}; do
  if [[ -d "$default_sdks_prefix/MacOSX10.$i.sdk" ]]; then
    default_sysroots+=" $default_sdks_prefix/MacOSX10.$i.sdk"
    break
  fi
done

local framework_dir=/System/Library/Frameworks/Python.framework/Versions
local usrlib_dir=/usr/lib


# default: latest version in /
local version=$(ls $framework_dir | sort | grep -v Current | tail -n 1 | tr -d '\n')

function py_version_print() {
  v=$(cd $framework_dir && \
      ls -ld Current | sed -e 's/^.*Current/Current/')
  sdk_v=$(cd $usrlib_dir && ls -l libpython.dylib)
  echo "Python.framework symlink: $v"
  echo -n "dylib symlink: "
  ls -l /usr/lib/libpython.dylib | sed -e 's/^[^/]*//'
  echo -n "python --version: "
  python --version
}

function list_versions {
  echo "Available python versions:"
  for v in $(cd $framework_dir && ls | grep -v Current); do
    if [[ -d "$framework_dir/$v" && -h "/usr/lib/libpython$v.dylib" ]] \
      && type "python$v" >&-; then
      echo $v
    fi
  done
}

while [[ "${1:0:1}" == "-" ]]; do
  case "$1" in
    -y|--dry-run)
      Verb="echo"
      shift
    ;;
    -c|--check|-p|--print)
      py_version_print
      echo
      list_versions
      exit 0
      ;;
    -l|--list)
      list_versions
      exit 0
      ;;
    -h|--help)
      py_version_print
      echo
      list_versions
      echo "\nUse '$0 <version> [sysroot ...]' to change python version in the \
  mentioned system roots."
      echo Other options:
      echo "-y|--dry-run\tPerform a dry run (only output commands, don't \
  execute them"
      echo
      echo "-l|--list\tList available Python versions"
      echo "-c|--check\tCheck the current Python version and list available \
  versions."
      echo "-p|--print\tSame as --check"
      echo "-h|--help\tThis message"
      exit 0
      ;;
  esac
done

user_version=$version
if [[ ${#*} > 0 ]]; then
  case "$1" in
    2.[0-9])
      echo Setting version $1
      user_version=$1
      shift
      ;;
  esac

  for sysroot in "$*"; do
    sysroots="$sysroots $sysroot"
  done
else
  sysroots=$default_sysroots
fi

if [[ ! -z "$user_version" && -d "$framework_dir/$user_version"
     && -h "/usr/lib/libpython$user_version.dylib" ]] \
     && type "python$user_version" >&-; then
  if [[ "$user_version" == "$version" ]]; then
    # default: use the latest version
    echo "Deleting versioner key"
    $Verb defaults delete com.apple.versioner.python Version 2>&-
  else
    version=$user_version
    echo "Writing versioner key 'Version = $version'"
    $Verb defaults write com.apple.versioner.python Version $version
  fi
else
  echo "$1 is not a valid python version for this system."
  list_versions
  echo
  py_version_print
  exit 1
fi

echo "Changing symlink for Python.framework/Versions/Current"
echo "and symlink for /usr/lib/libpython.dylib for the following system roots:"
for s in ${=sysroots}; do
  echo "\t" $s
done
echo to Python $version

for sysroot in ${=sysroots}; do
  $Verb ${Verb/*}
  ($Verb cd $sysroot$framework_dir
   $Verb sudo rm Current
   $Verb sudo ln -s $version Current)

  ($Verb cd $sysroot$usrlib_dir
   $Verb sudo rm libpython.dylib
   $Verb sudo ln -s libpython$version.dylib libpython.dylib)
  $Verb ${Verb/*}
done

echo
py_version_print "Updated"

