#!/usr/bin/env python3
#
# Simple LightDM greeter, based on GTK 3.
#
# The code is based on the example greeter written and explained by
# Matt Fischer:
# http://www.mattfischer.com/blog/archives/5

import configparser
import datetime
import gi
import os
import socket
import sys
from pathlib import Path

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("LightDM", "1")

from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import LightDM

DEFAULT_SESSION = "sway"
UI_FILE_LOCATION = "/usr/local/share/elephant-greeter/elephant-greeter.ui"
WAYLAND_ICON_LOCATION = "/usr/local/share/elephant-greeter/img/wayland.png"
X_ICON_LOCATION = "/usr/local/share/elephant-greeter/img/X.png"
CSS_FILE_LOCATION = "/usr/share/elephant-greeter/elephant-greeter.css"
BACKGROUND_LOCATION = ""

WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
            "sexta-feira", "sábado", "domingo"]
MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
          "agosto", "setembro", "outubro", "novembro", "dezembro"]

# read the cache
cache_dir = (Path.home() / ".cache" / "elephant-greeter")
cache_dir.mkdir(parents=True, exist_ok=True)
state_file = (cache_dir / "state")
state_file.touch()
cache = configparser.ConfigParser()
cache.read(str(state_file))
if not cache.has_section("greeter"):
    cache.add_section("greeter")

greeter = None
password_entry = None
message_label = None
login_clicked = False


def set_password_visibility(visible):
    """Show or hide the password entry field."""
    password_entry.set_sensitive(visible)
    password_label.set_sensitive(visible)
    if visible:
        password_entry.show()
        password_label.show()
    else:
        password_entry.hide()
        password_label.hide()


def read_config(gtk_settings, config_file="/etc/lightdm/elephant-greeter.conf"):
    """Read the configuration from the file."""
    if not os.path.isfile(config_file):
        return

    config = configparser.ConfigParser()
    config.read(config_file)
    if "GTK" in config:
        # every setting in the GTK section starting with 'gtk-' is applied directly
        for key in config["GTK"]:
            if key.startswith("gtk-"):
                value = config["GTK"][key]
                gtk_settings.set_property(key, value)

    if "Greeter" in config:
        global DEFAULT_SESSION, UI_FILE_LOCATION, X_ICON_LOCATION, WAYLAND_ICON_LOCATION
        global CSS_FILE_LOCATION, BACKGROUND_LOCATION
        DEFAULT_SESSION = config["Greeter"].get("default-session", DEFAULT_SESSION)
        UI_FILE_LOCATION = config["Greeter"].get("ui-file-location", UI_FILE_LOCATION)
        X_ICON_LOCATION = config["Greeter"].get("x-icon-location", X_ICON_LOCATION)
        WAYLAND_ICON_LOCATION = config["Greeter"].get("wayland-icon-location", WAYLAND_ICON_LOCATION)
        CSS_FILE_LOCATION = config["Greeter"].get("css-file-location", CSS_FILE_LOCATION)
        BACKGROUND_LOCATION = config["Greeter"].get("background", BACKGROUND_LOCATION)


def load_css():
    """Load the theme CSS and the background image (if configured)."""
    screen = Gdk.Screen.get_default()
    priority = Gtk.STYLE_PROVIDER_PRIORITY_USER

    if CSS_FILE_LOCATION and os.path.isfile(CSS_FILE_LOCATION):
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(CSS_FILE_LOCATION)
            Gtk.StyleContext.add_provider_for_screen(screen, provider, priority)
        except GLib.Error as err:
            print(f"failed to load css: {err}", file=sys.stderr)

    if BACKGROUND_LOCATION and os.path.isfile(BACKGROUND_LOCATION):
        uri = GLib.filename_to_uri(BACKGROUND_LOCATION, None)
        provider = Gtk.CssProvider()
        css = f'#login_window {{ background-image: url("{uri}"); }}'
        try:
            provider.load_from_data(css.encode())
            Gtk.StyleContext.add_provider_for_screen(screen, provider, priority + 1)
        except GLib.Error as err:
            print(f"failed to load background: {err}", file=sys.stderr)


def update_clock():
    """Refresh the clock and date labels (pt_BR, independent of locale)."""
    now = datetime.datetime.now()
    if clock_label is not None:
        clock_label.set_text(now.strftime("%H:%M"))
    if date_label is not None:
        date_label.set_text(f"{WEEKDAYS[now.weekday()]}, {now.day} de {MONTHS[now.month - 1]}")
    return True


