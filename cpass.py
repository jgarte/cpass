#!/usr/bin/env python3
# Author: Lu Xu <oliver_lew at outlook dot com>
# License: MIT License Copyright (c) 2021 Lu Xu

import os
import re
import urwid
import logging
import tempfile
import configparser
from subprocess import run, PIPE, DEVNULL

version = "0.9.1"


class PassNode(urwid.AttrMap):
    def __init__(self, node, root, isdir=False):
        """ node=None to represent empty node """
        self._selectable = True

        self.node = node
        self.isdir = isdir
        self.text = node if node else "-- EMPTY --"
        self.path = os.path.join(root, node) if node else ''
        self.icon = config.icon_dir if isdir else config.icon_file if node else ''

        super().__init__(urwid.Columns([
                ('pack', urwid.Text(self.icon)),
                urwid.Text(self.text, wrap='clip'),
                ('pack', urwid.Text(''))
            ]),
            'dir' if isdir else '' if node else 'bright',
            'focusdir' if isdir else 'focus' if node else 'bright',
        )

        self.update_count()

    def update_count(self):
        # topdown option in os.walk makes this possible,
        # so that children folders are traversed before its parent
        if self.isdir:
            count = len(Pass.all_pass[self.path])
            self.original_widget.contents[2][0].set_text(str(count))

    def keypress(self, size, key):
        """ let the widget pass through the keys to parent widget """
        return key


class PassList(urwid.ListBox):
    def __init__(self, body, root='', ui=None):
        self._ui = ui
        self.root = root
        self._size = (1, 1)
        super().__init__(body)

    def mouse_event(self, size, event, button, col, row, focus):
        self._size = size
        focus_offset = self.get_focus_offset_inset(size)[0]

        logging.debug("passlist mouse event: {} {} {} {} {} {} {} {}".format(
            size, event, button, col, row, focus, self.focus_position, focus_offset
        ))

        if button == 1:
            if size[1] > len(self.body):
                # NOTE: offset is wrong(?) when size is larger than length
                # so the processing is different
                if row == self.focus_position:
                    self.dir_navigate('down')
                else:
                    self.list_navigate(new_focus=row)
            else:
                if row == focus_offset:
                    self.dir_navigate('down')
                else:
                    self.list_navigate(new_focus=self.focus_position - focus_offset + row)
        elif button == 3:
            self.dir_navigate('up')
        elif button == 4:
            self.list_navigate(-1)
        elif button == 5:
            self.list_navigate(1)
        else:
            return super().mouse_event(size, event, button, col, row, focus)

    def keypress(self, size, key):
        self._size = size
        logging.debug("passlist keypress: {} {}".format(key, size))

        list_navigation_offsets = {
            'down': 1,
            'up': -1,
            'end': len(self.body),
            'home': -len(self.body),
            'down_screen': size[1],
            'up_screen': -size[1],
            'down_half_screen': size[1] // 2,
            'up_half_screen': -size[1] // 2,
            # overshoot to go to bottom/top
        }

        dir_navigation_directions = {
            'confirm': 'down',  # the confirm key doubles as enter folder key
            'dir_down': 'down',
            'dir_up':   'up',
        }

        action = config.keybindings.get(key)
        if action in list_navigation_offsets:
            self.list_navigate(list_navigation_offsets[action])
        elif action in dir_navigation_directions:
            self.dir_navigate(dir_navigation_directions[action])
        else:
            return super().keypress(size, key)

    def dir_navigate(self, direction):
        # record current position
        Pass.all_pass[self.root].pos = self.focus_position

        # change root position accordingly
        if direction in 'down' and self.focus.isdir:
            self.root = os.path.join(self.root, self.focus.node)
        elif direction in 'up':
            self.root = os.path.dirname(self.root)

        # update listbox content, this way the list itself is not replaced
        self.body[:] = Pass.all_pass[self.root]

        # restore cursor position of the new root
        self.focus_position = Pass.all_pass[self.root].pos

        self._ui.update_view()

    def list_navigate(self, shift=0, new_focus=None):
        offset = self.get_focus_offset_inset(self._size)[0]

        # either specify a shift offset, or an absolute position
        if new_focus is None:
            new_focus = self.focus_position + shift
        else:
            shift = new_focus - self.focus_position
        new_offset = offset + shift

        # border check
        new_focus = min(max(new_focus, 0), len(self.body) - 1)
        new_offset = min(max(new_offset, 0), self._size[1] - 1)

        self.change_focus(self._size, new_focus, offset_inset=new_offset)
        self._ui.update_view()

    def insert(self, node):
        def insert_relative(r, n):
            n1, sep, n2 = n.partition(os.sep)
            if sep == os.sep:
                insert_relative(os.path.join(r, n1), n2)
            passnode = PassNode(n1, r, isdir=(sep == os.sep))
            # change stored list
            if Pass.all_pass.get(r) is None:
                Pass.all_pass[r] = FolderWalker(r)
            pos = Pass.all_pass[r].insert_sorted(passnode)
            # change saved cursor position
            Pass.all_pass[r].pos = pos
            return pos

        inserted_pos = insert_relative(self.root, node)
        # change listwalker
        self.body[:] = Pass.all_pass[self.root]
        # focus the new node
        self.set_focus(inserted_pos)

        self._ui.update_view()

    def delete(self, pos):
        # change stored list
        Pass.all_pass[self.root].pop(pos)
        # change listwalker
        self.body[:] = Pass.all_pass[self.root]

        self._ui.update_view()

    def update_root_count(self):
        for n in Pass.all_pass[os.path.dirname(self.root)]:
            if n.node == self.root and n.isdir:
                n.update_count()
                return


