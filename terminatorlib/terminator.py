#!/usr/bin/python
# Terminator by Chris Jones <cmsj@tenshu.net>
# GPL v2 only
"""terminator.py - class for the master Terminator singleton"""

import copy
import os
from gi.repository import Gtk, Gdk

from borg import Borg
from config import Config
from keybindings import Keybindings
from util import dbg, err, enumerate_descendants, TMUX_ATTACH
from factory import Factory
from cwd import get_pid_cwd
from version import APP_NAME, APP_VERSION
import tmux.control
import tmux.notifications

def eventkey2gdkevent(eventkey):  # FIXME FOR GTK3: is there a simpler way of casting from specific EventKey to generic (union) GdkEvent?
    gdkevent = Gdk.Event.new(eventkey.type)
    gdkevent.key.window = eventkey.window
    gdkevent.key.send_event = eventkey.send_event
    gdkevent.key.time = eventkey.time
    gdkevent.key.state = eventkey.state
    gdkevent.key.keyval = eventkey.keyval
    gdkevent.key.length = eventkey.length
    gdkevent.key.string = eventkey.string
    gdkevent.key.hardware_keycode = eventkey.hardware_keycode
    gdkevent.key.group = eventkey.group
    gdkevent.key.is_modifier = eventkey.is_modifier
    return gdkevent

