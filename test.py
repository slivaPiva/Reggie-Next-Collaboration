import os
import shutil
import socket
import subprocess
import sys
import time

from PyQt6 import QtCore, QtGui, QtWidgets


SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_settings.ini")
DEFAULT_HOST_COLOR = "#ffff00"
DEFAULT_CLIENT_COLOR = "#00ffff"


def _normalize_path(path_value):
    return os.path.abspath(os.path.expanduser(str(path_value or "").strip()))


def _require_file(path_value, label):
    raw_value = str(path_value or "").strip()
    if not raw_value:
        raise ValueError("%s is not set." % label)
    path_value = _normalize_path(raw_value)
    if not os.path.isfile(path_value):
        raise FileNotFoundError("%s does not exist: %s" % (label, path_value))
    return path_value


def _require_directory(path_value, label):
    raw_value = str(path_value or "").strip()
    if not raw_value:
        raise ValueError("%s is not set." % label)
    path_value = _normalize_path(raw_value)
    if not os.path.isdir(path_value):
        raise FileNotFoundError("%s does not exist: %s" % (label, path_value))
    return path_value


def _optional_file(path_value):
    raw_value = str(path_value or "").strip()
    if not raw_value:
        return None
    path_value = _normalize_path(raw_value)
    if not os.path.isfile(path_value):
        raise FileNotFoundError("File does not exist: %s" % path_value)
    return path_value


def _optional_directory(path_value):
    raw_value = str(path_value or "").strip()
    if not raw_value:
        return None
    path_value = _normalize_path(raw_value)
    if not os.path.isdir(path_value):
        raise FileNotFoundError("Directory does not exist: %s" % path_value)
    return path_value


def _reggie_root_from_script(reggie_py_path):
    return os.path.dirname(os.path.abspath(reggie_py_path))


def _ensure_patch_available(reggie_root, patch_path):
    patch_path = os.path.abspath(patch_path)
    patch_id = os.path.basename(os.path.normpath(patch_path))
    if not patch_id:
        raise ValueError("Unable to detect patch folder name.")

    patches_dir = os.path.join(reggie_root, "reggiedata", "patches")
    os.makedirs(patches_dir, exist_ok=True)
    target_path = os.path.join(patches_dir, patch_id)

    if os.path.isdir(target_path):
        if os.path.abspath(os.path.realpath(target_path)) == os.path.abspath(os.path.realpath(patch_path)):
            return patch_id
        raise FileExistsError(
            "Patch '%s' already exists in %s, but points to a different folder." % (patch_id, reggie_root)
        )
    if os.path.exists(target_path):
        raise FileExistsError("Patch target already exists and is not a directory: %s" % target_path)

    try:
        os.symlink(patch_path, target_path, target_is_directory=True)
        return patch_id
    except (AttributeError, NotImplementedError, OSError):
        shutil.copytree(patch_path, target_path)
        return patch_id


def _configure_reggie_settings_for_path(settings_path, patch_id=None, stage_path=None):
    settings_path = os.path.abspath(settings_path)
    settings = QtCore.QSettings(settings_path, QtCore.QSettings.Format.IniFormat)
    if patch_id:
        settings.setValue("LastGameDef", patch_id)

    stage_path = _optional_directory(stage_path)
    if stage_path:
        texture_path = os.path.join(stage_path, "Texture")
        settings.setValue("StageGamePath", stage_path)
        settings.setValue("TextureGamePath", texture_path)
        if patch_id:
            settings.setValue("StageGamePath_" + patch_id, stage_path)
            settings.setValue("TextureGamePath_" + patch_id, texture_path)
    settings.sync()


def _create_temp_settings_copy(reggie_root, suffix):
    reggie_root = os.path.abspath(reggie_root)
    source_path = os.path.join(reggie_root, "settings.ini")
    temp_name = "settings_test_%s.ini" % str(suffix or "session")
    temp_path = os.path.join(reggie_root, temp_name)

    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass

    if os.path.isfile(source_path):
        shutil.copy2(source_path, temp_path)
    else:
        with open(temp_path, "w", encoding="utf-8"):
            pass

    return temp_path


