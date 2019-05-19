#!/usr/bin/python

# Convert .mo compiled catalog to .rpy translation blocks and strings

# Copyright (C) 2019  Sylvain Beucler

# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

from __future__ import print_function
import sys, os, fnmatch
import re
import subprocess, shutil
import tempfile
import tlparser
import gettext

# Doc: manual .mo test:
# mkdir -p $LANG/LC_MESSAGES/
# msgfmt xxx.po -o $LANG/LC_MESSAGES/game.mo
# TEXTDOMAINDIR=. gettext -s -d game "Start"
# TEXTDOMAINDIR=. gettext -s -d game "script_abcd1234"$'\x4'"You've created a new Ren'Py game."

def mo2tl(projectpath, mofile, renpy_target_language):
    if not renpy_target_language.isalpha():
        raise Exception("Invalid language", language)

    # Refresh strings
    try:
        # Ensure Ren'Py keeps the strings order (rather than append new strings)
        shutil.rmtree(os.path.join(projectpath,'game','tl','pot'))
    except OSError:
        pass
    # TODO: renpy within renpy == sys.executable -EO sys.argv[0]
    # cf. launcher/game/project.rpy
    print("Calling Ren'Py translate")
    # using --compile otherwise Ren'Py sometimes skips half of the files
    ret = subprocess.call(['renpy.sh', projectpath, 'translate', 'pot', '--compile'])
    if ret != 0:
        raise Exception("Ren'Py error")
    ret = subprocess.call(['renpy.sh', projectpath, 'translate', renpy_target_language])
    if ret != 0:
        raise Exception("Ren'Py error")
    
    originals = []
    for curdir, subdirs, filenames in os.walk(os.path.join(projectpath,'game','tl',renpy_target_language)):
        for filename in fnmatch.filter(filenames, '*.rpy'):
            print("Updating  " + os.path.join(curdir,filename))
            f = open(os.path.join(curdir,filename), 'r')
            lines = f.readlines()
            lines[0].lstrip('\ufeff')  # BOM

            lines.reverse()
            while len(lines) > 0:
                originals.extend(tlparser.parse_next_block(lines))

    o_blocks_index = {}
    o_basestr_index = {}
    for s in originals:
        if s['id']:
            o_blocks_index[s['id']] = s['text']
        else:
            o_basestr_index[s['text']] = s['translation']

    localedir = tempfile.mkdtemp()
    # Setup gettext directory structure
    msgdir = os.path.join(localedir,
                          os.environ.get('LANG', 'en_US.UTF-8'),
                          'LC_MESSAGES')
    os.makedirs(msgdir)
    if mofile.endswith('.po'):
        pofile = mofile
        ret = subprocess.call(['msgfmt', pofile, '-v', '-o', os.path.join(msgdir, 'game.mo')])
        if ret != 0:
            raise Exception("msgfmt failed")
    else:
        shutil.copy2(mofile, os.path.join(msgdir, 'game.mo'))
    gettext.bindtextdomain('game', localedir)
    gettext.dgettext('game', 'text')

    for curdir, subdirs, filenames in os.walk(os.path.join(projectpath,'game','tl',renpy_target_language)):
        for filename in fnmatch.filter(filenames, '*.rpy'):
            scriptpath = os.path.join(curdir,filename)
            f_in = open(scriptpath, 'r')
            lines = f_in.readlines()
            if lines[0].startswith('\xef\xbb\xbf'):
                lines[0] = lines[0][3:]  # BOM
            lines.reverse()  # reverse so we can pop/append efficiently
            f_in.close()
        
            out = open(scriptpath, 'w')
            out.write('\xef\xbb\xbf')  # BOM, just in case
            while len(lines) > 0:
                line = lines.pop()
                if tlparser.is_empty(line):
                    continue
                elif tlparser.is_comment(line):
                    continue
                elif tlparser.is_block_start(line):
                    msgid = line.strip(':\n').split()[2]
                    if msgid == 'strings':
                        # basic strings block
                        out.write(line)
                        s = None
                        translation = ''
                        while len(lines) > 0:
                            line = lines.pop()
                            if tlparser.is_empty(line):
                                pass
                            elif tlparser.is_comment(line):
                                pass
                            elif not line.startswith(' '):
                                # end of block
                                lines.append(line)
                                break
                            elif line.lstrip().startswith('old '):
                                msgstr = tlparser.extract_base_string(line)['text']
                                translation = gettext.dgettext('game', msgstr)
                            elif line.lstrip().startswith('new '):
                                if translation is not None:
                                    s = tlparser.extract_base_string(line)
                                    line = line[:s['start']]+translation+line[s['end']:]
                                translation = None
                            else:
                                pass
                            out.write(line)
                    else:
                        # dialog block
                        out.write(line)
                        while len(lines) > 0:
                            line = lines.pop()
                            if tlparser.is_empty(line):
                                pass
                            elif not line.startswith(' '):
                                # end of block
                                lines.append(line)
                                break
                            elif tlparser.is_comment(line):
                                # untranslated original
                                pass
                            else:
                                # dialog line
                                s = tlparser.extract_dialog_string(line)
                                if s is None:
                                    pass  # not a dialog line
                                elif o_blocks_index.get(msgid, None) is None:
                                    pass  # obsolete string
                                else:
                                    msgstr = msgid+'\x04'+o_blocks_index[msgid]
                                    translation = gettext.dgettext('game', msgstr)
                                    if translation == msgstr:
                                        msgstr = o_blocks_index[msgid]
                                        translation = gettext.dgettext('game', msgstr)
                                    line = line[:s['start']]+translation+line[s['end']:]
                            out.write(line)
                # Unknown
                else:
                    print("Warning: format not detected:", line)
                    out.write(line)
    shutil.rmtree(localedir)

if __name__ == '__main__':
    mo2tl(sys.argv[1], sys.argv[2], sys.argv[3])