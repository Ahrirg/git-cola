# Portions Copyright (C) 2023 Quard <2014500726@smail.xtu.edu.cn>
# Portions Copyright (C) 2024 Kelvin Wuite

import base64
import os
import platform
import select
import shlex
import socket
import sys
import tempfile
import threading
import time
from collections.abc import Callable

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
from .. import operations_remote
from .. import qtutils
from .. import server
from ..app import ApplicationContext
from ..i18n import N_
from ..qtutils import get
from . import defs
from . import text

SERVER_EXECUTABLE_URL = 'https://api.github.com/repos/Ahrirg/git-cola/releases'


class SSHTunnel:
    def __init__(
        self,
        ssh_host,
        ssh_user,
        ssh_password,
        local_port,
        remote_host,
        remote_port,
        ssh_port=22,
    ):
        self.ssh = SSHClient()
        self.ssh.load_system_host_keys()
        self.ssh.connect(
            ssh_host, port=ssh_port, username=ssh_user, password=ssh_password
        )
        self.transport = self.ssh.get_transport()
        self.ssh_host = ssh_host

        self.local_port = local_port
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.server = None

    def handle(self, client):
        chan = None
        try:
            chan = self.transport.open_channel(
                'direct-tcpip',
                (self.remote_host, self.remote_port),
                client.getpeername(),
            )
            if chan is None:
                return

            while True:
                readable, _, _ = select.select([client, chan], [], [])

                for s in readable:
                    data = s.recv(4096)

                    if not data:
                        return

                    if s == client:
                        chan.sendall(data)
                    else:
                        client.sendall(data)
        finally:
            if chan:
                chan.close()
            client.close()

    def start(self):
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(('127.0.0.1', self.local_port))
        self.server.listen(10)

        threading.Thread(
            target=self.accept_connections,
            daemon=True,
        ).start()

    def accept_connections(self):
        while True:
            try:
                client, _ = self.server.accept()
            except OSError:
                break

            threading.Thread(
                target=self.handle,
                args=(client,),
                daemon=True,
            ).start()

    def close(self):
        if self.server:
            self.server.close()
        self.ssh.close()


def connect_server(context: ApplicationContext):
    return Dialog.launch(context, ConnectPage())


def ssh_server(context: ApplicationContext, ip: str):
    return Dialog.launch(context, SshPage(ip, 42069))


def select_path(
    context: ApplicationContext, ops: operations_remote.RemoteOperations, ip: str
):
    return Dialog.launch(context, PathPage(ops, ip))


def remote_operations(server_ip: str, server_port):
    socket = server.SocketClient(server_ip, port=server_port)
    return operations_remote.RemoteOperations(socket)


class Dialog(QtWidgets.QDialog):
    def __init__(self, context: ApplicationContext, page, parent=None):
        super().__init__(parent)
        self.context = context
        self.page = None
        self._pages = {}
        if parent is not None:
            self.setWindowModality(Qt.WindowModal)

        self._stack = QtWidgets.QStackedWidget()

        self.accept_button = qtutils.create_button(
            text=N_('Select'), icon=icons.ok(), default=True
        )
        self.exit_button = qtutils.create_button(text=N_('Exit'), icon=icons.close())

        self._button_layout = qtutils.hbox(
            defs.no_margin,
            defs.button_spacing,
            qtutils.STRETCH,
            self.exit_button,
            self.accept_button,
        )

        self._layout = qtutils.vbox(
            defs.margin, defs.spacing, self._stack, self._button_layout
        )
        self.setLayout(self._layout)

        qtutils.connect_button(self.accept_button, self._on_accept)
        qtutils.connect_button(self.exit_button, self.reject)
        qtutils.add_close_action(self)

        self.resize(400, 150)
        self.set_page(page)

    @classmethod
    def launch(cls, context: ApplicationContext, page):
        view = cls(context, page, parent=qtutils.active_window())
        view.show()
        view.exec_()
        return view

    def set_page(self, page):
        widget = self._pages.get(id(page))
        if widget is None:
            widget = QtWidgets.QWidget(self)
            widget.setLayout(
                qtutils.form(defs.no_margin, defs.spacing, *page.build(self))
            )
            self._pages[id(page)] = widget
            self._stack.addWidget(widget)

        self.page = page
        self._stack.setCurrentWidget(widget)
        self.setWindowTitle(page.title)
        self.accept_button.setText(page.accept_text)
        page.activate(self)

    def _on_accept(self):
        self.page.on_accept(self, self.context)

    def create_lineedit(self, hint: str, hidden: bool = False):
        widget = text.HintedLineEdit(self.context, hint)
        width = qtutils.text_width(widget.font(), 'M')
        widget.setMinimumWidth(width * 32)
        if hidden:
            widget.setEchoMode(QtWidgets.QLineEdit.Password)
        return widget

    def warn(self, title: str, message: str):
        QtWidgets.QMessageBox.warning(self, title, message)

    def error(self, title: str, message: str):
        QtWidgets.QMessageBox.critical(self, title, message)