def _delete_temp_settings_file(path_value):
    path_value = str(path_value or "").strip()
    if not path_value:
        return
    try:
        if os.path.isfile(path_value):
            os.remove(path_value)
    except OSError:
        pass


def _build_host_command(config):
    command = [
        sys.executable,
        config["host_reggie_py"],
        "--settings-file",
        config["host_settings_path"],
        "--level",
        config["host_level_path"],
        "--collab-host",
        "--collab-mode",
        config["room_mode"],
        "--collab-port",
        str(config["host_port"]),
        "--collab-nick",
        config["host_nick"],
        "--collab-color",
        config["host_color"],
    ]
    if config["room_mode"] == "online":
        command.extend(
            [
                "--collab-room-name",
                config["room_name"],
                "--collab-region",
                config["room_region"],
                "--collab-password",
                config["room_password"],
            ]
        )
    return command


def _build_client_command(config):
    command = [
        sys.executable,
        config["client_reggie_py"],
        "--settings-file",
        config["client_settings_path"],
        "--collab-join-host",
        "127.0.0.1",
        "--collab-join-port",
        str(config["host_port"]),
        "--collab-nick",
        config["client_nick"],
        "--collab-color",
        config["client_color"],
    ]
    if config.get("client_level_path"):
        command[2:2] = ["--level", config["client_level_path"]]
    return command