class FolderWalker(list):
    def __init__(self, root, dirs=[], files=[]):
        self.pos = 0  # cursor position

        self[:] = [PassNode(f, root, True) for f in sorted(dirs, key=str.lower)] + \
                  [PassNode(f, root) for f in sorted(files, key=str.lower)]

        # prevent empty list, which troubles listbox operations
        if len(self) == 0:
            self[:] = [PassNode(None, None)]

    def pop(self, index=-1):
        super().pop(index)
        if len(self) == 0:
            super().append(PassNode(None, None))

    def insert_sorted(self, node):
        # if node already exist, return the index
        for n in self:
            if n.node == node.node and n.isdir == node.isdir:
                return self.index(n)

        # pop the empty placeholder node beforehand
        if len(self) == 1 and self[0].node is None:
            super().pop()

        # insert and sort, with directories sorted before files
        super().insert(self.pos, node)
        self[:] = sorted([n for n in self if n.isdir], key=lambda n: n.node.lower()) + \
            sorted([n for n in self if not n.isdir], key=lambda n: n.node.lower())
        return self.index(node)


# TODO: background preview, or/and cache preview results
# TODO: deal with focus changing when editing
class UI(urwid.Frame):
    def __init__(self):
        self._last_preview = None
        self._app_string = 'cPass'
        self._preview_shown = True
        self._edit_type = None
        self._search_pattern = None
        self._search_direction = 1
        self._help_string = ' a:generate e:edit i:insert y:copy z:toggle /:search'

        # widgets
        self.path_indicator = urwid.Text('', wrap='clip')
        self.help_text = urwid.Text(self._help_string)
        self.header_widget = urwid.Columns([self.path_indicator, ('pack', self.help_text)])
        self.messagebox = urwid.Text('')
        self.count_indicator = urwid.Text('', align='right')
        self.footer_widget = urwid.Columns([
            self.messagebox,
            ('pack', urwid.AttrMap(self.count_indicator, 'border'))
        ])
        self.divider = urwid.AttrMap(urwid.Divider('-'), 'border')
        self.preview = urwid.Filler(urwid.Text(''), valign='top')
        self.editbox = urwid.Edit()

        self.walker = urwid.SimpleListWalker(Pass.all_pass[''])
        self.listbox = PassList(self.walker, ui=self)

        # use Columns for horizonal layout, and Pile for vertical
        if config.preview_layout in ['side', 'horizontal']:
            self.middle = urwid.Columns([], dividechars=1)
        elif config.preview_layout in ['bottom', 'vertical']:
            self.middle = urwid.Pile([])
        self.update_preview_layout()
        self.update_view()

        super().__init__(self.middle, self.header_widget, self.footer_widget)

    def message(self, message, alert=False):
        self.messagebox.set_text(('alert' if alert else 'normal',
                                  message.replace('\n', ' ')))

    def update_preview_layout(self):
        if self._preview_shown:
            if config.preview_layout in ['side', 'horizontal']:
                self.middle.contents = [(self.listbox, ('weight', 1, False)),
                                        (self.preview, ('weight', 1, False))]
            if config.preview_layout in ['bottom', 'vertical']:
                self.middle.contents = [(self.listbox, ('weight', 1)),
                                        (self.divider, ('pack', 1)),
                                        (self.preview, ('weight', 1))]
            self.update_preview()
        else:
            self.middle.contents = [(self.listbox, ('weight', 1, False))]
        self.middle.focus_position = 0

    def keypress(self, size, key):
        logging.debug("ui keypress: {} {}".format(key, size))
        action = config.keybindings.get(key)
        if action == 'cancel':
            self.unfocus_edit()
        elif action == 'quit' and self._edit_type is None:
            raise urwid.ExitMainLoop
        elif self._edit_type == "copy":
            self.unfocus_edit()
            self.copy_by_key(key)
        elif self._edit_type == "delete":
            self.unfocus_edit()
            self.delete_confirm(key)
        elif action == 'confirm' and self._edit_type is not None:
            self.handle_input()
        elif self._edit_type is not None:
            # pass through to edit widget (the focused widget)
            return super().keypress(size, key)
        elif action == 'search' or action == 'search_back':
            self.focus_edit("search", '/' if action == 'search' else '?')
            self._search_direction = 1 if action == 'search' else -1
        elif action == 'search_next' or action == 'search_prev':
            self.search_in_dir(self._search_pattern,
                               1 if action == 'search_next' else -1)
        elif action == 'insert':
            self.focus_edit("insert", 'Enter password filename: ')
        elif action == 'generate':
            self.focus_edit("generate", 'Generate a password file: ')
        elif action == 'edit' and not self.listbox.focus.isdir:
            self.run_pass(Pass.edit, self.listbox.insert,
                          self.listbox.focus.node, self.listbox.root, "Edit: {}")
            urwid.emit_signal(self, 'redraw')
        elif action == 'delete':
            self.focus_edit("delete", 'Are you sure to delete {} {}? [Y/n]'.format(
                "the whole folder" if self.listbox.focus.isdir else "the file",
                os.path.join('/', self.listbox.root, self.listbox.focus.node)
            ))
        elif action == 'copy':
            self.copy_confirm()
        elif action == 'toggle_preview':
            self._preview_shown = not self._preview_shown
            self.update_preview_layout()
        else:
            return super().keypress(size, key)

    def unfocus_edit(self):
        self._edit_type = None
        self.contents['footer'] = (self.footer_widget, None)
        self.set_focus('body')
        self.messagebox.set_text('')
        self.editbox.set_mask(None)

    def focus_edit(self, edit_type, cap='', mask=None):
        self._edit_type = edit_type
        self.contents['footer'] = (self.editbox, None)
        self.set_focus('footer')
        self.editbox.set_caption(cap)
        self.editbox.set_mask(mask)
        self.editbox.set_edit_text('')

    def handle_input(self):
        if self._edit_type == "search":
            self._search_pattern = self.editbox.edit_text
            self.unfocus_edit()
            self.search_in_dir(self._search_pattern, 1)
        elif self._edit_type == "generate":
            self.unfocus_edit()
            self.run_pass(Pass.generate, self.listbox.insert,
                          self.editbox.edit_text, self.listbox.root, "Generate: {}")
            self.listbox.update_root_count()
        elif self._edit_type == "insert":
            self._insert_node = self.editbox.edit_text
            self.focus_edit("insert_password", 'Enter password: ', '*')
        elif self._edit_type == "insert_password":
            self._insert_pass = self.editbox.edit_text
            self.focus_edit("insert_password_confirm", 'Enter password again: ', '*')
        elif self._edit_type == "insert_password_confirm":
            self.unfocus_edit()
            self._insert_pass_again = self.editbox.edit_text
            if self._insert_pass == self._insert_pass_again:
                self.run_pass(Pass.insert, self.listbox.insert,
                              self._insert_node, self.listbox.root, "Insert: {}",
                              args=(self._insert_pass,))
                self.listbox.update_root_count()
            else:
                self.message("Password is not the same", alert=True)

    def update_view(self):
        # update header
        self.path_indicator.set_text([
            ('border', '{}: '.format(self._app_string)),
            ('bright', '/{}'.format(self.listbox.root)),
        ])

        # update footer
        self.count_indicator.set_text("{}/{}".format(
            self.listbox.focus_position + 1,
            len(self.listbox.body)
        ) if self.listbox.focus.node else "0/0")

        self.update_preview()

    def update_preview(self, force=False):
        if not self._preview_shown:
            return

        node = self.listbox.focus.text
        path = os.path.join(self.listbox.root, node)

        if not force and self.listbox.focus == self._last_preview:
            return
        self._last_preview = self.listbox.focus

        if self.listbox.focus.isdir:
            preview = "\n".join([(f.icon + f.text) for f in Pass.all_pass[path]])
        elif self.listbox.focus.node is None:
            preview = ""
        else:
            res = Pass.show(path)
            preview = res.stderr if res.returncode else res.stdout
        self.preview.original_widget.set_text(preview)

    def run_pass(self, func, lfunc, node, root, msg, args=(), largs=()):
        path = os.path.join(root, node)
        res = func(path, *args)
        if res.returncode == 0:
            self.message(msg.format(path))
            if lfunc == self.listbox.insert:
                lfunc(node)
            elif lfunc == self.listbox.delete:
                lfunc(largs[0])
            self.update_preview(force=True)
        else:
            self.message(res.stderr, alert=True)

    def delete_confirm(self, key):
        if key in ['y', 'Y', 'd', 'enter']:
            self.run_pass(Pass.delete, self.listbox.delete,
                          self.listbox.focus.node, self.listbox.root,
                          "Deleting {}", largs=(self.listbox.focus_position,))
            self.listbox.update_root_count()
        elif key in ['n', 'N']:
            self.message("Abort.")
        else:
            self.message("Invalid option.", alert=True)

    def parse_pass(self, passwd):
        lines = passwd.split('\n')
        copiable_fields = {str(i + 1): lines[i] for i in range(min(9, len(lines)))}
        copiable_fields['a'] = passwd
        copiable_fields['y'] = lines[0]

        for line in lines[1:]:
            if line.find(':') != -1:
                field, value = line.split(':')
                if field in config.copy_bindings:
                    copiable_fields[config.copy_bindings[field]] = value.strip()

        return copiable_fields

    def copy_confirm(self):
        if self.listbox.focus.isdir:
            return
        if self._preview_shown:
            password = self.preview.original_widget.text
        else:
            path = os.path.join(self.listbox.root, self.listbox.focus.node)
            res = Pass.show(path)
            if res.returncode != 0:
                self.message(res.stderr, alert=True)
                return
            password = res.stdout

        pw = self.parse_pass(password.strip('\n'))
        self.focus_edit("copy", 'Copy [{}]: '.format(''.join(pw.keys())))
        self._parsed_password = pw

    def copy_by_key(self, key):
        if key in self._parsed_password:
            copy_text = self._parsed_password[key]
            res = run(['xclip', '-selection', Pass.X_SELECTION],
                      text=True, input=copy_text, stderr=DEVNULL, stdout=DEVNULL)
            if res.returncode == 0:
                self.message("Copied.")
            else:
                self.message("Copy with xclip failed", alert=True)
        else:
            self.message("Nothing copied", alert=True)

    def search_in_dir(self, pattern, direction):
        """ direction = 1 or -1 to specify the search direction """
        if pattern is None:
            self.message("No search pattern", alert=True)
            return

        # search from the next/previous, wrap if reach bottom/top
        direction *= self._search_direction
        start = self.listbox.focus_position
        length = len(self.listbox.body)

        # The math here is kind of magic. It's the result after simplification
        if direction > 0:
            start += 1
        search_list = list(range(start, length)) + list(range(start))

        icase = pattern == pattern.lower()
        for i in search_list[::direction]:
            node = self.listbox.body[i].node
            if pattern in (node.lower() if icase else node):
                self.listbox.list_navigate(new_focus=i)
                return

        self.message("No matching", alert=True)


class Pass:
    FALLBACK_PASS_DIR = os.path.join(os.getenv("HOME"), ".password_store")
    PASS_DIR = os.getenv("PASSWORD_STORE_DIR", FALLBACK_PASS_DIR)
    X_SELECTION = os.getenv("PASSWORD_STORE_X_SELECTION", "clipboard")
    EDITOR = os.getenv("EDITOR", "vi")
    all_pass = dict()
    # exit if pass dir does not exit
    assert(os.path.exists(PASS_DIR))

    @classmethod
    def extract_all(cls):
        # pass files traversal, topdown option is essential, see PassNode
        for root, dirs, files in os.walk(cls.PASS_DIR, topdown=False):
            if not root.startswith(os.path.join(cls.PASS_DIR, '.git')):
                root = os.path.normpath(os.path.relpath(root, cls.PASS_DIR)).lstrip('.')
                dirs = [d for d in dirs if d != '.git']
                files = [file[:-4] for file in files if file.endswith('.gpg')]
                # NOTE: all_pass, FolderWalker, PassNode references are in a cycle.
                cls.all_pass[root] = FolderWalker(root, dirs, files)

    @staticmethod
    def show(path):
        logging.debug("Showing password for {}".format(path))
        result = run(['pass', 'show', path], stdout=PIPE, stderr=PIPE, text=True)
        return result

    @classmethod
    def edit(cls, path):
        # work around terminal output by manually edit temp file and insert with multiline
        with tempfile.NamedTemporaryFile() as fp:
            res = cls.show(path)
            if res.returncode != 0:
                return res
            fp.write(res.stdout.encode())
            fp.flush()
            # can not pipe stdout because editor won't show otherwise
            res = run([cls.EDITOR, fp.name], stderr=PIPE)
            if res.returncode != 0:
                return res
            fp.seek(0)
            password = fp.read()
            res = run(['pass', 'insert', '-m', '-f', path], input=password,
                      stderr=PIPE, stdout=PIPE)
            return res

    @staticmethod
    def insert(path, password):
        pw = password + '\n' + password + '\n'
        result = run(['pass', 'insert', '-f', path], input=pw,
                     stdout=PIPE, stderr=PIPE, text=True)
        return result

    @staticmethod
    def generate(path):
        command = ['pass', 'generate', '-f', path]
        if config.no_symbols:
            command.append('-n')
        result = run(command, stdout=PIPE, stderr=PIPE, text=True)
        return result

    @staticmethod
    def delete(path):
        command = ['pass', 'rm', '-r', '-f', path]
        result = run(command, stdout=PIPE, stderr=PIPE, text=True)
        return result


class MyConfigParser(configparser.RawConfigParser):
    def __init__(self):
        DEFAULT_CONFIG_DIR = os.path.join(os.getenv("HOME"), ".config")
        CONFIG_DIR = os.getenv("XDG_CONFIG_DIR", DEFAULT_CONFIG_DIR)
        CONFIG = os.path.join(CONFIG_DIR, "cpass", "cpass.cfg")
        super().__init__()
        if os.path.exists(CONFIG):
            self.read(CONFIG)

        self.preview_layout = self.get('ui', 'preview_layout', 'side')
        self.icon_dir = self.get('icon', 'dir', '/')
        self.icon_file = self.get('icon', 'file', ' ')
        self.no_symbols = self.get('pass', 'no_symbols', 'false', boolean=True)

        self.keybindings = self.get_keybindings()
        self.palette = self.get_palette()
        self.copy_bindings = self.get_copybindings()

    def get(self, section, option, fallback=None, boolean=False):
        try:
            result = super().get(section, option)
            return result == 'true' if boolean else result.strip("\"\'")
        except (configparser.NoOptionError, configparser.NoSectionError):
            return fallback

    def get_keybindings(self):
        action_keys = {
            'dir_down': ['l', 'right'],
            'dir_up': ['h', 'left'],
            'down': ['j', 'down', 'ctrl n'],
            'up': ['k', 'up', 'ctrl p'],
            'down_screen': ['page down', 'ctrl f'],
            'up_screen': ['page up', 'ctrl b'],
            'down_half_screen': ['ctrl d'],
            'up_half_screen': ['ctrl u'],
            'end': ['G', 'end'],
            'home': ['g', 'home'],
            'cancel': ['esc'],
            'confirm': ['enter'],
            'search': ['/'],
            'search_back': ['?'],
            'search_next': ['n'],
            'search_prev': ['N'],
            'insert': ['i'],
            'generate': ['a'],
            'edit': ['e'],
            'delete': ['d'],
            'copy': ['y'],
            'toggle_preview': ['z'],
            'quit': ['q']
        }

        keys = {}
        for action in action_keys:
            keys.update({key: action for key in action_keys[action]})
        # update from configuration file
        if self.has_section('keys'):
            for action in self.options('keys'):
                for key in re.split(',\\s*', self.get('keys', action, '')):
                    keys[key] = action

        return keys

    def get_palette(self):
        palette = [
            # name          fg              bg              mono
            ('normal',      'default',      'default'),
            ('border',      'light green',  'default'),
            ('dir',         'light blue',   'default'),
            ('alert',       'light red',    'default'),
            ('bright',      'white',        'default'),
            ('focus',       'black',        'white'),
            ('focusdir',    'black',        'light blue',   'bold'),
        ]
        # update from configuration file
        for attr in palette:
            colors = self.get('color', attr[0], ','.join(attr[1:]))
            if colors:
                palette[palette.index(attr)] = (attr[0], *re.split(',\\s*', colors))
        return palette

    def get_copybindings(self):
        """ get field-key pairs """
        copy_bindings = {'login': 'l'}

        if self.has_section('copy_fields'):
            for field in self.options('copy_fields'):
                copy_bindings[field] = self.get('copy_fields', field)

        return copy_bindings


def main():
    logging.basicConfig(level=(logging.DEBUG if os.getenv('DEBUG') else logging.DEBUG),
                        filename=os.path.join(tempfile.gettempdir(), 'cpass.log'))

    Pass.extract_all()
    passui = UI()

    mainloop = urwid.MainLoop(passui, palette=config.palette)
    # set no timeout after escape key
    mainloop.screen.set_input_timeouts(complete_wait=0)
    urwid.register_signal(UI, 'redraw')
    urwid.connect_signal(passui, 'redraw', mainloop.screen.clear)
    mainloop.run()


config = MyConfigParser()
if __name__ == '__main__':
    main()