class Terminator(Borg):
    """master object for the application"""

    windows = None
    launcher_windows = None
    windowtitle = None
    terminals = None
    groups = None
    config = None
    keybindings = None
    style_provider = None
    last_focused_term = None

    origcwd = None
    dbus_path = None
    dbus_name = None
    pid_cwd = None
    gnome_client = None
    debug_address = None
    ibus_running = None

    doing_layout = None
    layoutname = None
    last_active_window = None

    groupsend = None
    groupsend_type = {'all':0, 'group':1, 'off':2}

    tmux_control = None
    pane_id_to_terminal = None
    initial_layout = None

    def __init__(self):
        """Class initialiser"""

        Borg.__init__(self, self.__class__.__name__)
        self.prepare_attributes()

    def prepare_attributes(self):
        """Initialise anything that isn't already"""

        if not self.windows:
            self.windows = []
        if not self.launcher_windows:
            self.launcher_windows = []
        if not self.terminals:
            self.terminals = []
        if not self.groups:
            self.groups = []
        if not self.config:
            self.config = Config()
        if self.groupsend == None:
            self.groupsend = self.groupsend_type[self.config['broadcast_default']]
        if not self.keybindings:
            self.keybindings = Keybindings()
            self.keybindings.configure(self.config['keybindings'])
        if not self.doing_layout:
            self.doing_layout = False
        if not self.pid_cwd:
            self.pid_cwd = get_pid_cwd()
        if self.gnome_client is None:
            self.attempt_gnome_client()
        if self.pane_id_to_terminal is None:
            self.pane_id_to_terminal = {}
        if self.tmux_control is None:
            handler = tmux.notifications.NotificationsHandler(self)
            self.tmux_control = tmux.control.TmuxControl(
                session_name='terminator',
                notifications_handler=handler)
            if TMUX_ATTACH:
                self.tmux_control.attach_session()

    def set_origcwd(self, cwd):
        """Store the original cwd our process inherits"""
        if cwd == '/':
            cwd = os.path.expanduser('~')
            os.chdir(cwd)
        self.origcwd = cwd

    def set_dbus_data(self, dbus_service):
        """Store the DBus bus details, if they are available"""
        if dbus_service:
            self.dbus_name = dbus_service.bus_name.get_name()
            self.dbus_path = dbus_service.bus_path

    def attempt_gnome_client(self):
        """Attempt to find a GNOME Session to register with"""
        try:
            from gi.repository import Gnome
            self.gnome_program = Gnome.init(APP_NAME, APP_VERSION)  # VERIFY FOR GTK3
            self.gnome_client = Gnome.Ui.master_client()  # VERIFY FOR GTK3
            self.gnome_client.connect_to_session_manager()
            self.gnome_client.connect('save-yourself', self.save_yourself)
            self.gnome_client.connect('die', self.die)
            dbg('GNOME session support enabled and registered')
        except (ImportError, AttributeError):
            self.gnome_client = False
            dbg('GNOME session support not available')

    def save_yourself(self, *args):
        """Save as much state as possible for the session manager"""
        dbg('preparing session manager state')
        # FIXME: Implement this

    def die(self, *args):
        """Die at the hands of the session manager"""
        dbg('session manager asked us to die')
        # FIXME: Implement this

    def get_windows(self):
        """Return a list of windows"""
        return self.windows

    def register_window(self, window):
        """Register a new window widget"""
        if window not in self.windows:
            dbg('Terminator::register_window: registering %s:%s' % (id(window),
                type(window)))
            self.windows.append(window)

    def deregister_window(self, window):
        """de-register a window widget"""
        dbg('Terminator::deregister_window: de-registering %s:%s' %
                (id(window), type(window)))
        if window in self.windows:
            self.windows.remove(window)
        else:
            err('%s is not in registered window list' % window)

        if len(self.windows) == 0:
            # We have no windows left, we should exit
            dbg('no windows remain, quitting')
            Gtk.main_quit()

    def register_launcher_window(self, window):
        """Register a new launcher window widget"""
        if window not in self.launcher_windows:
            dbg('Terminator::register_launcher_window: registering %s:%s' % (id(window),
                type(window)))
            self.launcher_windows.append(window)

    def deregister_launcher_window(self, window):
        """de-register a launcher window widget"""
        dbg('Terminator::deregister_launcher_window: de-registering %s:%s' %
                (id(window), type(window)))
        if window in self.launcher_windows:
            self.launcher_windows.remove(window)
        else:
            err('%s is not in registered window list' % window)

        if len(self.launcher_windows) == 0 and len(self.windows) == 0:
            # We have no windows left, we should exit
            dbg('no windows remain, quitting')
            Gtk.main_quit()

    def register_terminal(self, terminal):
        """Register a new terminal widget"""
        if terminal not in self.terminals:
            dbg('Terminator::register_terminal: registering %s:%s' %
                    (id(terminal), type(terminal)))
            self.terminals.append(terminal)

    def deregister_terminal(self, terminal):
        """De-register a terminal widget"""
        dbg('Terminator::deregister_terminal: de-registering %s:%s' %
                (id(terminal), type(terminal)))
        self.terminals.remove(terminal)

        if len(self.terminals) == 0:
            dbg('no terminals remain, destroying all windows')
            for window in self.windows:
                window.destroy()
        else:
            dbg('Terminator::deregister_terminal: %d terminals remain' %
                    len(self.terminals))

    def find_terminal_by_uuid(self, uuid):
        """Search our terminals for one matching the supplied UUID"""
        dbg('searching self.terminals for: %s' % uuid)
        for terminal in self.terminals:
            dbg('checking: %s (%s)' % (terminal.uuid.urn, terminal))
            if terminal.uuid.urn == uuid:
                return terminal
        return None

    def find_terminal_by_pane_id(self, pane_id):
        """Search our terminals for one matching the supplied pane_id"""
        dbg('searching self.terminals for: %s' % pane_id)
        for terminal in self.terminals:
            dbg('checking: %s (%s)' % (terminal.pane_id, terminal))
            if terminal.pane_id == pane_id:
                return terminal
        return None

    def new_window(self, cwd=None, profile=None):
        """Create a window with a Terminal in it"""
        maker = Factory()
        window = maker.make('Window')
        terminal = maker.make('Terminal')
        if cwd:
            terminal.set_cwd(cwd)
        if profile and self.config['always_split_with_profile']:
            terminal.force_set_profile(None, profile)
        window.add(terminal)
        window.show(True)
        terminal.spawn_child()

        return(window, terminal)

    def create_layout(self, layoutname):
        """Create all the parts necessary to satisfy the specified layout"""
        layout = copy.deepcopy(self.initial_layout)
        objects = {}

        self.doing_layout = True

        if not layout:
            layout = copy.deepcopy(self.config.layout_get_config(layoutname))
            if not layout:
                # User specified a non-existent layout. default to one Terminal
                err('layout %s not defined' % layout)
                self.new_window()
                return

        # Wind the flat objects into a hierarchy
        hierarchy = {}
        count = 0
        # Loop over the layout until we have consumed it, or hit 1000 loops.
        # This is a stupid artificial limit, but it's safe.
        while len(layout) > 0 and count < 1000:
            count = count + 1
            if count == 1000:
                err('hit maximum loop boundary. THIS IS VERY LIKELY A BUG')
            for obj in layout.keys():
                if layout[obj]['type'].lower() == 'window':
                    hierarchy[obj] = {}
                    hierarchy[obj]['type'] = 'Window'
                    hierarchy[obj]['children'] = {}

                    # Copy any additional keys
                    for objkey in layout[obj].keys():
                        if layout[obj][objkey] != '' and not hierarchy[obj].has_key(objkey):
                            hierarchy[obj][objkey] = layout[obj][objkey]

                    objects[obj] = hierarchy[obj]
                    del(layout[obj])
                else:
                    # Now examine children to see if their parents exist yet
                    if not layout[obj].has_key('parent'):
                        err('Invalid object: %s' % obj)
                        del(layout[obj])
                        continue
                    if objects.has_key(layout[obj]['parent']):
                        # Our parent has been created, add ourselves
                        childobj = {}
                        childobj['type'] = layout[obj]['type']
                        childobj['children'] = {}

                        # Copy over any additional object keys
                        for objkey in layout[obj].keys():
                            if not childobj.has_key(objkey):
                                childobj[objkey] = layout[obj][objkey]

                        objects[layout[obj]['parent']]['children'][obj] = childobj
                        objects[obj] = childobj
                        del(layout[obj])

        layout = hierarchy

        for windef in layout:
            if layout[windef]['type'] != 'Window':
                err('invalid layout format. %s' % layout)
                raise(ValueError)
            dbg('Creating a window')
            window, terminal = self.new_window()
            if layout[windef].has_key('position'):
                parts = layout[windef]['position'].split(':')
                if len(parts) == 2:
                    window.move(int(parts[0]), int(parts[1]))
            if layout[windef].has_key('size'):
                parts = layout[windef]['size']
                winx = int(parts[0])
                winy = int(parts[1])
                if winx > 1 and winy > 1:
                    window.resize(winx, winy)
            if layout[windef].has_key('title'):
                window.title.force_title(layout[windef]['title'])
            if layout[windef].has_key('maximised'):
                if layout[windef]['maximised'] == 'True':
                    window.ismaximised = True
                else:
                    window.ismaximised = False
                window.set_maximised(window.ismaximised)
            if layout[windef].has_key('fullscreen'):
                if layout[windef]['fullscreen'] == 'True':
                    window.isfullscreen = True
                else:
                    window.isfullscreen = False
                window.set_fullscreen(window.isfullscreen)
            window.create_layout(layout[windef])

        self.layoutname = layoutname

    def layout_done(self):
        """Layout operations have finished, record that fact"""
        self.doing_layout = False
        maker = Factory()

        window_last_active_term_mapping = {}
        for window in self.windows:
            if window.is_child_notebook():
                source = window.get_toplevel().get_children()[0]
            else:
                source = window
            window_last_active_term_mapping[window] = copy.copy(source.last_active_term)

        for terminal in self.terminals:
            if not terminal.pid:
                terminal.spawn_child()

        for window in self.windows:
            if window.is_child_notebook():
                # For windows with a notebook
                notebook = window.get_toplevel().get_children()[0]
                # Cycle through pages by number
                for page in xrange(0, notebook.get_n_pages()):
                    # Try and get the entry in the previously saved mapping
                    mapping = window_last_active_term_mapping[window]
                    page_last_active_term = mapping.get(notebook.get_nth_page(page),  None)
                    if page_last_active_term is None:
                        # Couldn't find entry, so we find the first child of type Terminal
                        children = notebook.get_nth_page(page).get_children()
                        for page_last_active_term in children:
                            if maker.isinstance(page_last_active_term, 'Terminal'):
                                page_last_active_term = page_last_active_term.uuid
                                break
                        else:
                            err('Should never reach here!')
                            page_last_active_term = None
                    if page_last_active_term is None:
                        # Bail on this tab as we're having no luck here, continue with the next
                        continue
                    # Set the notebook entry, then ensure Terminal is visible and focussed
                    urn = page_last_active_term.urn
                    notebook.last_active_term[notebook.get_nth_page(page)] = page_last_active_term
                    if urn:
                        term = self.find_terminal_by_uuid(urn)
                        if term:
                            term.ensure_visible_and_focussed()
            else:
                # For windows without a notebook ensure Terminal is visible and focussed
                if window_last_active_term_mapping[window]:
                    term = self.find_terminal_by_uuid(window_last_active_term_mapping[window].urn)
                    term.ensure_visible_and_focussed()

        for window in self.windows:
            if window.uuid == self.last_active_window:
                window.show()

    def reconfigure(self):
        """Update configuration for the whole application"""

        if self.style_provider is not None:
            Gtk.StyleContext.remove_provider_for_screen(
                Gdk.Screen.get_default(),
                self.style_provider)
            self.style_provider = None
        if self.config['handle_size'] in xrange(0, 6):
            css = """
                GtkPaned {
                    -GtkPaned-handle-size: %s
                }
                """ % self.config['handle_size']
            self.style_provider = Gtk.CssProvider()
            self.style_provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), 
                self.style_provider,     
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Cause all the terminals to reconfigure
        for terminal in self.terminals:
            terminal.reconfigure()

        # Reparse our keybindings
        self.keybindings.configure(self.config['keybindings'])

        # Update tab position if appropriate
        maker = Factory()
        for window in self.windows:
            child = window.get_child()
            if maker.isinstance(child, 'Notebook'):
                child.configure()

    def create_group(self, name):
        """Create a new group"""
        if name not in self.groups:
            dbg('Terminator::create_group: registering group %s' % name)
            self.groups.append(name)

    def closegroupedterms(self, group):
        """Close all terminals in a group"""
        for terminal in self.terminals[:]:
            if terminal.group == group:
                terminal.close()

    def group_hoover(self):
        """Clean out unused groups"""

        if self.config['autoclean_groups']:
            inuse = []
            todestroy = []

            for terminal in self.terminals:
                if terminal.group:
                    if not terminal.group in inuse:
                        inuse.append(terminal.group)

            for group in self.groups:
                if not group in inuse:
                    todestroy.append(group)

            dbg('Terminator::group_hoover: %d groups, hoovering %d' %
                    (len(self.groups), len(todestroy)))
            for group in todestroy:
                self.groups.remove(group)

    def group_emit(self, terminal, group, type, event):
        """Emit to each terminal in a group"""
        dbg('Terminator::group_emit: emitting a keystroke for group %s' %
                group)
        for term in self.terminals:
            if term != terminal and term.group == group:
                term.vte.emit(type, eventkey2gdkevent(event))

    def all_emit(self, terminal, type, event):
        """Emit to all terminals"""
        for term in self.terminals:
            if term != terminal:
                term.vte.emit(type, eventkey2gdkevent(event))

    def do_enumerate(self, widget, pad):
        """Insert the number of each terminal in a group, into that terminal"""
        if pad:
            numstr = '%0'+str(len(str(len(self.terminals))))+'d'
        else:
            numstr = '%d'

        terminals = []
        for window in self.windows:
            containers, win_terminals = enumerate_descendants(window)
            terminals.extend(win_terminals)

        for term in self.get_target_terms(widget):
            idx = terminals.index(term)
            term.feed(numstr % (idx + 1))

    def get_sibling_terms(self, widget):
        termset = []
        for term in self.terminals:
            if term.group == widget.group:
                termset.append(term)
        return(termset)

    def get_target_terms(self, widget):
        """Get the terminals we should currently be broadcasting to"""
        if self.groupsend == self.groupsend_type['all']:
            return(self.terminals)
        elif self.groupsend == self.groupsend_type['group']:
            if widget.group != None:
                return(self.get_sibling_terms(widget))
        return([widget])

    def get_focussed_terminal(self):
        """iterate over all the terminals to find which, if any, has focus"""
        for terminal in self.terminals:
            if terminal.has_focus():
                return(terminal)
        return(None)

    def focus_changed(self, widget):
        """We just moved focus to a new terminal"""
        for terminal in self.terminals:
            terminal.titlebar.update(widget)
        return

    def focus_left(self, widget):
        self.last_focused_term=widget

    def describe_layout(self):
        """Describe our current layout"""
        layout = {}
        count = 0
        for window in self.windows:
            parent = ''
            count = window.describe_layout(count, parent, layout, 0)

        return(layout)
# vim: set expandtab ts=4 sw=4:
