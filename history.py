import sys
import os
import glob
import platform
import time
from datetime import datetime as dt
import difflib
import filecmp
import shutil
from threading import Thread
import subprocess
import sublime
import sublime_plugin

#==============#
#   Settings   #
#==============#
FILE_SIZE_LIMIT = 262144
FILE_HISTORY_RETENTION = 30
HISTORY_ON_CLOSE = False

def load_settings():
    settings = sublime.load_settings("LocalHistory.sublime-settings")
    global FILE_SIZE_LIMIT
    global FILE_HISTORY_RETENTION
    global HISTORY_ON_CLOSE

    FILE_SIZE_LIMIT = settings.get("file_size_limit")
    FILE_HISTORY_RETENTION = settings.get("file_history_retention")
    if FILE_HISTORY_RETENTION: FILE_HISTORY_RETENTION *= 86400  # Convert to seconds
    HISTORY_ON_CLOSE = settings.get("history_on_close")

PY2 = sys.version_info < (3, 0)
if PY2: load_settings()
HISTORY_ROOT = os.path.join(os.path.abspath(os.path.expanduser("~")), ".sublime", "history")

#==============#
#   Messages   #
#==============#
NO_HISTORY_MSG = "No local history found"
NO_INCREMENTAL_DIFF = "No incremental diff found"
HISTORY_DELETED_MSG = "All local history deleted"

# For ST3
def plugin_loaded():
    load_settings()

def get_file_dir(file_path):
    file_dir = os.path.dirname(file_path)
    if platform.system() == "Windows":
        if file_dir.find(os.sep) == 0:
            file_dir = file_dir[2:]  # Strip the network \\ starting path
        if file_dir.find(":") == 1:
            file_dir = file_dir.replace(":", "", 1)
    else:
        file_dir = file_dir[1:]  # Trim the root
    return os.path.join(HISTORY_ROOT, file_dir)


class HistorySave(sublime_plugin.EventListener):

    def on_close(self, view):
        if HISTORY_ON_CLOSE:
            t = Thread(target=self.process_history, args=(view.file_name(),))
            t.start()

    def on_post_save(self, view):
        if not HISTORY_ON_CLOSE:
            t = Thread(target=self.process_history, args=(view.file_name(),))
            t.start()

    def process_history(self, file_path):
        if PY2:
            file_path = file_path.encode("utf-8")
        # Return if file exceeds the size limit
        if os.path.getsize(file_path) > FILE_SIZE_LIMIT:
            print ("WARNING: Local History did not save a copy of this file \
                because it has exceeded {0}KB limit.".format(FILE_SIZE_LIMIT / 1024))
            return

        # Get history directory
        file_name = os.path.basename(file_path)
        history_dir = get_file_dir(file_path)
        if not os.path.exists(history_dir):
            # Create directory structure
            os.makedirs(history_dir)

        # Get history files
        history_files = glob.glob("*" + file_name)
        history_files.sort(key=lambda f: os.path.getmtime(os.path.join(history_dir, f)), reverse=True)

        # Skip if no changes
        if history_files:
            if filecmp.cmp(file_path, os.path.join(history_dir, history_files[0])):
                return

        # Store history
        shutil.copyfile(file_path, os.path.join(history_dir,
            "{0}.{1}".format(dt.now().strftime("%Y-%m-%d_%H.%M.%S"),
                file_name)))

        # Remove old files
        now = time.time()
        for file in history_files:
            file = os.path.join(history_dir, file)
            if os.path.getmtime(file) < now - FILE_HISTORY_RETENTION:
                os.remove(file)


class HistoryBrowse(sublime_plugin.TextCommand):

    def run(self, edit):
        system = platform.system()
        if system == "Darwin":
            subprocess.call(["open", get_file_dir(self.view.file_name())])
        elif system == "Linux":
            subprocess.call(["xdg-open", get_file_dir(self.view.file_name())])
        elif system == "Windows":
            subprocess.call(["explorer", get_file_dir(self.view.file_name())])


class HistoryOpen(sublime_plugin.TextCommand):

    def run(self, edit):
        # Get history directory
        file_name = os.path.basename(self.view.file_name())
        history_dir = get_file_dir(self.view.file_name())

        # Get history files
        history_files = glob.glob("*" + file_name)
        history_files.sort(key=lambda f: os.path.getmtime(os.path.join(history_dir, f)), reverse=True)
        if not history_files:
            sublime.status_message(NO_HISTORY_MSG)
            return

        def on_done(index):
            # Escape
            if index == -1:
                return

            # Open
            self.view.window().open_file(os.path.join(history_dir, history_files[index]))

        self.view.window().show_quick_panel(history_files, on_done)


