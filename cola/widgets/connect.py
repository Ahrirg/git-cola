# Portions Copyright (C) 2023 Quard <2014500726@smail.xtu.edu.cn>
import os
import shlex
import sys

import requests
from paramiko import AutoAddPolicy
from paramiko import SSHClient

from qtpy import QtWidgets
from qtpy.QtCore import QAbstractItemModel
from qtpy.QtCore import QModelIndex
from qtpy.QtCore import Qt
from qtpy.QtGui import QIcon

from .. import core
from .. import icons
from .. import operations
from .. import qtutils
from .. import server
from ..app import ApplicationContext
from ..i18n import N_
from ..qtutils import get
from . import defs
from . import text


def connect_server(context: ApplicationContext):
    """Launch a ConnectServerDialog instance"""
    view = ConnectServerDialog(context, parent=qtutils.active_window())
    view.show()
    view.exec_()
    return view


def ssh_server(context: ApplicationContext, ip: str):
    """Launch a ConnectServerDialog instance"""
    view = SshServerDialog(context, ip, parent=qtutils.active_window())
    view.show()
    view.exec_()
    return view


def select_path(context: ApplicationContext, ops: operations.RemoteOperations, ip: str):
    """Launch a SelectPathDialog instance"""
    view = SelectPathDialog(context, ops, ip, parent=qtutils.active_window())
    view.show()
    view.exec_()
    return view


class ConnectServerDialog(QtWidgets.QDialog):
    def __init__(self, context: ApplicationContext, parent=None):
        super().__init__(parent)
        self.context = context
        self.setWindowTitle(N_('Connect to Server Repository'))
        if parent is not None:
            self.setWindowModality(Qt.WindowModal)

        self.server_ip_input = self._create_lineedit(context, N_('e.g. 192.168.1.1'))

        self.server_port = self._create_lineedit(context, N_('49178'))

        self.connect_button = qtutils.create_button(
            text=N_('Connect'), icon=icons.ok(), default=True
        )
        self.exit_button = qtutils.create_button(text=N_('Exit'), icon=icons.close())

        self._form = qtutils.form(
            defs.margin,
            defs.spacing,
            (N_('Server IP'), self.server_ip_input),
            (N_('Server Port'), self.server_port),
        )

        self._button_layout = qtutils.hbox(
            defs.no_margin,
            defs.button_spacing,
            qtutils.STRETCH,
            self.exit_button,
            self.connect_button,
        )

        self._layout = qtutils.vbox(
            defs.margin, defs.spacing, self._form, self._button_layout
        )
        self.setLayout(self._layout)

        qtutils.connect_button(self.connect_button, self.on_connect)
        qtutils.connect_button(self.exit_button, self.reject)
        qtutils.add_close_action(self)

        self.resize(400, 150)

    def _create_lineedit(self, context: ApplicationContext, hint: str):
        widget = text.HintedLineEdit(context, hint)
        width = qtutils.text_width(widget.font(), 'M')
        widget.setMinimumWidth(width * 32)
        return widget

    def connect_to_server(self):
        server_ip = get(self.server_ip_input)
        server_port = get(self.server_port)
        if server_port == '':
            server_port = 49178

        socket = server.SocketClient(server_ip, port=server_port)
        ops = operations.RemoteOperations(socket)
        select_path(self.context, ops, f'{server_ip}:{server_port}')

    def on_connect(self):
        server_ip = get(self.server_ip_input)

        if server.server_is_up(server_ip):
            self.connect_to_server()
        else:
            ssh_server(self.context, server_ip)
            if server.server_is_up(server_ip, tries=10):
                self.connect_to_server()
            else:
                print('server coud not be reached')

        self.accept()


class SshServerDialog(QtWidgets.QDialog):
    def __init__(self, context: ApplicationContext, ip: str, parent=None):
        super().__init__(parent)
        self.context = context
        self.ip = ip
        self.setWindowTitle(N_('pipe git-cola to server'))
        if parent is not None:
            self.setWindowModality(Qt.WindowModal)

        self.username_input = self._create_lineedit(context, N_(''))

        self.password_input = self._create_lineedit(context, N_(''))

        self.connect_button = qtutils.create_button(
            text=N_('Connect'), icon=icons.ok(), default=True
        )
        self.exit_button = qtutils.create_button(text=N_('Exit'), icon=icons.close())

        self._form = qtutils.form(
            defs.margin,
            defs.spacing,
            (N_('Username'), self.username_input),
            (N_('Password'), self.password_input),
        )

        self._button_layout = qtutils.hbox(
            defs.no_margin,
            defs.button_spacing,
            qtutils.STRETCH,
            self.exit_button,
            self.connect_button,
        )

        self._layout = qtutils.vbox(
            defs.margin, defs.spacing, self._form, self._button_layout
        )
        self.setLayout(self._layout)

        qtutils.connect_button(self.connect_button, self.on_connect)
        qtutils.connect_button(self.exit_button, self.reject)
        qtutils.add_close_action(self)

        self.resize(400, 150)

    def _create_lineedit(
        self, context: ApplicationContext, hint: str, hidden: bool = False
    ):
        widget = text.HintedLineEdit(context, hint)
        width = qtutils.text_width(widget.font(), 'M')
        widget.setMinimumWidth(width * 32)
        if hidden:
            widget.setEchoMode(QtWidgets.QLineEdit.Password)
        return widget

    def get_platform(self, ssh: SSHClient) -> None:
        stdin, stdout, stderr = ssh.exec_command('uname -s && uname -m')
        stdout.channel.recv_exit_status()

        lines = stdout.read().decode().strip().splitlines()

        if len(lines) != 2:
            stdin, stdout, stderr = ssh.exec_command(
                'echo Windows^|%PROCESSOR_ARCHITECTURE%'
            )
            stdout.channel.recv_exit_status()
            t = stdout.read().decode(errors='replace')
            lines = t.strip().replace('Windows_NT', 'Windows').split('|')

        if len(lines) != 2:
            raise Exception('Unsupported system')

        system, machine = lines

        if machine in ('aarch64', 'arm64', 'ARM64'):
            self.machine = 'ARM64'
        if machine in ('AMD64', 'x86_64'):
            self.machine = 'x86_64'

        if system in ('Linux', 'Darwin', 'Windows'):
            self.system = system
            return

        raise Exception(f'Unsupported system: {system} {machine}')

    def get_url(self):
        url = ''
        if self.system == 'Linux':
            url = f'https://github.com/Ahrirg/git-cola/releases/download/latest/git-cola_linux-{self.machine}-server'
        if self.system == 'Windows':
            url = f'https://github.com/Ahrirg/git-cola/releases/download/latest/git-cola_windows-{self.machine}-server.exe'
        if self.system == 'Darwin':
            url = 'https://github.com/Ahrirg/git-cola/releases/download/latest/git-cola.app.zip'

        try:
            response = requests.head(url, allow_redirects=True, timeout=10)

            if response.status_code == 200:
                return url
        except requests.RequestException as e:
            raise Exception(f'Unsupported system: {e}')

    def get_command(self) -> str:
        remote_dir = '/tmp/git-cola'
        remote_executable = f'{remote_dir}/git-cola'

        url = self.get_url()

        if self.system == 'Linux':
            return (
                f'rm -rf {shlex.quote(remote_dir)} '
                f'&& mkdir -p {shlex.quote(remote_dir)} '
                f'&& curl -fL '
                f'-o {shlex.quote(remote_executable)} '
                f'{shlex.quote(url)} '
                f'&& chmod 700 {shlex.quote(remote_executable)} '
                f'&& nohup {shlex.quote(remote_executable)} server '
                f'>{shlex.quote(remote_dir)}/server.log 2>&1 </dev/null &'
            )
        elif self.system == 'Darwin':
            return (
                f'rm -rf {shlex.quote(remote_dir)} '
                f'&& mkdir -p {shlex.quote(remote_dir)} '
                f'&& curl -fL '
                f'-o {shlex.quote(remote_executable)} '
                f'{shlex.quote(url)} '
                f'&& unzip -q {shlex.quote(remote_executable)} -d {shlex.quote(remote_dir)} '
                f'&& chmod 700 {shlex.quote(remote_dir)}/git-cola.app/Contents/MacOS/git-cola '
                f'&& nohup {shlex.quote(remote_dir)}/git-cola.app/Contents/MacOS/git-cola server '
                f'>{shlex.quote(remote_dir)}/server.log 2>&1 </dev/null &'
            )
        elif self.system == 'Windows':
            remote_dir = r'%TEMP%\git-cola'
            remote_zip = rf'{remote_dir}\git-cola.zip'
            remote_executable = rf'{remote_dir}\git-cola.exe'

            return (
                f'rmdir /s /q "{remote_dir}" 2>nul & '
                f'mkdir "{remote_dir}" && '
                f'curl.exe -fL -o "{remote_executable}" "{url}" && '
                # f'powershell.exe -NoProfile -Command '
                # f"\"Expand-Archive -LiteralPath '{remote_zip}' "
                # f"-DestinationPath '{remote_dir}' -Force\" && "
                f'start "" /b cmd /c '
                f'""{remote_executable}" server > "{remote_dir}\\server.log" 2>&1"'
            )

        else:
            raise Exception(f'Unsupported system: {self.system}')

    def on_connect(self):
        username = get(self.username_input)
        password = get(self.password_input)

        if not username or not password:
            QtWidgets.QMessageBox.warning(
                self,
                N_('SSH'),
                N_('Username and password are required.'),
            )
            return

        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        try:
            ssh.connect(
                hostname=str(self.ip),
                port=22,
                username=username,
                password=password,
            )
            self.get_platform(ssh)
            stdin, stdout, stderr = ssh.exec_command(self.get_command())

            ssh.close()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                N_('SSH'),
                f'SSH error: {e}',
            )
        finally:
            self.accept()


class SelectPathDialog(QtWidgets.QDialog):
    def __init__(
        self,
        context: ApplicationContext,
        ops: operations.RemoteOperations,
        ip: str,
        parent=None,
    ):
        super().__init__(parent)
        self.context = context
        self.server_ip = ip
        self.ops = ops
        self.setWindowTitle(N_('Select Path To Repository'))
        if parent is not None:
            self.setWindowModality(Qt.WindowModal)

        self.repo_path_input = self._create_lineedit(context, N_('e.g. /path/to/repo'))

        self.browse_button = QtWidgets.QPushButton('...')
        self.browse_button.setMaximumWidth(30)
        self.browse_button.clicked.connect(self.on_browse)

        self.connect_button = qtutils.create_button(
            text=N_('Select'), icon=icons.ok(), default=True
        )
        self.exit_button = qtutils.create_button(text=N_('Exit'), icon=icons.close())

        input_layout = qtutils.hbox(
            defs.no_margin,
            defs.spacing,
            self.repo_path_input,
            self.browse_button,
        )

        self._form = qtutils.form(
            defs.margin,
            defs.spacing,
            (N_('Path to Repo'), input_layout),
        )

        self._button_layout = qtutils.hbox(
            defs.no_margin,
            defs.button_spacing,
            qtutils.STRETCH,
            self.exit_button,
            self.connect_button,
        )

        self._layout = qtutils.vbox(
            defs.margin, defs.spacing, self._form, self._button_layout
        )
        self.setLayout(self._layout)

        qtutils.connect_button(self.connect_button, self.on_connect)
        qtutils.connect_button(self.exit_button, self.reject)
        qtutils.add_close_action(self)

        self.resize(400, 150)

    def _create_lineedit(self, context: ApplicationContext, hint: str):
        widget = text.HintedLineEdit(context, hint)
        width = qtutils.text_width(widget.font(), 'M')
        widget.setMinimumWidth(width * 32)
        return widget

    def on_browse(self):
        dialog = RemoteFileBrowserDialog(self.context, self.ops, parent=self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            selected_path = dialog.selected_path()
            if selected_path:
                self.repo_path_input.setText(selected_path)

    def on_connect(self):
        repo_path = get(self.repo_path_input)
        print([sys.executable, '-m', 'cola', 'connect', self.server_ip, repo_path])
        cmd = [
            sys.executable,
            '-m',
            'cola',
            'connect',
            self.server_ip,
            repo_path,
        ]
        core.fork(cmd, cwd=os.getcwd())

        self.accept()
        QtWidgets.QApplication.quit()


class RemoteFileBrowserDialog(QtWidgets.QDialog):
    def __init__(
        self, context: ApplicationContext, ops: operations.RemoteOperations, parent=None
    ):
        super().__init__(parent)
        self.context = context
        self.ops = ops
        self.setWindowTitle(N_('Remote File Browser'))
        if parent is not None:
            self.setWindowModality(Qt.WindowModal)

        self.tree_view = QtWidgets.QTreeView()
        self.model = RemoteFileSystemModel(context, self.ops, self)

        self.model.setRootPath('/')
        self.tree_view.setModel(self.model)

        self.select_button = qtutils.create_button(
            text=N_('Select'), icon=icons.ok(), default=True
        )
        self.cancel_button = qtutils.create_button(
            text=N_('Cancel'), icon=icons.close()
        )

        self._button_layout = qtutils.hbox(
            defs.no_margin,
            defs.button_spacing,
            qtutils.STRETCH,
            self.cancel_button,
            self.select_button,
        )

        self._layout = qtutils.vbox(
            defs.margin, defs.spacing, self.tree_view, self._button_layout
        )
        self.setLayout(self._layout)

        qtutils.connect_button(self.select_button, self.accept)
        qtutils.connect_button(self.cancel_button, self.reject)

        self.resize(500, 400)

    def selected_path(self):
        index = self.tree_view.currentIndex()
        if index.isValid():
            return self.model.filePath(index)
        return ''


class QCustomFileSystemItem:
    def __init__(self, path, parent=None):
        super().__init__()
        self.path = path
        self.parentItem = parent
        self.childItems = []
        self._size = 0
        self._lastModified = None
        self._isDir = False

    def appendChild(self, child):
        self.childItems.append(child)

    def removeChild(self, row):
        self.childItems.pop(row)

    def removeChildren(self):
        self.childItems = []

    def child(self, row):
        return self.childItems[row]

    def childCount(self):
        return len(self.childItems)

    def columnCount(self):
        return 2

    def data(self):
        return self.path

    def row(self):
        if self.parentItem:
            return self.parentItem.childItems.index(self)
        return 0

    def setSize(self, size):
        self._size = size

    def size(self):
        return self._size

    def setLastModified(self, lastModified):
        self._lastModified = lastModified

    def lastModified(self):
        return self._lastModified

    def setIsDir(self, isDir):
        self._isDir = isDir

    def isDir(self):
        return self._isDir

    def parent(self):
        return self.parentItem


class QCustomFileSystemModel(QAbstractItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rootItem = None
        self.rootPath = ''

    def index(self, row, column, parent):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parentItem = None
        if not parent.isValid():
            parentItem = self.rootItem
        else:
            parentItem = parent.internalPointer()
        if parentItem is None:
            return QModelIndex()
        childItem = parentItem.child(row)
        if childItem:
            return self.createIndex(row, column, childItem)
        else:
            return QModelIndex()

    def parent(self, child):
        if not child.isValid():
            return QModelIndex()
        childItem = child.internalPointer()
        parentItem = childItem.parent()
        if parentItem is None:
            return QModelIndex()
        if parentItem == self.rootItem:
            return QModelIndex()
        return self.createIndex(parentItem.row(), 0, parentItem)

    def rowCount(self, parent):
        if parent.column() > 0:
            return 0
        if not parent.isValid():
            parentItem = self.rootItem
        else:
            parentItem = parent.internalPointer()
        if parentItem is None:
            return 0
        return parentItem.childCount()

    def columnCount(self, parent):
        if parent.isValid():
            return parent.internalPointer().columnCount()
        else:
            if self.rootItem is None:
                return 0
            return self.rootItem.columnCount()

    def data(self, index, role):
        if not index.isValid():
            return None

        item = index.internalPointer()

        if role == Qt.DecorationRole and index.column() == 0:
            if item.isDir():
                return QIcon.fromTheme('folder')
            return QIcon.fromTheme('text-x-generic')

        if role == Qt.DisplayRole:
            if index.column() == 0:
                return item.data().split(self.separator())[-1]

            elif index.column() == 1:
                return 'Directory' if item.isDir() else 'File'

        return None

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if section == 0:
                return 'Name'
            elif section == 1:
                return 'Type'
        return None

    def fetchMore(self, parent):
        if not parent.isValid():
            return
        parentItem = parent.internalPointer()
        if parentItem.childCount() != 1:
            return
        if parentItem.child(0).data() != '':
            return
        entries = self.pathEntryList(parentItem.data())
        if len(entries) == 0:
            return
        # remove dummy item
        parentItem.removeChild(0)
        dirItems = []
        fileItems = []
        for entry in entries:
            childPath = parentItem.data() + self.separator() + entry
            childItem = QCustomFileSystemItem(childPath, parentItem)
            isDir, size, lastModified = self.pathInfo(childPath)
            childItem.setIsDir(isDir)
            childItem.setLastModified(lastModified)
            if isDir:
                dirItems.append(childItem)
                # add dummy item
                dummyItem = QCustomFileSystemItem('', childItem)
                childItem.appendChild(dummyItem)
            else:
                childItem.setSize(size)
                fileItems.append(childItem)
        for item in dirItems:
            parentItem.appendChild(item)
        for item in fileItems:
            parentItem.appendChild(item)

    def canFetchMore(self, parent):
        if not parent.isValid():
            return False
        parentItem = parent.internalPointer()
        if parentItem.childCount() != 1:
            return False
        if parentItem.child(0).data() != '':
            return False
        return True

    def setRootPath(self, path):
        self.beginResetModel()
        self.rootItem = QCustomFileSystemItem(path)
        self.rootPath = path
        rootEntries = self.pathEntryList(self.rootPath)
        dirItems = []
        fileItems = []
        for entry in rootEntries:
            childPath = self.separator() + entry
            if path != self.separator():
                childPath = path + childPath
            childItem = QCustomFileSystemItem(childPath, self.rootItem)
            isDir, size, lastModified = self.pathInfo(childPath)
            childItem.setIsDir(isDir)
            childItem.setLastModified(lastModified)
            if isDir:
                dirItems.append(childItem)
                # add dummy item
                dummyItem = QCustomFileSystemItem('', childItem)
                childItem.appendChild(dummyItem)
            else:
                childItem.setSize(size)
                fileItems.append(childItem)
        for item in dirItems:
            self.rootItem.appendChild(item)
        for item in fileItems:
            self.rootItem.appendChild(item)
        self.endResetModel()
        return self.createIndex(0, 0, self.rootItem)

    def rootPath(self):
        return self.rootPath

    def filePath(self, index):
        if not index.isValid():
            return ''
        item = index.internalPointer()
        return item.data()

    def refresh(self, index):
        if not index.isValid():
            return
        item = index.internalPointer()
        if item.childCount() == 1 and item.child(0).data() == '':
            return
        self.beginResetModel()
        item.removeChildren()
        dummyItem = QCustomFileSystemItem('', item)
        item.appendChild(dummyItem)
        self.fetchMore(index)
        self.endResetModel()


class RemoteFileSystemModel(QCustomFileSystemModel):
    def __init__(
        self, context: ApplicationContext, ops: operations.RemoteOperations, parent=None
    ):
        super().__init__(parent)
        self.context = context
        self.ops = ops

    def separator(self) -> str:
        return '/'

    def pathEntryList(self, path: str) -> list:
        return self.ops.listdir(path)

    def pathInfo(self, path: str):
        is_dir = self.ops.isdir(path)
        size = 1  # TODO
        last_modified = None  # TODO
        return is_dir, size, last_modified