def set_message(text, error=False):
    """Show a message in the card; error=True paints it red via CSS."""
    message_label.set_text(text)
    ctx = message_label.get_style_context()
    if error:
        ctx.add_class("error")
    else:
        ctx.remove_class("error")


def update_avatar(username):
    """Show the first letter of the user's display name in the avatar."""
    if avatar_label is None or not username:
        return
    display = username
    for u in LightDM.UserList().get_users():
        if u.get_name() == username:
            display = u.get_display_name() or username
            break
    avatar_label.set_text(display[:1].upper())


def password_icon_press(entry, icon_pos, event):
    """Toggle the password visibility with the eye icon."""
    visible = not entry.get_visibility()
    entry.set_visibility(visible)
    entry.set_icon_from_icon_name(
        Gtk.EntryIconPosition.SECONDARY,
        "view-conceal-symbolic" if visible else "view-reveal-symbolic")
    entry.set_icon_tooltip_text(
        Gtk.EntryIconPosition.SECONDARY,
        "Ocultar senha" if visible else "Mostrar senha")


def update_caps_lock(keymap=None):
    """Show a warning while Caps Lock is on."""
    if caps_label is None:
        return
    keymap = keymap or Gdk.Keymap.get_for_display(Gdk.Display.get_default())
    caps_label.set_visible(keymap.get_caps_lock_state())


def write_cache():
    """Write the current cache to file."""
    with open(str(state_file), "w") as file_:
        cache.write(file_)


def auto_select_user_session(username):
    """Automatically select the user's preferred session."""
    users = LightDM.UserList().get_users()
    users = [u for u in users if u.get_name() == username] + [None]
    user = users[0]

    if user is not None:
        session_index = 0
        if user.get_session() is not None:
            # find the index of the user's session in the combobox
            session_index = [row[0] for row in sessions_box.get_model()].index(user.get_session())

        sessions_box.set_active(session_index)


def start_session():
    session = sessions_box.get_active_text() or DEFAULT_SESSION
    write_cache()
    if not greeter.start_session_sync(session):
        print("failed to start session", file=sys.stderr)
        set_message("Falha ao iniciar a sessão", error=True)


def dm_show_prompt_cb(greeter, text, prompt_type=None, **kwargs):
    """Respond to the password request sent by LightDM."""
    # this event is sent by LightDM after user authentication
    # started, if a password is required
    if login_clicked:
        greeter.respond(password_entry.get_text())
        password_entry.set_text("")

    if "password" not in text.lower():
        print(f"LightDM requested prompt: {text}", file=sys.stderr)


def dm_show_message_cb(greeter, text, message_type=None, **kwargs):
    """Show the message from LightDM to the user."""
    print(f"message from LightDM: {text}", file=sys.stderr)
    set_message(text, error=(message_type == LightDM.MessageType.ERROR))


def dm_authentication_complete_cb(greeter):
    """Handle the notification that the authentication is completed."""
    if not login_clicked:
        # if this callback is executed before we clicked the login button,
        # this means that this user doesn't require a password
        # - in this case, we hide the password entry
        set_password_visibility(False)

    else:
        if greeter.get_is_authenticated():
            # the user authenticated successfully:
            # try to start the session
            start_session()
        else:
            # autentication complete, but unsucessful:
            # likely, the password was wrong
            set_message("Senha incorreta. Tente novamente.", error=True)
            password_entry.grab_focus()
            print("login failed", file=sys.stderr)


def user_change_handler(widget, data=None):
    """Event handler for selecting a different username in the ComboBox."""
    global login_clicked
    login_clicked = False

    if greeter.get_in_authentication():
        greeter.cancel_authentication()

    username = usernames_box.get_active_text()
    greeter.authenticate(username)
    auto_select_user_session(username)

    set_password_visibility(True)
    password_entry.set_text("")
    update_avatar(username)
    set_message("Bem-vindo de volta!")
    cache.set("greeter", "last-user", username)


def login_click_handler(widget, data=None):
    """Event handler for clicking the Login button."""
    global login_clicked
    login_clicked = True

    if greeter.get_is_authenticated():
        # the user is already authenticated:
        # this is likely the case when the user doesn't require a password
        start_session()

    if greeter.get_in_authentication():
        # if we're in the middle of an authentication, let's cancel it
        greeter.cancel_authentication()

    # (re-)start the authentication for the selected user
    # this should trigger LightDM to send a 'show-prompt' signal
    # (note that this time, login_clicked is True, however)
    username = usernames_box.get_active_text()
    greeter.authenticate(username)