class Page:
    def build(self, dialog: Dialog):
        return ()

    def activate(self, dialog: Dialog):
        pass

    def on_accept(self, dialog: Dialog, context: ApplicationContext):
        raise NotImplementedError


class ConnectPage(Page):
    def __init__(self) -> None:
        self.title = N_('Connect to Server Repository')
        self.accept_text = N_('Connect')

    def build(self, dialog: Dialog):
        self.server_ip_input = dialog.create_lineedit(N_('e.g. 192.168.1.1'))
        self.server_port = dialog.create_lineedit(N_(str(42069)))
        return (
            (N_('Server IP'), self.server_ip_input),
            (N_('Server Port'), self.server_port),
        )

    def activate(self, dialog: Dialog):
        self.server_ip_input.setFocus()

    def on_accept(self, dialog: Dialog, context: ApplicationContext):
        server_ip = get(self.server_ip_input)
        if not server_ip:
            dialog.warn(self.title, N_('A server address is required.'))
            return

        server_port = get(self.server_port) or 42069

        if server.server_is_up('127.0.0.1'):
            dialog.set_page(PathPage.for_server('127.0.0.1', server_port))
        else:
            print(f'server ip = {server_ip}')
            dialog.set_page(SshPage(server_ip, server_port))


def run_cmd(ssh: SSHClient, command: str) -> tuple[str, str]:
    _, stdout, stderr = ssh.exec_command(command)
    stdout.channel.recv_exit_status()
    return stdout.read().decode(), stderr.read().decode()


class SshPage(Page):
    def __init__(self, ip: str, port=42069):
        self.title = N_('pipe git-cola to server')
        self.accept_text = N_('Connect')
        self.ip = ip
        self.port = port
        self.system = ''
        self.machine = ''

    def build(self, dialog: Dialog):
        self.username_input = dialog.create_lineedit(N_(''))
        self.password_input = dialog.create_lineedit(N_(''), hidden=True)
        return (
            (N_('Username'), self.username_input),
            (N_('Password'), self.password_input),
        )

    def activate(self, dialog: Dialog):
        self.username_input.setFocus()

    def download_executable(self, ssh: SSHClient):
        executable = ''
        if self.system == 'Linux':
            executable = f'git-cola-server-{self.get_hash()}'
        if self.system == 'Windows':
            executable = f'git-cola-server-{self.get_hash()}.exe'
        if self.system == 'Darwin':
            executable = f'git-cola-server-{self.get_hash()}.app.zip'

        if platform.system() in ('Linux', 'Darwin'):
            executable_path = f'/tmp/{executable}'

        if platform.system() == 'Windows':
            executable_path = os.path.join(tempfile.gettempdir(), executable)

        response = requests.get(self.get_url(), timeout=30)
        response.raise_for_status()

        with open(executable_path, 'wb') as f:
            f.write(response.content)

        sftp = ssh.open_sftp()
        sftp.put(executable_path, self.get_expected_path(executable))

        if self.system == 'Darwin':
            ssh.exec_command('unzip -o /tmp/git-cola.app.zip -d /tmp')

    def on_accept(self, dialog: Dialog, context: ApplicationContext):
        username = get(self.username_input)
        password = get(self.password_input)

        if not username or not password:
            dialog.warn(N_('SSH'), N_('Username and password are required.'))
            return

        if server.server_is_up('127.0.0.1'):
            dialog.set_page(PathPage.for_server('127.0.0.1', self.port))
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
            self.get_platform(lambda cmd: run_cmd(ssh, cmd))

            test_command, chmod_command, start_command = self.get_command()

            _, stdout, stderr = ssh.exec_command(test_command)

            exit_code = stdout.channel.recv_exit_status()
            if exit_code != 0:
                self.download_executable(ssh)
                ssh.exec_command(chmod_command)

            _, stdout, stderr = ssh.exec_command(start_command)

        except Exception as e:
            dialog.error(N_('SSH'), f'SSH error: {e}')
            return
        finally:
            for _ in range(10):
                _, stdout, _ = ssh.exec_command(f'ss -ltnp | grep {self.port}')
                if stdout.channel.recv_exit_status() == 0:
                    break
                time.sleep(1)
            ssh.close()

        tunnel = SSHTunnel(
            ssh_host=self.ip,
            ssh_user=username,
            ssh_password=password,
            local_port=self.port,
            remote_host='localhost',
            remote_port=self.port,
        )
        tunnel.start()

        if server.server_is_up('127.0.0.1', tries=20):
            dialog.set_page(PathPage.for_server('127.0.0.1', self.port))
        else:
            dialog.error(N_('SSH'), N_('Server could not be reached.'))

    def get_platform(self, run_cmd: Callable) -> None:
        stdout, _ = run_cmd('uname -s && uname -m')
        lines = stdout.strip().splitlines()

        if len(lines) != 2:
            stdout, _ = run_cmd('echo Windows^|%PROCESSOR_ARCHITECTURE%')
            lines = stdout.strip().replace('Windows_NT', 'Windows').split('|')

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

    def get_expected_path(self, executable_name: str) -> str:
        if self.system == 'Linux' or self.system == 'Darwin':
            return f'/tmp/{executable_name}'
        if self.system == 'Windows':
            return rf'C:\Users\{get(self.username_input)}\AppData\Local\Temp\{executable_name}'

        raise Exception('Unsupported system')

    def get_executable_name(self) -> str:
        if self.system == 'Linux':
            return f'git-cola_linux-{self.machine}-server'
        if self.system == 'Windows':
            return f'git-cola_windows-{self.machine}-server.exe'
        if self.system == 'Darwin':
            return 'git-cola.app.zip'

        raise Exception('System not supported')

    def get_hash(self) -> str:
        asset_name = self.get_executable_name()

        response = requests.get(SERVER_EXECUTABLE_URL, timeout=10)
        response.raise_for_status()
        releases = response.json()

        cur_release = None
        for release in releases:
            if release.get('prerelease'):
                cur_release = release
                break

        if cur_release is None:
            raise Exception('Release was not found')

        for asset in cur_release.get('assets', []):
            if asset['name'] == asset_name:
                digest = asset.get('digest')

                if digest and digest.startswith('sha256:'):
                    return digest.removeprefix('sha256:')

                raise Exception(f'No SHA-256 digest for {asset_name}')

        raise Exception(f'No prerelease asset found for {self.system} {self.machine}')

    def get_url(self) -> str:
        response = requests.get(SERVER_EXECUTABLE_URL, timeout=10)
        response.raise_for_status()
        releases = response.json()

        cur_release = None
        for release in releases:
            if release.get('prerelease'):
                cur_release = release
                break

        if cur_release is None:
            raise Exception('Release was not found')

        url = None
        executable_name = self.get_executable_name()
        for asset in cur_release.get('assets'):
            if asset.get('name') == executable_name:
                url = asset.get('browser_download_url', None)

        if not url:
            raise Exception(f'No release found for {self.system} {self.machine}')

        try:
            response = requests.head(url, allow_redirects=True, timeout=10)
            if response.status_code == 200:
                return url
        except requests.RequestException as e:
            raise Exception(f'Unsupported system: {e}')

        raise Exception(f'No release found for {self.system} {self.machine}')

    def get_command(self) -> tuple[str, str, str]:
        remote_dir = '/tmp'
        remote_executable = f'{remote_dir}/git-cola-server-{self.get_hash()}'

        if self.system == 'Linux':
            test_command = f'test -f {remote_executable}'

            chmod_command = f"chmod 700 {shlex.quote(f'{remote_executable}')}"

            start_command = f'nohup setsid {shlex.quote(remote_executable)} server ' f'> {shlex.quote(remote_dir)}/server.log ' f'2>&1 < /dev/null &'

            return test_command, chmod_command, start_command

        if self.system == 'Darwin':
            test_command = f'test -f {remote_executable}'

            chmod_command = f"chmod 700 {shlex.quote(f'{remote_executable}/git-cola')}"

            start_command = f'nohup {shlex.quote(remote_dir)}/git-cola.app/Contents/MacOS/git-cola server ' f'>{shlex.quote(remote_dir)}/server.log 2>&1 </dev/null &'

            return test_command, chmod_command, start_command

        if self.system == 'Windows':
            remote_dir = rf'C:\Users\{get(self.username_input)}\AppData\Local\Temp'
            remote_executable = rf'{remote_dir}\git-cola-server-{self.get_hash()}.exe'

            test_command = f'powershell -NoProfile -Command ' f"\"if (Test-Path -LiteralPath '{remote_executable}') " f'{{ exit 0 }} else {{ exit 1 }}"'
            chmod_command = ''

            ps = r"""
                    $d = $env:TEMP
                    $exe = Join-Path $d 'git-cola-server.exe'
                    $out = Join-Path $d 'server.out.log'
                    $err = Join-Path $d 'server.err.log'

                    $line = 'cmd /c ""' + $exe + '" server >"' + $out + '" 2>"' + $err + '""'

                    Invoke-CimMethod `
                        -ClassName Win32_Process `
                        -MethodName Create `
                        -Arguments @{ CommandLine = $line } |
                        Select-Object ProcessId, ReturnValue
                """
            blob = base64.b64encode(ps.encode('utf-16-le')).decode()
            start_command = f'powershell -NoProfile -EncodedCommand {blob}'

            return test_command, chmod_command, start_command

        raise Exception(f'Unsupported system: {self.system}')