class HistoryCompare(sublime_plugin.TextCommand):

    def run(self, edit):
        # Get history directory
        file_name = os.path.basename(self.view.file_name())
        history_dir = get_file_dir(self.view.file_name())

        # Get history files
        history_files = glob.glob("*" + file_name)
        history_files.sort(key=lambda f: os.path.getmtime(os.path.join(history_dir, f)), reverse=True)
        # Skip the first one as its always identical
        history_files = history_files[1:]

        if not history_files:
            sublime.status_message(NO_HISTORY_MSG)
            return

        def on_done(index):
            # Escape
            if index == -1:
                return

            # Trigger save before comparing, if required!
            if self.view.is_dirty():
                self.view.run_command("save")

            # Show diff
            from_file = os.path.join(history_dir, history_files[index])
            to_file = self.view.file_name()
            self.view.run_command("show_diff", {"from_file": from_file, "to_file": to_file})

        self.view.window().show_quick_panel(history_files, on_done)


class HistoryReplace(sublime_plugin.TextCommand):

    def run(self, edit):
        # Get history directory
        file_name = os.path.basename(self.view.file_name())
        history_dir = get_file_dir(self.view.file_name())

        # Get history files
        history_files = glob.glob("*" + file_name)
        history_files.sort(key=lambda f: os.path.getmtime(os.path.join(history_dir, f)), reverse=True)
        # Skip the first one as its always identical
        history_files = history_files[1:]

        if not history_files:
            sublime.status_message(NO_HISTORY_MSG)
            return

        def on_done(index):
            # Escape
            if index == -1:
                return

            # Replace
            file = os.path.join(history_dir, history_files[index])
            with open(file) as f:
                data = f.read()
                if PY2:
                    data.decode("utf-8")
                self.view.replace(edit, sublime.Region(0, self.view.size()), data)
            self.view.run_command("save")

        self.view.window().show_quick_panel(history_files, on_done)


class HistoryIncrementalDiff(sublime_plugin.TextCommand):

    def run(self, edit):
        # Get history directory
        file_name = os.path.basename(self.view.file_name())
        history_dir = get_file_dir(self.view.file_name())

        # Get history files
        history_files = glob.glob("*" + file_name)
        history_files.sort(key=lambda f: os.path.getmtime(os.path.join(history_dir, f)), reverse=True)
        if len(history_files) < 2:
            sublime.status_message(NO_INCREMENTAL_DIFF)
            return

        def on_done(index):
            # Escape
            if index == -1:
                return

            # Selected the last file
            if index == len(history_files) - 1:
                sublime.status_message(NO_INCREMENTAL_DIFF)
                return

            # Show diff
            from_file = os.path.join(history_dir, history_files[index + 1])
            to_file = os.path.join(history_dir, history_files[index])
            self.view.run_command("show_diff", {"from_file": from_file, "to_file": to_file})

        self.view.window().show_quick_panel(history_files, on_done)


class ShowDiff(sublime_plugin.TextCommand):

    def run(self, edit, **kwargs):
        from_file = kwargs["from_file"]
        to_file = kwargs["to_file"]
        # From
        if PY2:
            from_file = from_file.encode("utf-8")
            with open(from_file, "r") as f:
                from_content = f.readlines()
        else:
            with open(from_file, "r", encoding="utf-8") as f:
                from_content = f.readlines()

        # To
        if PY2:
            to_file = to_file.encode("utf-8")
            with open(to_file, "r") as f:
                to_content = f.readlines()
        else:
            with open(to_file, "r", encoding="utf-8") as f:
                to_content = f.readlines()

        # Compare and show diff
        diff = difflib.unified_diff(from_content, to_content, from_file, to_file)
        diff = "".join(diff)
        if PY2:
            diff = diff.decode("utf-8")
        panel = sublime.active_window().new_file()
        panel.set_scratch(True)
        panel.set_syntax_file("Packages/Diff/Diff.tmLanguage")
        panel.insert(edit, 0, diff)


class HistoryDeleteAll(sublime_plugin.TextCommand):

    def run(self, edit):
        shutil.rmtree(HISTORY_ROOT)
        sublime.status_message(HISTORY_DELETED_MSG)