def poweroff_click_handler(widget, data=None):
    """Event handler for clicking the Power-Off button."""
    if LightDM.get_can_shutdown():
        LightDM.shutdown()


def reboot_click_handler(widget, data=None):
    """Event handler for clicking the Reboot button."""
    if LightDM.get_can_restart():
        LightDM.restart()


if __name__ == "__main__":
    builder = Gtk.Builder()
    greeter = LightDM.Greeter()
    settings = Gtk.Settings.get_default()
    read_config(settings)
    load_css()
    cursor = Gdk.Cursor(Gdk.CursorType.LEFT_PTR)
    greeter_session_type = os.environ.get("XDG_SESSION_TYPE", None)

    # connect signal handlers to LightDM
    # signals: http://people.ubuntu.com/~robert-ancell/lightdm/reference/LightDMGreeter.html#LightDMGreeter-authentication-complete
    greeter.connect("authentication-complete", dm_authentication_complete_cb)
    greeter.connect("show-message", dm_show_message_cb)
    greeter.connect("show-prompt", dm_show_prompt_cb)

    # connect builder and widgets
    ui_file_path = UI_FILE_LOCATION
    builder.add_from_file(ui_file_path)
    login_window = builder.get_object("login_window")
    password_entry = builder.get_object("password_entry")
    password_label = builder.get_object("password_label")
    message_label = builder.get_object("message_label")
    usernames_box = builder.get_object("usernames_cb")
    sessions_box = builder.get_object("sessions_cb")
    login_button = builder.get_object("login_button")
    poweroff_button = builder.get_object("poweroff_button")
    icon = builder.get_object("icon")
    # optional widgets (an older .ui without them still works)
    reboot_button = builder.get_object("reboot_button")
    hostname_label = builder.get_object("hostname_label")
    clock_label = builder.get_object("clock_label")
    date_label = builder.get_object("date_label")
    avatar_label = builder.get_object("avatar_label")
    caps_label = builder.get_object("caps_label")

    # connect to greeter
    greeter.connect_to_daemon_sync()

    # set up the GUI
    login_window.get_root_window().set_cursor(cursor)
    password_entry.set_text("")
    password_entry.set_sensitive(True)
    password_entry.set_visibility(False)
    if greeter_session_type is not None:
        print(f"greeter session type: {greeter_session_type}", file=sys.stderr)
        if greeter_session_type.lower() == "wayland":
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(WAYLAND_ICON_LOCATION, 20, 20, True)
            icon.set_from_pixbuf(pixbuf)
        elif greeter_session_type.lower() == "x11":
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(X_ICON_LOCATION, 20, 20, True)
            icon.set_from_pixbuf(pixbuf)
    set_message("Bem-vindo de volta!")

    if hostname_label is not None:
        hostname_label.set_text(socket.gethostname().upper())
    update_clock()
    GLib.timeout_add_seconds(1, update_clock)

    # register handlers for our UI elements
    poweroff_button.connect("clicked", poweroff_click_handler)
    if reboot_button is not None:
        reboot_button.connect("clicked", reboot_click_handler)
    password_entry.connect("icon-press", password_icon_press)
    keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
    keymap.connect("state-changed", update_caps_lock)
    update_caps_lock(keymap)
    usernames_box.connect("changed", user_change_handler)
    password_entry.connect("activate", login_click_handler)
    login_button.connect("clicked", login_click_handler)
    login_window.set_default(login_button)

    # make the greeter "fullscreen"
    screen = login_window.get_screen()
    login_window.resize(screen.get_width(), screen.get_height())

    # populate the combo boxes
    user_idx = 0
    last_user = cache.get("greeter", "last-user", fallback=None)
    for idx, user in enumerate(LightDM.UserList().get_users()):
        usernames_box.append_text(user.get_name())
        if last_user == user.get_name():
            user_idx = idx

    for session in LightDM.get_sessions():
        sessions_box.append_text(session.get_key())

    sessions_box.set_active(0)
    usernames_box.set_active(user_idx)

    # if the selected user requires a password, (i.e the password entry
    # is visible), focus the password entry -- otherwise, focus the
    # user selection box
    if password_entry.get_sensitive():
        password_entry.grab_focus()
    else:
        usernames_box.grab_focus()

    login_window.show()
    login_window.fullscreen()
    GLib.MainLoop().run()