class PathPage(Page):
    def __init__(self, ops: operations_remote.RemoteOperations, ip: str):
        self.title = N_('Select Path To Repository')
        self.accept_text = N_('Select')
        self.ops = ops
        self.server_ip = ip

    @classmethod
    def for_server(cls, server_ip: str, server_port):
        ops = remote_operations(server_ip, server_port)
        return cls(ops, f'{server_ip}:{server_port}')

    def build(self, dialog: Dialog):
        self.repo_path_input = dialog.create_lineedit(N_('e.g. /path/to/repo'))

        self.browse_button = QtWidgets.QPushButton('...')
        self.browse_button.setMaximumWidth(30)
        self.browse_button.clicked.connect(lambda: self.on_browse(dialog))

        input_layout = qtutils.hbox(
            defs.no_margin,
            defs.spacing,
            self.repo_path_input,
            self.browse_button,
        )
        return ((N_('Path to Repo'), input_layout),)

    def activate(self, dialog: Dialog):
        self.repo_path_input.setFocus()

    def on_browse(self, dialog: Dialog):
        browser = RemoteFileBrowserDialog(dialog.context, self.ops, parent=dialog)
        if browser.exec_() == QtWidgets.QDialog.Accepted:
            selected_path = browser.selected_path()
            if selected_path:
                self.repo_path_input.setText(selected_path)

    def on_accept(self, dialog: Dialog, context: ApplicationContext):
        repo_path = get(self.repo_path_input)
        if not repo_path:
            dialog.warn(self.title, N_('A repository path is required.'))
            return

        cmd = [
            sys.executable,
            '-m',
            'cola',
            'connect',
            self.server_ip,
            repo_path,
        ]
        core.fork(cmd, cwd=os.getcwd())

        dialog.accept()
        QtWidgets.QApplication.quit()


class RemoteFileBrowserDialog(QtWidgets.QDialog):
    def __init__(
        self,
        context: ApplicationContext,
        ops: operations_remote.RemoteOperations,
        parent=None,
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
        self,
        context: ApplicationContext,
        ops: operations_remote.RemoteOperations,
        parent=None,
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