def _wait_for_port(host, port, timeout_seconds, stop_flag):
    deadline = time.time() + float(timeout_seconds)
    while time.time() < deadline:
        if stop_flag():
            return False
        try:
            with socket.create_connection((host, int(port)), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _terminate_process(process):
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def _format_command(command):
    return subprocess.list2cmdline([str(part) for part in command])


class TestRunner(QtCore.QObject):
    logMessage = QtCore.pyqtSignal(str)
    runFinished = QtCore.pyqtSignal(bool, str)

    def __init__(self, config):
        super().__init__()
        self.config = dict(config)
        self.host_process = None
        self.client_process = None
        self.host_settings_path = None
        self.client_settings_path = None
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True
        self._cleanup_processes()

    def run(self):
        try:
            self._validate_and_prepare()
            host_cmd = _build_host_command(self.config)
            client_cmd = _build_client_command(self.config)

            self.logMessage.emit("Host command:")
            self.logMessage.emit(_format_command(host_cmd))
            self.logMessage.emit("Client command:")
            self.logMessage.emit(_format_command(client_cmd))

            self.host_process = subprocess.Popen(host_cmd, cwd=self.config["host_root"])
            self.logMessage.emit("Host started with PID %d." % int(self.host_process.pid))

            started = _wait_for_port(
                "127.0.0.1",
                self.config["host_port"],
                self.config["host_start_timeout_seconds"],
                lambda: self._stop_requested,
            )
            if self._stop_requested:
                self.runFinished.emit(False, "Test stopped.")
                return
            if not started:
                raise TimeoutError("Host did not start listening on port %d in time." % self.config["host_port"])

            self.client_process = subprocess.Popen(client_cmd, cwd=self.config["client_root"])
            self.logMessage.emit("Client started with PID %d." % int(self.client_process.pid))
            self.logMessage.emit("Both Reggie instances are running.")

            while not self._stop_requested:
                host_code = self.host_process.poll()
                client_code = self.client_process.poll()
                if host_code is not None:
                    raise RuntimeError("Host process exited with code %s." % host_code)
                if client_code is not None:
                    raise RuntimeError("Client process exited with code %s." % client_code)
                time.sleep(1.0)

            self.runFinished.emit(False, "Test stopped.")
        except Exception as exc:
            self.runFinished.emit(False, str(exc))
        finally:
            self._cleanup_processes()

    def _cleanup_processes(self):
        _terminate_process(self.client_process)
        _terminate_process(self.host_process)
        self.client_process = None
        self.host_process = None
        _delete_temp_settings_file(self.client_settings_path)
        _delete_temp_settings_file(self.host_settings_path)
        self.client_settings_path = None
        self.host_settings_path = None

    def _validate_and_prepare(self):
        host_reggie_py = _require_file(self.config.get("host_reggie_py"), "Host reggie.py")
        client_reggie_py = _require_file(self.config.get("client_reggie_py"), "Client reggie.py")
        host_patch_path = _require_directory(self.config.get("host_patch_path"), "Host patch path")
        client_patch_path = _optional_directory(self.config.get("client_patch_path"))
        host_stage_path = _optional_directory(self.config.get("host_stage_path"))
        client_stage_path = _optional_directory(self.config.get("client_stage_path"))
        host_level_path = _require_file(self.config.get("host_level_path"), "Host level path")
        client_level_path = _optional_file(self.config.get("client_level_path"))

        if not host_reggie_py.lower().endswith("reggie.py"):
            raise ValueError("Host reggie.py must point to reggie.py")
        if not client_reggie_py.lower().endswith("reggie.py"):
            raise ValueError("Client reggie.py must point to reggie.py")

        room_mode = str(self.config.get("room_mode") or "lan").strip().lower()
        if room_mode not in ("lan", "online"):
            raise ValueError("Room mode must be lan or online.")
        if room_mode == "online" and not str(self.config.get("room_password") or ""):
            raise ValueError("Password is required for online mode.")

        host_root = _reggie_root_from_script(host_reggie_py)
        client_root = _reggie_root_from_script(client_reggie_py)

        host_patch_id = _ensure_patch_available(host_root, host_patch_path)
        client_patch_id = None
        if client_patch_path:
            client_patch_id = _ensure_patch_available(client_root, client_patch_path)

        self.host_settings_path = _create_temp_settings_copy(host_root, "host")
        self.client_settings_path = _create_temp_settings_copy(client_root, "client")
        _configure_reggie_settings_for_path(self.host_settings_path, host_patch_id, host_stage_path)
        _configure_reggie_settings_for_path(self.client_settings_path, client_patch_id, client_stage_path)

        self.config["host_reggie_py"] = host_reggie_py
        self.config["client_reggie_py"] = client_reggie_py
        self.config["host_patch_path"] = host_patch_path
        self.config["client_patch_path"] = client_patch_path
        self.config["host_stage_path"] = host_stage_path
        self.config["client_stage_path"] = client_stage_path
        self.config["host_level_path"] = host_level_path
        self.config["client_level_path"] = client_level_path
        self.config["host_root"] = host_root
        self.config["client_root"] = client_root
        self.config["host_settings_path"] = self.host_settings_path
        self.config["client_settings_path"] = self.client_settings_path
        self.config["room_mode"] = room_mode
        self.config["host_port"] = int(self.config.get("host_port") or 35000)
        self.config["host_start_timeout_seconds"] = float(self.config.get("host_start_timeout_seconds") or 30.0)


class ReggieConfigGroup(QtWidgets.QGroupBox):
    changed = QtCore.pyqtSignal()

    def __init__(self, title, default_nick, default_color, default_reggie_path="", patch_optional=False, level_optional=False):
        super().__init__(title)
        self._default_color = default_color
        self._patch_optional = patch_optional
        self._level_optional = level_optional
        self.reggieEdit = QtWidgets.QLineEdit(default_reggie_path)
        self.patchEdit = QtWidgets.QLineEdit()
        self.stageEdit = QtWidgets.QLineEdit()
        self.levelEdit = QtWidgets.QLineEdit()
        self.nickEdit = QtWidgets.QLineEdit(default_nick)
        self.colorEdit = QtWidgets.QLineEdit(default_color)
        self.colorButton = QtWidgets.QPushButton("Choose...")
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QFormLayout(self)
        layout.addRow("Reggie.py", self._create_path_row(self.reggieEdit, self._browse_reggie_file))
        layout.addRow("Patch" + (" (optional)" if self._patch_optional else ""), self._create_path_row(self.patchEdit, self._browse_patch_dir))
        layout.addRow("Stage", self._create_path_row(self.stageEdit, self._browse_stage_dir))
        layout.addRow("Level .arc" + (" (optional)" if self._level_optional else ""), self._create_path_row(self.levelEdit, self._browse_level_file))
        layout.addRow("Nick", self.nickEdit)
        layout.addRow("Color", self._create_color_row())

        for widget in (self.reggieEdit, self.patchEdit, self.stageEdit, self.levelEdit, self.nickEdit, self.colorEdit):
            widget.textChanged.connect(self.changed.emit)
        self.colorEdit.textChanged.connect(self._update_color_preview)

        self._update_color_preview(self.colorEdit.text())

    def _create_path_row(self, line_edit, browse_callback):
        container = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(line_edit, 1)
        browse_button = QtWidgets.QPushButton("Browse...")
        browse_button.clicked.connect(browse_callback)
        row.addWidget(browse_button)
        return container

    def _create_color_row(self):
        container = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.colorEdit, 1)
        self.colorButton.clicked.connect(self._choose_color)
        row.addWidget(self.colorButton)
        return container

    def _browse_reggie_file(self):
        file_path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose reggie.py",
            self.reggieEdit.text() or os.getcwd(),
            "Python Files (*.py);;All Files (*)",
        )
        if file_path:
            self.reggieEdit.setText(file_path)

    def _browse_patch_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose patch folder",
            self.patchEdit.text() or os.getcwd(),
        )
        if path:
            self.patchEdit.setText(path)

    def _browse_stage_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose Stage folder",
            self.stageEdit.text() or os.getcwd(),
        )
        if path:
            self.stageEdit.setText(path)

    def _browse_level_file(self):
        file_path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose level file",
            self.levelEdit.text() or os.getcwd(),
            "Level Files (*.arc *.arc.LH *.arc.LZ *.rgl);;All Files (*)",
        )
        if file_path:
            self.levelEdit.setText(file_path)

    def _choose_color(self):
        initial = QtGui.QColor(self.colorEdit.text() or self._default_color)
        color = QtWidgets.QColorDialog.getColor(initial, self, "Choose color")
        if color.isValid():
            self.colorEdit.setText(color.name())
            self._update_color_preview(color.name())

    def _update_color_preview(self, color_text):
        color = QtGui.QColor(color_text)
        if not color.isValid():
            color = QtGui.QColor(self._default_color)
        self.colorButton.setStyleSheet(
            "QPushButton { background-color: %s; color: %s; }"
            % (color.name(), "#000000" if color.lightness() > 128 else "#ffffff")
        )

    def get_data(self):
        return {
            "reggie_py": self.reggieEdit.text().strip(),
            "patch_path": self.patchEdit.text().strip(),
            "stage_path": self.stageEdit.text().strip(),
            "level_path": self.levelEdit.text().strip(),
            "nick": self.nickEdit.text().strip(),
            "color": self.colorEdit.text().strip(),
        }

    def set_data(self, data):
        data = dict(data or {})
        self.reggieEdit.setText(str(data.get("reggie_py") or ""))
        self.patchEdit.setText(str(data.get("patch_path") or ""))
        self.stageEdit.setText(str(data.get("stage_path") or ""))
        self.levelEdit.setText(str(data.get("level_path") or ""))
        self.nickEdit.setText(str(data.get("nick") or ""))
        self.colorEdit.setText(str(data.get("color") or self._default_color))
        self._update_color_preview(self.colorEdit.text())


class TestWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QtCore.QSettings(SETTINGS_PATH, QtCore.QSettings.Format.IniFormat)
        self.thread = None
        self.runner = None
        self.setWindowTitle("Reggie Collaboration Test")
        self.resize(980, 760)
        self._build_ui()
        self._load_settings()
        self._apply_mode_state()

    def _build_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)

        local_reggie = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reggie.py")
        self.hostGroup = ReggieConfigGroup("Host", "Host", DEFAULT_HOST_COLOR)
        self.clientGroup = ReggieConfigGroup(
            "Client",
            "Client",
            DEFAULT_CLIENT_COLOR,
            default_reggie_path=local_reggie,
            patch_optional=True,
            level_optional=True,
        )

        main_layout.addWidget(self.hostGroup)
        main_layout.addWidget(self.clientGroup)

        collab_group = QtWidgets.QGroupBox("Collaboration")
        collab_form = QtWidgets.QFormLayout(collab_group)
        self.modeCombo = QtWidgets.QComboBox()
        self.modeCombo.addItem("LAN", "lan")
        self.modeCombo.addItem("Online", "online")
        self.portSpin = QtWidgets.QSpinBox()
        self.portSpin.setRange(1, 65535)
        self.portSpin.setValue(35000)
        self.roomNameEdit = QtWidgets.QLineEdit("Host Room")
        self.regionEdit = QtWidgets.QLineEdit("EU")
        self.passwordEdit = QtWidgets.QLineEdit()
        self.passwordEdit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.timeoutSpin = QtWidgets.QDoubleSpinBox()
        self.timeoutSpin.setRange(1.0, 300.0)
        self.timeoutSpin.setDecimals(1)
        self.timeoutSpin.setValue(30.0)

        collab_form.addRow("Mode", self.modeCombo)
        collab_form.addRow("Port", self.portSpin)
        collab_form.addRow("Room name", self.roomNameEdit)
        collab_form.addRow("Region", self.regionEdit)
        collab_form.addRow("Password", self.passwordEdit)
        collab_form.addRow("Host timeout", self.timeoutSpin)
        main_layout.addWidget(collab_group)

        self.logEdit = QtWidgets.QPlainTextEdit()
        self.logEdit.setReadOnly(True)
        self.logEdit.setPlaceholderText("Logs will appear here...")
        main_layout.addWidget(self.logEdit, 1)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        self.stopButton = QtWidgets.QPushButton("Stop")
        self.stopButton.setEnabled(False)
        self.testButton = QtWidgets.QPushButton("Test")
        self.testButton.setMinimumHeight(40)
        button_row.addWidget(self.stopButton)
        button_row.addWidget(self.testButton)
        main_layout.addLayout(button_row)

        self.testButton.clicked.connect(self._start_test)
        self.stopButton.clicked.connect(self._stop_test)
        self.modeCombo.currentIndexChanged.connect(self._handle_form_change)
        self.portSpin.valueChanged.connect(self._handle_form_change)
        self.roomNameEdit.textChanged.connect(self._handle_form_change)
        self.regionEdit.textChanged.connect(self._handle_form_change)
        self.passwordEdit.textChanged.connect(self._handle_form_change)
        self.timeoutSpin.valueChanged.connect(self._handle_form_change)
        self.hostGroup.changed.connect(self._save_settings)
        self.clientGroup.changed.connect(self._save_settings)

    def _load_settings(self):
        self.hostGroup.set_data({
            "reggie_py": self.settings.value("host/reggie_py", ""),
            "patch_path": self.settings.value("host/patch_path", ""),
            "stage_path": self.settings.value("host/stage_path", ""),
            "level_path": self.settings.value("host/level_path", ""),
            "nick": self.settings.value("host/nick", "Host"),
            "color": self.settings.value("host/color", DEFAULT_HOST_COLOR),
        })
        self.clientGroup.set_data({
            "reggie_py": self.settings.value(
                "client/reggie_py",
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "reggie.py"),
            ),
            "patch_path": self.settings.value("client/patch_path", ""),
            "stage_path": self.settings.value("client/stage_path", ""),
            "level_path": self.settings.value("client/level_path", ""),
            "nick": self.settings.value("client/nick", "Client"),
            "color": self.settings.value("client/color", DEFAULT_CLIENT_COLOR),
        })

        mode = str(self.settings.value("collab/mode", "lan") or "lan")
        mode_index = max(self.modeCombo.findData(mode), 0)
        self.modeCombo.setCurrentIndex(mode_index)
        self.portSpin.setValue(int(self.settings.value("collab/port", 35000) or 35000))
        self.roomNameEdit.setText(str(self.settings.value("collab/room_name", "Host Room") or "Host Room"))
        self.regionEdit.setText(str(self.settings.value("collab/region", "EU") or "EU"))
        self.passwordEdit.setText(str(self.settings.value("collab/password", "") or ""))
        self.timeoutSpin.setValue(float(self.settings.value("collab/timeout", 30.0) or 30.0))

    def _save_settings(self):
        self.settings.setValue("host/reggie_py", self.hostGroup.reggieEdit.text().strip())
        self.settings.setValue("host/patch_path", self.hostGroup.patchEdit.text().strip())
        self.settings.setValue("host/stage_path", self.hostGroup.stageEdit.text().strip())
        self.settings.setValue("host/level_path", self.hostGroup.levelEdit.text().strip())
        self.settings.setValue("host/nick", self.hostGroup.nickEdit.text().strip())
        self.settings.setValue("host/color", self.hostGroup.colorEdit.text().strip())

        self.settings.setValue("client/reggie_py", self.clientGroup.reggieEdit.text().strip())
        self.settings.setValue("client/patch_path", self.clientGroup.patchEdit.text().strip())
        self.settings.setValue("client/stage_path", self.clientGroup.stageEdit.text().strip())
        self.settings.setValue("client/level_path", self.clientGroup.levelEdit.text().strip())
        self.settings.setValue("client/nick", self.clientGroup.nickEdit.text().strip())
        self.settings.setValue("client/color", self.clientGroup.colorEdit.text().strip())

        self.settings.setValue("collab/mode", self.modeCombo.currentData())
        self.settings.setValue("collab/port", self.portSpin.value())
        self.settings.setValue("collab/room_name", self.roomNameEdit.text().strip())
        self.settings.setValue("collab/region", self.regionEdit.text().strip())
        self.settings.setValue("collab/password", self.passwordEdit.text())
        self.settings.setValue("collab/timeout", self.timeoutSpin.value())
        self.settings.sync()

    def _handle_form_change(self):
        self._apply_mode_state()
        self._save_settings()

    def _apply_mode_state(self):
        is_online = self.modeCombo.currentData() == "online"
        self.roomNameEdit.setEnabled(is_online)
        self.regionEdit.setEnabled(is_online)
        self.passwordEdit.setEnabled(is_online)

    def _append_log(self, text):
        self.logEdit.appendPlainText(str(text))
        self.logEdit.verticalScrollBar().setValue(self.logEdit.verticalScrollBar().maximum())

    def _collect_config(self):
        host_data = self.hostGroup.get_data()
        client_data = self.clientGroup.get_data()
        return {
            "host_reggie_py": host_data["reggie_py"],
            "host_patch_path": host_data["patch_path"],
            "host_stage_path": host_data["stage_path"],
            "host_level_path": host_data["level_path"],
            "host_nick": host_data["nick"] or "Host",
            "host_color": host_data["color"] or DEFAULT_HOST_COLOR,
            "client_reggie_py": client_data["reggie_py"],
            "client_patch_path": client_data["patch_path"],
            "client_stage_path": client_data["stage_path"],
            "client_level_path": client_data["level_path"],
            "client_nick": client_data["nick"] or "Client",
            "client_color": client_data["color"] or DEFAULT_CLIENT_COLOR,
            "room_mode": self.modeCombo.currentData(),
            "host_port": self.portSpin.value(),
            "room_name": self.roomNameEdit.text().strip() or "Host Room",
            "room_region": self.regionEdit.text().strip() or "EU",
            "room_password": self.passwordEdit.text(),
            "host_start_timeout_seconds": self.timeoutSpin.value(),
        }

    def _start_test(self):
        if self.thread is not None:
            QtWidgets.QMessageBox.information(self, "Test already running", "Stop the current test before starting a new one.")
            return

        self._save_settings()
        self.logEdit.clear()
        self._append_log("Preparing test...")

        self.runner = TestRunner(self._collect_config())
        self.thread = QtCore.QThread(self)
        self.runner.moveToThread(self.thread)
        self.thread.started.connect(self.runner.run)
        self.runner.logMessage.connect(self._append_log)
        self.runner.runFinished.connect(self._handle_runner_finished)
        self.runner.runFinished.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup_thread)
        self.thread.start()

        self.testButton.setEnabled(False)
        self.stopButton.setEnabled(True)

    def _stop_test(self):
        if self.runner is not None:
            self._append_log("Stopping test...")
            self.runner.stop()

    def _handle_runner_finished(self, success, message):
        if message:
            self._append_log(message)
        if (not success) and message and message != "Test stopped.":
            QtWidgets.QMessageBox.warning(self, "Test failed", message)

    def _cleanup_thread(self):
        if self.runner is not None:
            self.runner.deleteLater()
        if self.thread is not None:
            self.thread.deleteLater()
        self.runner = None
        self.thread = None
        self.testButton.setEnabled(True)
        self.stopButton.setEnabled(False)

    def closeEvent(self, event):
        self._save_settings()
        if self.runner is not None:
            self.runner.stop()
            if self.thread is not None:
                self.thread.quit()
                self.thread.wait(3000)
        super().closeEvent(event)


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
