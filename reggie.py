#!/usr/bin/python
# -*- coding: latin-1 -*-

# Reggie Next - New Super Mario Bros. Wii Level Editor
# Milestone 4
# Copyright (C) 2009-2020 Treeki, Tempus, angelsl, JasonP27, Kamek64,
# MalStar1000, RoadrunnerWMC, AboodXD, John10v10, TheGrop, CLF78,
# Zementblock, Danster64

# This file is part of Reggie Next.

# Reggie Next is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Reggie Next is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with Reggie Next.  If not, see <http://www.gnu.org/licenses/>.


# reggie.py
# This is the main executable for Reggie Next.


################################################################
################################################################

# Python version: sanity check
minimum = (3, 5)
import sys

if sys.version_info < minimum:
    errormsg = 'Please update your copy of Python to ' + '.'.join(map(str, minimum)) + \
               ' or greater. Currently running on: ' + sys.version[:5]

    raise Exception(errormsg)

# Stdlib imports
import os.path
import random
import time
import traceback
import struct
import base64
import collections
import uuid
import zipfile
import re
import math
import hashlib
import zlib
import subprocess

# PyQt6: import, and error msg if not installed
try:
    from PyQt6 import QtCore, QtGui, QtWidgets
except (ImportError, NameError):
    errormsg = 'PyQt6 is not installed for this Python installation. Go online and download it.'
    raise Exception(errormsg)
Qt = QtCore.Qt

version = map(int, QtCore.QT_VERSION_STR.split('.'))
min_version = "6.9"
pqt_min = map(int, min_version.split('.'))
for v, c in zip(version, pqt_min):
    if c > v:
        # lower version
        errormsg = 'Please update your copy of PyQt to ' + min_version \
                 + ' or greater. Currently running on: ' + QtCore.QT_VERSION_STR

        raise Exception(errormsg) from None
    elif c < v:
        # higher version
        break

################################################################################
################################################################################
################################################################################

# Local imports
import archive
import sprites
import spritelib as SLib
import common

import globals_

################################################################################
################################################################################
################################################################################

from libs import lh, lib_versions, lz77
from ui import GetIcon, SetAppStyle, ListWidgetWithToolTipSignal, LoadNumberFont, LoadTheme, IconsOnlyTabBar
from misc import LoadActionsLists, LoadSpriteData, LoadTilesetInfo, FilesAreMissing, module_path, IsNSMBLevel, ChooseLevelNameDialog, LoadLevelNames, PreferencesDialog, LoadSpriteCategories, ZoomWidget, ZoomStatusWidget, RecentFilesMenu, SetGamePaths, areValidGamePaths, LoadZoneThemes, NormalizeToolbarToggles
from misc2 import LevelScene, LevelViewWidget, ChatWindow
from dirty import setting, setSetting, SetDirty
from gamedef import GameDefMenu, LoadGameDef, ReggieGameDefinition, getAvailableGameDefs
from levelitems import LocationItem, ZoneItem, ObjectItem, SpriteItem, EntranceItem, ListWidgetItem_SortsByOther, PathItem, Path, CommentItem, PathEditorLineItem
from dialogs import AutoSavedInfoDialog, DiagnosticToolDialog, ScreenCapChoiceDialog, AreaChoiceDialog, ObjectTypeSwapDialog, ObjectTilesetSwapDialog, ObjectShiftDialog, MetaInfoDialog, AboutDialog, CameraProfilesDialog
from background import BGDialog
from zones import ZonesDialog
from tiles import UnloadTileset, LoadTileset, LoadOverrides
from area import AreaOptionsDialog
from level import Level_NSMBW
from sidelists import Stamp, StampChooserWidget, SpriteList, SpritePickerWidget, ObjectPickerWidget, LevelOverviewWidget
from spriteeditor import SpriteEditorWidget
from editors import LocationEditorWidget, PathNodeEditorWidget, EntranceEditorWidget
from undo import UndoStack
from translation import LoadTranslation
from collaboration import CollaborationManager

# Quick Paint Tool - import only after QApplication is created to avoid import-chain issues.
QPT_AVAILABLE = True
QPT_INITIALIZED = False
_qpt_functions = None


def _get_reggie_base_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()


def _get_quickpaint_dir():
    return os.path.join(_get_reggie_base_dir(), 'quickpaint')


def _get_quickpaint_tileset_cache_dir():
    path = os.path.join(_get_reggie_base_dir(), 'collab_tilesets', 'quickpaint_prebuilt')
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def _register_quickpaint_tileset_overrides():
    quickpaint_dir = _get_quickpaint_dir()
    prepared = {}
    if not os.path.isdir(quickpaint_dir):
        globals_.QuickPaintTilesetOverrides = prepared
        return prepared

    overrides = getattr(globals_, 'CollabTilesetOverrides', None)
    if not isinstance(overrides, dict):
        globals_.CollabTilesetOverrides = {}
        overrides = globals_.CollabTilesetOverrides

    cache_dir = _get_quickpaint_tileset_cache_dir()

    for root, _dirs, files in os.walk(quickpaint_dir):
        for filename in sorted(files):
            lower_name = filename.lower()
            if lower_name.endswith('.arc.lh'):
                tileset_name = filename[:-7]
            elif lower_name.endswith('.arc'):
                tileset_name = filename[:-4]
            else:
                continue

            tileset_name = str(tileset_name or '').strip()
            if not tileset_name or tileset_name in prepared:
                continue

            source_path = os.path.join(root, filename)
            override_path = source_path

            try:
                if lower_name.endswith('.arc.lh'):
                    with open(source_path, 'rb') as f:
                        data = f.read()
                    if not data:
                        continue
                    if (data[0] & 0xF0) == 0x40:
                        data = lh.UncompressLH(data)
                    cache_path = os.path.join(cache_dir, '%s.arc' % tileset_name)
                    with open(cache_path, 'wb') as f:
                        f.write(data)
                    override_path = cache_path
            except Exception as e:
                print(f"[QPT] Warning: Could not prepare quickpaint tileset '{tileset_name}': {e}")
                continue

            prepared[tileset_name] = override_path
            overrides[tileset_name] = override_path

    globals_.QuickPaintTilesetOverrides = prepared
    return prepared

################################################################################
################################################################################
################################################################################

def _excepthook(*exc_info):
    """
    Custom unhandled exceptions handler
    """
    separator = '-' * 80
    logFile = "log.txt"
    notice = globals_.trans.string('ErrorDlg', 0, '[log]', logFile)

    timeString = time.strftime("%Y-%m-%d, %H:%M:%S")

    e = "".join(traceback.format_exception(*exc_info))
    sections = [separator, timeString, separator, e]
    msg = '\n'.join(sections)

    globals_.ErrMsg += msg

    try:
        with open(logFile, "w", encoding="utf-8") as f:
            f.write(globals_.ErrMsg)

    except IOError:
        pass

    errorbox = QtWidgets.QMessageBox()
    errorbox.setText(notice + msg)
    errorbox.exec()

    globals_.DirtyOverride = 0


# Override the exception handler with ours
sys.excepthook = _excepthook

################################################################################
################################################################################
################################################################################

DEFAULT_COLLAB_HIGHLIGHT_COLOR = '#ffff00'
COLLAB_CURSOR_DISPLAY_ALWAYS = 'always'
COLLAB_CURSOR_DISPLAY_ON_P = 'on_p'
COLLAB_CURSOR_DISPLAY_NEVER = 'never'
COLLAB_CURSOR_DISPLAY_MODES = {
    COLLAB_CURSOR_DISPLAY_ALWAYS,
    COLLAB_CURSOR_DISPLAY_ON_P,
    COLLAB_CURSOR_DISPLAY_NEVER,
}


def normalize_collab_color(value, default=DEFAULT_COLLAB_HIGHLIGHT_COLOR):
    try:
        if isinstance(value, QtGui.QColor):
            color = QtGui.QColor(value)
        else:
            color = QtGui.QColor(str(value or ''))
        if not color.isValid():
            color = QtGui.QColor(str(default or DEFAULT_COLLAB_HIGHLIGHT_COLOR))
        if not color.isValid():
            color = QtGui.QColor(255, 255, 0)
        return color.name(QtGui.QColor.NameFormat.HexRgb).lower()
    except Exception:
        return DEFAULT_COLLAB_HIGHLIGHT_COLOR


def collab_qcolor(value=None, alpha=None):
    color = QtGui.QColor(normalize_collab_color(value))
    if alpha is not None:
        color.setAlpha(max(0, min(255, int(alpha))))
    return color


def collab_color_button_stylesheet(value):
    color = collab_qcolor(value)
    brightness = (color.red() * 299 + color.green() * 587 + color.blue() * 114) / 1000
    text_color = '#111111' if brightness >= 160 else '#ffffff'
    return (
        'QPushButton {'
        'padding: 4px 10px;'
        'border: 1px solid palette(mid);'
        'border-radius: 4px;'
        'background: %s;'
        'color: %s;'
        '}'
        'QPushButton:hover { border: 1px solid palette(highlight); }'
    ) % (color.name(QtGui.QColor.NameFormat.HexRgb), text_color)

class CollaborationHostDialog(QtWidgets.QDialog):
    """
    Lets the user host either a private LAN room or a public room listed on the Dolphin lobby.
    """

    def __init__(self, parent=None, default_port=35000, default_mode='lan', default_name=''):
        super().__init__(parent)
        self.setWindowTitle('Host collaboration room')
        self.resize(520, 300)

        layout = QtWidgets.QVBoxLayout(self)

        intro = QtWidgets.QLabel('Choose whether to host a private LAN room or a public room listed through Dolphin servers.')
        intro.setWordWrap(True)
        layout.addWidget(intro)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel('Mode:'))
        self.lanRadio = QtWidgets.QRadioButton('Private LAN')
        self.publicRadio = QtWidgets.QRadioButton('Public Online')
        mode_row.addWidget(self.lanRadio)
        mode_row.addWidget(self.publicRadio)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.modeGroup = QtWidgets.QButtonGroup(self)
        self.modeGroup.addButton(self.lanRadio)
        self.modeGroup.addButton(self.publicRadio)
        if str(default_mode or 'lan').strip().lower() == 'public':
            self.publicRadio.setChecked(True)
        else:
            self.lanRadio.setChecked(True)

        form = QtWidgets.QFormLayout()
        self.portSpin = QtWidgets.QSpinBox()
        self.portSpin.setRange(1, 65535)
        self.portSpin.setValue(int(default_port))
        form.addRow('Port:', self.portSpin)
        layout.addLayout(form)

        self.publicBox = QtWidgets.QGroupBox('Public room settings')
        public_form = QtWidgets.QFormLayout(self.publicBox)
        self.roomNameEdit = QtWidgets.QLineEdit()
        self.roomNameEdit.setPlaceholderText(default_name or "Player's room")
        self.roomNameEdit.setText(str(setting('CollabPublicRoomName', default_name or '') or default_name or ''))
        public_form.addRow('Room name:', self.roomNameEdit)

        self.regionCombo = QtWidgets.QComboBox()
        saved_region = str(setting('CollabPublicRegion', 'EU') or 'EU').strip().upper() or 'EU'
        selected_region_index = 0
        for index, (code, label) in enumerate(CollaborationManager.PUBLIC_ROOM_REGIONS):
            self.regionCombo.addItem('%s (%s)' % (label, code), code)
            if code == saved_region:
                selected_region_index = index
        self.regionCombo.setCurrentIndex(selected_region_index)
        public_form.addRow('Region:', self.regionCombo)

        self.passwordEdit = QtWidgets.QLineEdit()
        self.passwordEdit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.passwordEdit.setPlaceholderText('Required for public rooms')
        public_form.addRow('Password:', self.passwordEdit)

        self.publicHelpLabel = QtWidgets.QLabel(
            'Public rooms are published to the Dolphin lobby and use Dolphin Traversal for NAT punching. The selected port is still used locally for LAN discovery and TCP fallback on the same network.'
        )
        self.publicHelpLabel.setWordWrap(True)
        public_form.addRow(self.publicHelpLabel)
        layout.addWidget(self.publicBox)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.okButton = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self.okButton.setText('Host room')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.lanRadio.toggled.connect(self._UpdateModeUi)
        self.publicRadio.toggled.connect(self._UpdateModeUi)
        self._UpdateModeUi()

    def _UpdateModeUi(self):
        is_public = self.publicRadio.isChecked()
        self.publicBox.setVisible(is_public)

    def selectedConfig(self):
        return {
            'mode': 'public' if self.publicRadio.isChecked() else 'lan',
            'port': self.portSpin.value(),
            'name': self.roomNameEdit.text().strip(),
            'region': str(self.regionCombo.currentData() or 'EU'),
            'password': self.passwordEdit.text(),
        }

    def accept(self):
        config = self.selectedConfig()
        if config['mode'] == 'public':
            if not config['name']:
                QtWidgets.QMessageBox.warning(self, 'Collaboration', 'Enter a room name for the public room.')
                return
            if not config['password']:
                QtWidgets.QMessageBox.warning(self, 'Collaboration', 'Enter a password for the public room.')
                return
            setSetting('CollabPublicRoomName', config['name'])
            setSetting('CollabPublicRegion', config['region'])
        setSetting('CollabHostMode', config['mode'])
        super().accept()


class CollaborationServerPickerDialog(QtWidgets.QDialog):
    """
    Lets the user browse LAN hosts or public rooms listed through the Dolphin lobby.
    """

    def __init__(self, parent=None, default_port=35000, default_source='lan'):
        super().__init__(parent)
        self._hosts = []
        self.setWindowTitle('Join collaboration room')
        self.resize(700, 430)

        layout = QtWidgets.QVBoxLayout(self)

        source_row = QtWidgets.QHBoxLayout()
        source_row.addWidget(QtWidgets.QLabel('Server list:'))
        self.lanRadio = QtWidgets.QRadioButton('LAN')
        self.onlineRadio = QtWidgets.QRadioButton('Online')
        source_row.addWidget(self.lanRadio)
        source_row.addWidget(self.onlineRadio)
        source_row.addStretch(1)
        layout.addLayout(source_row)

        self.sourceGroup = QtWidgets.QButtonGroup(self)
        self.sourceGroup.addButton(self.lanRadio)
        self.sourceGroup.addButton(self.onlineRadio)
        if str(default_source or 'lan').strip().lower() == 'online':
            self.onlineRadio.setChecked(True)
        else:
            self.lanRadio.setChecked(True)

        self.infoLabel = QtWidgets.QLabel('')
        self.infoLabel.setWordWrap(True)
        layout.addWidget(self.infoLabel)

        self.onlineFilterBox = QtWidgets.QGroupBox('Online filters')
        filter_layout = QtWidgets.QHBoxLayout(self.onlineFilterBox)
        filter_layout.addWidget(QtWidgets.QLabel('Name:'))
        self.nameFilterEdit = QtWidgets.QLineEdit()
        self.nameFilterEdit.setPlaceholderText('Optional room name filter')
        filter_layout.addWidget(self.nameFilterEdit, 1)
        filter_layout.addWidget(QtWidgets.QLabel('Region:'))
        self.regionFilterCombo = QtWidgets.QComboBox()
        self.regionFilterCombo.addItem('All regions', 'ALL')
        for code, label in CollaborationManager.PUBLIC_ROOM_REGIONS:
            self.regionFilterCombo.addItem('%s (%s)' % (label, code), code)
        filter_layout.addWidget(self.regionFilterCombo)
        layout.addWidget(self.onlineFilterBox)

        self.serverList = QtWidgets.QListWidget()
        self.serverList.itemSelectionChanged.connect(self._HandleSelectionChanged)
        self.serverList.itemDoubleClicked.connect(self._HandleItemActivated)
        layout.addWidget(self.serverList, 1)

        self.statusLabel = QtWidgets.QLabel('')
        self.statusLabel.setWordWrap(True)
        layout.addWidget(self.statusLabel)

        form = QtWidgets.QFormLayout()
        self.hostEdit = QtWidgets.QLineEdit()
        self.hostEdit.setPlaceholderText('192.168.196.10')
        self.hostEdit.textChanged.connect(self._UpdateConnectButton)
        form.addRow('Manual host:', self.hostEdit)

        self.portSpin = QtWidgets.QSpinBox()
        self.portSpin.setRange(1, 65535)
        self.portSpin.setValue(int(default_port))
        form.addRow('Port:', self.portSpin)
        layout.addLayout(form)

        button_row = QtWidgets.QHBoxLayout()
        self.refreshButton = QtWidgets.QPushButton('Refresh')
        self.refreshButton.clicked.connect(self.RefreshServers)
        button_row.addWidget(self.refreshButton)
        button_row.addStretch(1)

        self.connectButton = QtWidgets.QPushButton('Connect')
        self.connectButton.clicked.connect(self.accept)
        self.connectButton.setDefault(True)
        button_row.addWidget(self.connectButton)

        cancel_button = QtWidgets.QPushButton('Cancel')
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        self.lanRadio.toggled.connect(self._HandleSourceChanged)
        self.onlineRadio.toggled.connect(self._HandleSourceChanged)
        self.nameFilterEdit.returnPressed.connect(self.RefreshServers)
        self.regionFilterCombo.currentIndexChanged.connect(self._UpdateInfoLabel)

        self._HandleSourceChanged()

    def selectedSource(self):
        return 'online' if self.onlineRadio.isChecked() else 'lan'

    def _UpdateInfoLabel(self):
        if self.selectedSource() == 'online':
            self.infoLabel.setText('Browse public collaboration rooms listed on Dolphin servers, or enter a public IP address manually.')
        else:
            self.infoLabel.setText('Browse private LAN rooms on the selected port, or enter a local IP address manually.')

    def _HandleSourceChanged(self):
        is_online = self.selectedSource() == 'online'
        self.onlineFilterBox.setVisible(is_online)
        self.hostEdit.clear()
        if is_online:
            self.hostEdit.setPlaceholderText('Optional public IP/hostname')
        else:
            self.hostEdit.setPlaceholderText('192.168.196.10')
        self._UpdateInfoLabel()
        self.RefreshServers()

    def _FormatHostText(self, host_info):
        if str(host_info.get('source') or '') == 'online':
            text = str(host_info.get('session_name') or host_info.get('host_name') or 'Public room')
            details = []
            region = str(host_info.get('region') or '').strip()
            display_game = str(host_info.get('display_game') or '').strip()
            player_count = int(host_info.get('player_count', 0) or 0)
            if region:
                details.append(region)
            if display_game:
                details.append(display_game)
            if player_count > 0:
                details.append('%d player(s)' % player_count)
            if bool(host_info.get('requires_password')):
                details.append('Password')
            if details:
                text += '  |  ' + '  |  '.join(details)
            return text

        host_name = host_info.get('host_name') or host_info.get('host') or ''
        host = host_info.get('host') or ''
        port = int(host_info.get('port', self.portSpin.value()) or self.portSpin.value())
        display_game = str(host_info.get('display_game') or host_info.get('game_name') or '').strip()
        room_mode = str(host_info.get('room_mode') or 'lan').strip().lower()
        if host_name and host_name != host:
            text = '%s (%s:%d)' % (host_name, host, port)
        else:
            text = '%s:%d' % (host, port)
        if room_mode == 'public':
            public_name = str(host_info.get('public_room_name') or '').strip()
            text += '  |  PUBLIC'
            if public_name:
                text += '  |  %s' % public_name
        if display_game:
            text += '  |  %s' % display_game
        return text

    def _HandleSelectionChanged(self):
        item = self.serverList.currentItem()
        if item is None:
            self._UpdateConnectButton()
            return

        host_info = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(host_info, dict):
            self.portSpin.setValue(int(host_info.get('port', self.portSpin.value()) or self.portSpin.value()))
            if str(host_info.get('source') or '') != 'online':
                self.hostEdit.setText(host_info.get('host', ''))
        self._UpdateConnectButton()

    def _HandleItemActivated(self, item):
        self.serverList.setCurrentItem(item)
        self.accept()

    def _UpdateConnectButton(self):
        has_manual_host = bool(self.hostEdit.text().strip())
        has_selected_room = self.selectedHostInfo() is not None
        self.connectButton.setEnabled(has_manual_host or has_selected_room)

    def RefreshServers(self):
        port = self.portSpin.value()
        source = self.selectedSource()
        self.refreshButton.setEnabled(False)
        self.serverList.clear()
        self.statusLabel.setText('Refreshing...')
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        error_text = ''
        try:
            if source == 'online':
                filters = {
                    'name': self.nameFilterEdit.text().strip(),
                    'region': self.regionFilterCombo.currentData(),
                }
                self._hosts = CollaborationManager.list_public_rooms(filters=filters)
            else:
                self._hosts = CollaborationManager.discover_hosts(port=port)
        except Exception as exc:
            self._hosts = []
            error_text = str(exc)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.refreshButton.setEnabled(True)

        for host_info in self._hosts:
            item = QtWidgets.QListWidgetItem(self._FormatHostText(host_info))
            item.setData(Qt.ItemDataRole.UserRole, host_info)
            self.serverList.addItem(item)

        if self._hosts:
            self.serverList.setCurrentRow(0)
            if source == 'online':
                self.statusLabel.setText('Found %d public room(s).' % len(self._hosts))
            else:
                self.statusLabel.setText('Found %d LAN server(s).' % len(self._hosts))
        elif error_text:
            self.statusLabel.setText('Unable to refresh server list:\n%s' % error_text)
        elif source == 'online':
            self.statusLabel.setText('No public rooms were found. You can still enter a public IP address manually.')
            self.hostEdit.selectAll()
            self.hostEdit.setFocus()
        else:
            self.statusLabel.setText('No LAN servers were found. You can still enter an IP address manually.')
            self.hostEdit.selectAll()
            self.hostEdit.setFocus()
        self._UpdateConnectButton()

    def accept(self):
        if not self.hostEdit.text().strip() and self.selectedHostInfo() is None:
            QtWidgets.QMessageBox.warning(self, 'Collaboration', 'Select a server or enter a host address manually.')
            return
        setSetting('CollabJoinSource', self.selectedSource())
        super().accept()

    def selectedHost(self):
        return self.hostEdit.text().strip(), self.portSpin.value()

    def selectedHostInfo(self):
        item = self.serverList.currentItem()
        if item is None:
            return None
        host_info = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(host_info, dict):
            return None
        if self.selectedSource() == 'online':
            if self.hostEdit.text().strip():
                return None
            return dict(host_info)
        selected_host = str(host_info.get('host') or '').strip()
        selected_port = int(host_info.get('port', self.portSpin.value()) or self.portSpin.value())
        if selected_host != self.hostEdit.text().strip():
            return None
        if selected_port != self.portSpin.value():
            return None
        return dict(host_info)


class CollaborationGameSelectDialog(QtWidgets.QDialog):
    def __init__(self, host_info, parent=None):
        super().__init__(parent)
        self._host_info = dict(host_info or {})
        self._host_game_id = self._NormalizeGameId(self._host_info.get('game_id'))
        self._host_game_name = str(self._host_info.get('game_name') or 'Unknown game')
        self.setWindowTitle('Change Game')
        self.resize(520, 420)

        layout = QtWidgets.QVBoxLayout(self)

        title = QtWidgets.QLabel('Host game: %s' % self._host_game_name)
        title.setWordWrap(True)
        layout.addWidget(title)

        info = QtWidgets.QLabel('Choose the same game before connecting. Stage folder will not be requested here.')
        info.setWordWrap(True)
        layout.addWidget(info)

        self.gameList = QtWidgets.QListWidget()
        self.gameList.itemDoubleClicked.connect(self._HandleItemActivated)
        layout.addWidget(self.gameList, 1)

        self.statusLabel = QtWidgets.QLabel('')
        self.statusLabel.setWordWrap(True)
        layout.addWidget(self.statusLabel)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.okButton = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self.okButton.setText('Use selected game')
        layout.addWidget(buttons)

        self._PopulateGameList()

    @staticmethod
    def _NormalizeGameId(value):
        if value in (None, '', 'None', False, 0):
            return ''
        return str(value)

    def _PopulateGameList(self):
        self.gameList.clear()
        host_item = None
        current_item = None
        current_game_id = ''
        try:
            if getattr(globals_.gamedef, 'custom', False):
                current_game_id = self._NormalizeGameId(getattr(globals_.gamedef, 'gamepath', None))
        except Exception:
            current_game_id = ''

        for folder in getAvailableGameDefs():
            def_ = ReggieGameDefinition(folder)
            item = QtWidgets.QListWidgetItem(str(def_.name))
            item.setData(Qt.ItemDataRole.UserRole, folder)
            if getattr(def_, 'description', None):
                item.setToolTip(str(def_.description).replace('<br>', '\n'))
            self.gameList.addItem(item)

            item_game_id = self._NormalizeGameId(folder)
            if item_game_id == self._host_game_id:
                host_item = item
            if item_game_id == current_game_id:
                current_item = item

        preferred_item = host_item or current_item
        if preferred_item is not None:
            self.gameList.setCurrentItem(preferred_item)

        if host_item is None:
            self.statusLabel.setText('The host game is not installed locally.')
            self.okButton.setEnabled(False)
        else:
            self.statusLabel.setText('The selected game must match the host.')
            self.okButton.setEnabled(True)

    def _HandleItemActivated(self, item):
        self.gameList.setCurrentItem(item)
        self.accept()

    def selectedGameDef(self):
        item = self.gameList.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def accept(self):
        selected = self._NormalizeGameId(self.selectedGameDef())
        if selected != self._host_game_id:
            QtWidgets.QMessageBox.warning(
                self,
                'Change Game',
                'Choose the same game as the host:\n%s' % self._host_game_name,
            )
            return
        super().accept()


class CollaborationStartupDialog(QtWidgets.QDialog):
    def __init__(self, nickname='', highlight_color=DEFAULT_COLLAB_HIGHLIGHT_COLOR, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Reggie! Next startup')
        self.setModal(True)
        self.resize(460, 180)
        self._highlightColor = normalize_collab_color(highlight_color)

        layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel('Choose your collaboration nickname before opening Reggie.')
        title.setWordWrap(True)
        layout.addWidget(title)

        form = QtWidgets.QFormLayout()
        self.nicknameEdit = QtWidgets.QLineEdit(str(nickname or '').strip() or 'Player')
        self.nicknameEdit.setMaxLength(32)
        self.nicknameEdit.selectAll()
        nick_row = QtWidgets.QHBoxLayout()
        nick_row.setContentsMargins(0, 0, 0, 0)
        nick_row.setSpacing(6)
        nick_row.addWidget(self.nicknameEdit, 1)
        self.colorButton = QtWidgets.QPushButton('Color')
        self.colorButton.clicked.connect(self._ChooseHighlightColor)
        nick_row.addWidget(self.colorButton)
        self._RefreshColorButton()
        form.addRow('Nickname:', nick_row)
        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        ok_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        ok_button.setText('Continue')
        cancel_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setText('Quit')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def nickname(self):
        return str(self.nicknameEdit.text()).strip() or 'Player'

    def highlightColor(self):
        return normalize_collab_color(self._highlightColor)

    def _RefreshColorButton(self):
        self.colorButton.setStyleSheet(collab_color_button_stylesheet(self._highlightColor))
        self.colorButton.setText(self.highlightColor())

    def _ChooseHighlightColor(self):
        picked = QtWidgets.QColorDialog.getColor(collab_qcolor(self._highlightColor), self, 'Choose highlight color')
        if not picked.isValid():
            return
        self._highlightColor = normalize_collab_color(picked)
        self._RefreshColorButton()

    def accept(self):
        self.nicknameEdit.setText(self.nickname())
        super().accept()


class CollaborationBanListDialog(QtWidgets.QDialog):
    def __init__(self, remove_callback=None, parent=None):
        super().__init__(parent)
        self._remove_callback = remove_callback
        self._ban_list = {}
        self.setWindowTitle('Collaboration ban list')
        self.resize(420, 340)
        self.setStyleSheet(
            'QDialog { background: rgba(8, 8, 8, 225); color: white; }'
            'QListWidget { background: transparent; color: white; border: 1px solid rgba(255,255,255,80); }'
            'QPushButton { color: white; background: rgba(255,255,255,25); border: 1px solid rgba(255,255,255,90); padding: 6px 10px; }'
            'QLabel { color: white; }'
        )

        layout = QtWidgets.QVBoxLayout(self)
        info = QtWidgets.QLabel('Bans use IP address. Each entry shows the IP and the latest nickname seen on that IP.')
        info.setWordWrap(True)
        layout.addWidget(info)

        self.listWidget = QtWidgets.QListWidget()
        layout.addWidget(self.listWidget, 1)

        button_row = QtWidgets.QHBoxLayout()
        self.removeButton = QtWidgets.QPushButton('Remove selected ban')
        self.removeButton.clicked.connect(self._HandleRemove)
        button_row.addWidget(self.removeButton)
        button_row.addStretch(1)
        close_button = QtWidgets.QPushButton('Close')
        close_button.clicked.connect(self.close)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def setBanList(self, ban_list):
        self._ban_list = dict(ban_list or {})
        self.listWidget.clear()
        for ip, nickname in sorted(self._ban_list.items()):
            item = QtWidgets.QListWidgetItem('%s  |  %s' % (ip, str(nickname or 'Player')))
            item.setData(Qt.ItemDataRole.UserRole, ip)
            self.listWidget.addItem(item)
        self.removeButton.setEnabled(self.listWidget.count() > 0)

    def _HandleRemove(self):
        item = self.listWidget.currentItem()
        if item is None:
            return
        ip = item.data(Qt.ItemDataRole.UserRole)
        if callable(self._remove_callback):
            self._remove_callback(ip)


class CollaborationMonitorDialog(QtWidgets.QDialog):
    def __init__(self, participant_callback=None, ban_list_callback=None, parent=None):
        super().__init__(parent)
        self._participant_callback = participant_callback
        self._ban_list_callback = ban_list_callback
        self._is_host = False
        self.setWindowTitle('Collaboration online monitor')
        self.resize(440, 420)
        self.setStyleSheet(
            'QDialog { background: rgba(8, 8, 8, 225); color: white; }'
            'QListWidget { background: transparent; color: white; border: 1px solid rgba(255,255,255,80); }'
            'QPushButton { color: white; background: rgba(255,255,255,25); border: 1px solid rgba(255,255,255,90); padding: 6px 10px; }'
            'QLabel { color: white; }'
        )

        layout = QtWidgets.QVBoxLayout(self)
        self.infoLabel = QtWidgets.QLabel('')
        self.infoLabel.setWordWrap(True)
        layout.addWidget(self.infoLabel)

        self.listWidget = QtWidgets.QListWidget()
        self.listWidget.itemClicked.connect(self._HandleItemClicked)
        layout.addWidget(self.listWidget, 1)

        bottom_row = QtWidgets.QHBoxLayout()
        self.banListButton = QtWidgets.QPushButton('Open ban list')
        self.banListButton.clicked.connect(self._HandleBanList)
        bottom_row.addWidget(self.banListButton)
        bottom_row.addStretch(1)
        close_button = QtWidgets.QPushButton('Close')
        close_button.clicked.connect(self.close)
        bottom_row.addWidget(close_button)
        layout.addLayout(bottom_row)

    def setHostMode(self, is_host):
        self._is_host = bool(is_host)
        if self._is_host:
            self.infoLabel.setText('Online participants. Click a participant to choose kick or ban.')
        else:
            self.infoLabel.setText('Online participants.')
        self.banListButton.setVisible(self._is_host)

    def setParticipants(self, participants):
        self.listWidget.clear()
        participants = participants or []
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            role = 'Host' if participant.get('is_host') else 'Player'
            text = '%s  |  %s  |  %s' % (
                participant.get('nickname') or 'Player',
                participant.get('ip') or 'unknown',
                role,
            )
            item = QtWidgets.QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, dict(participant))
            self.listWidget.addItem(item)

    def _HandleItemClicked(self, item):
        if not self._is_host or item is None:
            return
        participant = item.data(Qt.ItemDataRole.UserRole)
        if callable(self._participant_callback):
            self._participant_callback(dict(participant or {}), self.listWidget.viewport().mapToGlobal(self.listWidget.visualItemRect(item).bottomRight()))

    def _HandleBanList(self):
        if callable(self._ban_list_callback):
            self._ban_list_callback()


class ReggieWindow(QtWidgets.QMainWindow):
    """
    Reggie main level editor window
    """

    def CreateAction(self, shortname, function, icon, text, statustext, shortcut, toggle=False):
        """
        Helper function to create an action
        """

        if icon is not None:
            act = QtGui.QAction(icon, text, self)
        else:
            act = QtGui.QAction(text, self)

        if shortcut is not None: act.setShortcut(shortcut)
        if statustext is not None: act.setStatusTip(statustext)
        if toggle:
            act.setCheckable(True)
        if function is not None: act.triggered.connect(function)

        self.actions[shortname] = act

    def __init__(self):
        """
        Editor window constructor
        """
        globals_.Initializing = True

        # Reggie Version number goes below here. 64 char max (32 if non-ascii).
        self.ReggieInfo = globals_.ReggieID

        self.ZoomLevels = [7.5, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0, 65.0, 70.0, 75.0,
                           85.0, 90.0, 95.0, 100.0, 125.0, 150.0, 175.0, 200.0, 250.0, 300.0, 350.0, 400.0]

        # add the undo stack object
        self.undoStack = UndoStack()
        self.UndoRedoInProgress = False

        # required variables
        self.UpdateFlag = False
        self.SelectionUpdateFlag = False
        self.selObj = None
        self.CurrentSelection = []
        self._pipeEntranceLinkItems = []
        self._pipeEntranceLinkSource = None
        self._pipeEntranceLinkRefreshPending = False

        # set up the window
        QtWidgets.QMainWindow.__init__(self, None)
        self.setWindowTitle('Reggie! Next Level Editor %s' % globals_.ReggieVersionShort)
        self.setWindowIcon(QtGui.QIcon('reggiedata/icon.png'))
        self.setIconSize(QtCore.QSize(16, 16))
        self.setUnifiedTitleAndToolBarOnMac(True)

        # create the level view
        self.scene = LevelScene(0, 0, 1024 * 24, 512 * 24, self)
        self.scene.setItemIndexMethod(QtWidgets.QGraphicsScene.ItemIndexMethod.NoIndex)
        self.scene.selectionChanged.connect(self.ChangeSelectionHandler)

        self.view = LevelViewWidget(self.scene, self)
        self.view.centerOn(0, 0)  # this scrolls to the top left
        self.view.PositionHover.connect(self.PositionHovered)
        self.view.XScrollBar.valueChanged.connect(self.XScrollChange)
        self.view.YScrollBar.valueChanged.connect(self.YScrollChange)
        self.view.FrameSize.connect(self.HandleWindowSizeChange)

        # done creating the window!
        self.setCentralWidget(self.view)

        # set up the clipboard stuff
        self.clipboard = None
        self.systemClipboard = QtWidgets.QApplication.clipboard()
        self.systemClipboard.dataChanged.connect(self.TrackClipboardUpdates)

        # we might have something there already, activate Paste if so
        self.TrackClipboardUpdates()

    def __init2__(self):
        """
        Finishes initialization. (fixes bugs with some widgets calling globals_.mainWindow.something before it's init'ed)
        """

        self.AutosaveTimer = QtCore.QTimer()
        self.AutosaveTimer.timeout.connect(self.Autosave)
        self.AutosaveTimer.start(20000)
        self.LevelBackupTimer = QtCore.QTimer(self)
        self.LevelBackupTimer.timeout.connect(self.LevelBackupTick)
        self.LevelBackupTimer.start(300000)
        self._GetBackupsDir()
        self.collabManager = CollaborationManager(self)
        self.collabManager.set_room_info_provider(self._BuildCollabRoomInfo)
#       self.collabManager.set_peer_intro_validator(self._ValidateCollabPeerIntro)
        self.collabManager.statusChanged.connect(self.HandleCollaborationStatus)
        self.collabManager.snapshotReceived.connect(self.HandleRemoteSnapshot)
        self.collabManager.messageReceived.connect(self.HandleRemoteMessage)
        self.collabManager.peerCountChanged.connect(self.HandleCollaborationPeerCount)
        self.collabManager.participantsChanged.connect(self.HandleCollaborationParticipantsChanged)
        self.collabManager.banListChanged.connect(self.HandleCollaborationBanListChanged)
        self.collabTimer = QtCore.QTimer(self)
        self.collabTimer.timeout.connect(self.CollaborationSyncTick)
        self.collabTimer.start(100)
        self.collabLastHash = None
        self.collabLastSentHash = None
        self.collabLastSceneSig = None
        self.collabLastLevelName = None
        self.collabOnlineCount = 0
        self.collabSceneRev = 0
        self.collabPeerLastRev = {}
        self.collabPeerLastState = {}
        self.collabAreaState = {}
        self.collabMetaRev = 0
        self.collabPeerLastMetaRev = {}
        self.collabPeerLastMetaState = {}
        self.collabAreaMetaState = {}
        self.collabSwitchingArea = False
        self.collabApplyingRemote = False
        self.collabApplyingRemoteHistory = False
        self.collabLastRemoteSender = None
        self.collabPendingSnapshot = None
        self.collabPendingMessages = collections.deque()
        self.collabHostSessionId = None
        self._collabOutOps = []
        # Rate-limit outgoing ops so we don't spam the network/UI thread while dragging.
        # 16ms ~= 60fps, keeps remote movement smooth but stable.
        self._collabOpsFlushIntervalMs = 16

        # Remote selection visualization (per-player outline for items selected by other peers).
        # We keep selection "soft": it doesn't fully sync UI selection, but remote selection can
        # steal an item (local deselect) to ensure the outline ownership transfers.
        self._collabSelectionOwnerByItem = {}      # item_id -> session_id
        self._collabSelectionItemsByOwner = {}     # session_id -> set(item_id)
        self._collabSelectionDebounce = QtCore.QTimer(self)
        self._collabSelectionDebounce.setSingleShot(True)
        self._collabSelectionDebounce.timeout.connect(self._FlushCollabSelectionBroadcast)
        self._collabLastBroadcastSelection = set()
        self._collabOutOpsTimer = QtCore.QTimer(self)
        self._collabOutOpsTimer.setSingleShot(True)
        self._collabOutOpsTimer.timeout.connect(self._FlushCollabOps)
        self._collabMetaDirty = False
        # Full meta-state is heavy; keep it as a slow fallback only.
        self._collabMetaFlushDelayMs = 350
        self._collabMetaTimer = QtCore.QTimer(self)
        self._collabMetaTimer.setSingleShot(True)
        self._collabMetaTimer.timeout.connect(self._FlushCollabMeta)
        self._zoneSpriteRefreshTimer = QtCore.QTimer(self)
        self._zoneSpriteRefreshTimer.setSingleShot(True)
        self._zoneSpriteRefreshTimer.timeout.connect(self._FlushZoneSpriteRefresh)
        self._spriteImageLoadTimer = QtCore.QTimer(self)
        self._spriteImageLoadTimer.setSingleShot(True)
        self._spriteImageLoadTimer.timeout.connect(self._ProcessSpriteImageLoadQueue)
        self._spriteImageLoadQueue = collections.deque()
        self._collabAuthoritativeAreas = set()
        self._collabAuthoritativeDueByArea = {}
        # Host authoritative full-state broadcast delay (after last edit).
        # Higher value reduces "full area" refresh frequency while dragging/editing.
        self._collabAuthoritativeSyncDelayMs = 1500
        self._collabAuthoritativeTimer = QtCore.QTimer(self)
        self._collabAuthoritativeTimer.setSingleShot(True)
        self._collabAuthoritativeTimer.timeout.connect(self._FlushHostAuthoritativeAreaSync)
        self._collabObjectById = {}
        self._collabSpriteById = {}
        self._collabHistorySeen = set()
        # Collaboration undo/redo: each peer keeps their own local undo stack.
        # Undo/redo results are propagated as delta ops through the normal
        # collaboration channel.
        self._collabSharedHistoryEnabled = False
        self._collabHistoryRev = 0
        self._collabHistoryLastAppliedRev = 0
        # Client-side pending history actions (created locally, awaiting host ack)
        self._collabPendingHistory = {}          # action_id -> UndoAction
        self._collabPendingHistoryLastId = None  # last pending action_id
        self.collabPeerNicks = {}
        self.collabPeerColors = {}
        self.collabSelfNick = str(getattr(globals_, 'CollabNickname', 'Player') or 'Player')
        self.collabSelfHighlightColor = normalize_collab_color(getattr(globals_, 'CollabHighlightColor', DEFAULT_COLLAB_HIGHLIGHT_COLOR))
        self.collabCursorDisplayMode = self._NormalizeCollabCursorDisplayMode(getattr(globals_, 'CollabCursorDisplayMode', COLLAB_CURSOR_DISPLAY_ALWAYS))
        self.collabCursorPKeyHeld = False
        self.collabRemoteCursors = {}
        self.collabCursorStaleSeconds = 1.6
        self.collabCursorBroadcastIntervalSeconds = 0.05
        self.collabCursorKeepAliveSeconds = 0.45
        self.collabLastBroadcastCursorAt = 0.0
        self.collabLastBroadcastCursorPos = None
        self._collabCursorAnimLastTick = time.monotonic()
        self._collabCursorAnimTimer = QtCore.QTimer(self)
        self._collabCursorAnimTimer.setInterval(1000 // 60)
        self._collabCursorAnimTimer.timeout.connect(self._AdvanceCollabRemoteCursors)
        self.collabParticipants = []
        self.collabWindow = None
        self.collabMonitorDialog = None
        self.collabBanListDialog = None
        self.collabLastMouseScenePos = None
        self.collabPings = []
        self.collabPingDurationMs = 2200
        self._collabPingTimer = QtCore.QTimer(self)
        self._collabPingTimer.setInterval(33)
        self._collabPingTimer.timeout.connect(self._UpdateCollabPings)
        self.collabManager.set_local_nickname(self.collabSelfNick)
        self.collabManager.set_local_highlight_color(self.collabSelfHighlightColor)
        self.collabManager.set_ban_list(setting('CollabBanList', {}))

        # Tileset editor / sync helpers
        self._tilesetEditWatcher = QtCore.QFileSystemWatcher(self)
        self._tilesetEditWatcher.fileChanged.connect(self._HandleTilesetEditorFileChanged)
        self._tilesetEditPendingPath = None
        self._tilesetEditDebounce = QtCore.QTimer(self)
        self._tilesetEditDebounce.setSingleShot(True)
        self._tilesetEditDebounce.timeout.connect(self._FlushTilesetEditorFileChanged)
        self._tilesetEditSession = None  # {'name': str, 'path': str}
        self._collabTilesetSha1ByName = {}
        self._collabTilesetSyncTimer = QtCore.QTimer(self)
        self._collabTilesetSyncTimer.setSingleShot(True)
        self._collabTilesetSyncTimer.timeout.connect(self._RequestHostTilesetsNow)
        self._collabPendingTilesetPayloads = []

        # set up actions and menus
        self.SetupActionsAndMenus()

        # set up the status bar
        self.posLabel = QtWidgets.QLabel()
        self.selectionLabel = QtWidgets.QLabel()
        self.hoverLabel = QtWidgets.QLabel()
        self.statusBar().addWidget(self.posLabel)
        self.statusBar().addWidget(self.selectionLabel)
        self.statusBar().addWidget(self.hoverLabel)
        #self.diagnostic = DiagnosticWidget()
        self.ZoomWidget = ZoomWidget()
        self.ZoomStatusWidget = ZoomStatusWidget()
        #self.statusBar().addPermanentWidget(self.diagnostic)
        self.statusBar().addPermanentWidget(self.ZoomWidget)
        self.statusBar().addPermanentWidget(self.ZoomStatusWidget)

        # create the various panels
        self.SetupDocksAndPanels()
        self.qpt_palette = None
        global QPT_AVAILABLE, QPT_INITIALIZED, _qpt_functions
        if QPT_AVAILABLE and not QPT_INITIALIZED and _qpt_functions:
            try:
                self.qpt_palette = _qpt_functions['initialize'](self)
                self.creationTabs.addTab(self.qpt_palette, GetIcon('palette'), '')
                self.creationTabs.setTabToolTip(self.creationTabs.count() - 1, 'Quick Paint')
                QPT_INITIALIZED = True
                try:
                    self._InstallQuickPaintCollabSync()
                except Exception:
                    pass
            except Exception as e:
                print(f"[QPT] Warning: Could not initialize Quick Paint Tool: {e}")
                traceback.print_exc()
                self.qpt_palette = None
                QPT_AVAILABLE = False
        self._EnsureChatWindow()

        # now get stuff ready
        loaded = False
        self.fileSavePath = None
        self._startupExitRequested = False
        startup_level_arg = None
        if len(sys.argv) > 1 and (IsNSMBLevel(sys.argv[1]) or self._IsReggieRawLevelPath(sys.argv[1])):
            startup_level_arg = sys.argv[1]

        if globals_.RestoredFromAutoSave:
            autosave_path = str(globals_.AutoSavePath or '')
            if autosave_path in ('', 'None'):
                autosave_path = '__autosave__.rgl'
            loaded = self.LoadLevel(autosave_path, True, 1)
            if not loaded:
                loaded = self.RunStartupFlow(startup_level_arg)
        else:
            loaded = self.RunStartupFlow(startup_level_arg)
        if self._startupExitRequested:
            globals_.Initializing = False
            return
        if not loaded:
            loaded = self.LoadLevel(None, False, 1)

        # call each toggle-button handler to set each feature correctly upon
        # startup
        toggleHandlers = {
            self.HandleSpritesVisibility: globals_.SpritesShown,
            self.HandleSpriteImages: globals_.SpriteImagesShown,
            self.HandleLocationsVisibility: globals_.LocationsShown,
            self.HandleCommentsVisibility: globals_.CommentsShown,
            self.HandlePathsVisibility: globals_.PathsShown,
            self.HandlePipeLinksVisibility: globals_.PipeLinksShown,
        }
        for handler in toggleHandlers:
            handler(toggleHandlers[handler])

        # let's restore the state and geometry
        # geometry: determines the main window position
        # state: determines positions of docks
        if globals_.settings.contains('MainWindowGeometry'):
            self.restoreGeometry(setting('MainWindowGeometry'))
        if globals_.settings.contains('MainWindowState'):
            self.restoreState(setting('MainWindowState'), 0)

        # Aaaaaand... initializing is done!
        globals_.Initializing = False
        self.UpdateSaveActionsForCollabMode()
    def QueueZoneSpriteRefresh(self):
        if not hasattr(self, '_zoneSpriteRefreshTimer'):
            return
        if not self._zoneSpriteRefreshTimer.isActive():
            self._zoneSpriteRefreshTimer.start(50)

    def _FlushZoneSpriteRefresh(self):
        try:
            for spr in globals_.Area.sprites:
                spr.ImageObj.positionChanged()
        except Exception:
            pass

    def _ClearSpriteImageLoadQueue(self):
        self._spriteImageLoadQueue.clear()
        if self._spriteImageLoadTimer.isActive():
            self._spriteImageLoadTimer.stop()

    def _QueueDeferredSpriteImageLoads(self):
        if globals_.Area is None:
            return

        spriteClasses = globals_.gamedef.getImageClasses()
        counts = collections.Counter()

        for spr in globals_.Area.sprites:
            if not spr.hasDeferredImageObj():
                continue
            if spr.type not in spriteClasses:
                continue
            if spr.type in SLib.SpriteImagesLoaded:
                continue

            counts[spr.type] += 1

        if not counts:
            return

        # Load common sprite types first so more items upgrade immediately.
        for type_, _count in counts.most_common():
            self._spriteImageLoadQueue.append(type_)

        if not self._spriteImageLoadTimer.isActive():
            self._spriteImageLoadTimer.start(0)

    def _ProcessSpriteImageLoadQueue(self):
        if globals_.Area is None or not globals_.SpriteImagesShown:
            self._ClearSpriteImageLoadQueue()
            return

        spriteClasses = globals_.gamedef.getImageClasses()
        deadline = time.perf_counter() + 0.012

        updated = False

        while self._spriteImageLoadQueue:
            type_ = self._spriteImageLoadQueue.popleft()
            spriteClass = spriteClasses.get(type_)

            if spriteClass is None or type_ in SLib.SpriteImagesLoaded:
                continue

            spriteClass.loadImages()
            SLib.SpriteImagesLoaded.add(type_)
            updated = True

            for spr in globals_.Area.sprites:
                if spr.type != type_ or not spr.hasDeferredImageObj():
                    continue

                spr.setImageObj(spriteClass)

                if globals_.Initializing:
                    continue

                spr.ChangingPos = True
                spr.setPos(
                    (spr.objx + spr.ImageObj.xOffset) * 1.5,
                    (spr.objy + spr.ImageObj.yOffset) * 1.5,
                )
                spr.ChangingPos = False
                spr.update()

            # Keep each slice short so the UI stays responsive.
            if time.perf_counter() >= deadline:
                break

        if updated:
            self.levelOverview.update()

        if self._spriteImageLoadQueue:
            self._spriteImageLoadTimer.start(0)

    def SetupActionsAndMenus(self):
        """
        Sets up Reggie's actions, menus and toolbars
        """
        self.RecentMenu = RecentFilesMenu()
        self.GameDefMenu = GameDefMenu()

        self.createMenubar()

    actions = {}

    def createMenubar(self):
        """
        Create actions, a menubar and a toolbar
        """

        # File
        self.CreateAction(
            'newlevel', self.HandleNewLevel, GetIcon('new'),
            globals_.trans.stringOneLine('MenuItems', 0), globals_.trans.stringOneLine('MenuItems', 1),
            QtGui.QKeySequence.StandardKey.New,
        )

        self.CreateAction(
            'openfromname', self.HandleOpenFromName, GetIcon('open'),
            globals_.trans.stringOneLine('MenuItems', 2), globals_.trans.stringOneLine('MenuItems', 3),
            QtGui.QKeySequence.StandardKey.Open,
        )

        self.CreateAction(
            'openfromfile', self.HandleOpenFromFile, GetIcon('openfromfile'),
            globals_.trans.stringOneLine('MenuItems', 4), globals_.trans.stringOneLine('MenuItems', 5),
            QtGui.QKeySequence('Ctrl+Shift+O'),
        )

        self.CreateAction(
            'openrecent', None, GetIcon('recent'),
            globals_.trans.stringOneLine('MenuItems', 6), globals_.trans.stringOneLine('MenuItems', 7),
            None,
        )

        self.CreateAction(
            'save', self.HandleSave, GetIcon('save'),
            globals_.trans.stringOneLine('MenuItems', 8), globals_.trans.stringOneLine('MenuItems', 9),
            QtGui.QKeySequence.StandardKey.Save,
        )

        self.CreateAction(
            'saveas', self.HandleSaveAs, GetIcon('saveas'),
            globals_.trans.stringOneLine('MenuItems', 10), globals_.trans.stringOneLine('MenuItems', 11),
            QtGui.QKeySequence.StandardKey.SaveAs,
        )

        self.CreateAction(
            'savecopyas', self.HandleSaveCopyAs, GetIcon('savecopyas'),
            globals_.trans.stringOneLine('MenuItems', 128), globals_.trans.stringOneLine('MenuItems', 129),
            None,
        )

        self.CreateAction(
            'metainfo', self.HandleInfo, GetIcon('info'),
            globals_.trans.stringOneLine('MenuItems', 12), globals_.trans.stringOneLine('MenuItems', 13),
            QtGui.QKeySequence('Ctrl+Alt+I'),
        )

        self.CreateAction(
            'changegamedef', None, GetIcon('game'),
            globals_.trans.stringOneLine('MenuItems', 98), globals_.trans.stringOneLine('MenuItems', 99),
            None,
        )

        self.CreateAction(
            'screenshot', self.HandleScreenshot, GetIcon('screenshot'),
            globals_.trans.stringOneLine('MenuItems', 14), globals_.trans.stringOneLine('MenuItems', 15),
            QtGui.QKeySequence('Ctrl+Alt+S'),
        )

        self.CreateAction(
            'changegamepath', self.HandleChangeGamePath, GetIcon('folderpath'),
            globals_.trans.stringOneLine('MenuItems', 16), globals_.trans.stringOneLine('MenuItems', 17),
            QtGui.QKeySequence('Ctrl+Alt+G'),
        )

        self.CreateAction(
            'preferences', self.HandlePreferences, GetIcon('settings'),
            globals_.trans.stringOneLine('MenuItems', 18), globals_.trans.stringOneLine('MenuItems', 19),
            QtGui.QKeySequence('Ctrl+Alt+P'),
        )

        self.CreateAction(
            'exit', self.HandleExit, GetIcon('delete'),
            globals_.trans.stringOneLine('MenuItems', 20), globals_.trans.stringOneLine('MenuItems', 21),
            QtGui.QKeySequence('Ctrl+Q'),
        )

        # Edit
        self.CreateAction(
            'selectall', self.SelectAll, GetIcon('selectall'),
            globals_.trans.stringOneLine('MenuItems', 22), globals_.trans.stringOneLine('MenuItems', 23),
            QtGui.QKeySequence.StandardKey.SelectAll,
        )

        self.CreateAction(
            'deselect', self.Deselect, GetIcon('deselect'),
            globals_.trans.stringOneLine('MenuItems', 24), globals_.trans.stringOneLine('MenuItems', 25),
            QtGui.QKeySequence('Ctrl+D'),
        )

        self.CreateAction(
            'undo', self.Undo, GetIcon('undo'),
            globals_.trans.stringOneLine('MenuItems', 124), globals_.trans.stringOneLine('MenuItems', 125),
            QtGui.QKeySequence.StandardKey.Undo,
        )

        self.CreateAction(
            'redo', self.Redo, GetIcon('redo'),
            globals_.trans.stringOneLine('MenuItems', 126), globals_.trans.stringOneLine('MenuItems', 127),
            QtGui.QKeySequence.StandardKey.Redo,
        )

        self.CreateAction(
            'cut', self.Cut, GetIcon('cut'),
            globals_.trans.stringOneLine('MenuItems', 26), globals_.trans.stringOneLine('MenuItems', 27),
            QtGui.QKeySequence.StandardKey.Cut,
        )

        self.CreateAction(
            'copy', self.Copy, GetIcon('copy'),
            globals_.trans.stringOneLine('MenuItems', 28), globals_.trans.stringOneLine('MenuItems', 29),
            QtGui.QKeySequence.StandardKey.Copy,
        )

        self.CreateAction(
            'paste', self.Paste, GetIcon('paste'),
            globals_.trans.stringOneLine('MenuItems', 30), globals_.trans.stringOneLine('MenuItems', 31),
            QtGui.QKeySequence.StandardKey.Paste,
        )

        self.CreateAction(
            'shiftitems', self.ShiftItems, GetIcon('move'),
            globals_.trans.stringOneLine('MenuItems', 32), globals_.trans.stringOneLine('MenuItems', 33),
            QtGui.QKeySequence('Ctrl+Shift+S'),
        )

        self.CreateAction(
            'mergelocations', self.MergeLocations, GetIcon('merge'),
            globals_.trans.stringOneLine('MenuItems', 34), globals_.trans.stringOneLine('MenuItems', 35),
            QtGui.QKeySequence('Ctrl+Shift+E'),
        )

        self.CreateAction(
            'swapobjectstilesets', self.SwapObjectsTilesets, GetIcon('swap'),
            globals_.trans.stringOneLine('MenuItems', 104), globals_.trans.stringOneLine('MenuItems', 105),
            QtGui.QKeySequence('Ctrl+Shift+L'),
        )

        self.CreateAction(
            'swapobjectstypes', self.SwapObjectsTypes, GetIcon('swap'),
            globals_.trans.stringOneLine('MenuItems', 106), globals_.trans.stringOneLine('MenuItems', 107),
            QtGui.QKeySequence('Ctrl+Shift+Y'),
        )

        self.CreateAction(
            'diagnostic', self.HandleDiagnostics, GetIcon('diagnostics'),
            globals_.trans.stringOneLine('MenuItems', 36), globals_.trans.stringOneLine('MenuItems', 37),
            QtGui.QKeySequence('Ctrl+Shift+D'),
        )

        self.CreateAction(
            'freezeobjects', self.HandleObjectsFreeze, GetIcon('objectsfreeze'),
            globals_.trans.stringOneLine('MenuItems', 38), globals_.trans.stringOneLine('MenuItems', 39),
            QtGui.QKeySequence('Ctrl+Shift+1'), True,
        )

        self.CreateAction(
            'freezesprites', self.HandleSpritesFreeze, GetIcon('spritesfreeze'),
            globals_.trans.stringOneLine('MenuItems', 40), globals_.trans.stringOneLine('MenuItems', 41),
            QtGui.QKeySequence('Ctrl+Shift+2'), True,
        )

        self.CreateAction(
            'freezeentrances', self.HandleEntrancesFreeze, GetIcon('entrancesfreeze'),
            globals_.trans.stringOneLine('MenuItems', 42), globals_.trans.stringOneLine('MenuItems', 43),
            QtGui.QKeySequence('Ctrl+Shift+3'), True,
        )

        self.CreateAction(
            'freezelocations', self.HandleLocationsFreeze, GetIcon('locationsfreeze'),
            globals_.trans.stringOneLine('MenuItems', 44), globals_.trans.stringOneLine('MenuItems', 45),
            QtGui.QKeySequence('Ctrl+Shift+4'), True,
        )

        self.CreateAction(
            'freezepaths', self.HandlePathsFreeze, GetIcon('pathsfreeze'),
            globals_.trans.stringOneLine('MenuItems', 46), globals_.trans.stringOneLine('MenuItems', 47),
            QtGui.QKeySequence('Ctrl+Shift+5'), True,
        )

        self.CreateAction(
            'freezecomments', self.HandleCommentsFreeze, GetIcon('commentsfreeze'),
            globals_.trans.stringOneLine('MenuItems', 114), globals_.trans.stringOneLine('MenuItems', 115),
            QtGui.QKeySequence('Ctrl+Shift+9'), True,
        )

        # View
        self.CreateAction(
            'showlay0', self.HandleUpdateLayer0, GetIcon('layer0'),
            globals_.trans.stringOneLine('MenuItems', 48), globals_.trans.stringOneLine('MenuItems', 49),
            QtGui.QKeySequence('Ctrl+1'), True,
        )

        self.CreateAction(
            'showlay1', self.HandleUpdateLayer1, GetIcon('layer1'),
            globals_.trans.stringOneLine('MenuItems', 50), globals_.trans.stringOneLine('MenuItems', 51),
            QtGui.QKeySequence('Ctrl+2'), True,
        )

        self.CreateAction(
            'showlay2', self.HandleUpdateLayer2, GetIcon('layer2'),
            globals_.trans.stringOneLine('MenuItems', 52), globals_.trans.stringOneLine('MenuItems', 53),
            QtGui.QKeySequence('Ctrl+3'), True,
        )

        self.CreateAction(
            'tileanim', self.HandleTilesetAnimToggle, GetIcon('animation'),
            globals_.trans.stringOneLine('MenuItems', 108), globals_.trans.stringOneLine('MenuItems', 109),
            QtGui.QKeySequence('Ctrl+7'), True,
        )

        self.CreateAction(
            'collisions', self.HandleCollisionsToggle, GetIcon('collisions'),
            globals_.trans.stringOneLine('MenuItems', 110), globals_.trans.stringOneLine('MenuItems', 111),
            QtGui.QKeySequence('Ctrl+8'), True,
        )

        self.CreateAction(
            'realview', self.HandleRealViewToggle, GetIcon('realview'),
            globals_.trans.stringOneLine('MenuItems', 118), globals_.trans.stringOneLine('MenuItems', 119),
            QtGui.QKeySequence('Ctrl+9'), True,
        )

        self.CreateAction(
            'showsprites', self.HandleSpritesVisibility, GetIcon('sprites'),
            globals_.trans.stringOneLine('MenuItems', 54), globals_.trans.stringOneLine('MenuItems', 55),
            QtGui.QKeySequence('Ctrl+4'), True,
        )

        self.CreateAction(
            'showspriteimages', self.HandleSpriteImages, GetIcon('sprites'),
            globals_.trans.stringOneLine('MenuItems', 56), globals_.trans.stringOneLine('MenuItems', 57),
            QtGui.QKeySequence('Ctrl+6'), True,
        )

        self.CreateAction(
            'showlocations', self.HandleLocationsVisibility, GetIcon('locations'),
            globals_.trans.stringOneLine('MenuItems', 58), globals_.trans.stringOneLine('MenuItems', 59),
            QtGui.QKeySequence('Ctrl+5'), True,
        )

        self.CreateAction(
            'showcomments', self.HandleCommentsVisibility, GetIcon('comments'),
            globals_.trans.stringOneLine('MenuItems', 116), globals_.trans.stringOneLine('MenuItems', 117),
            None, True,
        )

        self.CreateAction(
            'showpaths', self.HandlePathsVisibility, GetIcon('paths'),
            globals_.trans.stringOneLine('MenuItems', 130), globals_.trans.stringOneLine('MenuItems', 131),
            QtGui.QKeySequence('Ctrl+*'), True,
        )

        self.CreateAction(
            'showpipelinks', self.HandlePipeLinksVisibility, GetIcon('paths'),
            globals_.trans.stringOneLine('MenuItems', 142), globals_.trans.stringOneLine('MenuItems', 143),
            None, True,
        )

        self.CreateAction(
            'showeventlinks', self.HandleEventLinksVisibility, GetIcon('paths'),
            globals_.trans.stringOneLine('MenuItems', 144), globals_.trans.stringOneLine('MenuItems', 145),
            None, True,
        )

        self.CreateAction(
            'collabcursor_always', lambda checked=False: self.HandleCollabCursorDisplayModeChanged(COLLAB_CURSOR_DISPLAY_ALWAYS, checked), None,
            'Always display', 'Always display collaboration cursors and keep ping on P enabled',
            None, True,
        )

        self.CreateAction(
            'collabcursor_on_p', lambda checked=False: self.HandleCollabCursorDisplayModeChanged(COLLAB_CURSOR_DISPLAY_ON_P, checked), None,
            'When P is pressed', 'Show collaboration cursors while P is held and keep ping on P enabled',
            None, True,
        )

        self.CreateAction(
            'collabcursor_never', lambda checked=False: self.HandleCollabCursorDisplayModeChanged(COLLAB_CURSOR_DISPLAY_NEVER, checked), None,
            'Never', 'Never display collaboration cursors and disable ping on P',
            None, True,
        )

        self.CreateAction(
            'grid', self.HandleSwitchGrid, GetIcon('grid'),
            globals_.trans.stringOneLine('MenuItems', 60), globals_.trans.stringOneLine('MenuItems', 61),
            QtGui.QKeySequence('Ctrl+G'),
        )

        self.CreateAction(
            'uiscaling', self.HandleUIScaling, None,
            'UI Scaling...', 'Adjust UI and font scaling for better readability',
            None,
        )

        self.CreateAction(
            'zoommax', self.HandleZoomMax, GetIcon('zoommax'),
            globals_.trans.stringOneLine('MenuItems', 62), globals_.trans.stringOneLine('MenuItems', 63),
            QtGui.QKeySequence('Ctrl+PgDown'),
        )

        self.CreateAction(
            'zoomin', self.HandleZoomIn, GetIcon('zoomin'),
            globals_.trans.stringOneLine('MenuItems', 64), globals_.trans.stringOneLine('MenuItems', 65),
            QtGui.QKeySequence.StandardKey.ZoomIn,
        )

        self.CreateAction(
            'zoomactual', self.HandleZoomActual, GetIcon('zoomactual'),
            globals_.trans.stringOneLine('MenuItems', 66), globals_.trans.stringOneLine('MenuItems', 67),
            QtGui.QKeySequence('Ctrl+0'),
        )

        self.CreateAction(
            'zoomout', self.HandleZoomOut, GetIcon('zoomout'),
            globals_.trans.stringOneLine('MenuItems', 68), globals_.trans.stringOneLine('MenuItems', 69),
            QtGui.QKeySequence.StandardKey.ZoomOut,
        )

        self.CreateAction(
            'zoommin', self.HandleZoomMin, GetIcon('zoommin'),
            globals_.trans.stringOneLine('MenuItems', 70), globals_.trans.stringOneLine('MenuItems', 71),
            QtGui.QKeySequence('Ctrl+PgUp'),
        )

        # Show Overview and Show Palette are added later

        # Settings
        self.CreateAction(
            'areaoptions', self.HandleAreaOptions, GetIcon('area'),
            globals_.trans.stringOneLine('MenuItems', 72), globals_.trans.stringOneLine('MenuItems', 73),
            QtGui.QKeySequence('Ctrl+Alt+A'),
        )

        self.CreateAction(
            'zones', self.HandleZones, GetIcon('zones'),
            globals_.trans.stringOneLine('MenuItems', 74), globals_.trans.stringOneLine('MenuItems', 75),
            QtGui.QKeySequence('Ctrl+Alt+Z'),
        )

        self.CreateAction(
            'backgrounds', self.HandleBG, GetIcon('background'),
            globals_.trans.stringOneLine('MenuItems', 76), globals_.trans.stringOneLine('MenuItems', 77),
            QtGui.QKeySequence('Ctrl+Alt+B'),
        )

        self.CreateAction(
            'camprofiles', self.HandleCameraProfiles, GetIcon('camprofile'),
            globals_.trans.stringOneLine('MenuItems', 140), globals_.trans.stringOneLine('MenuItems', 141),
            QtGui.QKeySequence('Ctrl+Alt+C'),
        )

        self.CreateAction(
            'addarea', self.HandleAddNewArea, GetIcon('add'),
            globals_.trans.stringOneLine('MenuItems', 78), globals_.trans.stringOneLine('MenuItems', 79),
            QtGui.QKeySequence('Ctrl+Alt+N'),
        )

        self.CreateAction(
            'importarea', self.HandleImportArea, GetIcon('import'),
            globals_.trans.stringOneLine('MenuItems', 80), globals_.trans.stringOneLine('MenuItems', 81),
            QtGui.QKeySequence('Ctrl+Alt+O'),
        )

        self.CreateAction(
            'deletearea', self.HandleDeleteArea, GetIcon('delete'),
            globals_.trans.stringOneLine('MenuItems', 82), globals_.trans.stringOneLine('MenuItems', 83),
            QtGui.QKeySequence('Ctrl+Alt+D'),
        )

        self.CreateAction(
            'reloadgfx', self.ReloadTilesets, GetIcon('reload-tilesets'),
            globals_.trans.stringOneLine('MenuItems', 84), globals_.trans.stringOneLine('MenuItems', 85),
            QtGui.QKeySequence('Ctrl+Shift+R'),
        )

        self.CreateAction(
            'reloaddata', self.ReloadSpritedata, GetIcon('reload-spritedata'),
            globals_.trans.stringOneLine('MenuItems', 138), globals_.trans.stringOneLine('MenuItems', 139),
            # No shortcut for now...
            None
        )
        self.CreateAction(
            'collab_host', self.HandleCollabHost, None,
            'Host collaboration room', 'Start hosting a collaboration room',
            None,
        )
        self.CreateAction(
            'collab_join', self.HandleCollabJoin, None,
            'Join collaboration room', 'Join an existing collaboration room',
            None,
        )
        self.CreateAction(
            'collab_stop', self.HandleCollabStop, None,
            'Disconnect collaboration', 'Stop current collaboration session',
            None,
        )
        self.CreateAction(
            'collab_chat', self.HandleOpenCollabChat, None,
            'Open chat window', 'Show the detached collaboration chat window',
            QtGui.QKeySequence('T'),
        )
        self.CreateAction(
            'collab_monitor', self.HandleOpenCollabMonitor, None,
            'Open online monitor', 'Show online participants and moderation actions',
            None,
        )
        self.CreateAction(
            'collab_banlist', self.HandleOpenCollabBanList, None,
            'Open ban list', 'Show the collaboration IP ban list',
            None,
        )
        self.CreateAction(
            'collab_nick', self.HandleEditCollabNickname, None,
            'Change nickname', 'Edit the collaboration nickname',
            None,
        )
        self.CreateAction(
            'collab_color', self.HandleEditCollabHighlightColor, None,
            'Change highlight color', 'Choose the collaboration highlight color',
            None,
        )

        # Help actions are created later

        # Configure them
        self.actions['openrecent'].setMenu(self.RecentMenu)
        self.actions['changegamedef'].setMenu(self.GameDefMenu)

        self.actions['collisions'].setChecked(globals_.CollisionsShown)
        self.actions['realview'].setChecked(globals_.RealViewEnabled)

        self.actions['showsprites'].setChecked(globals_.SpritesShown)
        self.actions['showspriteimages'].setChecked(globals_.SpriteImagesShown)
        self.actions['showlocations'].setChecked(globals_.LocationsShown)
        self.actions['showcomments'].setChecked(globals_.CommentsShown)
        self.actions['showpaths'].setChecked(globals_.PathsShown)
        self.actions['showpipelinks'].setChecked(globals_.PipeLinksShown)
        self.actions['showeventlinks'].setChecked(globals_.EventLinksShown)
        self._UpdateCollabCursorDisplayActions()

        self.actions['freezeobjects'].setChecked(globals_.ObjectsFrozen)
        self.actions['freezesprites'].setChecked(globals_.SpritesFrozen)
        self.actions['freezeentrances'].setChecked(globals_.EntrancesFrozen )
        self.actions['freezelocations'].setChecked(globals_.LocationsFrozen)
        self.actions['freezepaths'].setChecked(globals_.PathsFrozen)
        self.actions['freezecomments'].setChecked(globals_.CommentsFrozen)

        self.actions['undo'].setEnabled(False)
        self.actions['redo'].setEnabled(False)
        self.actions['cut'].setEnabled(False)
        self.actions['copy'].setEnabled(False)
        self.actions['paste'].setEnabled(False)
        self.actions['shiftitems'].setEnabled(False)
        self.actions['mergelocations'].setEnabled(False)
        self.actions['deselect'].setEnabled(False)

        ####
        menubar = QtWidgets.QMenuBar()
        self.setMenuBar(menubar)

        fmenu = menubar.addMenu(globals_.trans.string('Menubar', 0))
        fmenu.addAction(self.actions['newlevel'])
        fmenu.addAction(self.actions['openfromname'])
        fmenu.addAction(self.actions['openfromfile'])
        fmenu.addAction(self.actions['openrecent'])
        fmenu.addSeparator()
        fmenu.addAction(self.actions['save'])
        fmenu.addAction(self.actions['saveas'])
        fmenu.addAction(self.actions['savecopyas'])
        fmenu.addAction(self.actions['metainfo'])
        fmenu.addSeparator()
        fmenu.addAction(self.actions['changegamedef'])
        fmenu.addAction(self.actions['screenshot'])
        fmenu.addAction(self.actions['changegamepath'])
        fmenu.addAction(self.actions['preferences'])
        fmenu.addSeparator()
        fmenu.addAction(self.actions['exit'])

        emenu = menubar.addMenu(globals_.trans.string('Menubar', 1))
        emenu.addAction(self.actions['selectall'])
        emenu.addAction(self.actions['deselect'])
        emenu.addSeparator()
        emenu.addAction(self.actions['undo'])
        emenu.addAction(self.actions['redo'])
        emenu.addSeparator()
        emenu.addAction(self.actions['cut'])
        emenu.addAction(self.actions['copy'])
        emenu.addAction(self.actions['paste'])
        emenu.addSeparator()
        emenu.addAction(self.actions['shiftitems'])
        emenu.addAction(self.actions['mergelocations'])
        emenu.addAction(self.actions['swapobjectstilesets'])
        emenu.addAction(self.actions['swapobjectstypes'])
        emenu.addSeparator()
        emenu.addAction(self.actions['diagnostic'])
        emenu.addSeparator()
        emenu.addAction(self.actions['freezeobjects'])
        emenu.addAction(self.actions['freezesprites'])
        emenu.addAction(self.actions['freezeentrances'])
        emenu.addAction(self.actions['freezelocations'])
        emenu.addAction(self.actions['freezepaths'])
        emenu.addAction(self.actions['freezecomments'])

        vmenu = menubar.addMenu(globals_.trans.string('Menubar', 2))
        vmenu.addAction(self.actions['showlay0'])
        vmenu.addAction(self.actions['showlay1'])
        vmenu.addAction(self.actions['showlay2'])
        vmenu.addAction(self.actions['tileanim'])
        vmenu.addAction(self.actions['collisions'])
        vmenu.addAction(self.actions['realview'])
        vmenu.addSeparator()
        vmenu.addAction(self.actions['showsprites'])
        vmenu.addAction(self.actions['showspriteimages'])
        vmenu.addAction(self.actions['showlocations'])
        vmenu.addAction(self.actions['showcomments'])
        vmenu.addAction(self.actions['showpaths'])
        vmenu.addAction(self.actions['showpipelinks'])
        vmenu.addAction(self.actions['showeventlinks'])
        collab_cursor_menu = vmenu.addMenu('Cursor display')
        collab_cursor_menu.addAction(self.actions['collabcursor_always'])
        collab_cursor_menu.addAction(self.actions['collabcursor_on_p'])
        collab_cursor_menu.addAction(self.actions['collabcursor_never'])
        vmenu.addSeparator()
        vmenu.addAction(self.actions['grid'])
        vmenu.addAction(self.actions['uiscaling'])
        vmenu.addSeparator()
        vmenu.addAction(self.actions['zoommax'])
        vmenu.addAction(self.actions['zoomin'])
        vmenu.addAction(self.actions['zoomactual'])
        vmenu.addAction(self.actions['zoomout'])
        vmenu.addAction(self.actions['zoommin'])
        vmenu.addSeparator()
        # self.levelOverviewDock.toggleViewAction() is added here later
        # so we assign it to self.vmenu
        self.vmenu = vmenu

        lmenu = menubar.addMenu(globals_.trans.string('Menubar', 3))
        lmenu.addAction(self.actions['areaoptions'])
        lmenu.addAction(self.actions['camprofiles'])
        lmenu.addAction(self.actions['zones'])
        lmenu.addAction(self.actions['backgrounds'])
        lmenu.addSeparator()
        lmenu.addAction(self.actions['addarea'])
        lmenu.addAction(self.actions['importarea'])
        lmenu.addAction(self.actions['deletearea'])
        lmenu.addSeparator()
        lmenu.addAction(self.actions['reloadgfx'])
        lmenu.addAction(self.actions['reloaddata'])

        collabmenu = menubar.addMenu('Collaboration')
        self.collabMenu = collabmenu
        collabmenu.addAction(self.actions['collab_host'])
        collabmenu.addAction(self.actions['collab_join'])
        collabmenu.addSeparator()
        collabmenu.addAction(self.actions['collab_chat'])
        collabmenu.addAction(self.actions['collab_monitor'])
        collabmenu.addAction(self.actions['collab_banlist'])
        collabmenu.addAction(self.actions['collab_nick'])
        collabmenu.addAction(self.actions['collab_color'])
        collabmenu.addSeparator()
        collabmenu.addAction(self.actions['collab_stop'])
        self.UpdateCollaborationMenuTitle()

        self.collabTopBarWidget = QtWidgets.QWidget(self)
        top_layout = QtWidgets.QHBoxLayout(self.collabTopBarWidget)
        top_layout.setContentsMargins(6, 0, 6, 0)
        top_layout.setSpacing(6)

        self.collabMonitorButton = QtWidgets.QToolButton(self.collabTopBarWidget)
        self.collabMonitorButton.setDefaultAction(self.actions['collab_monitor'])
        self.collabMonitorButton.setVisible(False)
        top_layout.addWidget(self.collabMonitorButton)

        self.collabChatButton = QtWidgets.QToolButton(self.collabTopBarWidget)
        self.collabChatButton.setDefaultAction(self.actions['collab_chat'])
        self.collabChatButton.setVisible(False)
        top_layout.addWidget(self.collabChatButton)

        self.collabOnlineLabel = QtWidgets.QLabel('Online: 0', self.collabTopBarWidget)
        self.collabOnlineLabel.setVisible(False)
        top_layout.addWidget(self.collabOnlineLabel)

        self.collabNickLabel = QtWidgets.QLabel('Nick:', self.collabTopBarWidget)
        top_layout.addWidget(self.collabNickLabel)

        self.collabNickEdit = QtWidgets.QLineEdit(self.collabTopBarWidget)
        self.collabNickEdit.setFixedWidth(140)
        self.collabNickEdit.setText(getattr(globals_, 'CollabNickname', 'Player'))
        self.collabNickEdit.editingFinished.connect(self.HandleCollabNicknameEdited)
        top_layout.addWidget(self.collabNickEdit)

        self.collabColorButton = QtWidgets.QPushButton(self.collabTopBarWidget)
        self.collabColorButton.setText(self.collabSelfHighlightColor)
        self.collabColorButton.clicked.connect(self.HandleEditCollabHighlightColor)
        top_layout.addWidget(self.collabColorButton)
        self._RefreshCollabColorButton()

        menubar.setCornerWidget(self.collabTopBarWidget, Qt.Corner.TopRightCorner)

        hmenu = menubar.addMenu(globals_.trans.string('Menubar', 4))
        self.SetupHelpMenu(hmenu)

        # create a toolbar
        self.toolbar = self.addToolBar(globals_.trans.string('Menubar', 5))
        self.toolbar.setObjectName('MainToolbar')

        # Add buttons to the toolbar
        self.addToolbarButtons()

        # Add the area combo box
        self.areaComboBox = QtWidgets.QComboBox()
        self.areaComboBox.activated.connect(self.HandleSwitchArea)
        self.toolbar.addWidget(self.areaComboBox)
        self.toolbar.addSeparator()

        self.pixelBrushButton = QtWidgets.QToolButton(self)
        self.pixelBrushButton.setText('Pixel Brush')
        self.pixelBrushButton.setToolTip('Paint objects cell by cell with the right mouse button')
        self.pixelBrushButton.setCheckable(True)
        self.pixelBrushButton.toggled.connect(self.HandlePixelBrushToggled)
        self.toolbar.addWidget(self.pixelBrushButton)

    def SetupHelpMenu(self, menu=None):
        """
        Creates the help menu.
        """
        self.CreateAction('infobox', self.AboutBox, GetIcon('reggie'), globals_.trans.stringOneLine('MenuItems', 86),
                          globals_.trans.string('MenuItems', 87), QtGui.QKeySequence('Ctrl+Shift+I'))
        self.CreateAction('helpbox', self.HelpBox, GetIcon('contents'), globals_.trans.stringOneLine('MenuItems', 88),
                          globals_.trans.string('MenuItems', 89), QtGui.QKeySequence('Ctrl+Shift+H'))
        self.CreateAction('tipbox', self.TipBox, GetIcon('tips'), globals_.trans.stringOneLine('MenuItems', 90),
                          globals_.trans.string('MenuItems', 91), QtGui.QKeySequence('Ctrl+Shift+T'))
        self.CreateAction('aboutqt', QtWidgets.QApplication.instance().aboutQt, GetIcon('qt'), globals_.trans.stringOneLine('MenuItems', 92),
                          globals_.trans.string('MenuItems', 93), QtGui.QKeySequence('Ctrl+Shift+Q'))

        if menu is None:
            menu = QtWidgets.QMenu(globals_.trans.string('Menubar', 4))
        menu.addAction(self.actions['infobox'])
        menu.addAction(self.actions['helpbox'])
        menu.addAction(self.actions['tipbox'])
        menu.addSeparator()
        menu.addAction(self.actions['aboutqt'])
        menu.addSeparator()

        if lib_versions["nsmblib-updated"] is not None:
            value = str(lib_versions["nsmblib-updated"])
            version = int(value[:4]), int(value[4:6]), int(value[6:8]), int(value[8:10])
            nsmblib_info_text = "Using NSMBLib Updated %d.%d.%d.%d" % version
        elif lib_versions["nsmblib"] is not None:
            nsmblib_info_text = "Using NSMBLib %d" % lib_versions["nsmblib"]
        else:
            nsmblib_info_text = "Not using NSMBLib"

        if lib_versions["cython"] is not None:
            cython_info_text = "Using Cython %s" % lib_versions["cython"]
        else:
            cython_info_text = "Not using Cython"

        menu.addAction("Using Python %d.%d.%d" % sys.version_info[:3]).setEnabled(False)
        menu.addAction("Using PyQt %s" % QtCore.PYQT_VERSION_STR).setEnabled(False)
        menu.addAction("Using Qt %s" % QtCore.QT_VERSION_STR).setEnabled(False)
        menu.addAction(cython_info_text).setEnabled(False)
        menu.addAction(nsmblib_info_text).setEnabled(False)

        return menu

    def HandlePixelBrushToggled(self, checked):
        if hasattr(self, 'hoverLabel'):
            if checked:
                self.hoverLabel.setText('Pixel Brush enabled')
            else:
                self.hoverLabel.setText('Pixel Brush disabled')

    def IsPixelBrushEnabled(self):
        return hasattr(self, 'pixelBrushButton') and self.pixelBrushButton.isChecked()

    def ShouldUsePixelBrush(self):
        return self.IsPixelBrushEnabled() and 0 <= globals_.CurrentPaintType < 4 and globals_.CurrentObject != -1

    def GetPixelBrushObjectSize(self, tileset, object_num):
        width = 1
        height = 1
        try:
            tile_def = globals_.ObjectDefinitions[tileset][object_num]
        except Exception:
            tile_def = None

        if tile_def is not None:
            try:
                width = max(1, int(getattr(tile_def, 'width', 1) or 1))
            except Exception:
                width = 1
            try:
                height = max(1, int(getattr(tile_def, 'height', 1) or 1))
            except Exception:
                height = 1

        return width, height

    def _BuildPixelBrushMergePlan(self, positions):
        remaining = set(positions)
        plan = []

        while remaining:
            start_x, start_y = min(remaining, key=lambda pos: (pos[1], pos[0]))

            width = 1
            while (start_x + width, start_y) in remaining:
                width += 1

            height = 1
            while True:
                next_y = start_y + height
                row = [(x, next_y) for x in range(start_x, start_x + width)]
                if all(pos in remaining for pos in row):
                    height += 1
                else:
                    break

            for y in range(start_y, start_y + height):
                for x in range(start_x, start_x + width):
                    remaining.discard((x, y))

            plan.append({
                'x': int(start_x),
                'y': int(start_y),
                'w': int(width),
                'h': int(height),
            })

        return plan

    def FinalizePixelBrushStroke(self, stroke):
        objects = stroke.get('objects', [])
        live_objects = []
        for obj in objects:
            if isinstance(obj, ObjectItem) and obj.scene() is not None:
                live_objects.append(obj)

        if not live_objects:
            return tuple()

        footprint = tuple(stroke.get('footprint', (1, 1)))
        if footprint != (1, 1):
            return tuple(live_objects)

        positions = set()
        for obj in live_objects:
            if obj.width != 1 or obj.height != 1:
                return tuple(live_objects)
            positions.add((int(obj.objx), int(obj.objy)))

        if len(positions) <= 1:
            return tuple(live_objects)

        plan = self._BuildPixelBrushMergePlan(positions)
        if len(plan) >= len(live_objects):
            return tuple(live_objects)

        for obj in live_objects:
            try:
                self._CollabEnsureItemId(obj)
            except Exception:
                pass

        for obj in live_objects:
            try:
                obj.delete()
            except Exception:
                pass
            try:
                self.scene.removeItem(obj)
            except Exception:
                pass

        created = []
        for spec in plan:
            obj = self.CreateObject(
                int(stroke['tileset']),
                int(stroke['type']),
                int(stroke['layer']),
                int(spec['x']),
                int(spec['y']),
                int(spec['w']),
                int(spec['h']),
                add_to_scene=True,
                record_undo=False,
            )
            if obj is not None:
                created.append(obj)

        if not created:
            return tuple()

        try:
            self.levelOverview.update()
        except Exception:
            pass

        return tuple(created)

    def HandleCollabNicknameEdited(self):
        nick = ''
        if hasattr(self, 'collabNickEdit'):
            nick = str(self.collabNickEdit.text() or '').strip()
        if not nick:
            nick = 'Player'
            if hasattr(self, 'collabNickEdit'):
                self.collabNickEdit.setText(nick)
        self.SetCollabNickname(nick, broadcast=True)

    def _RefreshCollabColorButton(self):
        if not hasattr(self, 'collabColorButton'):
            return
        color = normalize_collab_color(getattr(self, 'collabSelfHighlightColor', DEFAULT_COLLAB_HIGHLIGHT_COLOR))
        self.collabColorButton.setText(color)
        self.collabColorButton.setStyleSheet(collab_color_button_stylesheet(color))

    def _ChooseCollabHighlightColor(self, initial=None, parent=None):
        parent = parent if parent is not None else self
        chosen = QtWidgets.QColorDialog.getColor(
            collab_qcolor(initial or getattr(self, 'collabSelfHighlightColor', DEFAULT_COLLAB_HIGHLIGHT_COLOR)),
            parent,
            'Choose highlight color',
        )
        if not chosen.isValid():
            return None
        return normalize_collab_color(chosen)

    def _PromptCollabIdentity(self, title='Collaboration identity'):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setModal(True)
        dlg.resize(420, 120)

        layout = QtWidgets.QVBoxLayout(dlg)
        form = QtWidgets.QFormLayout()
        nick_edit = QtWidgets.QLineEdit(str(getattr(self, 'collabSelfNick', getattr(globals_, 'CollabNickname', 'Player')) or 'Player'))
        nick_edit.setMaxLength(32)
        color_value = {'value': normalize_collab_color(getattr(self, 'collabSelfHighlightColor', DEFAULT_COLLAB_HIGHLIGHT_COLOR))}
        color_button = QtWidgets.QPushButton(color_value['value'])
        color_button.setStyleSheet(collab_color_button_stylesheet(color_value['value']))

        def choose_color():
            chosen = self._ChooseCollabHighlightColor(color_value['value'], dlg)
            if not chosen:
                return
            color_value['value'] = chosen
            color_button.setText(chosen)
            color_button.setStyleSheet(collab_color_button_stylesheet(chosen))

        color_button.clicked.connect(choose_color)

        nick_row = QtWidgets.QHBoxLayout()
        nick_row.setContentsMargins(0, 0, 0, 0)
        nick_row.setSpacing(6)
        nick_row.addWidget(nick_edit, 1)
        nick_row.addWidget(color_button)
        form.addRow('Nickname:', nick_row)
        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None, None, False
        return str(nick_edit.text() or '').strip() or 'Player', color_value['value'], True

    def HandleEditCollabNickname(self):
        nick, color, ok = self._PromptCollabIdentity('Collaboration identity')
        if not ok:
            return
        self.SetCollabHighlightColor(color, broadcast=False)
        self.SetCollabNickname(nick, broadcast=True)

    def SetCollabNickname(self, nick, broadcast=True):
        nick = str(nick or '').strip()
        if not nick:
            nick = 'Player'
        self.collabSelfNick = nick
        globals_.CollabNickname = nick
        try:
            setSetting('CollabNickname', nick)
        except Exception:
            pass
        if hasattr(self, 'collabNickEdit') and self.collabNickEdit.text() != nick:
            self.collabNickEdit.setText(nick)
        if hasattr(self, 'collabManager'):
            try:
                self.collabManager.set_local_nickname(nick)
            except Exception:
                pass
        self._CollabSetPeerNick(getattr(self.collabManager, 'session_id', ''), nick)
        self._RefreshCollabUi()
        if broadcast and self._CollabEnabled():
            self._BroadcastCollabNick()

    def HandleEditCollabHighlightColor(self):
        chosen = self._ChooseCollabHighlightColor()
        if not chosen:
            return
        self.SetCollabHighlightColor(chosen, broadcast=True)

    def SetCollabHighlightColor(self, color, broadcast=True):
        color = normalize_collab_color(color)
        self.collabSelfHighlightColor = color
        globals_.CollabHighlightColor = color
        try:
            setSetting('CollabHighlightColor', color)
        except Exception:
            pass
        self._RefreshCollabColorButton()
        if hasattr(self, 'collabManager'):
            try:
                self.collabManager.set_local_highlight_color(color)
            except Exception:
                pass
        self._CollabSetPeerColor(getattr(self.collabManager, 'session_id', ''), color)
        try:
            if hasattr(self, 'view') and self.view is not None:
                self.view.viewport().update()
        except Exception:
            pass
        if broadcast and self._CollabEnabled():
            self._BroadcastCollabNick()

    def _BroadcastCollabNick(self):
        if not self._CollabEnabled():
            return
        try:
            self.collabManager.broadcast_message('nick', {
                'nick': self.collabSelfNick,
                'color': self.collabSelfHighlightColor,
            })
        except Exception:
            pass
        self._CollabSetPeerNick(getattr(self.collabManager, 'session_id', ''), self.collabSelfNick)
        self._CollabSetPeerColor(getattr(self.collabManager, 'session_id', ''), self.collabSelfHighlightColor)

    def _CollabSetPeerNick(self, session_id, nick):
        sid = str(session_id or '')
        if not sid:
            return
        nick = str(nick or '').strip()
        if not nick:
            return
        if not hasattr(self, 'collabPeerNicks'):
            self.collabPeerNicks = {}
        self.collabPeerNicks[sid] = nick

    def _CollabSetPeerColor(self, session_id, color):
        sid = str(session_id or '')
        if not sid:
            return
        if not hasattr(self, 'collabPeerColors'):
            self.collabPeerColors = {}
        self.collabPeerColors[sid] = normalize_collab_color(color)

    def _CollabPeerColor(self, session_id):
        sid = str(session_id or '')
        if not sid:
            return DEFAULT_COLLAB_HIGHLIGHT_COLOR
        if hasattr(self, 'collabManager') and sid == str(getattr(self.collabManager, 'session_id', '') or ''):
            return normalize_collab_color(getattr(self, 'collabSelfHighlightColor', DEFAULT_COLLAB_HIGHLIGHT_COLOR))
        color = None
        if hasattr(self, 'collabPeerColors'):
            color = self.collabPeerColors.get(sid)
        return normalize_collab_color(color)

    def _CollabPeerDisplayName(self, session_id):
        sid = str(session_id or '')
        if not sid:
            return 'Unknown'
        if hasattr(self, 'collabManager') and sid == str(getattr(self.collabManager, 'session_id', '') or ''):
            return str(getattr(self, 'collabSelfNick', 'Player') or 'Player')
        nick = None
        if hasattr(self, 'collabPeerNicks'):
            nick = self.collabPeerNicks.get(sid)
        if nick:
            return nick
        return sid[:8]

    def _NormalizeCollabCursorDisplayMode(self, mode):
        mode = str(mode or '').strip().lower()
        if mode not in COLLAB_CURSOR_DISPLAY_MODES:
            return COLLAB_CURSOR_DISPLAY_ALWAYS
        return mode

    def _UpdateCollabCursorDisplayActions(self):
        mode = self._NormalizeCollabCursorDisplayMode(getattr(self, 'collabCursorDisplayMode', COLLAB_CURSOR_DISPLAY_ALWAYS))
        mapping = (
            ('collabcursor_always', COLLAB_CURSOR_DISPLAY_ALWAYS),
            ('collabcursor_on_p', COLLAB_CURSOR_DISPLAY_ON_P),
            ('collabcursor_never', COLLAB_CURSOR_DISPLAY_NEVER),
        )
        for action_name, action_mode in mapping:
            action = self.actions.get(action_name)
            if action is None:
                continue
            action.blockSignals(True)
            action.setChecked(mode == action_mode)
            action.blockSignals(False)

    def _ShouldDisplayCollabCursors(self):
        mode = self._NormalizeCollabCursorDisplayMode(getattr(self, 'collabCursorDisplayMode', COLLAB_CURSOR_DISPLAY_ALWAYS))
        if mode == COLLAB_CURSOR_DISPLAY_NEVER:
            return False
        if mode == COLLAB_CURSOR_DISPLAY_ON_P:
            return bool(getattr(self, 'collabCursorPKeyHeld', False))
        return True

    def HandleCollabCursorDisplayModeChanged(self, mode, checked=False):
        mode = self._NormalizeCollabCursorDisplayMode(mode)
        if not checked and mode == getattr(self, 'collabCursorDisplayMode', COLLAB_CURSOR_DISPLAY_ALWAYS):
            self._UpdateCollabCursorDisplayActions()
            return

        self.collabCursorDisplayMode = mode
        globals_.CollabCursorDisplayMode = mode
        if mode != COLLAB_CURSOR_DISPLAY_ON_P:
            self.collabCursorPKeyHeld = False
        if mode == COLLAB_CURSOR_DISPLAY_NEVER:
            self.collabPings = []
            try:
                self._RefreshCollabPingTimer()
            except Exception:
                pass
        try:
            setSetting('CollabCursorDisplayMode', mode)
        except Exception:
            pass
        self._UpdateCollabCursorDisplayActions()
        try:
            if hasattr(self, 'view') and self.view is not None:
                self.view.viewport().update()
        except Exception:
            pass

    def _RefreshCollabUi(self):
        count = 0
        if hasattr(self, 'collabParticipants') and self.collabParticipants:
            count = len(self.collabParticipants)
        elif hasattr(self, 'collabOnlineCount'):
            count = int(self.collabOnlineCount or 0)
        collab_active = hasattr(self, 'collabManager') and self.collabManager.mode is not None

        if hasattr(self, 'collabOnlineLabel'):
            self.collabOnlineLabel.setText('Online: %d' % count)
            self.collabOnlineLabel.setVisible(collab_active)
        if hasattr(self, 'collabMonitorButton'):
            self.collabMonitorButton.setVisible(collab_active)
        if hasattr(self, 'collabChatButton'):
            self.collabChatButton.setVisible(collab_active)
        self._RefreshCollabColorButton()
        self.UpdateCollaborationMenuTitle()
        self._UpdateChatOverlayText()
        self._ClampChatOverlay()

        if hasattr(self, 'collabMonitorDialog') and self.collabMonitorDialog is not None:
            self.collabMonitorDialog.setHostMode(hasattr(self, 'collabManager') and self.collabManager.mode == "host")
            self.collabMonitorDialog.setParticipants(self.collabParticipants)
        if hasattr(self, 'collabBanListDialog') and self.collabBanListDialog is not None:
            self.collabBanListDialog.setBanList(self.collabManager.get_ban_list())

    def _AddCollabToolbarInfo(self, menu, text):
        label = QtWidgets.QLabel(str(text), menu)
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        label.setStyleSheet(
            'padding: 4px 10px;'
            'color: palette(window-text);'
            'background: transparent;'
        )
        action = QtWidgets.QWidgetAction(menu)
        action.setDefaultWidget(label)
        menu.addAction(action)
        return action

    def _PopulateCollabToolbarMenu(self):
        if not hasattr(self, 'collabToolbarMenu'):
            return
        menu = self.collabToolbarMenu
        menu.clear()

        mode = getattr(self.collabManager, 'mode', None) if hasattr(self, 'collabManager') else None
        mode_text = 'offline' if mode is None else str(mode)
        self._AddCollabToolbarInfo(menu, 'Mode: %s' % mode_text)
        self._AddCollabToolbarInfo(menu, 'Nickname: %s' % str(getattr(self, 'collabSelfNick', 'Player') or 'Player'))

        menu.addSeparator()
        self._AddCollabToolbarInfo(menu, 'Online: %d' % len(self.collabParticipants or []))

        if not self.collabParticipants:
            self._AddCollabToolbarInfo(menu, 'No peers')
        else:
            for participant in self.collabParticipants:
                role = 'Host' if participant.get('is_host') else 'Player'
                self._AddCollabToolbarInfo(menu, '%s | %s | %s' % (
                    participant.get('nickname') or 'Player',
                    participant.get('ip') or 'unknown',
                    role,
                ))

        menu.addSeparator()
        if 'collab_host' in self.actions:
            menu.addAction(self.actions['collab_host'])
        if 'collab_join' in self.actions:
            menu.addAction(self.actions['collab_join'])
        if 'collab_chat' in self.actions:
            menu.addAction(self.actions['collab_chat'])
        if 'collab_monitor' in self.actions:
            menu.addAction(self.actions['collab_monitor'])
        if 'collab_banlist' in self.actions:
            menu.addAction(self.actions['collab_banlist'])
        if 'collab_nick' in self.actions:
            menu.addAction(self.actions['collab_nick'])
        if 'collab_color' in self.actions:
            menu.addAction(self.actions['collab_color'])
        if 'collab_stop' in self.actions:
            menu.addAction(self.actions['collab_stop'])

    def _EnsureChatWindow(self):
        if hasattr(self, 'collabWindow') and self.collabWindow is not None:
            try:
                self.collabWindow.setAutoHideDelay(self._GetCollabChatAutoHideMs())
            except Exception:
                pass
            return
        self.collabWindow = ChatWindow(self, send_callback=self.HandleCollabChatSend)
        self.collabWindow.setWindowTitle('Collaboration Chat')
        try:
            self.collabWindow.setAutoHideDelay(self._GetCollabChatAutoHideMs())
        except Exception:
            pass
        self._UpdateChatEnabled()
        self._UpdateChatOverlayText()
        self._ClampChatOverlay()

    def _GetCollabChatAutoHideMs(self):
        try:
            value = int(setting('CollabChatHideDelayMs', 4500) or 4500)
        except Exception:
            value = 4500
        return max(0, value)

    def _RememberLastOpenedLevel(self, path):
        path = str(path or '').strip()
        if not path:
            return
        try:
            setSetting('LastLevel', path)
        except Exception:
            pass
        try:
            globals_.gamedef.SetLastLevel(path)
        except Exception:
            pass

    def _ClampChatOverlay(self):
        if not hasattr(self, 'collabWindow') or self.collabWindow is None:
            return
        if self.isMinimized():
            self.collabWindow.hide()
            return
        if self.collabWindow.parentWidget() is not self:
            self.collabWindow.setParent(self)
        if not self.isVisible():
            return
        self.collabWindow.adjustSize()
        margin = 12
        status_height = self.statusBar().height() if self.statusBar() is not None else 0
        height = max(
            int(self.collabWindow.height() or 0),
            int(self.collabWindow.sizeHint().height() or 0),
            int(getattr(self.collabWindow, 'panel', self.collabWindow).sizeHint().height() or 0),
        )
        local_pos = QtCore.QPoint(
            margin,
            max(margin, self.height() - status_height - height - margin),
        )
        global_pos = self.mapToGlobal(local_pos)
        self.collabWindow.move(global_pos)
        if self.collabWindow.isVisible():
            self.collabWindow.raise_()

    def _UpdateChatOverlayText(self):
        if not hasattr(self, 'collabWindow') or self.collabWindow is None:
            return
        level_name = str(getattr(self, 'fileTitle', '') or 'Untitled level')
        area = getattr(globals_, 'Area', None)
        area_num = int(getattr(area, 'areanum', 1) or 1) if area is not None else 1
        mode = getattr(self.collabManager, 'mode', None) if hasattr(self, 'collabManager') else None
        mode_text = 'offline' if mode is None else str(mode)
        self.collabWindow.setLevelText('Level: %s | Area %d | %s' % (level_name, area_num, mode_text))

    def _UpdateChatEnabled(self):
        if not hasattr(self, 'collabWindow') or self.collabWindow is None:
            return
        try:
            self.collabWindow.input.setEnabled(self._CollabEnabled())
            self.collabWindow.input.setPlaceholderText('Enter to send...' if self._CollabEnabled() else 'Connect to collaboration to chat...')
            self._UpdateChatOverlayText()
        except Exception:
            pass

    def _ChatAddLine(self, text):
        self._EnsureChatWindow()
        try:
            self.collabWindow.addLine(text)
        except Exception:
            pass
        self._ClampChatOverlay()

    def HandleCollabChatSend(self, text):
        nick = str(getattr(self, 'collabSelfNick', getattr(globals_, 'CollabNickname', 'Player')) or 'Player')
        line = '%s: %s' % (nick, str(text))
        self._ChatAddLine(line)

        if not self._CollabEnabled():
            return
        try:
            self.collabManager.broadcast_message('chat', {'nick': nick, 'text': str(text)})
        except Exception:
            pass

    def _CurrentCollabPingScenePos(self):
        if not hasattr(self, 'view') or self.view is None:
            return None
        try:
            local_pos = self.view.viewport().mapFromGlobal(QtGui.QCursor.pos())
            if self.view.viewport().rect().contains(local_pos):
                scene_pos = self.view.mapToScene(local_pos)
                return QtCore.QPointF(float(scene_pos.x()), float(scene_pos.y()))
        except Exception:
            pass
        if self.collabLastMouseScenePos is not None:
            return QtCore.QPointF(self.collabLastMouseScenePos)
        try:
            scene_pos = self.view.mapToScene(self.view.viewport().rect().center())
            return QtCore.QPointF(float(scene_pos.x()), float(scene_pos.y()))
        except Exception:
            return None

    def _MaybeBroadcastCollabCursorState(self, scene_pos=None, force=False):
        if not self._CollabEnabled() or globals_.Area is None:
            return
        if scene_pos is None:
            scene_pos = self._CurrentCollabPingScenePos()
        if scene_pos is None:
            return
        scene_pos = QtCore.QPointF(float(scene_pos.x()), float(scene_pos.y()))
        now = time.monotonic()
        last_pos = getattr(self, 'collabLastBroadcastCursorPos', None)
        moved_far_enough = True
        if last_pos is not None:
            moved_far_enough = math.hypot(scene_pos.x() - last_pos.x(), scene_pos.y() - last_pos.y()) >= 6.0
        elapsed = now - float(getattr(self, 'collabLastBroadcastCursorAt', 0.0) or 0.0)
        if not force and not moved_far_enough and elapsed < float(getattr(self, 'collabCursorKeepAliveSeconds', 0.45) or 0.45):
            return
        if not force and elapsed < float(getattr(self, 'collabCursorBroadcastIntervalSeconds', 0.05) or 0.05):
            return

        self.collabLastBroadcastCursorAt = now
        self.collabLastBroadcastCursorPos = QtCore.QPointF(scene_pos)
        try:
            self.collabManager.broadcast_message('cursor_state', {
                'nick': str(getattr(self, 'collabSelfNick', getattr(globals_, 'CollabNickname', 'Player')) or 'Player'),
                'color': getattr(self, 'collabSelfHighlightColor', DEFAULT_COLLAB_HIGHLIGHT_COLOR),
                'x': float(scene_pos.x()),
                'y': float(scene_pos.y()),
                'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
                'level_name': self._CollabCurrentLevelName(),
            })
        except Exception:
            pass

    def _UpdateRemoteCursorState(self, sender, payload):
        if globals_.Area is None:
            return
        try:
            scene_pos = QtCore.QPointF(float(payload.get('x', 0.0)), float(payload.get('y', 0.0)))
        except Exception:
            return

        sid = str(sender or '')
        if not sid:
            return

        nick = str(payload.get('nick') or '').strip()
        if nick:
            self._CollabSetPeerNick(sid, nick)
        self._CollabSetPeerColor(sid, payload.get('color'))

        try:
            area_num = int(payload.get('area_num', 0) or 0)
        except Exception:
            area_num = 0
        level_name = str(payload.get('level_name') or '')
        now = time.monotonic()

        cursor = self.collabRemoteCursors.get(sid)
        if cursor is None:
            cursor = {}
            self.collabRemoteCursors[sid] = cursor

        reinitialize = (
            not cursor
            or cursor.get('area_num') != area_num
            or str(cursor.get('level_name') or '') != level_name
            or (now - float(cursor.get('last_seen', 0.0) or 0.0)) > float(getattr(self, 'collabCursorStaleSeconds', 1.6) or 1.6)
        )

        cursor['area_num'] = area_num
        cursor['level_name'] = level_name
        cursor['nick'] = nick if nick else self._CollabPeerDisplayName(sid)
        cursor['color'] = normalize_collab_color(payload.get('color') or self._CollabPeerColor(sid))
        cursor['target_x'] = float(scene_pos.x())
        cursor['target_y'] = float(scene_pos.y())
        cursor['last_seen'] = now
        if reinitialize:
            cursor['render_x'] = float(scene_pos.x())
            cursor['render_y'] = float(scene_pos.y())

        self._collabCursorAnimLastTick = now
        if not self._collabCursorAnimTimer.isActive():
            self._collabCursorAnimTimer.start()
        try:
            if hasattr(self, 'view') and self.view is not None:
                self.view.viewport().update()
        except Exception:
            pass

    def _AdvanceCollabRemoteCursors(self):
        now = time.monotonic()
        dt = max(0.001, min(0.1, now - float(getattr(self, '_collabCursorAnimLastTick', now) or now)))
        self._collabCursorAnimLastTick = now
        follow = 1.0 - math.pow(0.12, dt * 60.0)
        stale_after = float(getattr(self, 'collabCursorStaleSeconds', 1.6) or 1.6)

        changed = False
        alive = False
        for sid, cursor in list(getattr(self, 'collabRemoteCursors', {}).items()):
            last_seen = float(cursor.get('last_seen', 0.0) or 0.0)
            if (now - last_seen) > stale_after:
                del self.collabRemoteCursors[sid]
                changed = True
                continue

            alive = True
            render_x = float(cursor.get('render_x', cursor.get('target_x', 0.0)) or 0.0)
            render_y = float(cursor.get('render_y', cursor.get('target_y', 0.0)) or 0.0)
            target_x = float(cursor.get('target_x', render_x) or render_x)
            target_y = float(cursor.get('target_y', render_y) or render_y)
            dx = target_x - render_x
            dy = target_y - render_y
            if abs(dx) <= 0.15 and abs(dy) <= 0.15:
                new_x = target_x
                new_y = target_y
            else:
                new_x = render_x + (dx * follow)
                new_y = render_y + (dy * follow)
            if new_x != render_x or new_y != render_y:
                cursor['render_x'] = new_x
                cursor['render_y'] = new_y
                changed = True

        if not alive:
            self._collabCursorAnimTimer.stop()

        if changed and hasattr(self, 'view') and self.view is not None:
            try:
                self.view.viewport().update()
            except Exception:
                pass

    def _CollabCursorMatchesCurrentContext(self, cursor):
        if globals_.Area is None:
            return False
        try:
            area_num = int(cursor.get('area_num', 0) or 0)
        except Exception:
            area_num = 0
        if area_num and area_num != int(getattr(globals_.Area, 'areanum', 0) or 0):
            return False
        level_name = str(cursor.get('level_name') or '')
        return self._CollabMatchesLevelName(level_name)

    def _AddCollabPing(self, scene_pos, nick, sender_id='', color=None):
        if scene_pos is None:
            return
        now = time.monotonic()
        ping = {
            'x': float(scene_pos.x()),
            'y': float(scene_pos.y()),
            'nick': str(nick or 'Player'),
            'sender_id': str(sender_id or ''),
            'color': normalize_collab_color(color or self._CollabPeerColor(sender_id)),
            'created_at': now,
            'expires_at': now + (float(self.collabPingDurationMs) / 1000.0),
        }
        self.collabPings.append(ping)
        self._RefreshCollabPingTimer()
        try:
            self.view.viewport().update()
        except Exception:
            pass

    def _RefreshCollabPingTimer(self):
        self.collabPings = [ping for ping in self.collabPings if ping.get('expires_at', 0.0) > time.monotonic()]
        if self.collabPings:
            if not self._collabPingTimer.isActive():
                self._collabPingTimer.start()
        elif self._collabPingTimer.isActive():
            self._collabPingTimer.stop()

    def _UpdateCollabPings(self):
        before = len(self.collabPings)
        self._RefreshCollabPingTimer()
        if before or self.collabPings:
            try:
                self.view.viewport().update()
            except Exception:
                pass

    def HandleCollabPingShortcut(self):
        if self._NormalizeCollabCursorDisplayMode(getattr(self, 'collabCursorDisplayMode', COLLAB_CURSOR_DISPLAY_ALWAYS)) == COLLAB_CURSOR_DISPLAY_NEVER:
            return
        if hasattr(self, 'qpt_palette') and self.qpt_palette and hasattr(self, 'creationTabs'):
            for i in range(self.creationTabs.count()):
                if self.creationTabs.widget(i) == self.qpt_palette:
                    if self.creationTabs.currentIndex() != i:
                        self.creationTabs.setCurrentIndex(i)
                        return
                    break
        scene_pos = self._CurrentCollabPingScenePos()
        if scene_pos is None:
            return
        nick = str(getattr(self, 'collabSelfNick', getattr(globals_, 'CollabNickname', 'Player')) or 'Player')
        self._AddCollabPing(scene_pos, nick, getattr(self.collabManager, 'session_id', ''), self.collabSelfHighlightColor)
        if not self._CollabEnabled():
            return
        try:
            self.collabManager.broadcast_message('ping', {
                'nick': nick,
                'color': self.collabSelfHighlightColor,
                'x': float(scene_pos.x()),
                'y': float(scene_pos.y()),
                'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
                'level_name': self._CollabCurrentLevelName(),
            })
        except Exception:
            pass

    def DrawCollabRemoteCursors(self, view, painter):
        if not self._ShouldDisplayCollabCursors():
            return
        if not getattr(self, 'collabRemoteCursors', None):
            return

        viewport_rect = view.viewport().rect()
        font = painter.font()
        font.setBold(True)
        margin = 18.0

        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
        painter.setFont(font)

        for sid, cursor in list(self.collabRemoteCursors.items()):
            if not self._CollabCursorMatchesCurrentContext(cursor):
                continue
            scene_point = QtCore.QPointF(
                float(cursor.get('render_x', cursor.get('target_x', 0.0)) or 0.0),
                float(cursor.get('render_y', cursor.get('target_y', 0.0)) or 0.0),
            )
            target = QtCore.QPointF(view.mapFromScene(scene_point))
            draw_x = min(max(float(target.x()), margin), max(margin, viewport_rect.width() - margin))
            draw_y = min(max(float(target.y()), margin), max(margin, viewport_rect.height() - margin))
            draw_point = QtCore.QPointF(draw_x, draw_y)

            color = collab_qcolor(cursor.get('color'), 240)
            fill = collab_qcolor(cursor.get('color'), 90)
            shadow = QtGui.QColor(0, 0, 0, 170)
            nick = str(cursor.get('nick') or self._CollabPeerDisplayName(sid))

            pointer = QtGui.QPolygonF((
                QtCore.QPointF(0, 0),
                QtCore.QPointF(0, 18),
                QtCore.QPointF(4, 14),
                QtCore.QPointF(8, 24),
                QtCore.QPointF(12, 22),
                QtCore.QPointF(9, 12),
                QtCore.QPointF(17, 12),
            ))

            painter.save()
            painter.translate(draw_point + QtCore.QPointF(1.5, 1.5))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(shadow)
            painter.drawPolygon(pointer)
            painter.restore()

            painter.save()
            painter.translate(draw_point)
            painter.setPen(QtGui.QPen(color, 1.6))
            painter.setBrush(fill)
            painter.drawPolygon(pointer)
            painter.restore()

            metrics = painter.fontMetrics()
            label_width = max(56, metrics.horizontalAdvance(nick) + 14)
            label_rect = QtCore.QRectF(draw_point.x() - (label_width / 2.0), draw_point.y() - 30.0, label_width, 20.0)
            painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 170), 1))
            painter.setBrush(QtGui.QColor(20, 20, 20, 130))
            painter.drawRoundedRect(label_rect, 7, 7)
            painter.setPen(color)
            painter.drawText(label_rect, QtCore.Qt.AlignmentFlag.AlignCenter, nick)

        painter.restore()

    def DrawCollabPings(self, view, painter):
        if self._NormalizeCollabCursorDisplayMode(getattr(self, 'collabCursorDisplayMode', COLLAB_CURSOR_DISPLAY_ALWAYS)) == COLLAB_CURSOR_DISPLAY_NEVER:
            return
        if not self.collabPings:
            return
        now = time.monotonic()
        viewport_rect = view.viewport().rect()
        inset_rect = viewport_rect.adjusted(28, 28, -28, -28)
        if inset_rect.width() <= 0 or inset_rect.height() <= 0:
            inset_rect = viewport_rect.adjusted(8, 8, -8, -8)
        center = QtCore.QPointF(viewport_rect.center())
        font = painter.font()
        font.setBold(True)

        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
        painter.setFont(font)

        for ping in list(self.collabPings):
            expires_at = float(ping.get('expires_at', 0.0) or 0.0)
            if expires_at <= now:
                continue
            remaining = max(0.0, min(1.0, (expires_at - now) / (float(self.collabPingDurationMs) / 1000.0)))
            alpha = max(70, min(255, int(255 * remaining)))
            nick = str(ping.get('nick') or 'Player')
            ping_color = collab_qcolor(ping.get('color'), alpha)
            ping_fill = collab_qcolor(ping.get('color'), max(60, alpha // 3))
            scene_point = QtCore.QPointF(float(ping.get('x', 0.0)), float(ping.get('y', 0.0)))
            target = QtCore.QPointF(view.mapFromScene(scene_point))

            visible = inset_rect.contains(QtCore.QPoint(int(target.x()), int(target.y())))
            if visible:
                radius = 28.0 + (1.0 - remaining) * 10.0
                pen = QtGui.QPen(ping_color, 3)
                painter.setPen(pen)
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawEllipse(target, radius, radius)

                text_rect = QtCore.QRectF(target.x() - 90, target.y() - radius - 28, 180, 22)
                painter.setPen(QtGui.QColor(20, 20, 20, alpha))
                painter.drawText(text_rect.translated(1, 1), QtCore.Qt.AlignmentFlag.AlignCenter, nick)
                painter.setPen(QtGui.QColor(255, 255, 255, alpha))
                painter.drawText(text_rect, QtCore.Qt.AlignmentFlag.AlignCenter, nick)
                continue

            dx = target.x() - center.x()
            dy = target.y() - center.y()
            length = math.hypot(dx, dy)
            if length < 0.001:
                continue

            candidates = []
            if abs(dx) > 0.001:
                for edge_x in (inset_rect.left(), inset_rect.right()):
                    t = (edge_x - center.x()) / dx
                    y = center.y() + t * dy
                    if t > 0 and inset_rect.top() <= y <= inset_rect.bottom():
                        candidates.append(t)
            if abs(dy) > 0.001:
                for edge_y in (inset_rect.top(), inset_rect.bottom()):
                    t = (edge_y - center.y()) / dy
                    x = center.x() + t * dx
                    if t > 0 and inset_rect.left() <= x <= inset_rect.right():
                        candidates.append(t)
            if not candidates:
                continue

            t_edge = min(candidates)
            edge = QtCore.QPointF(center.x() + dx * t_edge, center.y() + dy * t_edge)
            ux = dx / length
            uy = dy / length
            label_pos = QtCore.QPointF(edge.x() - ux * 34.0, edge.y() - uy * 34.0)

            painter.save()
            painter.translate(edge)
            painter.rotate(math.degrees(math.atan2(dy, dx)))
            arrow = QtGui.QPolygonF([
                QtCore.QPointF(0.0, 0.0),
                QtCore.QPointF(-18.0, -10.0),
                QtCore.QPointF(-18.0, 10.0),
            ])
            painter.setPen(QtGui.QPen(ping_color, 2))
            painter.setBrush(ping_fill)
            painter.drawPolygon(arrow)
            painter.restore()

            text_rect = QtCore.QRectF(label_pos.x() - 70, label_pos.y() - 12, 140, 24)
            painter.setPen(QtGui.QColor(20, 20, 20, alpha))
            painter.drawText(text_rect.translated(1, 1), QtCore.Qt.AlignmentFlag.AlignCenter, nick)
            painter.setPen(QtGui.QColor(255, 255, 255, alpha))
            painter.drawText(text_rect, QtCore.Qt.AlignmentFlag.AlignCenter, nick)

        painter.restore()

    def HandleOpenCollabChat(self):
        self._EnsureChatWindow()
        try:
            self.collabWindow.activateInput()
            self._ClampChatOverlay()
            QtCore.QTimer.singleShot(0, self._ClampChatOverlay)
            QtCore.QTimer.singleShot(0, self.collabWindow.activateInput)
        except Exception:
            pass
        self._UpdateChatEnabled()

    def HandleOpenCollabMonitor(self):
        if self.collabMonitorDialog is None:
            self.collabMonitorDialog = CollaborationMonitorDialog(
                participant_callback=self._HandleCollabMonitorParticipant,
                ban_list_callback=self.HandleOpenCollabBanList,
                parent=self,
            )
        self.collabMonitorDialog.setHostMode(hasattr(self, 'collabManager') and self.collabManager.mode == "host")
        self.collabMonitorDialog.setParticipants(self.collabParticipants)
        self.collabMonitorDialog.show()
        self.collabMonitorDialog.raise_()
        self.collabMonitorDialog.activateWindow()

    def HandleOpenCollabBanList(self):
        if self.collabBanListDialog is None:
            self.collabBanListDialog = CollaborationBanListDialog(self._HandleCollabBanRemove, self)
        self.collabBanListDialog.setBanList(self.collabManager.get_ban_list())
        self.collabBanListDialog.show()
        self.collabBanListDialog.raise_()
        self.collabBanListDialog.activateWindow()

    def _HandleCollabMonitorParticipant(self, participant, global_pos):
        if not isinstance(participant, dict):
            return
        if not hasattr(self, 'collabManager') or self.collabManager.mode != "host":
            return
        if participant.get('is_host'):
            return
        session_id = str(participant.get('session_id') or '')
        if session_id == str(getattr(self.collabManager, 'session_id', '') or ''):
            return

        menu = QtWidgets.QMenu(self)
        kick_action = menu.addAction('Kick')
        ban_action = menu.addAction('Ban by IP')
        chosen = menu.exec(global_pos)
        if chosen == kick_action:
            self.collabManager.kick_peer(session_id)
        elif chosen == ban_action:
            self.collabManager.ban_peer(session_id)

    def _HandleCollabBanRemove(self, ip):
        self.collabManager.remove_ban(ip)

    def HandleCollaborationParticipantsChanged(self, participants):
        prev_count = int(getattr(self, 'collabOnlineCount', 0) or 0)
        self.collabParticipants = list(participants or [])
        self.collabOnlineCount = len(self.collabParticipants)
        # Cleanup remote selection outlines for peers that left.
        try:
            alive = set(str(p.get('session_id') or '') for p in self.collabParticipants if isinstance(p, dict))
            alive.add(self._CollabLocalSessionId())
        except Exception:
            alive = set()
        try:
            for owner in list(getattr(self, '_collabSelectionItemsByOwner', {}).keys()):
                if owner and owner not in alive:
                    self._CollabClearRemoteSelectionsForOwner(owner)
        except Exception:
            pass
        try:
            self.collabPeerNicks = {sid: nick for sid, nick in getattr(self, 'collabPeerNicks', {}).items() if sid in alive}
        except Exception:
            pass
        try:
            self.collabPeerColors = {sid: color for sid, color in getattr(self, 'collabPeerColors', {}).items() if sid in alive}
        except Exception:
            pass
        try:
            self.collabRemoteCursors = {sid: data for sid, data in getattr(self, 'collabRemoteCursors', {}).items() if sid in alive}
        except Exception:
            pass
        for participant in self.collabParticipants:
            try:
                self._CollabSetPeerNick(participant.get('session_id'), participant.get('nickname'))
                self._CollabSetPeerColor(participant.get('session_id'), participant.get('highlight_color'))
            except Exception:
                pass
        if (
            self._CollabEnabled()
            and getattr(self.collabManager, 'mode', None) == 'host'
            and self.collabOnlineCount > prev_count
            and self.collabOnlineCount > 1
        ):
            try:
                self.CollabEnsureCurrentAreaIds()
                self.BroadcastFullLevelSnapshot()
                self.BroadcastFullSceneState()
                self.BroadcastFullMetaState()
            except Exception:
                pass
        self._RefreshCollabUi()

    def HandleCollaborationBanListChanged(self, ban_list):
        try:
            setSetting('CollabBanList', dict(ban_list or {}))
        except Exception:
            pass
        self._RefreshCollabUi()

    def addToolbarButtons(self):
        """
        Reads from the Preferences file and adds the appropriate options to the toolbar
        """
        # First, define groups. Each group is isolated by separators.
        Groups = (
            (
                'newlevel',
                'openfromname',
                'openfromfile',
                'openrecent',
                'save',
                'saveas',
                'savecopyas',
                'metainfo',
                'screenshot',
                'changegamepath',
                'preferences',
                'exit',
            ), (
                'selectall',
                'deselect',
            ), (
                'cut',
                'copy',
                'paste',
            ), (
                'shiftitems',
                'mergelocations',
            ), (
                'freezeobjects',
                'freezesprites',
                'freezeentrances',
                'freezelocations',
                'freezepaths',
            ), (
                'diagnostic',
            ), (
                'zoommax',
                'zoomin',
                'zoomactual',
                'zoomout',
                'zoommin',
            ), (
                'grid',
            ), (
                'showlay0',
                'showlay1',
                'showlay2',
            ), (
                'showsprites',
                'showlocations',
                'showpaths',
            ), (
                'areaoptions',
                'zones',
                'backgrounds',
            ), (
                'addarea',
                'importarea',
                'deletearea',
            ), (
                'reloadgfx',
                'reloaddata',
            ), (
                'infobox',
                'helpbox',
                'tipbox',
                'aboutqt',
            ),
        )

        # Determine which keys are activated
        toggled = NormalizeToolbarToggles(setting('ToolbarActs'))

        # Add each to the toolbar if toggled[key]
        for group in Groups:
            addedButtons = False
            for key in group:
                if key in toggled and toggled[key]:
                    act = self.actions[key]
                    self.toolbar.addAction(act)
                    addedButtons = True
            if addedButtons:
                self.toolbar.addSeparator()

    def SetupDocksAndPanels(self):
        """
        Sets up the dock widgets and panels
        """
        # level overview
        dock = QtWidgets.QDockWidget(globals_.trans.string('MenuItems', 94), self)
        dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable)
        # dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        dock.setObjectName('leveloverview')  # needed for the state to save/restore correctly

        self.levelOverview = LevelOverviewWidget()
        self.levelOverview.moveIt.connect(self.HandleOverviewClick)
        self.levelOverviewDock = dock
        dock.setWidget(self.levelOverview)

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.setVisible(True)
        act = dock.toggleViewAction()
        act.setShortcut(QtGui.QKeySequence('Ctrl+M'))
        act.setIcon(GetIcon('overview'))
        act.setStatusTip(globals_.trans.string('MenuItems', 95))
        self.vmenu.addAction(act)

        # create the sprite editor panel
        dock = QtWidgets.QDockWidget(globals_.trans.string('SpriteDataEditor', 0), self)
        dock.setVisible(False)
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        dock.setObjectName('spriteeditor')  # needed for the state to save/restore correctly
        dock.move(100, 100) # offset the dock from the top-left corner

        self.spriteDataEditor = SpriteEditorWidget()
        self.spriteDataEditor.DataUpdate.connect(self.SpriteDataUpdated)
        dock.setWidget(self.spriteDataEditor)
        self.spriteEditorDock = dock

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.setFloating(True)

        # create the entrance editor panel
        dock = QtWidgets.QDockWidget(globals_.trans.string('EntranceDataEditor', 24), self)
        dock.setVisible(False)
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        dock.setObjectName('entranceeditor')  # needed for the state to save/restore correctly
        dock.move(100, 100) # offset the dock from the top-left corner

        self.entranceEditor = EntranceEditorWidget()
        dock.setWidget(self.entranceEditor)
        self.entranceEditorDock = dock

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.setFloating(True)

        # create the path node editor panel
        dock = QtWidgets.QDockWidget(globals_.trans.string('PathDataEditor', 10), self)
        dock.setVisible(False)
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        dock.setObjectName('pathnodeeditor')  # needed for the state to save/restore correctly
        dock.move(100, 100) # offset the dock from the top-left corner

        self.pathEditor = PathNodeEditorWidget()
        dock.setWidget(self.pathEditor)
        self.pathEditorDock = dock

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.setFloating(True)

        # create the location editor panel
        dock = QtWidgets.QDockWidget(globals_.trans.string('LocationDataEditor', 12), self)
        dock.setVisible(False)
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        dock.setObjectName('locationeditor')  # needed for the state to save/restore correctly
        dock.move(100, 100) # offset the dock from the top-left corner

        self.locationEditor = LocationEditorWidget()
        dock.setWidget(self.locationEditor)
        self.locationEditorDock = dock

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.setFloating(True)

        # create the palette
        dock = QtWidgets.QDockWidget(globals_.trans.string('MenuItems', 96), self)
        dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        dock.setObjectName('palette')  # needed for the state to save/restore correctly

        self.creationDock = dock
        act = dock.toggleViewAction()
        act.setShortcut(QtGui.QKeySequence('Ctrl+P'))
        act.setIcon(GetIcon('palette'))
        act.setStatusTip(globals_.trans.string('MenuItems', 97))
        self.vmenu.addAction(act)

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        dock.setVisible(True)

        # add tabs to it
        tabs = QtWidgets.QTabWidget()
        tabs.setTabBar(IconsOnlyTabBar())
        tabs.setIconSize(QtCore.QSize(16, 16))
        tabs.currentChanged.connect(self.CreationTabChanged)
        dock.setWidget(tabs)
        self.creationTabs = tabs

        # object choosing tabs
        tsicon = GetIcon('objects')

        self.objAllTab = QtWidgets.QTabWidget()
        self.objAllTab.currentChanged.connect(self.ObjTabChanged)
        tabs.addTab(self.objAllTab, tsicon, '')
        tabs.setTabToolTip(0, globals_.trans.string('Palette', 13))

        self.objTS0Tab = QtWidgets.QWidget()
        self.objTS1Tab = QtWidgets.QWidget()
        self.objTS2Tab = QtWidgets.QWidget()
        self.objTS3Tab = QtWidgets.QWidget()
        self.objAllTab.addTab(self.objTS0Tab, tsicon, '1')
        self.objAllTab.addTab(self.objTS1Tab, tsicon, '2')
        self.objAllTab.addTab(self.objTS2Tab, tsicon, '3')
        self.objAllTab.addTab(self.objTS3Tab, tsicon, '4')

        oel = QtWidgets.QVBoxLayout(self.objTS0Tab)
        self.createObjectLayout = oel

        ll = QtWidgets.QHBoxLayout()
        self.objUseLayer0 = QtWidgets.QRadioButton('0')
        self.objUseLayer0.setToolTip(globals_.trans.string('Palette', 1))
        self.objUseLayer1 = QtWidgets.QRadioButton('1')
        self.objUseLayer1.setToolTip(globals_.trans.string('Palette', 2))
        self.objUseLayer2 = QtWidgets.QRadioButton('2')
        self.objUseLayer2.setToolTip(globals_.trans.string('Palette', 3))

        self.layerChangeButton = QtWidgets.QPushButton(globals_.trans.string('Palette', 36))
        self.layerChangeButton.clicked.connect(self.ChangeSelectionLayer)
        self.layerChangeButton.setEnabled(False)

        self.tilesetEditButton = QtWidgets.QPushButton('Edit')
        self.tilesetEditButton.setToolTip('Open tileset editor for the current tileset slot (collaboration: edits host tileset)')
        self.tilesetEditButton.clicked.connect(self.HandleTilesetEditClicked)
        self.tilesetEditButton.setEnabled(False)

        ll.addWidget(QtWidgets.QLabel(globals_.trans.string('Palette', 0)))
        ll.addWidget(self.objUseLayer0)
        ll.addWidget(self.objUseLayer1)
        ll.addWidget(self.objUseLayer2)
        ll.addStretch(1)
        ll.addWidget(self.layerChangeButton)
        ll.addWidget(self.tilesetEditButton)
        oel.addLayout(ll)

        lbg = QtWidgets.QButtonGroup(self)
        lbg.addButton(self.objUseLayer0, 0)
        lbg.addButton(self.objUseLayer1, 1)
        lbg.addButton(self.objUseLayer2, 2)
        lbg.buttonClicked.connect(lambda button: self.LayerChoiceChanged(lbg.id(button)))
        self.LayerButtonGroup = lbg

        self.objPicker = ObjectPickerWidget()
        self.objPicker.ObjChanged.connect(self.ObjectChoiceChanged)
        self.objPicker.ObjReplace.connect(self.ObjectReplace)
        oel.addWidget(self.objPicker, 1)

        # sprite tab
        self.sprAllTab = QtWidgets.QTabWidget()
        self.sprAllTab.currentChanged.connect(self.SprTabChanged)
        tabs.addTab(self.sprAllTab, GetIcon('sprites'), '')
        tabs.setTabToolTip(1, globals_.trans.string('Palette', 14))

        # sprite tab: add
        self.sprPickerTab = QtWidgets.QWidget()
        self.sprAllTab.addTab(self.sprPickerTab, GetIcon('spritesadd'), globals_.trans.string('Palette', 25))

        spl = QtWidgets.QVBoxLayout(self.sprPickerTab)
        self.sprPickerLayout = spl

        svpl = QtWidgets.QHBoxLayout()
        svpl.addWidget(QtWidgets.QLabel(globals_.trans.string('Palette', 4)))

        sspl = QtWidgets.QHBoxLayout()
        sspl.addWidget(QtWidgets.QLabel(globals_.trans.string('Palette', 5)))

        LoadSpriteCategories()
        viewpicker = QtWidgets.QComboBox()
        for view in globals_.SpriteCategories:
            viewpicker.addItem(view[0])
        viewpicker.currentIndexChanged.connect(self.SelectNewSpriteView)

        self.spriteViewPicker = viewpicker
        svpl.addWidget(viewpicker, 1)

        self.spriteSearchTerm = QtWidgets.QLineEdit()
        self.spriteSearchTerm.textChanged.connect(self.NewSearchTerm)
        sspl.addWidget(self.spriteSearchTerm, 1)

        self.spritePreviewButton = QtWidgets.QToolButton()
        self.spritePreviewButton.setText('Preview')
        self.spritePreviewButton.setCheckable(True)

        spl.addLayout(svpl)
        spl.addLayout(sspl)

        self.spriteSearchLayout = sspl

        self.sprPicker = SpritePickerWidget()
        self.sprPicker.SpriteChanged.connect(self.SpriteChoiceChanged)
        self.sprPicker.SpriteReplace.connect(self.SpriteReplace)
        self.sprPicker.SwitchView(globals_.SpriteCategories[0])
        self.spritePreviewButton.setChecked(self.sprPicker.previewEnabled())
        self.spritePreviewButton.toggled.connect(self.sprPicker.setPreviewEnabled)
        self.spritePreviewButton.setToolTip('Show sprite previews in the palette')
        sspl.addWidget(self.spritePreviewButton)
        spl.addWidget(self.sprPicker, 1)

        self.defaultPropButton = QtWidgets.QPushButton(globals_.trans.string('Palette', 6))
        self.defaultPropButton.setEnabled(False)
        self.defaultPropButton.clicked.connect(self.ShowDefaultProps)

        sdpl = QtWidgets.QHBoxLayout()
        sdpl.addStretch(1)
        sdpl.addWidget(self.defaultPropButton)
        sdpl.addStretch(1)
        spl.addLayout(sdpl)

        # default sprite data editor
        ddock = QtWidgets.QDockWidget(globals_.trans.string('Palette', 7), self)
        ddock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable)
        ddock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        ddock.setObjectName('defaultprops')  # needed for the state to save/restore correctly
        ddock.move(100, 100) # offset the dock from the top-left corner

        self.defaultDataEditor = SpriteEditorWidget(True)
        self.defaultDataEditor.setVisible(False)
        ddock.setWidget(self.defaultDataEditor)

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, ddock)
        ddock.setVisible(False)
        ddock.setFloating(True)
        self.defaultPropDock = ddock

        # sprite tab: current
        self.sprEditorTab = QtWidgets.QWidget()
        self.sprAllTab.addTab(self.sprEditorTab, GetIcon('spritelist'), globals_.trans.string('Palette', 26))

        spel = QtWidgets.QVBoxLayout(self.sprEditorTab)
        self.sprEditorLayout = spel

        slabel = QtWidgets.QLabel(globals_.trans.string('Palette', 11))
        slabel.setWordWrap(True)
        self.spriteList = SpriteList()

        spel.addWidget(slabel)
        spel.addWidget(self.spriteList)

        # entrance tab
        self.entEditorTab = QtWidgets.QWidget()
        tabs.addTab(self.entEditorTab, GetIcon('entrances'), '')
        tabs.setTabToolTip(2, globals_.trans.string('Palette', 15))

        eel = QtWidgets.QVBoxLayout(self.entEditorTab)
        self.entEditorLayout = eel

        elabel = QtWidgets.QLabel(globals_.trans.string('Palette', 8))
        elabel.setWordWrap(True)
        self.entranceList = ListWidgetWithToolTipSignal()
        self.entranceList.itemActivated.connect(self.HandleEntranceSelectByList)
        self.entranceList.toolTipAboutToShow.connect(self.HandleEntranceToolTipAboutToShow)
        self.entranceList.setSortingEnabled(True)

        eel.addWidget(elabel)
        eel.addWidget(self.entranceList)

        # locations tab
        self.locEditorTab = QtWidgets.QWidget()
        tabs.addTab(self.locEditorTab, GetIcon('locations'), '')
        tabs.setTabToolTip(3, globals_.trans.string('Palette', 16))

        locL = QtWidgets.QVBoxLayout(self.locEditorTab)
        self.locEditorLayout = locL

        Llabel = QtWidgets.QLabel(globals_.trans.string('Palette', 12))
        Llabel.setWordWrap(True)
        self.locationList = ListWidgetWithToolTipSignal()
        self.locationList.itemActivated.connect(self.HandleLocationSelectByList)
        self.locationList.toolTipAboutToShow.connect(self.HandleLocationToolTipAboutToShow)
        self.locationList.setSortingEnabled(True)

        locL.addWidget(Llabel)
        locL.addWidget(self.locationList)

        # paths tab
        self.pathEditorTab = QtWidgets.QWidget()
        tabs.addTab(self.pathEditorTab, GetIcon('paths'), '')
        tabs.setTabToolTip(4, globals_.trans.string('Palette', 17))

        pathel = QtWidgets.QVBoxLayout(self.pathEditorTab)
        self.pathEditorLayout = pathel

        pathlabel = QtWidgets.QLabel(globals_.trans.string('Palette', 9))
        pathlabel.setWordWrap(True)
        deselectbtn = QtWidgets.QPushButton(globals_.trans.string('Palette', 10))
        deselectbtn.clicked.connect(self.DeselectPathSelection)
        self.pathList = ListWidgetWithToolTipSignal()
        self.pathList.itemActivated.connect(self.HandlePathSelectByList)
        self.pathList.toolTipAboutToShow.connect(self.HandlePathToolTipAboutToShow)
        self.pathList.setSortingEnabled(True)

        pathel.addWidget(pathlabel)
        pathel.addWidget(deselectbtn)
        pathel.addWidget(self.pathList)

        # events tab
        self.eventEditorTab = QtWidgets.QWidget()
        tabs.addTab(self.eventEditorTab, GetIcon('events'), '')
        tabs.setTabToolTip(5, globals_.trans.string('Palette', 18))

        eventel = QtWidgets.QGridLayout(self.eventEditorTab)

        eventlabel = QtWidgets.QLabel(globals_.trans.string('Palette', 20))
        eventNotesLabel = QtWidgets.QLabel(globals_.trans.string('Palette', 21))
        self.eventNotesEditor = QtWidgets.QLineEdit()
        self.eventNotesEditor.textEdited.connect(self.handleEventNotesEdit)

        self.eventChooser = QtWidgets.QTreeWidget()
        self.eventChooser.setColumnCount(2)
        self.eventChooser.setHeaderLabels((globals_.trans.string('Palette', 22), globals_.trans.string('Palette', 23)))
        self.eventChooser.itemClicked.connect(self.handleEventTabItemClick)
        self.eventChooserItems = []
        flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
        for id in range(64):
            itm = QtWidgets.QTreeWidgetItem()
            itm.setFlags(flags)
            itm.setCheckState(0, Qt.CheckState.Unchecked)
            itm.setText(0, globals_.trans.string('Palette', 24, '[id]', str(id + 1)))
            itm.setText(1, '')
            self.eventChooser.addTopLevelItem(itm)
            self.eventChooserItems.append(itm)
            if id == 0: itm.setSelected(True)

        eventel.addWidget(eventlabel, 0, 0, 1, 2)
        eventel.addWidget(eventNotesLabel, 1, 0)
        eventel.addWidget(self.eventNotesEditor, 1, 1)
        eventel.addWidget(self.eventChooser, 2, 0, 1, 2)

        # stamps tab
        self.stampTab = QtWidgets.QWidget()
        tabs.addTab(self.stampTab, GetIcon('stamp'), '')
        tabs.setTabToolTip(6, globals_.trans.string('Palette', 19))

        stampLabel = QtWidgets.QLabel(globals_.trans.string('Palette', 27))

        stampAddBtn = QtWidgets.QPushButton(globals_.trans.string('Palette', 28))
        stampAddBtn.clicked.connect(self.handleStampsAdd)
        stampAddBtn.setEnabled(False)
        self.stampAddBtn = stampAddBtn  # so we can enable/disable it later
        stampRemoveBtn = QtWidgets.QPushButton(globals_.trans.string('Palette', 29))
        stampRemoveBtn.clicked.connect(self.handleStampsRemove)
        stampRemoveBtn.setEnabled(False)
        self.stampRemoveBtn = stampRemoveBtn  # so we can enable/disable it later

        menu = QtWidgets.QMenu()
        menu.addAction(globals_.trans.string('Palette', 31), self.handleStampsOpen)  # Open Set...
        menu.addAction(globals_.trans.string('Palette', 32), self.handleStampsSave)  # Save Set As...
        stampToolsBtn = QtWidgets.QToolButton()
        stampToolsBtn.setText(globals_.trans.string('Palette', 30))
        stampToolsBtn.setMenu(menu)
        stampToolsBtn.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        stampToolsBtn.setSizePolicy(stampAddBtn.sizePolicy())
        stampToolsBtn.setMinimumHeight(stampAddBtn.height() // 20)

        self.autoTilingBtn = QtWidgets.QPushButton('Auto-tiling')
        self.autoTilingBtn.clicked.connect(self.handleAutoTiling)
        self.randomFillBtn = QtWidgets.QPushButton('Random fill')
        self.randomFillBtn.clicked.connect(self.handleRandomFillFromStamp)

        stampNameLabel = QtWidgets.QLabel(globals_.trans.string('Palette', 35))
        self.stampNameEdit = QtWidgets.QLineEdit()
        self.stampNameEdit.setEnabled(False)
        self.stampNameEdit.textChanged.connect(self.handleStampNameEdited)

        nameLayout = QtWidgets.QHBoxLayout()
        nameLayout.addWidget(stampNameLabel)
        nameLayout.addWidget(self.stampNameEdit)

        self.stampChooser = StampChooserWidget()
        self.stampChooser.selectionChangedSignal.connect(self.handleStampSelectionChanged)

        stampL = QtWidgets.QGridLayout()
        stampL.addWidget(stampLabel, 0, 0, 1, 3)
        stampL.addWidget(stampAddBtn, 1, 0)
        stampL.addWidget(stampRemoveBtn, 1, 1)
        stampL.addWidget(stampToolsBtn, 1, 2)
        stampL.addWidget(self.autoTilingBtn, 2, 0, 1, 3)
        stampL.addWidget(self.randomFillBtn, 3, 0, 1, 3)
        stampL.addLayout(nameLayout, 4, 0, 1, 3)
        stampL.addWidget(self.stampChooser, 5, 0, 1, 3)
        self.stampTab.setLayout(stampL)

        # comments tab
        self.commentsTab = QtWidgets.QWidget()
        tabs.addTab(self.commentsTab, GetIcon('comments'), '')
        tabs.setTabToolTip(7, globals_.trans.string('Palette', 33))

        cel = QtWidgets.QVBoxLayout()
        self.commentsTab.setLayout(cel)

        clabel = QtWidgets.QLabel(globals_.trans.string('Palette', 34))
        clabel.setWordWrap(True)

        self.commentList = ListWidgetWithToolTipSignal()
        self.commentList.itemActivated.connect(self.HandleCommentSelectByList)
        self.commentList.toolTipAboutToShow.connect(self.HandleCommentToolTipAboutToShow)
        self.commentList.setSortingEnabled(True)

        cel.addWidget(clabel)
        cel.addWidget(self.commentList)

        # Set the current tab to the Object tab
        self.CreationTabChanged(0)

    def DeselectPathSelection(self, checked):
        """
        Deselects selected path nodes in the list
        """
        for selecteditem in self.pathList.selectedItems():
            selecteditem.setSelected(False)

    def Autosave(self):
        """
        Auto saves the level
        """
        if self.IsCollabClientMode():
            globals_.AutoSaveDirty = False
            return
        if not globals_.AutoSaveDirty: return

        data = globals_.Level.save()
        setSetting('AutoSaveFilePath', self.fileSavePath)
        setSetting('AutoSaveFileData', QtCore.QByteArray(data))
        globals_.AutoSaveDirty = False

    def TrackClipboardUpdates(self):
        """
        Catches systemwide clipboard updates
        """
        if globals_.Initializing: return
        clip = self.systemClipboard.text()
        if clip is not None and clip != '':
            clip = str(clip).strip()

            if clip.startswith('ReggieClip|') and clip.endswith('|%'):
                self.clipboard = clip.replace(' ', '').replace('\n', '').replace('\r', '').replace('\t', '')

                self.actions['paste'].setEnabled(True)
            else:
                self.clipboard = None
                self.actions['paste'].setEnabled(False)

    def XScrollChange(self, pos):
        """
        Moves the Overview current position box based on X scroll bar value
        """
        self.levelOverview.Xposlocator = pos
        self.levelOverview.update()

    def YScrollChange(self, pos):
        """
        Moves the Overview current position box based on Y scroll bar value
        """
        self.levelOverview.Yposlocator = pos
        self.levelOverview.update()

    def HandleWindowSizeChange(self, w, h):
        self.levelOverview.Hlocator = h
        self.levelOverview.Wlocator = w
        self.levelOverview.update()
        self._UpdateChatOverlayText()
        self._ClampChatOverlay()

    def UpdateTitle(self):
        """
        Sets the window title accordingly
        """
        # ' - Reggie Next' is added automatically by Qt (see QApplication.setApplicationDisplayName()).
        collab_suffix = ''
        if hasattr(self, 'collabManager') and self.collabManager.mode is not None:
            collab_suffix = ' [Collab: %s]' % self.collabManager.mode
        dirty_suffix = (' ' + globals_.trans.string('MainWindow', 0)) if globals_.Dirty and not self.IsCollabClientMode() else ''
        self.setWindowTitle('%s%s%s' % (self.fileTitle, dirty_suffix, collab_suffix))
        self._UpdateChatOverlayText()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._ClampChatOverlay()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ClampChatOverlay()

    def showEvent(self, event):
        super().showEvent(event)
        self._ClampChatOverlay()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.WindowStateChange:
            if self.isMinimized():
                if hasattr(self, 'collabWindow') and self.collabWindow is not None:
                    self.collabWindow.hide()
            else:
                if hasattr(self, 'collabWindow') and self.collabWindow is not None and getattr(self.collabWindow, '_expanded', False):
                    self.collabWindow.show()
                self._ClampChatOverlay()

    def IsCollabClientMode(self):
        return hasattr(self, 'collabManager') and self.collabManager.mode == "client"

    def UpdateSaveActionsForCollabMode(self):
        client_mode = self.IsCollabClientMode()
        for action_name in ('save', 'saveas', 'savecopyas'):
            action = self.actions.get(action_name)
            if action is not None:
                action.setEnabled(not client_mode)

        if client_mode:
            globals_.Dirty = False
            globals_.AutoSaveDirty = False
        self.UpdateTitle()
        self._UpdateTilesetEditButtonState()

    def _GetTilesetNameForSlot(self, slot):
        if globals_.Area is None:
            return ''
        if slot == 0:
            return str(getattr(globals_.Area, 'tileset0', '') or '')
        if slot == 1:
            return str(getattr(globals_.Area, 'tileset1', '') or '')
        if slot == 2:
            return str(getattr(globals_.Area, 'tileset2', '') or '')
        if slot == 3:
            return str(getattr(globals_.Area, 'tileset3', '') or '')
        return ''

    def _GetTilesetSlotsForName(self, name):
        name = str(name or '')
        slots = []
        for slot in range(4):
            if self._GetTilesetNameForSlot(slot) == name:
                slots.append(slot)
        return slots

    def _GetTilesetCacheDir(self):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            base_dir = os.getcwd()
        path = os.path.join(base_dir, 'collab_tilesets')
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
        return path

    def _GetTilesetFinalDir(self):
        """
        Directory where the final tileset .arc should be stored for the game.

        User expectation: <StageGamePath>\\Texture\\
        """
        try:
            stage_dir = str(getattr(globals_, 'gamedef', None).GetStageGamePath() or '')
        except Exception:
            stage_dir = ''
        if not stage_dir:
            return None
        out_dir = os.path.join(stage_dir, 'Texture')
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            # If we can't create it (permissions, invalid path), fall back later.
            return None
        return out_dir

    def _GetTilesetOverridePath(self, name):
        """
        Returns the path used for tileset overrides.

        - Host / offline: write into Stage\\Texture (so the game uses it).
        - Client: keep a local cache (do not touch user's game directory).
        """
        name = str(name or '')
        if not name:
            return os.path.join(self._GetTilesetCacheDir(), '.arc')

        if not self.IsCollabClientMode():
            final_dir = self._GetTilesetFinalDir()
            if final_dir:
                return os.path.join(final_dir, '%s.arc' % name)

        return os.path.join(self._GetTilesetCacheDir(), '%s.arc' % name)

    def _ReadTilesetArcFromGame(self, name):
        """
        Reads a tileset from the configured game paths.
        Returns (arc_bytes, source_path) where arc_bytes is an uncompressed U8.
        """
        name = str(name or '')
        if not name:
            return None, None

        tileset_paths = list(reversed(globals_.gamedef.GetTexturePaths()))
        # Prefer Stage\Texture (where the game expects custom tilesets) if set.
        try:
            stage_texture = self._GetTilesetFinalDir()
        except Exception:
            stage_texture = None
        if stage_texture:
            norm = os.path.normpath(stage_texture)
            if all(os.path.normpath(str(p or '')) != norm for p in tileset_paths):
                tileset_paths.insert(0, stage_texture)

        tileset_paths = tileset_paths
        for path in tileset_paths:
            if path is None:
                break

            lh_path = os.path.join(path, name + '.arc.LH')
            arc_path = os.path.splitext(lh_path)[0]

            if os.path.isfile(lh_path):
                with open(lh_path, 'rb') as f:
                    data = f.read()
                if (data[0] & 0xF0) == 0x40:
                    try:
                        data = lh.UncompressLH(data)
                    except Exception:
                        return None, lh_path
                return data, lh_path

            if os.path.isfile(arc_path):
                with open(arc_path, 'rb') as f:
                    data = f.read()
                return data, arc_path

        return None, None

    def _EnsureTilesetOverrideFile(self, name):
        name = str(name or '')
        if not name:
            return None

        overrides = getattr(globals_, 'CollabTilesetOverrides', None)
        if not isinstance(overrides, dict):
            globals_.CollabTilesetOverrides = {}
            overrides = globals_.CollabTilesetOverrides

        override_path = str(overrides.get(name) or '')
        if override_path and os.path.isfile(override_path):
            return override_path

        data, _src = self._ReadTilesetArcFromGame(name)
        if not data:
            return None

        override_path = self._GetTilesetOverridePath(name)
        try:
            with open(override_path, 'wb') as f:
                f.write(data)
        except Exception:
            return None

        overrides[name] = override_path
        return override_path

    def _UpdateTilesetEditButtonState(self):
        btn = getattr(self, 'tilesetEditButton', None)
        if btn is None:
            return
        if globals_.Area is None:
            btn.setEnabled(False)
            return
        try:
            slot = int(self.objAllTab.currentIndex())
        except Exception:
            slot = int(getattr(globals_, 'CurrentPaintType', 0) or 0)
        name = self._GetTilesetNameForSlot(slot)
        btn.setEnabled(bool(name))

    def _GetPuzzleLaunchDetails(self):
        try:
            base_dir = module_path()
        except Exception:
            base_dir = None
        if not base_dir:
            try:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            except Exception:
                base_dir = os.getcwd()

        is_frozen = hasattr(sys, 'frozen') and hasattr(sys, '_MEIPASS')
        if is_frozen:
            candidates = (
                ('exe', os.path.join(base_dir, 'Puzzle-Next', 'puzzle.exe')),
                ('script', os.path.join(base_dir, 'Puzzle-Next', 'puzzle.py')),
                ('script', os.path.join(base_dir, 'Puzzle-Next-master', 'puzzle.py')),
            )
        else:
            candidates = (
                ('script', os.path.join(base_dir, 'Puzzle-Next-master', 'puzzle.py')),
                ('script', os.path.join(base_dir, 'Puzzle-Next', 'puzzle.py')),
                ('exe', os.path.join(base_dir, 'Puzzle-Next', 'puzzle.exe')),
            )

        for launch_type, path in candidates:
            if os.path.isfile(path):
                return launch_type, path

        return None, candidates[0][1]

    def _TilesetBytesSha1(self, data):
        try:
            return hashlib.sha1(bytes(data or b'')).hexdigest()
        except Exception:
            return ''

    def HandleTilesetEditClicked(self, checked=False):
        if globals_.Area is None:
            return

        try:
            slot = int(self.objAllTab.currentIndex())
        except Exception:
            slot = int(getattr(globals_, 'CurrentPaintType', 0) or 0)
        if slot < 0 or slot > 3:
            return
        name = self._GetTilesetNameForSlot(slot)
        if not name:
            return

        puzzle_launch_type, puzzle_path = self._GetPuzzleLaunchDetails()
        if puzzle_launch_type is None:
            QtWidgets.QMessageBox.warning(self, 'Tileset editor', 'Puzzle editor not found:\n%s' % puzzle_path)
            return

        override_path = None
        if self.IsCollabClientMode():
            try:
                overrides = getattr(globals_, 'CollabTilesetOverrides', None)
                if isinstance(overrides, dict):
                    candidate = str(overrides.get(name) or '')
                    if candidate and os.path.isfile(candidate):
                        override_path = candidate
            except Exception:
                override_path = None

            if not override_path:
                # We cannot assume client's game files match the host.
                self._RequestHostTilesetsNow()
                QtWidgets.QMessageBox.information(
                    self,
                    'Tileset editor',
                    'Tileset is not synced yet.\nRequested tileset from host, please try again in a moment.'
                )
                return
        else:
            override_path = self._EnsureTilesetOverrideFile(name)
            if not override_path:
                QtWidgets.QMessageBox.warning(self, 'Tileset editor', 'Unable to locate tileset "%s" in game paths.' % name)
                return

        # Ensure we're currently using the override file (important when the
        # original tileset exists only as .arc.LH in the game directory).
        try:
            globals_.CollabTilesetOverrides[name] = override_path
        except Exception:
            pass
        self._ReloadTilesetNameEverywhere(name)

        # (Re)start file watcher for this tileset edit session.
        self._tilesetEditSession = {'name': name, 'path': override_path}
        try:
            with open(override_path, 'rb') as f:
                self._collabTilesetSha1ByName[name] = self._TilesetBytesSha1(f.read())
        except Exception:
            pass
        try:
            self._tilesetEditWatcher.removePaths(self._tilesetEditWatcher.files())
        except Exception:
            pass
        try:
            self._tilesetEditWatcher.addPath(override_path)
        except Exception:
            pass

        # Launch Puzzle as a separate process.
        try:
            puzzle_dir = os.path.dirname(puzzle_path)
            if puzzle_launch_type == 'exe':
                command = [puzzle_path, override_path]
            else:
                command = [sys.executable, puzzle_path, override_path]
            subprocess.Popen(command, cwd=puzzle_dir)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, 'Tileset editor', 'Unable to launch Puzzle:\n%s' % str(e))
            return

    def _HandleTilesetEditorFileChanged(self, path):
        if not path:
            return
        self._tilesetEditPendingPath = str(path)
        # Debounce: Puzzle may save multiple times / write temp files.
        self._tilesetEditDebounce.start(250)

        # QFileSystemWatcher can drop paths after change on some platforms.
        try:
            if os.path.isfile(path) and path not in self._tilesetEditWatcher.files():
                self._tilesetEditWatcher.addPath(path)
        except Exception:
            pass

    def _FlushTilesetEditorFileChanged(self):
        if not self._tilesetEditSession:
            return
        path = str(self._tilesetEditPendingPath or self._tilesetEditSession.get('path') or '')
        if not path or not os.path.isfile(path):
            return
        name = str(self._tilesetEditSession.get('name') or '')
        if not name:
            return

        try:
            with open(path, 'rb') as f:
                data = f.read()
        except Exception:
            return

        new_sha1 = self._TilesetBytesSha1(data)
        if new_sha1 and new_sha1 == str(self._collabTilesetSha1ByName.get(name) or ''):
            return

        # Apply locally and broadcast to peers if hosting.
        self._ApplyCollabTilesetBytes(name, data, slots=self._GetTilesetSlotsForName(name), broadcast=True)

    def _ReloadTilesetNameEverywhere(self, name):
        name = str(name or '')
        if not name or globals_.Area is None:
            return
        slots = self._GetTilesetSlotsForName(name)
        for slot in slots:
            try:
                LoadTileset(int(slot), name, reload_=True)
            except Exception:
                pass

        # Refresh object picker even if tileset names didn't change.
        try:
            self._lastObjectPickerTilesets = None
        except Exception:
            pass
        try:
            self._LoadObjectPickerForCurrentArea()
        except Exception:
            pass
        try:
            self.objPicker.update()
        except Exception:
            pass
        try:
            for layer in globals_.Area.layers:
                for obj in layer:
                    obj.updateObjCache()
        except Exception:
            pass
        try:
            self.scene.update()
        except Exception:
            pass

        self._RefreshQuickPaintTilesetState()

    def _RefreshQuickPaintTilesetState(self, schedule_retry=True):
        """
        Refresh Quick Paint state after tileset changes without touching the
        quickpaint package directly.
        """
        if not hasattr(self, 'qpt_palette') or self.qpt_palette is None:
            return

        try:
            quick_paint_tab = self.qpt_palette.get_quick_paint_tab()
        except Exception:
            quick_paint_tab = None

        if not quick_paint_tab:
            return

        try:
            tileset_selector = getattr(quick_paint_tab, 'tileset_selector', None)
            qpt_widget = getattr(quick_paint_tab, 'qpt_widget', None)
            fill_paint_tab = None

            try:
                fill_paint_tab = self.qpt_palette.get_fill_paint_tab()
            except Exception:
                fill_paint_tab = None

            self._RefreshQuickPaintTilesetSelector(tileset_selector)
            if fill_paint_tab is not None:
                self._RefreshQuickPaintTilesetSelector(getattr(fill_paint_tab, 'tileset_selector', None))

            if qpt_widget is not None:
                qpt_widget.initialize_with_current_tileset()
        except Exception as e:
            print(f"[QPT] Warning: Could not refresh QPT tilesets: {e}")

        # Client tileset data can arrive slightly after the area metadata;
        # retry once on the next event loop to catch late ObjectDefinitions.
        if schedule_retry:
            QtCore.QTimer.singleShot(200, self._RefreshQuickPaintTilesetStateDeferred)

    def _RefreshQuickPaintTilesetStateDeferred(self):
        if not hasattr(self, 'qpt_palette') or self.qpt_palette is None:
            return

        try:
            quick_paint_tab = self.qpt_palette.get_quick_paint_tab()
        except Exception:
            quick_paint_tab = None

        if not quick_paint_tab:
            return

        try:
            tileset_selector = getattr(quick_paint_tab, 'tileset_selector', None)
            fill_paint_tab = None
            try:
                fill_paint_tab = self.qpt_palette.get_fill_paint_tab()
            except Exception:
                fill_paint_tab = None

            needs_retry = (
                tileset_selector is not None and not getattr(tileset_selector, 'objects_loaded', False)
            )
            fill_selector = getattr(fill_paint_tab, 'tileset_selector', None) if fill_paint_tab is not None else None
            needs_retry = needs_retry or (
                fill_selector is not None and not getattr(fill_selector, 'objects_loaded', False)
            )

            if needs_retry:
                self._RefreshQuickPaintTilesetState(schedule_retry=False)
        except Exception:
            pass

    def _RefreshQuickPaintTilesetSelector(self, tileset_selector):
        """Reload a Quick Paint tileset selector from current ObjectDefinitions."""
        if tileset_selector is None:
            return

        try:
            current_tileset = int(tileset_selector.tileset_combo.currentIndex())
        except Exception:
            current_tileset = int(getattr(tileset_selector, 'current_tileset', 0) or 0)

        tileset_selector.objects_loaded = False
        tileset_selector.tileset_objects.clear()
        tileset_selector.load_objects_from_reggie()
        tileset_selector.objects_loaded = bool(tileset_selector.tileset_objects)
        tileset_selector.current_tileset = current_tileset

        if hasattr(tileset_selector, 'tileset_combo'):
            tileset_selector.tileset_combo.blockSignals(True)
            tileset_selector.tileset_combo.setCurrentIndex(current_tileset)
            tileset_selector.tileset_combo.blockSignals(False)

        tileset_selector.update_object_list()

    def _InstallQuickPaintCollabSync(self):
        if getattr(self, '_qptCollabSyncInstalled', False):
            return
        if not hasattr(self, 'qpt_palette') or self.qpt_palette is None:
            return

        self._qptCollabSyncInstalled = True
        self._qptCollabApplyingUiState = False
        # Keep Quick Paint UI local to each participant. Only actual level edits
        # are synchronized through collaboration/undo bridges.
        self._InstallQuickPaintExternalBridge()

    def _InstallQuickPaintExternalBridge(self):
        if not hasattr(self, 'qpt_palette') or self.qpt_palette is None:
            return
        if getattr(self, '_qptExternalBridgeInstalled', False):
            return

        patched_any = False

        try:
            qpt_tab = self.qpt_palette.get_quick_paint_tab()
        except Exception:
            qpt_tab = None

        if qpt_tab is not None and not getattr(qpt_tab, '_reggie_qpt_remove_patch', False):
            try:
                def _patched_remove_object(obj, *, _mw=self):
                    return _mw._QuickPaintDeleteObject(obj)
                qpt_tab._remove_object = _patched_remove_object
                qpt_tab._reggie_qpt_remove_patch = True
                patched_any = True
            except Exception:
                pass

        hook = None
        try:
            getter = (_qpt_functions or {}).get('get_hook')
            if callable(getter):
                hook = getter()
        except Exception:
            hook = None

        if hook is not None and not getattr(hook, '_reggie_qpt_erase_patch', False):
            try:
                def _patched_erase_at_position(x: int, y: int, layer: int, *, _mw=self):
                    return _mw._QuickPaintEraseAtPosition(x, y, layer)
                hook.erase_at_position = _patched_erase_at_position
                hook._reggie_qpt_erase_patch = True
                patched_any = True
            except Exception:
                pass

        if patched_any:
            self._qptExternalBridgeInstalled = True

    def _QuickPaintDeleteObject(self, obj, update_overview=True):
        if obj is None or globals_.Area is None:
            return False

        try:
            from levelitems import ObjectItem
            if not isinstance(obj, ObjectItem):
                return False
        except Exception:
            return False

        try:
            self._CollabEnsureItemId(obj)
        except Exception:
            pass

        if not self.UndoRedoInProgress and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False) and not globals_.DirtyOverride:
            try:
                from undo import CreateOrDeleteInstanceUndoAction
                extra = {'z': obj.zValue()}
                self.undoStack.addAction(CreateOrDeleteInstanceUndoAction('delete', obj.instanceDef(obj), collab_id=getattr(obj, '_collab_id', None), extra=extra))
            except Exception:
                pass

        try:
            obj.delete()
        except Exception:
            pass
        try:
            obj.setSelected(False)
        except Exception:
            pass
        try:
            self.scene.removeItem(obj)
        except Exception:
            pass
        try:
            SetDirty()
        except Exception:
            pass
        if update_overview:
            try:
                self.levelOverview.update()
            except Exception:
                pass
        return True

    def _QuickPaintEraseAtPosition(self, x: int, y: int, layer: int):
        if globals_.Area is None:
            return

        try:
            layer = int(layer)
            x = int(x)
            y = int(y)
        except Exception:
            return

        if layer < 0 or layer >= len(globals_.Area.layers):
            return

        try:
            layer_obj = globals_.Area.layers[layer]
        except Exception:
            return

        to_process = []
        for obj in list(layer_obj):
            try:
                if obj.objx <= x < obj.objx + obj.width and obj.objy <= y < obj.objy + obj.height:
                    to_process.append(obj)
            except Exception:
                continue

        changed = False
        for obj in to_process:
            try:
                obj_x = int(obj.objx)
                obj_y = int(obj.objy)
                obj_w = int(obj.width)
                obj_h = int(obj.height)
                obj_type = int(obj.type)
                obj_tileset = int(obj.tileset)
            except Exception:
                continue

            if not self._QuickPaintDeleteObject(obj, update_overview=False):
                continue
            changed = True

            if obj_w == 1 and obj_h == 1:
                continue

            for dy in range(obj_h):
                for dx in range(obj_w):
                    tile_x = obj_x + dx
                    tile_y = obj_y + dy
                    if tile_x == x and tile_y == y:
                        continue
                    try:
                        self.CreateObject(
                            tileset=obj_tileset,
                            object_num=obj_type,
                            layer=layer,
                            x=tile_x,
                            y=tile_y,
                            width=1,
                            height=1,
                        )
                    except Exception:
                        pass

        if changed:
            try:
                self.levelOverview.update()
            except Exception:
                pass

    def _BroadcastQuickPaintUiState(self, state: dict):
        if self._qptCollabApplyingUiState:
            return
        if not hasattr(self, 'collabManager') or not self._CollabEnabled():
            return
        if globals_.Area is None:
            return

        payload = dict(state or {})
        payload['area_num'] = int(getattr(globals_.Area, 'areanum', 0) or 0)
        payload['level_name'] = self._CollabCurrentLevelName()
        payload['ts'] = int(time.time() * 1000)

        try:
            self.collabManager.broadcast_message('qpt_ui', payload)
        except Exception:
            pass

    def _NormalizeQuickPaintMode(self, mode):
        try:
            mode = str(mode or '')
        except Exception:
            mode = ''
        if not mode:
            return ''
        m = mode.strip()
        if ' (' in m:
            try:
                m = m.split(' (', 1)[0].strip()
            except Exception:
                pass
        if m.lower() == 'singletile':
            return 'Single Tile'
        if m.lower() == 'shapecreator':
            return 'Shape Creator'
        return m

    def _OnLocalQuickPaintModeChanged(self, mode: str):
        mode = self._NormalizeQuickPaintMode(mode)
        if not mode:
            return
        self._BroadcastQuickPaintUiState({'scope': 'qpt', 'mode': mode})

    def _OnLocalQuickPaintTilesetChanged(self, tileset_idx: int):
        try:
            tileset_idx = int(tileset_idx)
        except Exception:
            return

        mode = None
        try:
            qpt_tab = self.qpt_palette.get_quick_paint_tab()
            mode = qpt_tab.qpt_widget.get_current_mode()
        except Exception:
            pass

        msg = {'scope': 'qpt', 'tileset': tileset_idx}
        mode_norm = self._NormalizeQuickPaintMode(mode)
        if mode_norm:
            msg['mode'] = mode_norm
        self._BroadcastQuickPaintUiState(msg)

    def _OnLocalQuickPaintObjectSelected(self, tileset: int, obj_type: int, obj_id: int):
        try:
            tileset = int(tileset)
            obj_id = int(obj_id)
        except Exception:
            return

        mode = None
        try:
            qpt_tab = self.qpt_palette.get_quick_paint_tab()
            mode = qpt_tab.qpt_widget.get_current_mode()
        except Exception:
            pass

        msg = {'scope': 'qpt', 'tileset': tileset, 'obj_id': obj_id}
        mode_norm = self._NormalizeQuickPaintMode(mode)
        if mode_norm:
            msg['mode'] = mode_norm
        self._BroadcastQuickPaintUiState(msg)

    def _OnLocalFillPaintTilesetChanged(self, tileset_idx: int):
        try:
            tileset_idx = int(tileset_idx)
        except Exception:
            return
        self._BroadcastQuickPaintUiState({'scope': 'fill', 'tileset': tileset_idx})

    def _OnLocalFillPaintObjectSelected(self, tileset: int, obj_type: int, obj_id: int):
        try:
            tileset = int(tileset)
            obj_id = int(obj_id)
        except Exception:
            return
        self._BroadcastQuickPaintUiState({'scope': 'fill', 'tileset': tileset, 'obj_id': obj_id})

    def _ApplyRemoteQuickPaintUiState(self, payload: dict, sender: str):
        if not hasattr(self, 'qpt_palette') or self.qpt_palette is None:
            return

        scope = str((payload or {}).get('scope') or '')
        if scope not in {'qpt', 'fill'}:
            return

        self._qptCollabApplyingUiState = True
        try:
            if scope == 'qpt':
                try:
                    qpt_tab = self.qpt_palette.get_quick_paint_tab()
                except Exception:
                    qpt_tab = None
                if qpt_tab is None:
                    return

                mode = payload.get('mode')
                mode = self._NormalizeQuickPaintMode(mode)
                if mode and hasattr(qpt_tab, 'qpt_widget'):
                    try:
                        qpt_tab.qpt_widget.set_mode(str(mode))
                    except Exception:
                        pass

                tileset_idx = payload.get('tileset')
                if tileset_idx is not None and hasattr(qpt_tab, 'tileset_selector'):
                    try:
                        qpt_tab.tileset_selector.tileset_combo.setCurrentIndex(int(tileset_idx))
                    except Exception:
                        pass

                obj_id = payload.get('obj_id')
                if obj_id is not None and hasattr(qpt_tab, 'tileset_selector'):
                    try:
                        current_tileset = int(qpt_tab.tileset_selector.tileset_combo.currentIndex())
                    except Exception:
                        current_tileset = 0
                    try:
                        qpt_tab.tileset_selector.on_object_selected(current_tileset, 0, int(obj_id))
                    except Exception:
                        pass

            elif scope == 'fill':
                try:
                    fill_tab = self.qpt_palette.get_fill_paint_tab()
                except Exception:
                    fill_tab = None
                if fill_tab is None:
                    return

                tileset_idx = payload.get('tileset')
                if tileset_idx is not None and hasattr(fill_tab, 'tileset_selector'):
                    try:
                        fill_tab.tileset_selector.tileset_combo.setCurrentIndex(int(tileset_idx))
                    except Exception:
                        pass

                obj_id = payload.get('obj_id')
                if obj_id is not None and hasattr(fill_tab, 'tileset_selector'):
                    try:
                        current_tileset = int(fill_tab.tileset_selector.tileset_combo.currentIndex())
                    except Exception:
                        current_tileset = 0
                    try:
                        fill_tab.tileset_selector.on_object_selected(current_tileset, 0, int(obj_id))
                    except Exception:
                        pass
        finally:
            self._qptCollabApplyingUiState = False

    def _RestoreQuickPaintToolState(self):
        """Restore the Quick Paint tool that is selected in the UI."""
        try:
            from quickpaint.core.tool_manager import get_tool_manager, ToolType
            tool_manager = get_tool_manager()
        except Exception:
            return

        if not hasattr(self, 'qpt_palette') or self.qpt_palette is None:
            return

        quick_paint_tab = None
        fill_paint_tab = None
        active_tab_index = 0

        try:
            quick_paint_tab = self.qpt_palette.get_quick_paint_tab()
        except Exception:
            pass
        try:
            fill_paint_tab = self.qpt_palette.get_fill_paint_tab()
        except Exception:
            pass
        try:
            active_tab_index = int(self.qpt_palette.tabs.currentIndex())
        except Exception:
            active_tab_index = 0

        if active_tab_index == 1 and fill_paint_tab is not None:
            active_deco = getattr(fill_paint_tab, '_active_deco_container', None)
            if active_deco is not None and active_deco.is_selected():
                try:
                    fill_paint_tab._on_deco_container_selected(active_deco)
                    return
                except Exception:
                    pass

            fill_radio = getattr(fill_paint_tab, 'fill_radio', None)
            if fill_radio is not None and fill_radio.isChecked():
                try:
                    fill_paint_tab._on_fill_radio_toggled(True)
                    return
                except Exception:
                    pass

        if active_tab_index == 2:
            try:
                tool_manager.activate_tool(ToolType.TILESET_OVERLAY)
                return
            except Exception:
                pass

        if quick_paint_tab is not None:
            try:
                current_mode = quick_paint_tab.qpt_widget.get_current_mode()
                quick_paint_tab.on_mode_changed(current_mode)
                return
            except Exception:
                pass

        tool_manager.activate_tool(ToolType.QPT_SMART_PAINT)

    def _PackTilesetPayload(self, name, data, slots=None):
        if slots is None:
            slots = self._GetTilesetSlotsForName(name)
        name = str(name or '')
        raw = bytes(data or b'')
        compressed = zlib.compress(raw, 6)
        sha1 = self._TilesetBytesSha1(raw)
        return {
            'name': name,
            'slots': list(map(int, slots or [])),
            'sha1': sha1,
            'data': base64.b64encode(compressed).decode('ascii'),
            'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0) if globals_.Area is not None else 0,
            'level_name': self._CollabCurrentLevelName(),
        }

    def _ApplyCollabTilesetBytes(self, name, data, slots=None, broadcast=False, target_peer=None):
        """
        Stores the tileset in the collab cache, reloads it locally,
        and optionally sends it to collaboration peers.
        """
        name = str(name or '')
        if not name:
            return
        raw = bytes(data or b'')
        if not raw:
            return
        raw_sha1 = self._TilesetBytesSha1(raw)
        if raw_sha1 and raw_sha1 == str(self._collabTilesetSha1ByName.get(name) or ''):
            self._ReloadTilesetNameEverywhere(name)
            return

        override_path = self._GetTilesetOverridePath(name)
        try:
            with open(override_path, 'wb') as f:
                f.write(raw)
        except Exception:
            return

        try:
            globals_.CollabTilesetOverrides[name] = override_path
        except Exception:
            pass
        if raw_sha1:
            self._collabTilesetSha1ByName[name] = raw_sha1

        self._ReloadTilesetNameEverywhere(name)

        if not broadcast or not self._CollabEnabled():
            return

        payload = self._PackTilesetPayload(name, raw, slots=slots)
        if self.IsCollabClientMode():
            # Client edits are forwarded to host; host will rebroadcast to others.
            try:
                self.collabManager.broadcast_message('tileset_update', payload)
            except Exception:
                pass
            return
        if target_peer and hasattr(self, 'collabManager') and getattr(self.collabManager, 'mode', None) == 'host':
            try:
                if self.collabManager.send_message_to(target_peer, 'tileset_data', payload):
                    return
            except Exception:
                pass
        self.collabManager.broadcast_message('tileset_update', payload)

    def _ScheduleCollabTilesetSync(self, delay_ms=250):
        if not self.IsCollabClientMode():
            return
        if not hasattr(self, '_collabTilesetSyncTimer'):
            return
        if self._collabTilesetSyncTimer.isActive():
            return
        self._collabTilesetSyncTimer.start(int(delay_ms))

    def _RequestHostTilesetsNow(self):
        if not self.IsCollabClientMode():
            return
        if not self._CollabEnabled():
            return
        if globals_.Area is None:
            return
        try:
            self.collabManager.broadcast_message('tileset_sync_request', {
                'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
                'level_name': self._CollabCurrentLevelName(),
            })
        except Exception:
            pass

    def _HostSendTilesetsToPeer(self, peer_session_id, area_num=None):
        if not self._CollabEnabled() or getattr(self.collabManager, 'mode', None) != 'host':
            return
        if globals_.Area is None:
            return

        if area_num is not None:
            try:
                area_num = int(area_num)
            except Exception:
                area_num = None

        slot_map = []
        if area_num is not None:
            try:
                level_bytes = globals_.Level.save() if globals_.Level is not None else None
            except Exception:
                level_bytes = None
            if level_bytes:
                slot_map = self._GetTilesetSlotsFromLevelData(level_bytes, area_num)

        if not slot_map:
            slot_map = [(slot, self._GetTilesetNameForSlot(slot)) for slot in range(4)]

        for slot, name in slot_map:
            if not name:
                continue

            override_path = self._EnsureTilesetOverrideFile(name)
            if not override_path or not os.path.isfile(override_path):
                continue
            try:
                with open(override_path, 'rb') as f:
                    data = f.read()
            except Exception:
                continue

            payload = self._PackTilesetPayload(name, data, slots=[int(slot)])
            try:
                if self.collabManager.send_message_to(peer_session_id, 'tileset_data', payload):
                    continue
            except Exception:
                pass
            # Fallback: broadcast to all peers.
            try:
                self.collabManager.broadcast_message('tileset_data', payload)
            except Exception:
                pass

    def _HostBroadcastTilesetsToAllPeers(self):
        """
        Host-side helper: broadcast the current area's tilesets to all peers.
        This ensures that newly connected clients get the host tilesets without
        needing to click "Edit" first or rely on their own game dump matching.
        """
        if not self._CollabEnabled() or getattr(self.collabManager, 'mode', None) != 'host':
            return
        if globals_.Area is None:
            return

        for slot in range(4):
            name = self._GetTilesetNameForSlot(slot)
            if not name:
                continue
            override_path = self._EnsureTilesetOverrideFile(name)
            if not override_path or not os.path.isfile(override_path):
                continue
            try:
                with open(override_path, 'rb') as f:
                    data = f.read()
            except Exception:
                continue
            payload = self._PackTilesetPayload(name, data, slots=self._GetTilesetSlotsForName(name))
            try:
                self.collabManager.broadcast_message('tileset_data', payload)
            except Exception:
                pass

    def _DecodeTilesetPayload(self, payload):
        if not isinstance(payload, dict):
            return None, None, None
        name = str(payload.get('name') or '')
        if not name:
            return None, None, None
        b64 = payload.get('data')
        if not b64:
            return None, None, None
        try:
            compressed = base64.b64decode(b64)
            data = zlib.decompress(compressed)
        except Exception:
            return None, None, None
        slots = payload.get('slots') or []
        if not isinstance(slots, list):
            slots = []
        slots = [int(x) for x in slots if isinstance(x, (int, float, str)) and str(x).isdigit()]
        return name, data, slots

    def _ApplyPendingTilesetPayloads(self):
        if not getattr(self, '_collabPendingTilesetPayloads', None):
            return
        if globals_.Area is None or globals_.Level is None:
            return
        pending = list(self._collabPendingTilesetPayloads)
        self._collabPendingTilesetPayloads = []
        for payload, _sender in pending:
            name, data, slots = self._DecodeTilesetPayload(payload)
            if name and data:
                self._ApplyCollabTilesetBytes(name, data, slots=slots, broadcast=False)

    def _GetTilesetNamesFromLevelData(self, level_data, area_num):
        names = []
        try:
            arc = archive.U8.load(level_data)
            course_name = 'course/course%d.bin' % int(area_num)
            course_data = arc[course_name]
            blocks = [None] * 14
            getblock = struct.Struct('>II')
            for i in range(14):
                start, length = getblock.unpack_from(course_data, i * 8)
                blocks[i] = course_data[start:start + length]
            raw_names = struct.unpack('>32s32s32s32s', blocks[0])
            for raw_name in raw_names:
                name = raw_name.strip(b'\0').decode('latin-1')
                if name:
                    names.append(name)
        except Exception:
            return []
        return names

    def _GetTilesetSlotsFromLevelData(self, level_data, area_num):
        slot_map = []
        try:
            arc = archive.U8.load(level_data)
            course_name = 'course/course%d.bin' % int(area_num)
            course_data = arc[course_name]
            blocks = [None] * 14
            getblock = struct.Struct('>II')
            for i in range(14):
                start, length = getblock.unpack_from(course_data, i * 8)
                blocks[i] = course_data[start:start + length]
            raw_names = struct.unpack('>32s32s32s32s', blocks[0])
            for idx, raw_name in enumerate(raw_names):
                name = raw_name.strip(b'\0').decode('latin-1')
                if name:
                    slot_map.append((idx, name))
        except Exception:
            return []
        return slot_map

    def _SetCollabMissingTilesetWarningsSuppressed(self, suppressed):
        globals_.CollabSuppressMissingTilesetWarnings = bool(suppressed)

    def _HasCollabTilesetAvailable(self, name):
        name = str(name or '').strip()
        if not name:
            return True

        overrides = getattr(globals_, 'CollabTilesetOverrides', None)
        if isinstance(overrides, dict):
            override_path = str(overrides.get(name) or '')
            if override_path and os.path.isfile(override_path):
                return True

        data, _src = self._ReadTilesetArcFromGame(name)
        return bool(data)

    def _GetMissingTilesetsForLevelData(self, level_data, area_num):
        missing = []
        for name in self._GetTilesetNamesFromLevelData(level_data, area_num):
            if not self._HasCollabTilesetAvailable(name):
                missing.append(name)
        return missing

    def _ShowStartupModeDialog(self):
        dlg = QtWidgets.QDialog(None, QtCore.Qt.WindowType.Window)
        dlg.setWindowTitle('Reggie Next')
        dlg.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        layout = QtWidgets.QVBoxLayout(dlg)

        text = QtWidgets.QLabel('What would you like to do?')
        layout.addWidget(text)

        info = QtWidgets.QLabel('Choose whether to open a level or connect to Collaboration.')
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QtWidgets.QFormLayout()
        nick_edit = QtWidgets.QLineEdit(str(getattr(self, 'collabSelfNick', getattr(globals_, 'CollabNickname', 'Player')) or 'Player'))
        nick_edit.setMaxLength(32)
        color_value = {'value': normalize_collab_color(getattr(self, 'collabSelfHighlightColor', DEFAULT_COLLAB_HIGHLIGHT_COLOR))}
        color_button = QtWidgets.QPushButton(color_value['value'])
        color_button.setStyleSheet(collab_color_button_stylesheet(color_value['value']))

        def choose_color():
            chosen = self._ChooseCollabHighlightColor(color_value['value'], dlg)
            if not chosen:
                return
            color_value['value'] = chosen
            color_button.setText(chosen)
            color_button.setStyleSheet(collab_color_button_stylesheet(chosen))

        color_button.clicked.connect(choose_color)
        nick_row = QtWidgets.QHBoxLayout()
        nick_row.setContentsMargins(0, 0, 0, 0)
        nick_row.setSpacing(6)
        nick_row.addWidget(nick_edit, 1)
        nick_row.addWidget(color_button)
        form.addRow('Nickname:', nick_row)
        layout.addLayout(form)

        choice = {'value': 'exit', 'path': None}
        last_level = str(setting('LastLevel', '') or '').strip()
        has_recent_files = any(os.path.isfile(path) for path in getattr(self.RecentMenu, 'FileList', []))
        has_backups = any(
            filename.lower().endswith('.rgl')
            for filename in os.listdir(self._GetBackupsDir())
        )

        button_row = QtWidgets.QHBoxLayout()
        open_btn = QtWidgets.QPushButton('Open Level')
        join_btn = QtWidgets.QPushButton('Connect to Collaboration')
        exit_btn = QtWidgets.QPushButton('Exit')
        button_row.addWidget(open_btn)
        button_row.addWidget(join_btn)
        button_row.addStretch(1)
        button_row.addWidget(exit_btn)
        layout.addLayout(button_row)

        quick_row = QtWidgets.QHBoxLayout()
        recent_btn = QtWidgets.QPushButton('Recent')
        backups_btn = QtWidgets.QPushButton('Backups')
        recent_btn.setMinimumHeight(36)
        backups_btn.setMinimumHeight(36)
        recent_btn.setEnabled(has_recent_files)
        backups_btn.setEnabled(has_backups)
        quick_row.addWidget(recent_btn)
        quick_row.addWidget(backups_btn)
        layout.addLayout(quick_row)

        last_btn = QtWidgets.QPushButton('Open Last File')
        last_btn.setMinimumHeight(42)
        last_btn.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        if not last_level:
            last_btn.setEnabled(False)
            last_btn.setText('Open Last File (unavailable)')
        layout.addWidget(last_btn)

        def finish(result, path=None):
            self.SetCollabNickname(nick_edit.text(), broadcast=False)
            self.SetCollabHighlightColor(color_value['value'], broadcast=False)
            choice['value'] = result
            choice['path'] = path
            dlg.accept()

        def pick_recent():
            path = self._ShowStartupRecentFilesDialog()
            if path:
                finish('recent', path)

        def pick_backup():
            path = self._ShowStartupBackupsDialog()
            if path:
                finish('backup', path)

        open_btn.clicked.connect(lambda: finish('open'))
        join_btn.clicked.connect(lambda: finish('join'))
        exit_btn.clicked.connect(lambda: finish('exit'))
        recent_btn.clicked.connect(pick_recent)
        backups_btn.clicked.connect(pick_backup)
        last_btn.clicked.connect(lambda: finish('last'))
        last_btn.setDefault(True)
        last_btn.setAutoDefault(True)
        last_btn.setFocus()
        dlg.exec()
        return choice['value'], choice['path']

    def _HasConfiguredGamePaths(self):
        stage_path = str(globals_.gamedef.GetStageGamePath() or '').strip()
        texture_path = str(globals_.gamedef.GetTextureGamePath() or '').strip()
        return bool(stage_path and texture_path and os.path.isdir(stage_path) and os.path.isdir(texture_path))

    def _EnsureGamePathsForLevelOpen(self):
        if self._HasConfiguredGamePaths():
            return True
        return self.HandleChangeGamePath(True)

    def _StartupOpenPath(self, path, title='Open Level'):
        if not path:
            return None
        if not os.path.isfile(path):
            QtWidgets.QMessageBox.warning(self, title, 'The selected file could not be found:\n%s' % path)
            return None
        return self.LoadLevel(str(path), True, 1)

    def _ShowStartupPathPickerDialog(self, title, description, headers, entries, empty_message):
        if not entries:
            QtWidgets.QMessageBox.information(self, title, empty_message)
            return None

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setModal(True)
        layout = QtWidgets.QVBoxLayout(dlg)

        info = QtWidgets.QLabel(description)
        info.setWordWrap(True)
        layout.addWidget(info)

        tree = QtWidgets.QTreeWidget()
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        tree.setColumnCount(len(headers))
        tree.setHeaderLabels(headers)
        tree.setSortingEnabled(False)
        header = tree.header()
        header.setStretchLastSection(True)
        for idx in range(max(0, len(headers) - 1)):
            header.setSectionResizeMode(idx, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)

        for columns, path in entries:
            item = QtWidgets.QTreeWidgetItem([str(col) for col in columns])
            item.setData(0, Qt.ItemDataRole.UserRole, str(path))
            tree.addTopLevelItem(item)

        if tree.topLevelItemCount():
            tree.setCurrentItem(tree.topLevelItem(0))
        layout.addWidget(tree)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Open | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        open_btn = button_box.button(QtWidgets.QDialogButtonBox.StandardButton.Open)
        open_btn.setEnabled(tree.currentItem() is not None)
        button_box.accepted.connect(dlg.accept)
        button_box.rejected.connect(dlg.reject)
        tree.itemDoubleClicked.connect(lambda *_: dlg.accept())
        tree.itemSelectionChanged.connect(lambda: open_btn.setEnabled(tree.currentItem() is not None))
        layout.addWidget(button_box)

        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None

        current = tree.currentItem()
        if current is None:
            return None
        return str(current.data(0, Qt.ItemDataRole.UserRole))

    def _ShowStartupRecentFilesDialog(self):
        entries = []
        for path in getattr(self.RecentMenu, 'FileList', []):
            if not os.path.isfile(path):
                continue
            entries.append(((os.path.basename(path), os.path.dirname(path) or path), path))

        return self._ShowStartupPathPickerDialog(
            'Recent Files',
            'Choose a recently opened level.',
            ['File', 'Location'],
            entries,
            'No recent files are available.',
        )

    def _GetBackupEntries(self):
        entries = []
        backups_dir = self._GetBackupsDir()
        for filename in os.listdir(backups_dir):
            if not filename.lower().endswith('.rgl'):
                continue

            path = os.path.join(backups_dir, filename)
            if not os.path.isfile(path):
                continue

            match = re.match(r'^(?P<level>.+?)_(?P<date>\d{8})_(?P<time>\d{6})\.rgl$', filename, re.IGNORECASE)
            if match:
                date_part = match.group('date')
                time_part = match.group('time')
                timestamp_text = '%s-%s-%s %s:%s:%s' % (
                    date_part[0:4], date_part[4:6], date_part[6:8],
                    time_part[0:2], time_part[2:4], time_part[4:6],
                )
                sort_key = date_part + time_part
                level_name = match.group('level')
            else:
                modified = os.path.getmtime(path)
                timestamp_text = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(modified))
                sort_key = time.strftime('%Y%m%d%H%M%S', time.localtime(modified))
                level_name = os.path.splitext(filename)[0]

            entries.append({
                'path': path,
                'level_name': level_name,
                'timestamp_text': timestamp_text,
                'filename': filename,
                'sort_key': sort_key,
            })

        entries.sort(key=lambda entry: (entry['sort_key'], entry['filename']), reverse=True)
        return entries

    def _ShowStartupBackupsDialog(self):
        entries = [
            ((entry['level_name'], entry['timestamp_text'], entry['filename']), entry['path'])
            for entry in self._GetBackupEntries()
        ]

        return self._ShowStartupPathPickerDialog(
            'Backups',
            'Choose a backup level to open. Entries are sorted by date and time.',
            ['Level', 'Date / Time', 'File'],
            entries,
            'No backup files were found in the Backups folder.',
        )

    def _StartupOpenLastLevel(self):
        last_level = str(setting('LastLevel', '') or '').strip()
        if not last_level:
            QtWidgets.QMessageBox.information(self, 'Open Last File', 'No last file is saved in settings.')
            return None
        return self._StartupOpenPath(last_level, 'Open Last File')

    def _ShowStartupOpenModeDialog(self):
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Question)
        box.setWindowTitle('Open Level')
        box.setText('How would you like to open the level?')
        name_btn = box.addButton('By Name', QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        file_btn = box.addButton('From File', QtWidgets.QMessageBox.ButtonRole.ActionRole)
        back_btn = box.addButton('Back', QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(name_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked == name_btn:
            return 'name'
        if clicked == file_btn:
            return 'file'
        return 'back'

    def _StartupOpenLevelFromName(self):
        if not self._EnsureGamePathsForLevelOpen():
            return None
        LoadLevelNames()
        dlg = ChooseLevelNameDialog()
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        return self.LoadLevel(dlg.currentlevel, False, 1)

    def _StartupOpenLevelFromFile(self, startup_level_arg=None):
        if not self._EnsureGamePathsForLevelOpen():
            return None

        if startup_level_arg and os.path.isfile(str(startup_level_arg)):
            return self.LoadLevel(str(startup_level_arg), True, 1)

        filetypes = ''
        filetypes += globals_.trans.string('FileDlgs', 9) + ' (*.arc *.arc.LH *.arc.LZ *.rgl);;'
        filetypes += globals_.trans.string('FileDlgs', 1) + ' (*.arc);;'
        filetypes += globals_.trans.string('FileDlgs', 5) + ' (*.arc.LH);;'
        filetypes += globals_.trans.string('FileDlgs', 10) + ' (*.arc.LZ);;'
        filetypes += globals_.trans.string('FileDlgs', 11) + ' (*.rgl);;'
        filetypes += globals_.trans.string('FileDlgs', 2) + ' (*)'
        fn = QtWidgets.QFileDialog.getOpenFileName(self, globals_.trans.string('FileDlgs', 0), '', filetypes)[0]
        if fn == '':
            return None
        return self.LoadLevel(str(fn), True, 1)

    def RunStartupFlow(self, startup_level_arg=None):
        while True:
            action, selected_path = self._ShowStartupModeDialog()
            if action == 'open':
                while True:
                    open_mode = self._ShowStartupOpenModeDialog()
                    if open_mode == 'name':
                        loaded = self._StartupOpenLevelFromName()
                    elif open_mode == 'file':
                        loaded = self._StartupOpenLevelFromFile(startup_level_arg)
                    else:
                        break

                    if loaded is None:
                        continue
                    if loaded:
                        return True
                    continue

            elif action == 'join':
                if globals_.Level is None or globals_.Area is None:
                    if not self.LoadLevel(None, False, 1):
                        return False
                    globals_.Dirty = False
                    globals_.AutoSaveDirty = False
                    self.UpdateTitle()

                self.HandleCollabJoin()
                if self.collabManager.mode == "client":
                    self.UpdateSaveActionsForCollabMode()
                    return True
            elif action == 'recent':
                loaded = self._StartupOpenPath(selected_path, 'Recent Files')
                if loaded is None:
                    continue
                if loaded:
                    return True
            elif action == 'backup':
                loaded = self._StartupOpenPath(selected_path, 'Backups')
                if loaded is None:
                    continue
                if loaded:
                    return True
            elif action == 'last':
                loaded = self._StartupOpenLastLevel()
                if loaded is None:
                    continue
                if loaded:
                    return True
            else:
                self._startupExitRequested = True
                return False

    def HandleCollaborationStatus(self, message):
        self.UpdateSaveActionsForCollabMode()
        if hasattr(self, 'hoverLabel'):
            self.hoverLabel.setText(message)
        if message.startswith('Hosting room') or message.startswith('Connected to'):
            self._BroadcastCollabNick()
            self._EnsureChatWindow()
            try:
                self.collabWindow.setExpanded(False)
            except Exception:
                pass
            if message.startswith('Connected to') and self.IsCollabClientMode():
                # Request tilesets early; client game files may differ from host.
                self._ScheduleCollabTilesetSync(250)
        if message.startswith('Peer connected'):
            if hasattr(self, 'collabManager') and self.collabManager.mode == "host":
                self.collabManager.broadcast_message('host_hello', {'host': self.collabManager.session_id})
                self._BroadcastCollabNick()
            self.BroadcastFullLevelSnapshot()
            self.BroadcastFullSceneState()
            self.BroadcastFullMetaState()
            # Send current tilesets proactively so clients don't rely on their
            # local game files matching the host.
            try:
                self._HostBroadcastTilesetsToAllPeers()
            except Exception:
                pass
        if message.startswith('Disconnected from host') or message.startswith('Collaboration stopped'):
            self.collabPeerNicks = {}
            self.collabPeerColors = {}
            self.collabRemoteCursors = {}
            self.collabCursorPKeyHeld = False
            self.collabLastBroadcastCursorAt = 0.0
            self.collabLastBroadcastCursorPos = None
            self._CollabSetPeerNick(getattr(self.collabManager, 'session_id', ''), getattr(self, 'collabSelfNick', 'Player'))
            self._CollabSetPeerColor(getattr(self.collabManager, 'session_id', ''), getattr(self, 'collabSelfHighlightColor', DEFAULT_COLLAB_HIGHLIGHT_COLOR))
        self._UpdateChatEnabled()
        self._RefreshCollabUi()
        self.UpdateTitle()

    def HandleCollaborationPeerCount(self, count):
        try:
            self.collabOnlineCount = int(count)
        except Exception:
            self.collabOnlineCount = 0
        self._RefreshCollabUi()

    def UpdateCollaborationMenuTitle(self):
        if not hasattr(self, 'collabMenu'):
            return
        count = len(self.collabParticipants) if getattr(self, 'collabParticipants', None) else int(getattr(self, 'collabOnlineCount', 0) or 0)
        if hasattr(self, 'collabManager') and self.collabManager.mode is not None and count:
            self.collabMenu.setTitle('Collaboration (%d)' % count)
        else:
            self.collabMenu.setTitle('Collaboration')

    def _NormalizeCollabGameDefId(self, game_def_id):
        if game_def_id in (None, '', 'None', False, 0):
            return ''
        return str(game_def_id)

    def _CurrentCollabGameDefId(self):
        try:
            if getattr(globals_.gamedef, 'custom', False):
                return self._NormalizeCollabGameDefId(getattr(globals_.gamedef, 'gamepath', None))
        except Exception:
            pass
        return ''

    def _GetCollabGamePluginHash(self, game_def_id=None):
        normalized_id = self._NormalizeCollabGameDefId(game_def_id)
        if not normalized_id:
            return 'builtin-nsmbw'

        cache = getattr(self, '_collabGamePluginHashCache', None)
        if cache is None:
            self._collabGamePluginHashCache = {}
            cache = self._collabGamePluginHashCache
        if normalized_id in cache:
            return cache[normalized_id]

        patch_dir = os.path.join('reggiedata', 'patches', normalized_id)
        if not os.path.isdir(patch_dir):
            return ''

        digest = hashlib.sha256()
        digest.update(b'reggie-collab-game-plugin-v1\0')

        for root, dirs, files in os.walk(patch_dir):
            dirs[:] = [name for name in sorted(dirs) if name != '__pycache__']
            for filename in sorted(files):
                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, patch_dir).replace('\\', '/')
                digest.update(rel_path.encode('utf-8', 'surrogatepass'))
                digest.update(b'\0')
                try:
                    with open(file_path, 'rb') as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            digest.update(chunk)
                except OSError:
                    return ''
                digest.update(b'\0')

        value = digest.hexdigest()
        cache[normalized_id] = value
        return value

    def _BuildCollabRoomInfo(self):
        game_id = self._CurrentCollabGameDefId()
        try:
            game_name = str(getattr(globals_.gamedef, 'name', '') or '')
        except Exception:
            game_name = ''

        if not game_name:
            try:
                game_name = str(ReggieGameDefinition(game_id or None).name)
            except Exception:
                game_name = 'Unknown game'

        return {
            'game_id': game_id,
            'game_name': game_name,
            'game_plugin_hash': self._GetCollabGamePluginHash(game_id),
            'game_is_custom': bool(game_id),
        }

    def _HasUsableCollabHostGameInfo(self, host_info):
        if not isinstance(host_info, dict):
            return False
        return any(key in host_info for key in ('game_id', 'game_name', 'game_plugin_hash', 'game_is_custom'))

    def _ValidateCollabPeerIntro(self, payload, meta):
        host_info = self._BuildCollabRoomInfo()
        host_game_id = self._NormalizeCollabGameDefId(host_info.get('game_id'))
        peer_game_id = self._NormalizeCollabGameDefId(payload.get('game_id'))

        if peer_game_id != host_game_id:
            return 'Connection rejected. Host game: %s.' % str(host_info.get('game_name') or 'Unknown game')

#       if bool(host_info.get('game_is_custom')):
#           host_hash = str(host_info.get('game_plugin_hash') or '')
#           peer_hash = str(payload.get('game_plugin_hash') or '')
#           if (not host_hash) or (peer_hash != host_hash):
#               return 'Connection rejected. Plugin checksum mismatch for game "%s".' % str(host_info.get('game_name') or 'Unknown game')

        return None

    def _SetCheckedGameDefAction(self, game_def_id):
        if not hasattr(self, 'GameDefMenu'):
            return
        self.GameDefMenu.update_flag = True
        try:
            for act in self.GameDefMenu.actGroup.actions():
                act.setChecked(act.data() == game_def_id)
        finally:
            self.GameDefMenu.update_flag = False
        try:
            self.GameDefMenu.gameChanged.emit()
        except Exception:
            pass

    def _LoadCollabGameDef(self, game_def_id):
        dlg = QtWidgets.QProgressDialog()
        dlg.setAutoClose(True)
        btn = QtWidgets.QPushButton('Cancel')
        btn.setEnabled(False)
        dlg.setCancelButton(btn)
        dlg.show()
        dlg.setValue(0)

        try:
            self._SetCollabMissingTilesetWarningsSuppressed(True)
            result = LoadGameDef(game_def_id, dlg, prompt_for_stage_path=False)
        finally:
            self._SetCollabMissingTilesetWarningsSuppressed(False)

        dlg.setValue(100)
        if result:
            setSetting('LastGameDef', game_def_id)
            self._SetCheckedGameDefAction(game_def_id)
        return result

    def _EnsureCollabGameMatchesHost(self, host_info):
        if not self._HasUsableCollabHostGameInfo(host_info):
            # Some hosts or network paths do not provide pre-connect room info.
            # Do not block the connection here: the host will still validate the
            # joining peer after connect via peer_intro.
            return True

        host_game_id = self._NormalizeCollabGameDefId(host_info.get('game_id'))
        host_game_name = str(host_info.get('game_name') or 'Unknown game')
        host_plugin_hash = str(host_info.get('game_plugin_hash') or '')
        host_is_custom = bool(host_info.get('game_is_custom'))

        dlg = CollaborationGameSelectDialog(host_info, self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return False

        selected_game_def = dlg.selectedGameDef()
        if self._NormalizeCollabGameDefId(selected_game_def) != host_game_id:
            return False

        if self._CurrentCollabGameDefId() != host_game_id:
            if not self._LoadCollabGameDef(selected_game_def):
                QtWidgets.QMessageBox.warning(
                    self,
                    'Collaboration',
                    'Unable to load the host game without connecting.\nHost game: %s' % host_game_name,
                )
                return False

        local_info = self._BuildCollabRoomInfo()
        if self._NormalizeCollabGameDefId(local_info.get('game_id')) != host_game_id:
            QtWidgets.QMessageBox.warning(
                self,
                'Collaboration',
                'Selected game does not match the host.\nHost game: %s' % host_game_name,
            )
            return False

#       if host_is_custom:
#           local_hash = str(local_info.get('game_plugin_hash') or '')
#           if (not host_plugin_hash) or (local_hash != host_plugin_hash):
#               QtWidgets.QMessageBox.warning(
#                   self,
#                   'Collaboration',
#                   'Plugin checksum mismatch.\nHost game: %s' % host_game_name,
#               )
#               return False

        return True

    def HandleCollabHost(self):
        default_mode = str(setting('CollabHostMode', 'lan') or 'lan')
        default_name = "%s's room" % str(getattr(self, 'collabSelfNick', getattr(globals_, 'CollabNickname', 'Player')) or 'Player')
        dlg = CollaborationHostDialog(self, 35000, default_mode=default_mode, default_name=default_name)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        config = dlg.selectedConfig()
        port = int(config.get('port', 35000) or 35000)
        self.collabManager.set_local_nickname(getattr(self, 'collabSelfNick', getattr(globals_, 'CollabNickname', 'Player')))
        self.collabManager.set_local_highlight_color(getattr(self, 'collabSelfHighlightColor', DEFAULT_COLLAB_HIGHLIGHT_COLOR))
        try:
            self.collabManager.start_host(port, room_mode=config.get('mode', 'lan'), public_room_config=config)
        except (OSError, ValueError) as e:
            try:
                self.collabManager.stop()
            except Exception:
                pass
            QtWidgets.QMessageBox.warning(self, 'Collaboration', 'Unable to host room:\n%s' % str(e))
            return
        self.BroadcastFullLevelSnapshot()
        self._RefreshCollabUi()

    def HandleCollabJoin(self):
        default_source = str(setting('CollabJoinSource', 'lan') or 'lan')
        dlg = CollaborationServerPickerDialog(self, 35000, default_source=default_source)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        source = dlg.selectedSource()
        host, port = dlg.selectedHost()
        host_info = dlg.selectedHostInfo()

        if source == 'online' and host_info is not None:
            password = ''
            if bool(host_info.get('requires_password')):
                password, ok = QtWidgets.QInputDialog.getText(
                    self,
                    'Enter public room password',
                    'This public room requires a password:',
                    QtWidgets.QLineEdit.EchoMode.Password,
                )
                if not ok:
                    return
            resolved_host = CollaborationManager.resolve_public_room_host(host_info, password=password)
            if not resolved_host:
                QtWidgets.QMessageBox.warning(self, 'Collaboration', 'Unable to resolve the selected public room. Check the password and try again.')
                return
            room_method = str(host_info.get('method') or 'direct').strip().lower() or 'direct'
            host = resolved_host
            lan_match = CollaborationManager.find_matching_lan_host_for_public_room(host_info, resolved_host)
            if lan_match is not None:
                host = str(lan_match.get('host') or resolved_host).strip()
                port = int(lan_match.get('port', port) or port)
                host_info = lan_match
                room_method = 'direct'
        elif host_info is None:
            host_info = CollaborationManager.probe_host(host.strip(), port)
            room_method = 'direct'
        else:
            room_method = 'direct'

        if self._HasUsableCollabHostGameInfo(host_info) and not self._EnsureCollabGameMatchesHost(host_info):
            return
        self.collabManager.set_local_nickname(getattr(self, 'collabSelfNick', getattr(globals_, 'CollabNickname', 'Player')))
        self.collabManager.set_local_highlight_color(getattr(self, 'collabSelfHighlightColor', DEFAULT_COLLAB_HIGHLIGHT_COLOR))
        try:
            if source == 'online' and room_method == 'traversal':
                self.collabManager.connect_to_public_host(host.strip(), bind_port=port)
            else:
                self.collabManager.connect_to_host(host.strip(), port)
        except OSError as e:
            error_text = str(e)
            if source == 'online':
                if room_method == 'traversal':
                    error_text += '\n\nThis public room uses Dolphin Traversal. If the host is on your LAN, refresh the LAN list and try the direct local room instead.'
                else:
                    error_text += '\n\nThis public room uses direct TCP. If you are on the same LAN as the host, refresh the LAN list or check that the host stays visible there. If you are outside the LAN, make sure the host port is open in the firewall/router.'
            QtWidgets.QMessageBox.warning(self, 'Collaboration', 'Unable to join room:\n%s' % error_text)
            return
        # Do not broadcast immediately on join: wait for host snapshot to avoid
        # racing initial state with client's local copy.
        self._RefreshCollabUi()

    def HandleCollabStop(self):
        if hasattr(self, 'collabManager'):
            self.collabManager.stop()
        try:
            self._CollabClearRemoteSelections()
        except Exception:
            pass
        self.collabRemoteCursors = {}
        self.collabCursorPKeyHeld = False
        self.collabLastBroadcastCursorAt = 0.0
        self.collabLastBroadcastCursorPos = None
        self.UpdateSaveActionsForCollabMode()
        self._RefreshCollabUi()

    def CollaborationSyncTick(self):
        if not hasattr(self, 'collabManager') or self.collabManager.mode is None:
            return
        if getattr(self, 'collabSwitchingArea', False):
            return
        self.TryApplyPendingRemoteSnapshot()
        for _ in range(64):
            if not self.TryApplyPendingRemoteMessage():
                break
        if self.collabApplyingRemote:
            return
        if globals_.Level is None or globals_.Area is None:
            return

        self._MaybeBroadcastCollabCursorState()

        current_level_name = os.path.basename(self.fileSavePath) if self.fileSavePath else None
        if self.collabManager.mode == "host" and self.collabLastLevelName is not None and current_level_name != self.collabLastLevelName:
            self.collabManager.broadcast_message('level_switch', {
                'level_name': current_level_name,
                'area_num': globals_.Area.areanum,
            })
            self.BroadcastFullLevelSnapshot()
            self.BroadcastFullSceneState()
        self.collabLastLevelName = current_level_name

    def BroadcastFullLevelSnapshot(self):
        if globals_.Level is None or globals_.Area is None:
            return
        try:
            level_data = globals_.Level.save()
        except Exception:
            return
        self.collabLastHash = hash(level_data)
        self.collabLastSentHash = self.collabLastHash
        self.collabLastSceneSig = hash(repr(self.BuildCollabSceneState()))
        self.collabLastLevelName = os.path.basename(self.fileSavePath) if self.fileSavePath else None
        self.collabManager.broadcast_snapshot(level_data, globals_.Area.areanum)

    def _CollabEnabled(self):
        return hasattr(self, 'collabManager') and self.collabManager.mode is not None

    def _CollabHistoryEnabled(self):
        # Shared distributed undo/redo history replication (delta). History is
        # synchronized independently of scene snapshots.
        return self._CollabEnabled() and bool(getattr(self, '_collabSharedHistoryEnabled', False))

    def _CollabHistoryBlocked(self):
        return self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False)

    def CollabHistoryActionAdded(self, act):
        if not self._CollabHistoryEnabled() or self._CollabHistoryBlocked():
            return
        # Host is authoritative for history ordering; clients submit history via
        # `_CollabClientHandleUndoAction`.
        if self.IsCollabClientMode():
            return
        from undo import serialize_undo_action
        payload = serialize_undo_action(act)
        if not isinstance(payload, dict):
            return
        act_id = str(payload.get('id') or '')
        if act_id:
            self._collabHistorySeen.add(act_id)
        self._collabHistoryRev = int(getattr(self, '_collabHistoryRev', 0) or 0) + 1
        self.collabManager.broadcast_message('hist_add', {
            'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
            'level_name': self._CollabCurrentLevelName(),
            'rev': int(self._collabHistoryRev),
            'origin': str(getattr(self.collabManager, 'session_id', '') or ''),
            'action': payload,
        })

    def CollabHistoryActionUpdated(self, act):
        if not self._CollabHistoryEnabled() or self._CollabHistoryBlocked():
            return
        if self.IsCollabClientMode():
            return
        from undo import serialize_undo_action
        payload = serialize_undo_action(act)
        if not isinstance(payload, dict):
            return
        act_id = str(payload.get('id') or '')
        if act_id:
            self._collabHistorySeen.add(act_id)
        self._collabHistoryRev = int(getattr(self, '_collabHistoryRev', 0) or 0) + 1
        self.collabManager.broadcast_message('hist_upd', {
            'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
            'level_name': self._CollabCurrentLevelName(),
            'rev': int(self._collabHistoryRev),
            'origin': str(getattr(self.collabManager, 'session_id', '') or ''),
            'action': payload,
        })

    def _CollabClientHandleUndoAction(self, act, allow_extend=False):
        """
        Called from UndoStack (undo.py). In collaboration client mode we submit
        undo actions to the host instead of immediately mutating the local stack.
        Returns True if handled.
        """
        try:
            if not self._CollabHistoryEnabled() or self._CollabHistoryBlocked():
                return False
            if not self.IsCollabClientMode():
                return False
        except Exception:
            return False

        from undo import serialize_undo_action

        pending = getattr(self, '_collabPendingHistory', None)
        last_id = getattr(self, '_collabPendingHistoryLastId', None)
        if pending is None:
            pending = {}
            self._collabPendingHistory = pending
        action_id = str(getattr(act, 'action_id', '') or '')

        # Try extending the last pending action (dragging/multiple edits).
        if allow_extend and last_id and last_id in pending:
            prev = pending.get(last_id)
            try:
                if prev is not None and prev.isExtentionOf(act):
                    prev.extend(act)
                    upd = serialize_undo_action(prev)
                    if isinstance(upd, dict):
                        self._CollabSubmitHistoryMessage('hist_submit_upd', upd)
                        return True
            except Exception:
                pass

        payload = serialize_undo_action(act)
        if not isinstance(payload, dict):
            return False
        if not action_id:
            action_id = str(payload.get('id') or '')
        if not action_id:
            return False

        pending[action_id] = act
        self._collabPendingHistoryLastId = action_id
        self._CollabSubmitHistoryMessage('hist_submit_add', payload)
        return True

    def _CollabSubmitHistoryMessage(self, msg_type, action_payload):
        if not self._CollabEnabled() or not self.IsCollabClientMode():
            return
        if not isinstance(action_payload, dict):
            return
        self.collabManager.broadcast_message(msg_type, {
            'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
            'level_name': self._CollabCurrentLevelName(),
            'action': action_payload,
        })

    def _CollabPeekNextUndoActionId(self):
        for act in reversed(self.undoStack.pastActions or []):
            try:
                if act is not None and not act.isNull():
                    return str(getattr(act, 'action_id', '') or '')
            except Exception:
                continue
        return ''

    def _CollabPeekNextRedoActionId(self):
        for act in reversed(self.undoStack.futureActions or []):
            try:
                if act is not None and not act.isNull():
                    return str(getattr(act, 'action_id', '') or '')
            except Exception:
                continue
        return ''

    def _CollabClearPendingHistory(self, action_id):
        action_id = str(action_id or '')
        if not action_id:
            return
        pending = getattr(self, '_collabPendingHistory', None)
        if not isinstance(pending, dict) or not pending:
            return
        pending.pop(action_id, None)
        if getattr(self, '_collabPendingHistoryLastId', None) == action_id:
            self._collabPendingHistoryLastId = None

    def _CollabRequestHistorySync(self):
        if not self._CollabEnabled() or not self.IsCollabClientMode():
            return
        self.collabManager.broadcast_message('hist_sync_req', {
            'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
            'level_name': self._CollabCurrentLevelName(),
        })

    def _CollabBuildHistoryStatePayload(self):
        from undo import serialize_undo_action
        past = []
        future = []
        for act in self.undoStack.pastActions or []:
            payload = serialize_undo_action(act)
            if isinstance(payload, dict):
                past.append(payload)
        for act in self.undoStack.futureActions or []:
            payload = serialize_undo_action(act)
            if isinstance(payload, dict):
                future.append(payload)
        return {
            'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
            'level_name': self._CollabCurrentLevelName(),
            'rev': int(getattr(self, '_collabHistoryRev', 0) or 0),
            'past': past,
            'future': future,
        }

    def _CollabHostSendHistoryStateToPeer(self, peer_session_id):
        if not self._CollabEnabled() or getattr(self.collabManager, 'mode', None) != 'host':
            return
        peer_session_id = str(peer_session_id or '')
        if not peer_session_id:
            return
        try:
            self.collabManager.send_message_to(peer_session_id, 'hist_state', self._CollabBuildHistoryStatePayload())
        except Exception:
            pass

    def _CollabHostHandleHistorySubmitAdd(self, payload, sender):
        if not self._CollabEnabled() or getattr(self.collabManager, 'mode', None) != 'host':
            return
        action_data = payload.get('action')
        if not isinstance(action_data, dict):
            return
        from undo import deserialize_undo_action, serialize_undo_action
        act = deserialize_undo_action(action_data)
        if act is None:
            return
        act_payload = serialize_undo_action(act)
        if not isinstance(act_payload, dict):
            return
        act_id = str(act_payload.get('id') or getattr(act, 'action_id', '') or '')
        if act_id:
            self._collabHistorySeen.add(act_id)

        self.collabApplyingRemoteHistory = True
        try:
            self.undoStack.addAction(act)
        finally:
            self.collabApplyingRemoteHistory = False

        self._collabHistoryRev = int(getattr(self, '_collabHistoryRev', 0) or 0) + 1
        self.collabManager.broadcast_message('hist_add', {
            'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
            'level_name': self._CollabCurrentLevelName(),
            'rev': int(self._collabHistoryRev),
            'origin': str(sender or ''),
            'action': act_payload,
        })

    def _CollabHostHandleHistorySubmitUpdate(self, payload, sender):
        if not self._CollabEnabled() or getattr(self.collabManager, 'mode', None) != 'host':
            return
        action_data = payload.get('action')
        if not isinstance(action_data, dict):
            return
        act_id = str(action_data.get('id') or '')
        if not act_id:
            return
        from undo import deserialize_undo_action, serialize_undo_action
        act = deserialize_undo_action(action_data)
        if act is None:
            return

        self.collabApplyingRemoteHistory = True
        try:
            replaced = False
            for idx, existing in enumerate(self.undoStack.pastActions):
                if str(getattr(existing, 'action_id', '')) == act_id:
                    self.undoStack.pastActions[idx] = act
                    replaced = True
                    break
            if not replaced:
                for idx, existing in enumerate(self.undoStack.futureActions):
                    if str(getattr(existing, 'action_id', '')) == act_id:
                        self.undoStack.futureActions[idx] = act
                        replaced = True
                        break
            if replaced:
                self.undoStack.enableOrDisableMenuItems()
        finally:
            self.collabApplyingRemoteHistory = False

        if not replaced:
            return

        act_payload = serialize_undo_action(act)
        if not isinstance(act_payload, dict):
            return

        self._collabHistorySeen.add(act_id)
        self._collabHistoryRev = int(getattr(self, '_collabHistoryRev', 0) or 0) + 1
        self.collabManager.broadcast_message('hist_upd', {
            'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
            'level_name': self._CollabCurrentLevelName(),
            'rev': int(self._collabHistoryRev),
            'origin': str(sender or ''),
            'action': act_payload,
        })

    def _CollabHostBroadcastUndo(self, origin=''):
        if not self._CollabEnabled() or getattr(self.collabManager, 'mode', None) != 'host':
            return
        target_id = self._CollabPeekNextUndoActionId()
        if not target_id:
            return
        self.collabApplyingRemoteHistory = True
        try:
            self.undoStack.undo()
        finally:
            self.collabApplyingRemoteHistory = False

        self._collabHistoryRev = int(getattr(self, '_collabHistoryRev', 0) or 0) + 1
        self.collabManager.broadcast_message('hist_undo', {
            'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
            'level_name': self._CollabCurrentLevelName(),
            'rev': int(self._collabHistoryRev),
            'origin': str(origin or ''),
            'action_id': target_id,
        })

    def _CollabHostBroadcastRedo(self, origin=''):
        if not self._CollabEnabled() or getattr(self.collabManager, 'mode', None) != 'host':
            return
        target_id = self._CollabPeekNextRedoActionId()
        if not target_id:
            return
        self.collabApplyingRemoteHistory = True
        try:
            self.undoStack.redo()
        finally:
            self.collabApplyingRemoteHistory = False

        self._collabHistoryRev = int(getattr(self, '_collabHistoryRev', 0) or 0) + 1
        self.collabManager.broadcast_message('hist_redo', {
            'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
            'level_name': self._CollabCurrentLevelName(),
            'rev': int(self._collabHistoryRev),
            'origin': str(origin or ''),
            'action_id': target_id,
        })

    def _CollabApplyHistoryState(self, payload):
        if not isinstance(payload, dict):
            return
        # Apply only for the currently loaded level/area.
        try:
            area_num = int(payload.get('area_num', 0) or 0)
        except Exception:
            area_num = 0
        level_name = str(payload.get('level_name') or '')
        if area_num and area_num != int(getattr(globals_.Area, 'areanum', 0) or 0):
            return
        if not self._CollabMatchesLevelName(level_name):
            return

        from undo import deserialize_undo_action
        past_raw = payload.get('past')
        fut_raw = payload.get('future')
        past = []
        future = []
        seen = set()
        for entry in past_raw if isinstance(past_raw, list) else []:
            act = deserialize_undo_action(entry)
            if act is None:
                continue
            aid = str(getattr(act, 'action_id', '') or '')
            if aid:
                seen.add(aid)
            past.append(act)
        for entry in fut_raw if isinstance(fut_raw, list) else []:
            act = deserialize_undo_action(entry)
            if act is None:
                continue
            aid = str(getattr(act, 'action_id', '') or '')
            if aid:
                seen.add(aid)
            future.append(act)

        self.collabApplyingRemoteHistory = True
        try:
            self.undoStack.pastActions = past
            self.undoStack.futureActions = future
            self.undoStack.enableOrDisableMenuItems()
            self._collabHistorySeen.update(seen)
            self._collabPendingHistory = {}
            self._collabPendingHistoryLastId = None
            self._collabHistoryLastAppliedRev = int(payload.get('rev', 0) or 0)
        finally:
            self.collabApplyingRemoteHistory = False

    def _ApplyRemoteHistoryAdd(self, payload):
        action_data = payload.get('action')
        if not isinstance(action_data, dict):
            return
        act_id = str(action_data.get('id') or '')
        if act_id and act_id in self._collabHistorySeen:
            return
        from undo import deserialize_undo_action
        act = deserialize_undo_action(action_data)
        if act is None:
            return
        if act_id:
            self._collabHistorySeen.add(act_id)
        self._CollabClearPendingHistory(act_id)
        self.collabApplyingRemoteHistory = True
        try:
            self.undoStack.addAction(act)
        finally:
            self.collabApplyingRemoteHistory = False

    def _ApplyRemoteHistoryUpdate(self, payload):
        action_data = payload.get('action')
        if not isinstance(action_data, dict):
            return
        act_id = str(action_data.get('id') or '')
        if not act_id:
            return
        from undo import deserialize_undo_action
        act = deserialize_undo_action(action_data)
        if act is None:
            return
        self._CollabClearPendingHistory(act_id)
        self.collabApplyingRemoteHistory = True
        try:
            self._collabHistorySeen.add(act_id)
            for idx, existing in enumerate(self.undoStack.pastActions):
                if str(getattr(existing, 'action_id', '')) == act_id:
                    self.undoStack.pastActions[idx] = act
                    self.undoStack.enableOrDisableMenuItems()
                    return
            for idx, existing in enumerate(self.undoStack.futureActions):
                if str(getattr(existing, 'action_id', '')) == act_id:
                    self.undoStack.futureActions[idx] = act
                    self.undoStack.enableOrDisableMenuItems()
                    return
        finally:
            self.collabApplyingRemoteHistory = False

    def _ApplyRemoteHistoryUndo(self, payload):
        target_id = str(payload.get('action_id') or '')
        if not target_id:
            return
        current_id = self._CollabPeekNextUndoActionId()
        if current_id and current_id != target_id:
            self._CollabRequestHistorySync()
            return
        self.collabApplyingRemoteHistory = True
        try:
            self.undoStack.undo()
        finally:
            self.collabApplyingRemoteHistory = False

    def _ApplyRemoteHistoryRedo(self, payload):
        target_id = str(payload.get('action_id') or '')
        if not target_id:
            return
        current_id = self._CollabPeekNextRedoActionId()
        if current_id and current_id != target_id:
            self._CollabRequestHistorySync()
            return
        self.collabApplyingRemoteHistory = True
        try:
            self.undoStack.redo()
        finally:
            self.collabApplyingRemoteHistory = False

    def _QueuePendingRemoteMessage(self, message, sender):
        if not isinstance(message, dict):
            return
        if not hasattr(self, 'collabPendingMessages'):
            self.collabPendingMessages = collections.deque()
        if len(self.collabPendingMessages) >= 2048:
            try:
                self.collabPendingMessages.popleft()
            except Exception:
                pass
        self.collabPendingMessages.append((dict(message), str(sender or '')))

    def TryApplyPendingRemoteMessage(self):
        if not hasattr(self, 'collabPendingMessages') or not self.collabPendingMessages:
            return False
        if self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return False
        if self.IsLocalEditInProgress():
            return False

        message, sender = self.collabPendingMessages.popleft()
        self.HandleRemoteMessage(message, sender)
        return True

    def _ScheduleHostAuthoritativeAreaSync(self, area_num):
        if not self._CollabEnabled() or self.collabManager.mode != "host":
            return
        try:
            area_num = int(area_num)
        except Exception:
            return
        if area_num < 1:
            return

        self._collabAuthoritativeAreas.add(area_num)
        delay_ms = int(getattr(self, '_collabAuthoritativeSyncDelayMs', 450) or 450)
        if delay_ms < 120:
            delay_ms = 120
        due_at = time.monotonic() + (delay_ms / 1000.0)
        prev_due = self._collabAuthoritativeDueByArea.get(area_num, 0.0)
        if due_at < prev_due:
            due_at = prev_due
        self._collabAuthoritativeDueByArea[area_num] = due_at
        self._ArmHostAuthoritativeTimer()

    def _ArmHostAuthoritativeTimer(self):
        if not self._collabAuthoritativeDueByArea:
            try:
                self._collabAuthoritativeTimer.stop()
            except Exception:
                pass
            return

        now = time.monotonic()
        next_due = min(self._collabAuthoritativeDueByArea.values())
        wait_ms = max(0, int((next_due - now) * 1000))
        self._collabAuthoritativeTimer.start(wait_ms)

    def _FlushHostAuthoritativeAreaSync(self):
        if not self._CollabEnabled() or self.collabManager.mode != "host":
            self._collabAuthoritativeAreas = set()
            self._collabAuthoritativeDueByArea = {}
            return
        now = time.monotonic()
        pending = []
        for area_num in sorted(self._collabAuthoritativeAreas):
            due_at = self._collabAuthoritativeDueByArea.get(area_num, 0.0)
            if due_at <= now + 0.01:
                pending.append(area_num)

        if not pending:
            self._ArmHostAuthoritativeTimer()
            return

        for area_num in pending:
            self._collabAuthoritativeAreas.discard(area_num)
            self._collabAuthoritativeDueByArea.pop(area_num, None)
            try:
                self.BroadcastFullStateForArea(area_num)
            except Exception:
                pass
        self._ArmHostAuthoritativeTimer()

    def _CollabCurrentLevelName(self):
        if self.fileSavePath:
            return os.path.basename(self.fileSavePath)
        return str(getattr(self, 'collabLastLevelName', '') or '') or None

    def _CollabMatchesLevelName(self, remote_level_name):
        """
        Returns True if a remote message belongs to the currently synchronized
        collaboration level. When the local side has no file path yet, adopt
        the first incoming remote level name so transient messages like ping and
        selection are not discarded.
        """
        remote_level_name = str(remote_level_name or '')
        if not remote_level_name:
            return True

        local_level_name = str(self._CollabCurrentLevelName() or '')
        if local_level_name:
            return remote_level_name == local_level_name

        try:
            self.collabLastLevelName = remote_level_name
        except Exception:
            pass
        return True

    def _CollabEnsureItemId(self, item):
        if not hasattr(item, '_collab_id'):
            item._collab_id = uuid.uuid4().hex
        return str(getattr(item, '_collab_id', ''))

    def _CollabSelectionItemId(self, item):
        """
        Returns a stable ID used specifically for collaboration selection
        ownership. Entrances and locations use their editor IDs because their
        delta sync is keyed by those IDs, while other items keep using
        `_collab_id`.
        """
        if item is None:
            return ''
        try:
            if isinstance(item, EntranceItem):
                return 'ent:%d' % int(getattr(item, 'entid', 0))
            if isinstance(item, LocationItem):
                return 'loc:%d' % int(getattr(item, 'id', 0))
        except Exception:
            return ''

        try:
            item_id = str(getattr(item, '_collab_id', '') or '')
            if not item_id:
                item_id = str(self._CollabEnsureItemId(item) or '')
            return item_id
        except Exception:
            return ''

    def _CollabEnsurePathNodeId(self, node):
        return self._CollabEnsureItemId(node)

    def _CollabBuildPathNodeState(self, path_obj, node, index=None):
        if path_obj is None or node is None:
            return None
        try:
            if index is None:
                index = int(path_obj.get_index(node))
            else:
                index = int(index)
        except Exception:
            return None
        try:
            speed, accel, delay = path_obj.get_data_for_node(index)
        except Exception:
            speed, accel, delay = (0.5, 0.00498, 0)
        return {
            'node_uid': self._CollabEnsurePathNodeId(node),
            'index': int(index),
            'x': int(getattr(node, 'objx', 0)),
            'y': int(getattr(node, 'objy', 0)),
            'speed': float(speed),
            'accel': float(accel),
            'delay': int(delay),
        }

    def _CollabBuildPathState(self, path_obj):
        if path_obj is None:
            return None
        nodes = []
        try:
            for idx, node in enumerate(getattr(path_obj, '_nodes', []) or []):
                node_state = self._CollabBuildPathNodeState(path_obj, node, idx)
                if node_state is not None:
                    nodes.append(node_state)
        except Exception:
            pass
        return {
            'path_id': int(getattr(path_obj, '_id', 0)),
            'loops': bool(path_obj.get_loops()),
            'nodes': nodes,
        }

    def _CollabNormalizePathNodeState(self, node_def, fallback_index=None):
        if isinstance(node_def, dict):
            try:
                index = int(node_def.get('index', fallback_index if fallback_index is not None else 0))
            except Exception:
                index = int(fallback_index or 0)
            return {
                'node_uid': str(node_def.get('node_uid') or node_def.get('id') or ''),
                'index': int(index),
                'x': int(node_def.get('x', 0)),
                'y': int(node_def.get('y', 0)),
                'speed': float(node_def.get('speed', 0.5)),
                'accel': float(node_def.get('accel', 0.00498)),
                'delay': int(node_def.get('delay', 0)),
            }
        if isinstance(node_def, (list, tuple)) and len(node_def) >= 5:
            x, y, speed, accel, delay = node_def[:5]
            return {
                'node_uid': '',
                'index': int(fallback_index or 0),
                'x': int(x),
                'y': int(y),
                'speed': float(speed),
                'accel': float(accel),
                'delay': int(delay),
            }
        return None

    def _CollabFindPathById(self, path_id):
        try:
            path_id = int(path_id)
        except Exception:
            return None
        for path_obj in getattr(globals_.Area, 'paths', []) or []:
            try:
                if int(getattr(path_obj, '_id', -1)) == path_id:
                    return path_obj
            except Exception:
                continue
        return None

    def _CollabFindPathNode(self, path_obj, node_uid='', node_index=None, strict_uid=False):
        if path_obj is None:
            return None, None
        node_uid = str(node_uid or '')
        if node_uid:
            for idx, node in enumerate(getattr(path_obj, '_nodes', []) or []):
                if str(getattr(node, '_collab_id', '') or '') == node_uid:
                    return idx, node
            if strict_uid:
                return None, None
        try:
            if node_index is not None:
                node_index = int(node_index)
                if 0 <= node_index < len(getattr(path_obj, '_nodes', []) or []):
                    return node_index, path_obj._nodes[node_index]
        except Exception:
            pass
        return None, None

    def _CollabRequestFullSync(self, area_num=None):
        try:
            if area_num is None:
                area_num = int(getattr(globals_.Area, 'areanum', 1))
            else:
                area_num = int(area_num)
        except Exception:
            area_num = 1
        try:
            if hasattr(self, 'collabManager') and self.collabManager.mode != "host":
                self.collabManager.broadcast_message('request_full_sync', {'area_num': area_num})
            else:
                self.BroadcastFullStateForArea(area_num)
        except Exception:
            pass

    def _CollabItemIsHot(self, item):
        ts = getattr(item, '_collab_local_edit_ts', None)
        if ts is None:
            return False
        try:
            age = time.monotonic() - float(ts)
        except Exception:
            return False
        return age < 2.5

    def _CollabMarkItemHot(self, item):
        if item is None:
            return
        try:
            item._collab_local_edit_ts = time.monotonic()
        except Exception:
            pass

    def _CollabClearItemHot(self, item):
        if item is None:
            return
        try:
            delattr(item, '_collab_local_edit_ts')
        except Exception:
            try:
                item._collab_local_edit_ts = None
            except Exception:
                pass

    def _CollabPathIsHot(self, path_obj):
        if path_obj is None:
            return False
        if self._CollabItemIsHot(path_obj):
            return True
        for node in getattr(path_obj, '_nodes', []):
            if self._CollabItemIsHot(node):
                return True
        return False

    def _BuildCollabCommentState(self, comment):
        return {
            'id': self._CollabEnsureItemId(comment),
            'x': int(comment.objx),
            'y': int(comment.objy),
            'text': str(getattr(comment, 'text', '')),
        }

    def _CollabRebuildIndexes(self):
        self._collabObjectById = {}
        self._collabSpriteById = {}
        self._collabEntranceById = {}
        self._collabLocationById = {}
        self._collabCommentById = {}
        self._collabPathNodeById = {}
        if globals_.Area is None:
            return
        for layer in globals_.Area.layers[:3]:
            for obj in layer:
                obj_id = getattr(obj, '_collab_id', None)
                if obj_id:
                    self._collabObjectById[str(obj_id)] = obj
        for spr in globals_.Area.sprites:
            spr_id = getattr(spr, '_collab_id', None)
            if spr_id:
                self._collabSpriteById[str(spr_id)] = spr
        for ent in getattr(globals_.Area, 'entrances', []) or []:
            ent_id = getattr(ent, '_collab_id', None)
            if ent_id:
                self._collabEntranceById[str(ent_id)] = ent
        for loc in getattr(globals_.Area, 'locations', []) or []:
            loc_id = getattr(loc, '_collab_id', None)
            if loc_id:
                self._collabLocationById[str(loc_id)] = loc
        for com in getattr(globals_.Area, 'comments', []) or []:
            com_id = getattr(com, '_collab_id', None)
            if com_id:
                self._collabCommentById[str(com_id)] = com
        for path_obj in getattr(globals_.Area, 'paths', []) or []:
            for node in getattr(path_obj, '_nodes', []) or []:
                node_id = getattr(node, '_collab_id', None)
                if node_id:
                    self._collabPathNodeById[str(node_id)] = node

    def _CollabFindItemById(self, item_id):
        """
        Best-effort lookup for any selectable scene item by its _collab_id.
        """
        item_id = str(item_id or '')
        if not item_id:
            return None
        if item_id.startswith('ent:'):
            try:
                entid = int(item_id.split(':', 1)[1])
            except Exception:
                entid = None
            if entid is not None:
                for ent in getattr(getattr(globals_, 'Area', None), 'entrances', []) or []:
                    try:
                        if int(getattr(ent, 'entid', -1)) == entid:
                            self._collabEntranceById[item_id] = ent
                            return ent
                    except Exception:
                        continue
            return None
        if item_id.startswith('loc:'):
            try:
                locid = int(item_id.split(':', 1)[1])
            except Exception:
                locid = None
            if locid is not None:
                for loc in getattr(getattr(globals_, 'Area', None), 'locations', []) or []:
                    try:
                        if int(getattr(loc, 'id', -1)) == locid:
                            self._collabLocationById[item_id] = loc
                            return loc
                    except Exception:
                        continue
            return None
        try:
            found = getattr(self, '_collabObjectById', {}).get(item_id)
            if found is not None:
                return found
            found = getattr(self, '_collabSpriteById', {}).get(item_id)
            if found is not None:
                return found
            found = getattr(self, '_collabEntranceById', {}).get(item_id)
            if found is not None:
                return found
            found = getattr(self, '_collabLocationById', {}).get(item_id)
            if found is not None:
                return found
            found = getattr(self, '_collabCommentById', {}).get(item_id)
            if found is not None:
                return found
            found = getattr(self, '_collabPathNodeById', {}).get(item_id)
            if found is not None:
                return found
        except Exception:
            pass

        area = getattr(globals_, 'Area', None)
        if area is None:
            return None

        try:
            for layer in getattr(area, 'layers', [])[:3]:
                for obj in layer:
                    if str(getattr(obj, '_collab_id', '') or '') == item_id:
                        self._collabObjectById[item_id] = obj
                        return obj
            for spr in getattr(area, 'sprites', []) or []:
                if str(getattr(spr, '_collab_id', '') or '') == item_id:
                    self._collabSpriteById[item_id] = spr
                    return spr
            for ent in getattr(area, 'entrances', []) or []:
                if str(getattr(ent, '_collab_id', '') or '') == item_id:
                    self._collabEntranceById[item_id] = ent
                    return ent
            for loc in getattr(area, 'locations', []) or []:
                if str(getattr(loc, '_collab_id', '') or '') == item_id:
                    self._collabLocationById[item_id] = loc
                    return loc
            for com in getattr(area, 'comments', []) or []:
                if str(getattr(com, '_collab_id', '') or '') == item_id:
                    self._collabCommentById[item_id] = com
                    return com
            for path_obj in getattr(area, 'paths', []) or []:
                for node in getattr(path_obj, '_nodes', []) or []:
                    if str(getattr(node, '_collab_id', '') or '') == item_id:
                        self._collabPathNodeById[item_id] = node
                        return node
        except Exception:
            pass
        return None

    def _CollabLocalSessionId(self):
        try:
            return str(getattr(self.collabManager, 'session_id', '') or '')
        except Exception:
            return ''

    def _CollabRemoveRemoteOutline(self, item):
        if item is None:
            return
        outline = getattr(item, '_collab_remote_outline', None)
        if outline is not None:
            try:
                outline.setParentItem(None)
            except Exception:
                pass
            try:
                if outline.scene() is not None:
                    outline.scene().removeItem(outline)
            except Exception:
                pass
            try:
                outline.deleteLater()
            except Exception:
                pass
        try:
            delattr(item, '_collab_remote_outline')
        except Exception:
            item._collab_remote_outline = None
        try:
            delattr(item, '_collab_selected_by')
        except Exception:
            item._collab_selected_by = ''
        try:
            delattr(item, '_collab_selection_color')
        except Exception:
            item._collab_selection_color = ''
        try:
            item.update()
        except Exception:
            pass
        try:
            scene = item.scene()
            if scene is not None:
                scene.update()
        except Exception:
            pass

    def _CollabEnsureRemoteOutline(self, item, owner_session_id, color=None):
        """
        Creates/updates a colored outline on top of an item to indicate it's selected by another peer.
        """
        if item is None:
            return
        owner_session_id = str(owner_session_id or '')
        if not owner_session_id or owner_session_id == self._CollabLocalSessionId():
            self._CollabRemoveRemoteOutline(item)
            return
        color_hex = normalize_collab_color(color or self._CollabPeerColor(owner_session_id))

        try:
            item._collab_selected_by = owner_session_id
        except Exception:
            pass
        try:
            item._collab_selection_color = color_hex
        except Exception:
            pass

        outline = getattr(item, '_collab_remote_outline', None)
        if outline is None:
            try:
                outline = QtWidgets.QGraphicsRectItem(item)
                outline.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
                outline.setAcceptHoverEvents(False)
                outline.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
                outline.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                outline.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                outline.setZValue(999999)
                item._collab_remote_outline = outline
            except Exception:
                return
        try:
            pen = QtGui.QPen(collab_qcolor(color_hex), 2)
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            outline.setPen(pen)
        except Exception:
            pass

        try:
            rect = item.boundingRect()
            outline.setRect(rect.adjusted(-1.0, -1.0, 1.0, 1.0))
        except Exception:
            pass
        try:
            item.update()
        except Exception:
            pass

    def _CollabClearRemoteSelections(self):
        """
        Clears all cached remote selections and removes outlines.
        """
        try:
            owners = list(getattr(self, '_collabSelectionItemsByOwner', {}).keys())
        except Exception:
            owners = []
        for owner in owners:
            self._CollabClearRemoteSelectionsForOwner(owner)
        try:
            self._collabSelectionOwnerByItem = {}
            self._collabSelectionItemsByOwner = {}
        except Exception:
            pass

    def _CollabClearRemoteSelectionsForOwner(self, owner_session_id):
        owner_session_id = str(owner_session_id or '')
        if not owner_session_id:
            return
        ids = set(getattr(self, '_collabSelectionItemsByOwner', {}).get(owner_session_id) or set())
        for item_id in list(ids):
            if str(getattr(self, '_collabSelectionOwnerByItem', {}).get(item_id) or '') == owner_session_id:
                try:
                    self._collabSelectionOwnerByItem.pop(item_id, None)
                except Exception:
                    pass
            item = self._CollabFindItemById(item_id)
            self._CollabRemoveRemoteOutline(item)
        try:
            self._collabSelectionItemsByOwner.pop(owner_session_id, None)
        except Exception:
            pass

    def _ScheduleCollabSelectionBroadcast(self, delay_ms=40, force=False):
        if not self._CollabEnabled():
            return
        if self._CollabHistoryBlocked():
            return
        if globals_.Area is None or globals_.Level is None:
            return
        try:
            if self._collabSelectionDebounce.isActive():
                if not force:
                    return
                self._collabSelectionDebounce.stop()
            self._collabSelectionDebounce.start(int(delay_ms))
        except Exception:
            pass

    def _FlushCollabSelectionBroadcast(self):
        if not self._CollabEnabled() or self._CollabHistoryBlocked():
            return
        if globals_.Area is None or globals_.Level is None:
            return
        try:
            selitems = list(self.scene.selectedItems())
        except Exception:
            selitems = []

        selected_ids = set()
        for item in selitems:
            try:
                cid = str(self._CollabSelectionItemId(item) or '')
                if cid:
                    selected_ids.add(cid)
            except Exception:
                continue

        if selected_ids == set(getattr(self, '_collabLastBroadcastSelection', set()) or set()):
            return
        self._collabLastBroadcastSelection = set(selected_ids)

        # Track local "ownership" so we can release if someone else selects the same item.
        local_id = self._CollabLocalSessionId()
        if local_id:
            self._collabSelectionItemsByOwner[local_id] = set(selected_ids)
            for item_id in list(self._collabSelectionOwnerByItem.keys()):
                if self._collabSelectionOwnerByItem.get(item_id) == local_id and item_id not in selected_ids:
                    self._collabSelectionOwnerByItem.pop(item_id, None)
            for item_id in selected_ids:
                self._collabSelectionOwnerByItem[item_id] = local_id

        try:
            self.collabManager.broadcast_message('sel', {
                'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
                'level_name': self._CollabCurrentLevelName(),
                'items': sorted(selected_ids),
                'color': self.collabSelfHighlightColor,
            })
        except Exception:
            pass

    def _CollabAdoptLocalSelection(self, selitems):
        """
        Claim ownership of the current local selection immediately.
        This makes remote outlines disappear locally as soon as we click
        an item and ensures ownership transfers to us before the debounced
        network broadcast is flushed.
        """
        if not self._CollabEnabled():
            return False

        local_id = str(self._CollabLocalSessionId() or '')
        if not local_id:
            return False

        claimed_ids = set()
        ownership_changed = False

        for item in selitems or ():
            try:
                item_id = str(self._CollabSelectionItemId(item) or '')
                if not item_id:
                    continue
            except Exception:
                continue

            claimed_ids.add(item_id)
            prev_owner = str(self._collabSelectionOwnerByItem.get(item_id) or '')
            if prev_owner != local_id:
                ownership_changed = True

            if prev_owner and prev_owner != local_id:
                try:
                    prev_set = set(self._collabSelectionItemsByOwner.get(prev_owner) or set())
                    if item_id in prev_set:
                        prev_set.discard(item_id)
                        if prev_set:
                            self._collabSelectionItemsByOwner[prev_owner] = prev_set
                        else:
                            self._collabSelectionItemsByOwner.pop(prev_owner, None)
                except Exception:
                    pass

            self._collabSelectionOwnerByItem[item_id] = local_id
            self._CollabRemoveRemoteOutline(item)

        prev_local_ids = set(self._collabSelectionItemsByOwner.get(local_id) or set())
        for item_id in list(prev_local_ids - claimed_ids):
            if self._collabSelectionOwnerByItem.get(item_id) == local_id:
                self._collabSelectionOwnerByItem.pop(item_id, None)

        self._collabSelectionItemsByOwner[local_id] = set(claimed_ids)
        return ownership_changed

    def _ApplyRemoteSelection(self, payload, sender):
        """
        Apply selection ownership from another peer and render it as a per-player outline.
        If the remote peer selects an item that we currently have selected, we deselect it locally
        (ownership transfer).
        """
        if not isinstance(payload, dict):
            return
        try:
            area_num = int(payload.get('area_num', 0) or 0)
        except Exception:
            area_num = 0
        level_name = str(payload.get('level_name') or '')
        if area_num and area_num != int(getattr(globals_.Area, 'areanum', 0) or 0):
            return
        if not self._CollabMatchesLevelName(level_name):
            return

        sender = str(sender or '')
        if not sender:
            return
        local_session = self._CollabLocalSessionId()
        if sender == local_session:
            return
        self._CollabSetPeerColor(sender, payload.get('color'))

        items = payload.get('items')
        if not isinstance(items, list):
            items = []
        new_ids = set(str(x or '') for x in items if str(x or ''))

        # Remove items this sender no longer selects.
        old_ids = set(self._collabSelectionItemsByOwner.get(sender) or set())
        for item_id in list(old_ids - new_ids):
            if self._collabSelectionOwnerByItem.get(item_id) == sender:
                self._collabSelectionOwnerByItem.pop(item_id, None)
            item = self._CollabFindItemById(item_id)
            self._CollabRemoveRemoteOutline(item)

        local_selection_changed = False

        # Apply new selection, stealing ownership if needed.
        for item_id in list(new_ids):
            prev_owner = str(self._collabSelectionOwnerByItem.get(item_id) or '')
            if prev_owner and prev_owner != sender:
                # Remove from previous owner.
                try:
                    prev_set = set(self._collabSelectionItemsByOwner.get(prev_owner) or set())
                    if item_id in prev_set:
                        prev_set.discard(item_id)
                        self._collabSelectionItemsByOwner[prev_owner] = prev_set
                except Exception:
                    pass
            self._collabSelectionOwnerByItem[item_id] = sender

            item = self._CollabFindItemById(item_id)
            if item is not None:
                # If we currently have it selected locally, drop our selection (transfer).
                try:
                    if item.isSelected():
                        self.SelectionUpdateFlag = True
                        item.setSelected(False)
                        self.SelectionUpdateFlag = False
                        local_selection_changed = True
                except Exception:
                    self.SelectionUpdateFlag = False
                self._CollabClearItemHot(item)
                self._CollabClearItemHot(getattr(item, 'path', None))
                self._CollabEnsureRemoteOutline(item, sender, payload.get('color'))

        self._collabSelectionItemsByOwner[sender] = set(new_ids)
        try:
            self.view.viewport().update()
        except Exception:
            pass

        if local_selection_changed:
            try:
                self.SelectionUpdateFlag = False
                self.ChangeSelectionHandler()
                self._ScheduleCollabSelectionBroadcast(delay_ms=0, force=True)
            except Exception:
                pass

    def CollabEnsureCurrentAreaIds(self):
        if globals_.Area is None:
            return
        for layer in globals_.Area.layers[:3]:
            for obj in layer:
                self._CollabEnsureItemId(obj)
        for spr in globals_.Area.sprites:
            self._CollabEnsureItemId(spr)
        for ent in globals_.Area.entrances:
            self._CollabEnsureItemId(ent)
        for loc in globals_.Area.locations:
            self._CollabEnsureItemId(loc)
        for com in globals_.Area.comments:
            self._CollabEnsureItemId(com)
        for path_obj in getattr(globals_.Area, 'paths', []) or []:
            for node in getattr(path_obj, '_nodes', []) or []:
                self._CollabEnsurePathNodeId(node)
        self._CollabRebuildIndexes()

    def _CollabPruneDuplicateIdsCurrentArea(self):
        if globals_.Area is None:
            return

        duplicate_objects = []
        seen_object_ids = {}
        for layer in globals_.Area.layers[:3]:
            for obj in list(layer):
                obj_id = str(getattr(obj, '_collab_id', '') or '')
                if not obj_id:
                    continue
                if obj_id in seen_object_ids:
                    duplicate_objects.append(obj)
                    continue
                seen_object_ids[obj_id] = obj

        duplicate_sprites = []
        seen_sprite_ids = {}
        for spr in list(globals_.Area.sprites):
            spr_id = str(getattr(spr, '_collab_id', '') or '')
            if not spr_id:
                continue
            if spr_id in seen_sprite_ids:
                duplicate_sprites.append(spr)
                continue
            seen_sprite_ids[spr_id] = spr

        for obj in duplicate_objects:
            try:
                obj.delete()
            except Exception:
                pass
            try:
                self.scene.removeItem(obj)
            except Exception:
                pass

        for spr in duplicate_sprites:
            try:
                spr.delete()
            except Exception:
                pass
            try:
                self.scene.removeItem(spr)
            except Exception:
                pass

        if duplicate_objects or duplicate_sprites:
            self._CollabRebuildIndexes()

    def BroadcastFullSceneState(self):
        if not self._CollabEnabled() or self.collabManager.mode != "host":
            return
        if globals_.Level is None or globals_.Area is None:
            return
        current_level_name = self._CollabCurrentLevelName()
        self.CollabEnsureCurrentAreaIds()
        scene_state = self.BuildCollabSceneState()
        try:
            self.collabAreaState[int(globals_.Area.areanum)] = scene_state
        except Exception:
            pass
        self.collabSceneRev += 1
        self.collabManager.broadcast_message('scene_patch', {
            'area_num': globals_.Area.areanum,
            'level_name': current_level_name,
            'rev': self.collabSceneRev,
            'state': scene_state,
        })
        self.collabLastSceneSig = hash(repr(scene_state))

    def _QueueCollabOp(self, op):
        if not self._CollabEnabled():
            return
        if self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        if globals_.Area is None:
            return
        self._collabOutOps.append(op)
        if not self._collabOutOpsTimer.isActive():
            delay_ms = int(getattr(self, '_collabOpsFlushIntervalMs', 16) or 16)
            if delay_ms < 0:
                delay_ms = 0
            self._collabOutOpsTimer.start(delay_ms)

    def CollabQueueObjectUpdate(self, obj):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        obj_id = self._CollabEnsureItemId(obj)
        obj._collab_local_edit_ts = time.monotonic()
        self._collabObjectById[obj_id] = obj
        self._QueueCollabOp({
            'op': 'obj_upd',
            'id': obj_id,
            'layer': int(getattr(obj, 'layer', 1)),
            'tileset': int(getattr(obj, 'tileset', 0)),
            'type': int(getattr(obj, 'type', 0)),
            'x': int(getattr(obj, 'objx', 0)),
            'y': int(getattr(obj, 'objy', 0)),
            'w': int(getattr(obj, 'width', 1)),
            'h': int(getattr(obj, 'height', 1)),
        })

    def CollabQueueSpriteUpdate(self, obj, include_data=False):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        spr_id = self._CollabEnsureItemId(obj)
        self._collabSpriteById[spr_id] = obj
        msg = {
            'op': 'spr_upd',
            'id': spr_id,
            'type': int(getattr(obj, 'type', 0)),
            'x': int(getattr(obj, 'objx', 0)),
            'y': int(getattr(obj, 'objy', 0)),
        }
        if include_data:
            msg['data'] = base64.b64encode(getattr(obj, 'spritedata', bytes())).decode('ascii')
        self._QueueCollabOp(msg)

    def CollabQueueObjectDelete(self, obj):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        obj_id = getattr(obj, '_collab_id', None)
        if not obj_id:
            return
        obj_id = str(obj_id)
        self._collabObjectById.pop(obj_id, None)
        self._QueueCollabOp({'op': 'obj_del', 'id': obj_id})

    def CollabQueueSpriteDelete(self, obj):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        spr_id = getattr(obj, '_collab_id', None)
        if not spr_id:
            return
        spr_id = str(spr_id)
        self._collabSpriteById.pop(spr_id, None)
        self._QueueCollabOp({'op': 'spr_del', 'id': spr_id})

    def CollabQueueEntranceUpsert(self, ent, is_add=False):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        if ent is None:
            return
        try:
            entid = int(getattr(ent, 'entid', 0))
        except Exception:
            return
        op = {
            'op': 'ent_add' if is_add else 'ent_upd',
            'id': str(entid),
            'x': int(getattr(ent, 'objx', 0)),
            'y': int(getattr(ent, 'objy', 0)),
            'destarea': int(getattr(ent, 'destarea', 0)),
            'destentrance': int(getattr(ent, 'destentrance', 0)),
            'enttype': int(getattr(ent, 'enttype', 0)),
            'entzone': int(getattr(ent, 'entzone', 0)),
            'entlayer': int(getattr(ent, 'entlayer', 0)),
            'entpath': int(getattr(ent, 'entpath', 0)),
            'entsettings': int(getattr(ent, 'entsettings', 0)),
            'leave_level': bool(getattr(ent, 'leave_level', False)),
            'cpdirection': int(getattr(ent, 'cpdirection', 0)),
        }
        self._QueueCollabOp(op)

    def CollabQueueEntranceDelete(self, ent):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        if ent is None:
            return
        try:
            entid = int(getattr(ent, 'entid', 0))
        except Exception:
            return
        self._QueueCollabOp({'op': 'ent_del', 'id': str(entid)})

    def CollabQueueLocationUpsert(self, loc, is_add=False):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        if loc is None:
            return
        try:
            locid = int(getattr(loc, 'id', 0))
        except Exception:
            return
        op = {
            'op': 'loc_add' if is_add else 'loc_upd',
            'id': str(locid),
            'x': int(getattr(loc, 'objx', 0)),
            'y': int(getattr(loc, 'objy', 0)),
            'w': int(getattr(loc, 'width', 16)),
            'h': int(getattr(loc, 'height', 16)),
        }
        self._QueueCollabOp(op)

    def CollabQueueLocationDelete(self, loc):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        if loc is None:
            return
        try:
            locid = int(getattr(loc, 'id', 0))
        except Exception:
            return
        self._QueueCollabOp({'op': 'loc_del', 'id': str(locid)})

    def CollabQueueCommentUpsert(self, com, is_add=False):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        if com is None:
            return
        cid = self._CollabEnsureItemId(com)
        if not cid:
            return
        op = {
            'op': 'com_add' if is_add else 'com_upd',
            'id': str(cid),
            'x': int(getattr(com, 'objx', 0)),
            'y': int(getattr(com, 'objy', 0)),
            'text': str(getattr(com, 'text', '')),
        }
        self._QueueCollabOp(op)

    def CollabQueueCommentDelete(self, com):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        if com is None:
            return
        cid = str(getattr(com, '_collab_id', '') or '')
        if not cid:
            return
        self._QueueCollabOp({'op': 'com_del', 'id': cid})

    def CollabQueuePathSet(self, path_obj):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        if path_obj is None:
            return
        try:
            path_id = int(getattr(path_obj, '_id', 0))
        except Exception:
            return
        if path_id < 0:
            return
        path_state = self._CollabBuildPathState(path_obj)
        if path_state is None:
            return
        self._QueueCollabOp({
            'op': 'path_set',
            'id': str(path_id),
            'path_id': int(path_id),
            'loops': bool(path_obj.get_loops()),
            'nodes': path_state.get('nodes', []),
        })

    def CollabQueuePathDelete(self, path_id):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        try:
            path_id = int(path_id)
        except Exception:
            return
        self._QueueCollabOp({'op': 'path_del', 'id': str(path_id), 'path_id': int(path_id)})

    def CollabQueuePathNodeUpdate(self, node):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        if node is None:
            return
        try:
            path_id = int(getattr(node, 'pathid', -1))
        except Exception:
            return
        if path_id < 0:
            return
        path_obj = getattr(node, 'path', None)
        node_state = self._CollabBuildPathNodeState(path_obj, node, getattr(node, 'nodeid', None))
        if node_state is None:
            return
        key = str(node_state.get('node_uid') or f"{path_id}:{node_state.get('index', -1)}")
        self._QueueCollabOp({
            'op': 'path_node_upd',
            'id': key,
            'path_id': int(path_id),
            'node_id': int(node_state.get('index', 0)),
            'node_uid': str(node_state.get('node_uid') or ''),
            'x': int(node_state.get('x', 0)),
            'y': int(node_state.get('y', 0)),
            'speed': float(node_state.get('speed', 0.5)),
            'accel': float(node_state.get('accel', 0.00498)),
            'delay': int(node_state.get('delay', 0)),
        })

    def CollabQueuePathNodeAdd(self, path_obj, node):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        if path_obj is None or node is None:
            return
        try:
            path_id = int(getattr(path_obj, '_id', -1))
        except Exception:
            return
        if path_id < 0:
            return
        node_state = self._CollabBuildPathNodeState(path_obj, node, getattr(node, 'nodeid', None))
        if node_state is None:
            return
        self._QueueCollabOp({
            'op': 'path_node_add',
            'id': str(node_state.get('node_uid') or f"{path_id}:{node_state.get('index', -1)}"),
            'path_id': int(path_id),
            'node_id': int(node_state.get('index', 0)),
            'node_uid': str(node_state.get('node_uid') or ''),
            'loops': bool(path_obj.get_loops()),
            'x': int(node_state.get('x', 0)),
            'y': int(node_state.get('y', 0)),
            'speed': float(node_state.get('speed', 0.5)),
            'accel': float(node_state.get('accel', 0.00498)),
            'delay': int(node_state.get('delay', 0)),
        })

    def CollabQueuePathNodeDelete(self, path_id, node_id, node_uid=''):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        try:
            path_id = int(path_id)
            node_id = int(node_id)
        except Exception:
            return
        if path_id < 0:
            return
        node_uid = str(node_uid or '')
        self._QueueCollabOp({
            'op': 'path_node_del',
            'id': node_uid or f"{path_id}:{node_id}",
            'path_id': int(path_id),
            'node_id': int(node_id),
            'node_uid': node_uid,
        })

    def CollabQueuePathNodeOrder(self, path_obj):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        if path_obj is None:
            return
        try:
            path_id = int(getattr(path_obj, '_id', -1))
        except Exception:
            return
        if path_id < 0:
            return
        order = []
        for idx, node in enumerate(getattr(path_obj, '_nodes', []) or []):
            node_state = self._CollabBuildPathNodeState(path_obj, node, idx)
            if node_state is None:
                continue
            order.append(str(node_state.get('node_uid') or ''))
        self._QueueCollabOp({
            'op': 'path_node_order',
            'id': str(path_id),
            'path_id': int(path_id),
            'order': order,
        })

    def CollabQueuePathConfigUpdate(self, path_obj):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        if path_obj is None:
            return
        try:
            path_id = int(getattr(path_obj, '_id', -1))
        except Exception:
            return
        if path_id < 0:
            return
        self._QueueCollabOp({
            'op': 'path_cfg_upd',
            'id': str(path_id),
            'path_id': int(path_id),
            'loops': bool(path_obj.get_loops()),
        })

    def _FlushCollabOps(self):
        if not self._CollabEnabled():
            self._collabOutOps = []
            return
        if globals_.Area is None:
            self._collabOutOps = []
            return
        ops = self._collabOutOps
        self._collabOutOps = []
        if not ops:
            return

        result = []
        slots = {}
        for op in ops:
            op_type = op.get('op')
            ent_id = op.get('id')
            if not op_type or not ent_id:
                continue
            if op_type.startswith('obj_'):
                key = ('obj', str(ent_id))
            elif op_type.startswith('spr_'):
                key = ('spr', str(ent_id))
            elif op_type.startswith('ent_'):
                key = ('ent', str(ent_id))
            elif op_type.startswith('loc_'):
                key = ('loc', str(ent_id))
            elif op_type.startswith('com_'):
                key = ('com', str(ent_id))
            elif op_type in {'path_set', 'path_del'}:
                key = ('path', str(ent_id))
            elif op_type == 'path_cfg_upd':
                key = ('path_cfg', str(op.get('path_id', ent_id)))
            elif op_type == 'path_node_order':
                key = ('path_order', str(op.get('path_id', ent_id)))
            elif op_type.startswith('path_node_'):
                key = ('path_node', str(ent_id))
            else:
                continue

            if op_type.endswith('_del'):
                idx = slots.get(key)
                if idx is not None:
                    prev = result[idx]
                    if prev is not None and prev.get('op', '').endswith('_add'):
                        result[idx] = None
                        del slots[key]
                    else:
                        result[idx] = op
                else:
                    slots[key] = len(result)
                    result.append(op)
                continue

            idx = slots.get(key)
            if idx is None:
                slots[key] = len(result)
                result.append(op)
                continue

            prev = result[idx]
            if prev is None:
                slots[key] = len(result)
                result.append(op)
                continue
            if prev.get('op', '').endswith('_del') and op_type.endswith('_upd'):
                continue
            if prev.get('op', '').endswith('_add') and op_type.endswith('_upd'):
                merged = dict(prev)
                merged.update(op)
                merged['op'] = prev.get('op')
                result[idx] = merged
                continue
            result[idx] = op

        result = [o for o in result if o is not None]
        if not result:
            return

        payload = {
            'area_num': globals_.Area.areanum,
            'level_name': self._CollabCurrentLevelName(),
            'ops': result,
        }
        self.collabManager.broadcast_message('ops', payload)

    def CollabQueueMetaUpdate(self):
        if not self._CollabEnabled() or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False):
            return
        if globals_.Area is None:
            return
        self._collabMetaDirty = True
        if not self._collabMetaTimer.isActive():
            delay_ms = int(getattr(self, '_collabMetaFlushDelayMs', 350) or 350)
            if delay_ms < 80:
                delay_ms = 80
            self._collabMetaTimer.start(delay_ms)

    def _CacheCurrentAreaCollabState(self, include_scene=True, include_meta=True):
        if globals_.Area is None:
            return
        try:
            area_num = int(getattr(globals_.Area, 'areanum', 0) or 0)
        except Exception:
            area_num = 0
        if area_num < 1:
            return

        if include_scene:
            try:
                self.collabAreaState[area_num] = self.BuildCollabSceneState()
            except Exception:
                pass
        if include_meta:
            try:
                self.collabAreaMetaState[area_num] = self.BuildCollabMetaState()
            except Exception:
                pass

    def BroadcastFullMetaState(self):
        if not self._CollabEnabled() or self.collabManager.mode != "host":
            return
        if globals_.Level is None or globals_.Area is None:
            return
        self.collabMetaRev += 1
        state = self.BuildCollabMetaState()
        try:
            self.collabAreaMetaState[int(globals_.Area.areanum)] = state
        except Exception:
            pass
        self.collabManager.broadcast_message('meta_state', {
            'area_num': globals_.Area.areanum,
            'level_name': self._CollabCurrentLevelName(),
            'rev': self.collabMetaRev,
            'state': state,
        })

    def _FlushCollabMeta(self):
        if not self._CollabEnabled():
            self._collabMetaDirty = False
            return
        if globals_.Area is None:
            self._collabMetaDirty = False
            return
        if not self._collabMetaDirty:
            return
        self._collabMetaDirty = False
        self.collabMetaRev += 1
        state = self.BuildCollabMetaState()
        try:
            self.collabAreaMetaState[int(globals_.Area.areanum)] = state
        except Exception:
            pass
        self.collabManager.broadcast_message('meta_state', {
            'area_num': globals_.Area.areanum,
            'level_name': self._CollabCurrentLevelName(),
            'rev': self.collabMetaRev,
            'state': state,
        })

    def BroadcastFullStateForArea(self, area_num):
        if not self._CollabEnabled() or self.collabManager.mode != "host":
            return
        if globals_.Level is None or globals_.Area is None:
            return
        try:
            area_num = int(area_num)
        except Exception:
            return
        if area_num < 1:
            return

        if area_num == getattr(globals_.Area, 'areanum', None):
            self.CollabEnsureCurrentAreaIds()
            self.BroadcastFullSceneState()
            self.BroadcastFullMetaState()
            try:
                self.collabAreaState[int(area_num)] = self.BuildCollabSceneState()
            except Exception:
                pass
            try:
                self.collabAreaMetaState[int(area_num)] = self.BuildCollabMetaState()
            except Exception:
                pass
            return

        cached_scene = self.collabAreaState.get(int(area_num)) if hasattr(self, 'collabAreaState') else None
        cached_meta = self.collabAreaMetaState.get(int(area_num)) if hasattr(self, 'collabAreaMetaState') else None
        if isinstance(cached_scene, dict):
            self.collabSceneRev += 1
            self.collabManager.broadcast_message('scene_patch', {
                'area_num': int(area_num),
                'level_name': self._CollabCurrentLevelName(),
                'rev': self.collabSceneRev,
                'state': cached_scene,
            })
            if isinstance(cached_meta, dict):
                self.collabMetaRev += 1
                self.collabManager.broadcast_message('meta_state', {
                    'area_num': int(area_num),
                    'level_name': self._CollabCurrentLevelName(),
                    'rev': self.collabMetaRev,
                    'state': cached_meta,
                })
            return

        try:
            level_bytes = globals_.Level.save()
        except Exception:
            return

        old_area = getattr(globals_.Area, 'areanum', None)
        self.collabApplyingRemote = True
        self.collabSwitchingArea = True
        try:
            try:
                self.LoadLevelFromNetwork(level_bytes, area_num)
            except Exception:
                return
            self.CollabEnsureCurrentAreaIds()
            self.BroadcastFullSceneState()
            self.BroadcastFullMetaState()
            try:
                self.collabAreaState[int(area_num)] = self.BuildCollabSceneState()
            except Exception:
                pass
            try:
                self.collabAreaMetaState[int(area_num)] = self.BuildCollabMetaState()
            except Exception:
                pass
        finally:
            try:
                if old_area:
                    self.LoadLevelFromNetwork(level_bytes, int(old_area))
            except Exception:
                pass
            self.collabSwitchingArea = False
            self.collabApplyingRemote = False

    def ApplyRemoteOps(self, payload, sender):
        try:
            area_num = int(payload.get('area_num', 0))
        except Exception:
            area_num = 0
        ops = payload.get('ops')
        if not isinstance(ops, list) or not ops:
            return

        self._ApplyRemoteOpsToCache(area_num, ops)
        try:
            self._ApplyRemoteMetaOpsToCache(area_num, ops)
        except Exception:
            pass
        if area_num != getattr(globals_.Area, 'areanum', None):
            return

        self.collabApplyingRemote = True
        self.scene.blockSignals(True)
        try:
            globals_.DirtyOverride += 1
            self._CollabRebuildIndexes()
            needs_event_links = False
            needs_pipe_links = False
            for op in ops:
                if not isinstance(op, dict):
                    continue
                op_type = op.get('op')
                if op_type == 'obj_add' or op_type == 'obj_upd':
                    self._ApplyRemoteObjectUpsert(op)
                    needs_event_links = True
                elif op_type == 'obj_del':
                    self._ApplyRemoteObjectDelete(op)
                    needs_event_links = True
                elif op_type == 'spr_add' or op_type == 'spr_upd':
                    self._ApplyRemoteSpriteUpsert(op)
                    needs_event_links = True
                elif op_type == 'spr_del':
                    self._ApplyRemoteSpriteDelete(op)
                    needs_event_links = True
                elif op_type in ('ent_add', 'ent_upd'):
                    self._ApplyRemoteEntranceUpsertFromOp(op)
                    needs_pipe_links = True
                elif op_type == 'ent_del':
                    self._ApplyRemoteEntranceDeleteFromOp(op)
                    needs_pipe_links = True
                elif op_type in ('loc_add', 'loc_upd'):
                    self._ApplyRemoteLocationUpsertFromOp(op)
                elif op_type == 'loc_del':
                    self._ApplyRemoteLocationDeleteFromOp(op)
                elif op_type in ('com_add', 'com_upd'):
                    self._ApplyRemoteCommentUpsertFromOp(op)
                elif op_type == 'com_del':
                    self._ApplyRemoteCommentDeleteFromOp(op)
                elif op_type == 'path_set':
                    self._ApplyRemotePathSetFromOp(op)
                elif op_type == 'path_del':
                    self._ApplyRemotePathDeleteFromOp(op)
                elif op_type == 'path_cfg_upd':
                    self._ApplyRemotePathConfigUpdateFromOp(op)
                elif op_type == 'path_node_add':
                    self._ApplyRemotePathNodeAddFromOp(op)
                elif op_type == 'path_node_upd':
                    self._ApplyRemotePathNodeUpdateFromOp(op)
                elif op_type == 'path_node_del':
                    self._ApplyRemotePathNodeDeleteFromOp(op)
                elif op_type == 'path_node_order':
                    self._ApplyRemotePathNodeOrderFromOp(op)

            try:
                if needs_pipe_links and getattr(globals_, 'PipeLinksShown', True):
                    self.UpdatePipeEntranceLinks()
            except Exception:
                pass
            try:
                if needs_event_links and getattr(globals_, 'EventLinksShown', False):
                    self.UpdateEventLinks()
            except Exception:
                pass
            self.scene.update()
            self.levelOverview.update()
        finally:
            globals_.DirtyOverride -= 1
            self.scene.blockSignals(False)
            try:
                self.ChangeSelectionHandler()
            except Exception:
                pass
            self.collabApplyingRemote = False

    def _ApplyRemoteOpsToCache(self, area_num, ops):
        if not hasattr(self, 'collabAreaState'):
            return
        try:
            area_num = int(area_num)
        except Exception:
            return
        if area_num < 1:
            return

        state = self.collabAreaState.get(area_num)
        if not isinstance(state, dict):
            if hasattr(self, 'collabManager') and self.collabManager.mode == "host":
                self.BroadcastFullStateForArea(area_num)
                state = self.collabAreaState.get(area_num)
        if not isinstance(state, dict):
            return

        objects = state.get('objects')
        sprites = state.get('sprites')
        if not (isinstance(objects, list) and len(objects) >= 3):
            return
        if not isinstance(sprites, list):
            return

        default_sprite_data = base64.b64encode(bytes(10)).decode('ascii')

        for op in ops:
            if not isinstance(op, dict):
                continue
            op_type = op.get('op')
            ent_id = op.get('id')
            if not op_type or not ent_id:
                continue
            ent_id = str(ent_id)

            if op_type.startswith('obj_'):
                if op_type.endswith('_del'):
                    for layer in objects[:3]:
                        if not isinstance(layer, list):
                            continue
                        for i in range(len(layer) - 1, -1, -1):
                            item = layer[i]
                            if isinstance(item, (list, tuple)) and len(item) == 7 and str(item[0]) == ent_id:
                                del layer[i]
                                break
                    continue

                try:
                    layer_idx = int(op.get('layer', 1))
                    tileset = int(op.get('tileset', 0))
                    obj_type = int(op.get('type', 0))
                    x = int(op.get('x', 0))
                    y = int(op.get('y', 0))
                    w = int(op.get('w', 1))
                    h = int(op.get('h', 1))
                except Exception:
                    continue
                layer_idx = max(0, min(2, layer_idx))

                for li, layer in enumerate(objects[:3]):
                    if not isinstance(layer, list):
                        continue
                    for i in range(len(layer) - 1, -1, -1):
                        item = layer[i]
                        if isinstance(item, (list, tuple)) and len(item) == 7 and str(item[0]) == ent_id:
                            del layer[i]
                            break

                target_layer = objects[layer_idx]
                if isinstance(target_layer, list):
                    target_layer.append((ent_id, tileset, obj_type, x, y, w, h))
                continue

            if op_type.startswith('spr_'):
                if op_type.endswith('_del'):
                    for i in range(len(sprites) - 1, -1, -1):
                        item = sprites[i]
                        if isinstance(item, (list, tuple)) and len(item) == 5 and str(item[0]) == ent_id:
                            del sprites[i]
                            break
                    continue

                try:
                    spr_type = int(op.get('type', 0))
                    x = int(op.get('x', 0))
                    y = int(op.get('y', 0))
                except Exception:
                    continue

                data = None
                if isinstance(op.get('data'), str):
                    data = op.get('data')

                for i in range(len(sprites) - 1, -1, -1):
                    item = sprites[i]
                    if isinstance(item, (list, tuple)) and len(item) == 5 and str(item[0]) == ent_id:
                        prev_data = str(item[4]) if item[4] else default_sprite_data
                        sprites[i] = (ent_id, spr_type, x, y, data if data is not None else prev_data)
                        break
                else:
                    sprites.append((ent_id, spr_type, x, y, data if data is not None else default_sprite_data))

    def _ApplyRemoteMetaOpsToCache(self, area_num, ops):
        if not hasattr(self, 'collabAreaMetaState'):
            return
        try:
            area_num = int(area_num)
        except Exception:
            return
        if area_num < 1:
            return
        if not isinstance(ops, list) or not ops:
            return

        state = self.collabAreaMetaState.get(area_num)
        if not isinstance(state, dict):
            state = {'zones': [], 'options': {}, 'event_notes': '', 'paths': [], 'entrances': [], 'locations': [], 'comments': []}
            self.collabAreaMetaState[area_num] = state

        entrances = state.setdefault('entrances', [])
        locations = state.setdefault('locations', [])
        comments = state.setdefault('comments', [])
        paths = state.setdefault('paths', [])

        def upsert_list_item(lst, key_name, key_value, new_item):
            try:
                key_value = int(key_value) if key_name != 'id' or isinstance(key_value, int) else key_value
            except Exception:
                pass
            for idx, it in enumerate(lst):
                if not isinstance(it, dict):
                    continue
                if str(it.get(key_name)) == str(key_value):
                    lst[idx] = new_item
                    return
            lst.append(new_item)

        def delete_list_item(lst, key_name, key_value):
            for idx in range(len(lst) - 1, -1, -1):
                it = lst[idx]
                if not isinstance(it, dict):
                    continue
                if str(it.get(key_name)) == str(key_value):
                    del lst[idx]
                    return

        for op in ops:
            if not isinstance(op, dict):
                continue
            op_type = op.get('op')
            if op_type in ('ent_add', 'ent_upd'):
                entid = op.get('id')
                if entid is None:
                    continue
                new_ent = {
                    'entid': int(entid),
                    'x': int(op.get('x', 0)),
                    'y': int(op.get('y', 0)),
                    'destarea': int(op.get('destarea', 0)),
                    'destentrance': int(op.get('destentrance', 0)),
                    'enttype': int(op.get('enttype', 0)),
                    'entzone': int(op.get('entzone', 0)),
                    'entlayer': int(op.get('entlayer', 0)),
                    'entpath': int(op.get('entpath', 0)),
                    'entsettings': int(op.get('entsettings', 0)),
                    'leave_level': bool(op.get('leave_level', False)),
                    'cpdirection': int(op.get('cpdirection', 0)),
                }
                upsert_list_item(entrances, 'entid', entid, new_ent)
            elif op_type == 'ent_del':
                entid = op.get('id')
                if entid is None:
                    continue
                delete_list_item(entrances, 'entid', entid)
            elif op_type in ('loc_add', 'loc_upd'):
                locid = op.get('id')
                if locid is None:
                    continue
                new_loc = {
                    'id': int(locid),
                    'x': int(op.get('x', 0)),
                    'y': int(op.get('y', 0)),
                    'w': int(op.get('w', 16)),
                    'h': int(op.get('h', 16)),
                }
                upsert_list_item(locations, 'id', locid, new_loc)
            elif op_type == 'loc_del':
                locid = op.get('id')
                if locid is None:
                    continue
                delete_list_item(locations, 'id', locid)
            elif op_type in ('com_add', 'com_upd'):
                cid = str(op.get('id') or '')
                if not cid:
                    continue
                new_com = {
                    'id': cid,
                    'x': int(op.get('x', 0)),
                    'y': int(op.get('y', 0)),
                    'text': str(op.get('text', '')),
                }
                upsert_list_item(comments, 'id', cid, new_com)
            elif op_type == 'com_del':
                cid = str(op.get('id') or '')
                if not cid:
                    continue
                delete_list_item(comments, 'id', cid)
            elif op_type == 'path_set':
                pid = op.get('path_id', op.get('id'))
                if pid is None:
                    continue
                node_states = []
                for idx, node_def in enumerate(op.get('nodes', []) if isinstance(op.get('nodes'), list) else []):
                    normalized = self._CollabNormalizePathNodeState(node_def, idx)
                    if normalized is not None:
                        node_states.append(normalized)
                new_path = {
                    'path_id': int(pid),
                    'loops': bool(op.get('loops', False)),
                    'nodes': node_states,
                }
                upsert_list_item(paths, 'path_id', pid, new_path)
            elif op_type == 'path_del':
                pid = op.get('path_id', op.get('id'))
                if pid is None:
                    continue
                delete_list_item(paths, 'path_id', pid)
            elif op_type == 'path_cfg_upd':
                pid = op.get('path_id', op.get('id'))
                if pid is None:
                    continue
                for p in paths:
                    if isinstance(p, dict) and str(p.get('path_id')) == str(pid):
                        p['loops'] = bool(op.get('loops', p.get('loops', False)))
                        break
            elif op_type == 'path_node_add':
                try:
                    pid = int(op.get('path_id', -1))
                except Exception:
                    continue
                if pid < 0:
                    continue
                node_state = self._CollabNormalizePathNodeState(op, op.get('node_id'))
                if node_state is None:
                    continue
                target_path = None
                for p in paths:
                    if isinstance(p, dict) and int(p.get('path_id', -1)) == pid:
                        target_path = p
                        break
                if target_path is None:
                    target_path = {'path_id': pid, 'loops': bool(op.get('loops', False)), 'nodes': []}
                    paths.append(target_path)
                nodes = target_path.setdefault('nodes', [])
                existing_idx = None
                for idx, existing_node in enumerate(nodes):
                    existing_node = self._CollabNormalizePathNodeState(existing_node, idx)
                    if existing_node is not None and str(existing_node.get('node_uid') or '') == str(node_state.get('node_uid') or '') and str(node_state.get('node_uid') or ''):
                        existing_idx = idx
                        break
                insert_idx = max(0, min(int(node_state.get('index', len(nodes))), len(nodes)))
                if existing_idx is not None:
                    nodes.pop(existing_idx)
                    if existing_idx < insert_idx:
                        insert_idx -= 1
                nodes.insert(insert_idx, node_state)
                for idx, existing_node in enumerate(nodes):
                    normalized = self._CollabNormalizePathNodeState(existing_node, idx)
                    if normalized is not None:
                        normalized['index'] = idx
                        nodes[idx] = normalized
            elif op_type == 'path_node_upd':
                try:
                    pid = int(op.get('path_id', -1))
                except Exception:
                    continue
                if pid < 0:
                    continue
                node_state = self._CollabNormalizePathNodeState(op, op.get('node_id'))
                if node_state is None:
                    continue
                for p in paths:
                    if not isinstance(p, dict) or int(p.get('path_id', -1)) != pid:
                        continue
                    nodes = p.get('nodes')
                    if not isinstance(nodes, list):
                        break
                    target_idx = None
                    for idx, existing_node in enumerate(nodes):
                        normalized = self._CollabNormalizePathNodeState(existing_node, idx)
                        if normalized is None:
                            continue
                        if str(normalized.get('node_uid') or '') and str(normalized.get('node_uid') or '') == str(node_state.get('node_uid') or ''):
                            target_idx = idx
                            break
                    if target_idx is None:
                        try:
                            fallback_idx = int(node_state.get('index', -1))
                        except Exception:
                            fallback_idx = -1
                        if 0 <= fallback_idx < len(nodes):
                            target_idx = fallback_idx
                    if target_idx is None:
                        break
                    node_state['index'] = int(target_idx)
                    nodes[target_idx] = node_state
                    break
            elif op_type == 'path_node_del':
                try:
                    pid = int(op.get('path_id', -1))
                except Exception:
                    continue
                if pid < 0:
                    continue
                node_uid = str(op.get('node_uid') or '')
                try:
                    node_idx = int(op.get('node_id', -1))
                except Exception:
                    node_idx = -1
                for p in paths:
                    if not isinstance(p, dict) or int(p.get('path_id', -1)) != pid:
                        continue
                    nodes = p.get('nodes')
                    if not isinstance(nodes, list):
                        break
                    removed = False
                    if node_uid:
                        for idx in range(len(nodes) - 1, -1, -1):
                            normalized = self._CollabNormalizePathNodeState(nodes[idx], idx)
                            if normalized is not None and str(normalized.get('node_uid') or '') == node_uid:
                                del nodes[idx]
                                removed = True
                                break
                    elif 0 <= node_idx < len(nodes):
                        del nodes[node_idx]
                        removed = True
                    if removed:
                        for idx, existing_node in enumerate(nodes):
                            normalized = self._CollabNormalizePathNodeState(existing_node, idx)
                            if normalized is not None:
                                normalized['index'] = idx
                                nodes[idx] = normalized
                    break
            elif op_type == 'path_node_order':
                try:
                    pid = int(op.get('path_id', -1))
                except Exception:
                    continue
                if pid < 0:
                    continue
                desired_order = [str(item or '') for item in (op.get('order') if isinstance(op.get('order'), list) else [])]
                if not desired_order:
                    continue
                for p in paths:
                    if not isinstance(p, dict) or int(p.get('path_id', -1)) != pid:
                        continue
                    nodes = p.get('nodes')
                    if not isinstance(nodes, list):
                        break
                    by_uid = {}
                    for idx, existing_node in enumerate(nodes):
                        normalized = self._CollabNormalizePathNodeState(existing_node, idx)
                        if normalized is not None and str(normalized.get('node_uid') or ''):
                            by_uid[str(normalized.get('node_uid'))] = normalized
                    reordered = []
                    for uid in desired_order:
                        normalized = by_uid.get(uid)
                        if normalized is not None:
                            reordered.append(normalized)
                    if len(reordered) == len(nodes):
                        for idx, normalized in enumerate(reordered):
                            normalized['index'] = idx
                        p['nodes'] = reordered
                    break

    def _ApplyRemoteObjectUpsert(self, op):
        obj_id = op.get('id')
        if not obj_id:
            return
        obj_id = str(obj_id)

        try:
            layer_idx = int(op.get('layer', 1))
        except Exception:
            layer_idx = 1
        layer_idx = max(0, min(2, layer_idx))

        try:
            tileset = int(op.get('tileset', 0))
            obj_type = int(op.get('type', 0))
            x = int(op.get('x', 0))
            y = int(op.get('y', 0))
            w = int(op.get('w', 1))
            h = int(op.get('h', 1))
        except Exception:
            return

        existing = self._collabObjectById.get(obj_id)
        if existing is not None and self._CollabItemIsHot(existing):
            return
        if existing is None:
            try:
                for candidate in globals_.Area.layers[layer_idx]:
                    if getattr(candidate, '_collab_id', None):
                        continue
                    if (candidate.tileset, candidate.type, candidate.objx, candidate.objy, candidate.width, candidate.height) == (tileset, obj_type, x, y, w, h):
                        candidate._collab_id = obj_id
                        self._collabObjectById[obj_id] = candidate
                        existing = candidate
                        break
            except Exception:
                existing = None

        if existing is None:
            created = self.CreateObject(tileset, obj_type, layer_idx, x, y, w, h, add_to_scene=True)
            if created is None:
                return
            created._collab_id = obj_id
            self._collabObjectById[obj_id] = created
            return

        obj = existing
        if getattr(obj, 'layer', layer_idx) != layer_idx:
            try:
                globals_.Area.RemoveFromLayer(obj)
            except Exception:
                pass
            new_layer = globals_.Area.layers[layer_idx]
            if not new_layer:
                z_value = (2 - layer_idx) * 8192
            else:
                z_value = new_layer[-1].zValue() + 1
            obj.layer = layer_idx
            new_layer.append(obj)
            obj.setZValue(z_value)
            if layer_idx == 0:
                obj.setVisible(globals_.Layer0Shown)
            elif layer_idx == 1:
                obj.setVisible(globals_.Layer1Shown)
            else:
                obj.setVisible(globals_.Layer2Shown)

        if getattr(obj, 'tileset', tileset) != tileset or getattr(obj, 'type', obj_type) != obj_type:
            try:
                obj.SetType(tileset, obj_type)
            except Exception:
                pass

        oldx = getattr(obj, 'objx', 0)
        oldy = getattr(obj, 'objy', 0)
        size_changed = (getattr(obj, 'width', 1) != w) or (getattr(obj, 'height', 1) != h)
        pos_changed = (oldx != x) or (oldy != y)

        obj.autoPosChange = True
        try:
            if pos_changed:
                obj.setPos(int(x) * 24, int(y) * 24)
            if size_changed:
                try:
                    obj.UpdateObj(oldx, oldy, [w, h])
                except Exception:
                    obj.width = w
                    obj.height = h
                    obj.UpdateRects()
            obj.UpdateTooltip()
            obj.update()
        finally:
            obj.autoPosChange = False

    def _ApplyRemoteObjectDelete(self, op):
        obj_id = op.get('id')
        if not obj_id:
            return
        obj_id = str(obj_id)
        victim = self._collabObjectById.pop(obj_id, None)
        if victim is None:
            return
        try:
            victim.delete()
        except Exception:
            pass
        try:
            self.scene.removeItem(victim)
        except Exception:
            pass

    def _ApplyRemoteSpriteUpsert(self, op):
        spr_id = op.get('id')
        if not spr_id:
            return
        spr_id = str(spr_id)
        try:
            spr_type = int(op.get('type', 0))
            x = int(op.get('x', 0))
            y = int(op.get('y', 0))
        except Exception:
            return

        data_b64 = op.get('data')
        decoded = None
        if isinstance(data_b64, str):
            try:
                decoded = base64.b64decode(data_b64)
            except (ValueError, TypeError):
                decoded = bytes(10)

        existing = self._collabSpriteById.get(spr_id)
        if existing is None:
            try:
                for candidate in globals_.Area.sprites:
                    if getattr(candidate, '_collab_id', None):
                        continue
                    if int(getattr(candidate, 'type', -1)) == spr_type and int(getattr(candidate, 'objx', 0)) == x and int(getattr(candidate, 'objy', 0)) == y:
                        candidate._collab_id = spr_id
                        self._collabSpriteById[spr_id] = candidate
                        existing = candidate
                        break
            except Exception:
                existing = None

        if existing is None:
            if decoded is None:
                decoded = bytes(10)
            created = self.CreateSprite(x, y, id_=spr_type, data=decoded, add_to_scene=True)
            if created is None:
                return
            created._collab_id = spr_id
            self._collabSpriteById[spr_id] = created
            return

        spr = existing
        if getattr(spr, 'type', spr_type) != spr_type:
            try:
                spr.SetType(spr_type)
            except Exception:
                pass

        if decoded is not None:
            spr.spritedata = decoded
            try:
                spr.UpdateDynamicSizing()
            except Exception:
                pass
            try:
                self.spriteList.updateSprite(spr)
            except Exception:
                pass

        try:
            spr.ChangingPos = True
        except Exception:
            pass
        try:
            spr.setNewObjPos(x, y)
        except Exception:
            try:
                spr.objx = x
                spr.objy = y
                spr.setPos(int(x) * 1.5, int(y) * 1.5)
            except Exception:
                pass
        finally:
            try:
                spr.ChangingPos = False
            except Exception:
                pass
        try:
            spr.UpdateListItem()
        except Exception:
            pass

    def _ApplyRemoteSpriteDelete(self, op):
        spr_id = op.get('id')
        if not spr_id:
            return
        spr_id = str(spr_id)
        victim = self._collabSpriteById.pop(spr_id, None)
        if victim is None:
            return
        try:
            victim.delete()
        except Exception:
            pass
        try:
            self.scene.removeItem(victim)
        except Exception:
            pass

    def _ApplyRemoteEntranceUpsertFromOp(self, op):
        try:
            entid = int(op.get('id', op.get('entid', 0)))
        except Exception:
            return
        if entid < 0:
            return
        existing = None
        try:
            for ent in globals_.Area.entrances:
                if int(getattr(ent, 'entid', -1)) == entid:
                    existing = ent
                    break
        except Exception:
            existing = None

        if existing is None:
            existing = self.CreateEntrance(int(op.get('x', 0)), int(op.get('y', 0)), id_=entid, add_to_scene=True, record_undo=False)
            if existing is None:
                return

        if self._CollabItemIsHot(existing):
            return

        existing.autoPosChange = True
        try:
            existing.destarea = int(op.get('destarea', getattr(existing, 'destarea', 0)))
            existing.destentrance = int(op.get('destentrance', getattr(existing, 'destentrance', 0)))
            existing.enttype = int(op.get('enttype', getattr(existing, 'enttype', 0)))
            existing.entzone = int(op.get('entzone', getattr(existing, 'entzone', 0)))
            existing.entlayer = int(op.get('entlayer', getattr(existing, 'entlayer', 0)))
            existing.entpath = int(op.get('entpath', getattr(existing, 'entpath', 0)))
            existing.entsettings = int(op.get('entsettings', getattr(existing, 'entsettings', 0)))
            existing.leave_level = bool(op.get('leave_level', getattr(existing, 'leave_level', False)))
            existing.cpdirection = int(op.get('cpdirection', getattr(existing, 'cpdirection', 0)))

            existing.objx = int(op.get('x', getattr(existing, 'objx', 0)))
            existing.objy = int(op.get('y', getattr(existing, 'objy', 0)))
            existing.setPos(int(existing.objx * 1.5), int(existing.objy * 1.5))
            try:
                existing.UpdateRects()
                existing.aux.TypeChange()
                existing.UpdateTooltip()
            except Exception:
                pass
            try:
                existing.UpdateListItem()
            except Exception:
                pass
        finally:
            existing.autoPosChange = False

    def _ApplyRemoteEntranceDeleteFromOp(self, op):
        try:
            entid = int(op.get('id', op.get('entid', 0)))
        except Exception:
            return
        victim = None
        try:
            for ent in globals_.Area.entrances:
                if int(getattr(ent, 'entid', -1)) == entid:
                    victim = ent
                    break
        except Exception:
            victim = None
        if victim is None or self._CollabItemIsHot(victim):
            return
        try:
            victim.delete()
        except Exception:
            pass
        try:
            self.scene.removeItem(victim)
        except Exception:
            pass

    def _ApplyRemoteLocationUpsertFromOp(self, op):
        try:
            locid = int(op.get('id', op.get('locid', 0)))
        except Exception:
            return
        if locid < 0:
            return
        existing = None
        try:
            for loc in globals_.Area.locations:
                if int(getattr(loc, 'id', -1)) == locid:
                    existing = loc
                    break
        except Exception:
            existing = None

        if existing is None:
            existing = self.CreateLocation(
                int(op.get('x', 0)),
                int(op.get('y', 0)),
                int(op.get('w', 16)),
                int(op.get('h', 16)),
                id_=locid,
                add_to_scene=True,
                record_undo=False,
            )
            if existing is None:
                return

        if self._CollabItemIsHot(existing):
            return

        existing.autoPosChange = True
        try:
            existing.objx = int(op.get('x', getattr(existing, 'objx', 0)))
            existing.objy = int(op.get('y', getattr(existing, 'objy', 0)))
            existing.width = int(op.get('w', getattr(existing, 'width', 16)))
            existing.height = int(op.get('h', getattr(existing, 'height', 16)))
            existing.setPos(int(existing.objx * 1.5), int(existing.objy * 1.5))
            try:
                existing.UpdateTitle()
                existing.UpdateRects()
            except Exception:
                pass
            try:
                existing.UpdateListItem()
            except Exception:
                pass
        finally:
            existing.autoPosChange = False

    def _ApplyRemoteLocationDeleteFromOp(self, op):
        try:
            locid = int(op.get('id', op.get('locid', 0)))
        except Exception:
            return
        victim = None
        try:
            for loc in globals_.Area.locations:
                if int(getattr(loc, 'id', -1)) == locid:
                    victim = loc
                    break
        except Exception:
            victim = None
        if victim is None or self._CollabItemIsHot(victim):
            return
        try:
            victim.delete()
        except Exception:
            pass
        try:
            self.scene.removeItem(victim)
        except Exception:
            pass

    def _ApplyRemoteCommentUpsertFromOp(self, op):
        cid = str(op.get('id') or '')
        if not cid:
            return
        existing = None
        try:
            for com in globals_.Area.comments:
                if str(getattr(com, '_collab_id', '') or '') == cid:
                    existing = com
                    break
        except Exception:
            existing = None

        if existing is None:
            existing = self.CreateCommentRemote(int(op.get('x', 0)), int(op.get('y', 0)), str(op.get('text', '')))
            if existing is None:
                return
            existing._collab_id = cid

        if self._CollabItemIsHot(existing):
            return

        existing.autoPosChange = True
        try:
            existing.objx = int(op.get('x', getattr(existing, 'objx', 0)))
            existing.objy = int(op.get('y', getattr(existing, 'objy', 0)))
            existing.setPos(int(existing.objx * 1.5), int(existing.objy * 1.5))
            new_text = str(op.get('text', getattr(existing, 'text', '')))
            if getattr(existing, 'text', '') != new_text:
                try:
                    existing.text = new_text
                except Exception:
                    pass
                try:
                    te = getattr(existing, 'TextEdit', None)
                    if te is not None:
                        te.blockSignals(True)
                        te.setPlainText(new_text)
                        te.blockSignals(False)
                except Exception:
                    pass
            try:
                existing.UpdateTooltip()
                existing.UpdateListItem()
            except Exception:
                pass
        finally:
            existing.autoPosChange = False

    def _ApplyRemoteCommentDeleteFromOp(self, op):
        cid = str(op.get('id') or '')
        if not cid:
            return
        victim = None
        try:
            for com in globals_.Area.comments:
                if str(getattr(com, '_collab_id', '') or '') == cid:
                    victim = com
                    break
        except Exception:
            victim = None
        if victim is None or self._CollabItemIsHot(victim):
            return
        try:
            victim.delete()
        except Exception:
            pass
        try:
            self.scene.removeItem(victim)
        except Exception:
            pass

    def _ApplyRemotePathSetFromOp(self, op):
        try:
            path_id = int(op.get('path_id', op.get('id', -1)))
        except Exception:
            return
        if path_id < 0:
            return
        nodes = op.get('nodes')
        if not isinstance(nodes, list):
            nodes = []
        loops = bool(op.get('loops', False))

        path_obj = self._CollabFindPathById(path_id)
        if path_obj is not None and self._CollabPathIsHot(path_obj):
            return

        if path_obj is not None:
            try:
                if getattr(path_obj, '_has_line', False):
                    self.scene.removeItem(path_obj._line_item)
            except Exception:
                pass
            for node in list(getattr(path_obj, '_nodes', [])):
                try:
                    node.delete()
                    self.scene.removeItem(node)
                except Exception:
                    pass
            try:
                globals_.Area.paths.remove(path_obj)
            except Exception:
                pass

        rebuilt = Path(path_id, self.scene, loops)
        globals_.Area.paths.append(rebuilt)
        for idx, node_def in enumerate(nodes):
            normalized = self._CollabNormalizePathNodeState(node_def, idx)
            if normalized is None:
                continue
            created = rebuilt.add_node(
                int(normalized.get('x', 0)),
                int(normalized.get('y', 0)),
                speed=float(normalized.get('speed', 0.5)),
                accel=float(normalized.get('accel', 0.00498)),
                delay=int(normalized.get('delay', 0)),
                add_to_list=True,
                add_to_scene=True,
            )
            if created is not None and str(normalized.get('node_uid') or ''):
                created._collab_id = str(normalized.get('node_uid'))
        rebuilt.add_to_scene()

    def _ApplyRemotePathDeleteFromOp(self, op):
        try:
            path_id = int(op.get('path_id', op.get('id', -1)))
        except Exception:
            return
        if path_id < 0:
            return
        path_obj = self._CollabFindPathById(path_id)
        if path_obj is None or self._CollabPathIsHot(path_obj):
            return
        try:
            if getattr(path_obj, '_has_line', False):
                self.scene.removeItem(path_obj._line_item)
        except Exception:
            pass
        for node in list(getattr(path_obj, '_nodes', [])):
            try:
                node.delete()
                self.scene.removeItem(node)
            except Exception:
                pass
        try:
            globals_.Area.paths.remove(path_obj)
        except Exception:
            pass

    def _ApplyRemotePathConfigUpdateFromOp(self, op):
        try:
            path_id = int(op.get('path_id', op.get('id', -1)))
        except Exception:
            return
        if path_id < 0:
            return
        path_obj = self._CollabFindPathById(path_id)
        if path_obj is None or self._CollabPathIsHot(path_obj):
            return
        try:
            path_obj.set_loops(bool(op.get('loops', path_obj.get_loops())))
        except Exception:
            pass

    def _ApplyRemotePathNodeAddFromOp(self, op):
        try:
            path_id = int(op.get('path_id', -1))
        except Exception:
            return
        if path_id < 0:
            return
        node_state = self._CollabNormalizePathNodeState(op, op.get('node_id'))
        if node_state is None:
            return
        path_obj = self._CollabFindPathById(path_id)
        if path_obj is not None and self._CollabPathIsHot(path_obj):
            return
        if path_obj is None:
            path_obj = Path(path_id, self.scene, bool(op.get('loops', False)))
            globals_.Area.paths.append(path_obj)
            path_obj.add_to_scene()
        else:
            try:
                path_obj.set_loops(bool(op.get('loops', path_obj.get_loops())))
            except Exception:
                pass

        existing_idx, existing_node = self._CollabFindPathNode(
            path_obj,
            node_state.get('node_uid'),
            node_state.get('index'),
            strict_uid=bool(node_state.get('node_uid')),
        )
        if existing_node is not None:
            self._ApplyRemotePathNodeUpdateFromOp(op)
            return

        insert_idx = max(0, min(int(node_state.get('index', len(getattr(path_obj, '_nodes', []) or []))), len(getattr(path_obj, '_nodes', []) or [])))
        created = path_obj.add_node(
            int(node_state.get('x', 0)),
            int(node_state.get('y', 0)),
            speed=float(node_state.get('speed', 0.5)),
            accel=float(node_state.get('accel', 0.00498)),
            delay=int(node_state.get('delay', 0)),
            index=insert_idx,
            add_to_list=True,
            add_to_scene=True,
        )
        if created is None:
            return
        if str(node_state.get('node_uid') or ''):
            created._collab_id = str(node_state.get('node_uid'))
        try:
            path_obj._line_item.update_path()
        except Exception:
            pass

    def _ApplyRemotePathNodeUpdateFromOp(self, op):
        try:
            path_id = int(op.get('path_id', -1))
        except Exception:
            return
        if path_id < 0:
            return
        path_obj = self._CollabFindPathById(path_id)
        if path_obj is None or self._CollabPathIsHot(path_obj):
            return
        node_state = self._CollabNormalizePathNodeState(op, op.get('node_id'))
        if node_state is None:
            return
        _idx, node = self._CollabFindPathNode(
            path_obj,
            node_state.get('node_uid'),
            node_state.get('index'),
            strict_uid=bool(node_state.get('node_uid')),
        )
        if node is None:
            self._CollabRequestFullSync(int(getattr(globals_.Area, 'areanum', 1)))
            return
        if self._CollabItemIsHot(node):
            return
        node.autoPosChange = True
        try:
            if str(node_state.get('node_uid') or ''):
                node._collab_id = str(node_state.get('node_uid'))
            node.objx = int(node_state.get('x', 0))
            node.objy = int(node_state.get('y', 0))
            node.setPos(int(node.objx) * 1.5, int(node.objy) * 1.5)
            try:
                path_obj.set_node_data(
                    node,
                    speed=float(node_state.get('speed', 0.5)),
                    accel=float(node_state.get('accel', 0.00498)),
                    delay=int(node_state.get('delay', 0)),
                )
            except Exception:
                pass
            try:
                node.UpdateListItem()
            except Exception:
                pass
            try:
                path_obj._line_item.update_path()
            except Exception:
                pass
        finally:
            node.autoPosChange = False

    def _ApplyRemotePathNodeDeleteFromOp(self, op):
        try:
            path_id = int(op.get('path_id', -1))
        except Exception:
            return
        if path_id < 0:
            return
        path_obj = self._CollabFindPathById(path_id)
        if path_obj is None or self._CollabPathIsHot(path_obj):
            return
        node_idx, node = self._CollabFindPathNode(
            path_obj,
            op.get('node_uid'),
            op.get('node_id'),
            strict_uid=bool(op.get('node_uid')),
        )
        if node is None:
            self._CollabRequestFullSync(int(getattr(globals_.Area, 'areanum', 1)))
            return
        if self._CollabItemIsHot(node):
            return
        try:
            became_empty = path_obj.remove_node(int(node_idx))
        except Exception:
            self._CollabRequestFullSync(int(getattr(globals_.Area, 'areanum', 1)))
            return
        if became_empty:
            try:
                globals_.Area.paths.remove(path_obj)
            except Exception:
                pass

    def _ApplyRemotePathNodeOrderFromOp(self, op):
        try:
            path_id = int(op.get('path_id', -1))
        except Exception:
            return
        if path_id < 0:
            return
        order = [str(item or '') for item in (op.get('order') if isinstance(op.get('order'), list) else [])]
        if not order:
            return
        path_obj = self._CollabFindPathById(path_id)
        if path_obj is None or self._CollabPathIsHot(path_obj):
            return
        nodes = list(getattr(path_obj, '_nodes', []) or [])
        node_data = list(getattr(path_obj, '_node_data', []) or [])
        if len(nodes) != len(order):
            self._CollabRequestFullSync(int(getattr(globals_.Area, 'areanum', 1)))
            return
        node_map = {}
        for idx, node in enumerate(nodes):
            node_uid = str(getattr(node, '_collab_id', '') or '')
            if not node_uid:
                continue
            node_map[node_uid] = (node, node_data[idx] if idx < len(node_data) else None)
        reordered_nodes = []
        reordered_data = []
        for uid in order:
            pair = node_map.get(uid)
            if pair is None:
                self._CollabRequestFullSync(int(getattr(globals_.Area, 'areanum', 1)))
                return
            reordered_nodes.append(pair[0])
            reordered_data.append(pair[1])
        path_obj._nodes = reordered_nodes
        path_obj._node_data = reordered_data
        for idx, node in enumerate(path_obj._nodes):
            try:
                node.update_id(idx)
            except Exception:
                pass
        try:
            path_obj._line_item.update_path()
        except Exception:
            pass

    def HandleRemoteMessage(self, message, sender):
        msg_type = message.get('type')
        if globals_.Area is None or globals_.Level is None:
            # During startup, tileset updates may arrive before the level is
            # ready. Keep them around for later.
            if msg_type in {'tileset_data', 'tileset_update'}:
                try:
                    self._collabPendingTilesetPayloads.append((message.get('payload') or {}, sender))
                except Exception:
                    pass
            return

        if msg_type not in {'host_hello', 'peer_kicked', 'peer_banned', 'peer_rejected'} and (
            getattr(self, 'collabSwitchingArea', False)
            or self.collabApplyingRemote
            or self.collabApplyingRemoteHistory
            or self.IsLocalEditInProgress()
        ):
            self._QueuePendingRemoteMessage(message, sender)
            return

        payload = message.get('payload') or {}
        if msg_type == 'host_hello':
            host = payload.get('host')
            if host:
                self.collabHostSessionId = str(host)
            else:
                self.collabHostSessionId = str(sender)
            self._BroadcastCollabNick()
            self._ScheduleCollabTilesetSync(50)
            # Request authoritative undo/redo history state from the host.
            if self._CollabHistoryEnabled() and self.IsCollabClientMode():
                try:
                    self._CollabRequestHistorySync()
                except Exception:
                    pass
        elif msg_type == 'nick':
            nick = str(payload.get('nick') or '').strip()
            if nick:
                self._CollabSetPeerNick(sender, nick)
            self._CollabSetPeerColor(sender, payload.get('color'))
        elif msg_type == 'chat':
            nick = str(payload.get('nick') or '').strip()
            if nick:
                self._CollabSetPeerNick(sender, nick)
            text = str(payload.get('text') or '')
            display = nick if nick else self._CollabPeerDisplayName(sender)
            if text:
                self._ChatAddLine('%s: %s' % (display, text))
        elif msg_type == 'cursor_state':
            self._UpdateRemoteCursorState(sender, payload)
        elif msg_type == 'ping':
            if self._NormalizeCollabCursorDisplayMode(getattr(self, 'collabCursorDisplayMode', COLLAB_CURSOR_DISPLAY_ALWAYS)) == COLLAB_CURSOR_DISPLAY_NEVER:
                return
            nick = str(payload.get('nick') or '').strip()
            if nick:
                self._CollabSetPeerNick(sender, nick)
            self._CollabSetPeerColor(sender, payload.get('color'))
            try:
                area_num = int(payload.get('area_num', 0) or 0)
            except Exception:
                area_num = 0
            level_name = str(payload.get('level_name') or '')
            if area_num and area_num != int(getattr(globals_.Area, 'areanum', 0) or 0):
                return
            if not self._CollabMatchesLevelName(level_name):
                return
            try:
                scene_pos = QtCore.QPointF(float(payload.get('x', 0.0)), float(payload.get('y', 0.0)))
            except Exception:
                scene_pos = None
            if scene_pos is not None:
                display = nick if nick else self._CollabPeerDisplayName(sender)
                self._AddCollabPing(scene_pos, display, sender, payload.get('color'))
        elif msg_type == 'peer_kicked':
            QtWidgets.QMessageBox.information(self, 'Collaboration', 'You were kicked by the host.')
            self.HandleCollabStop()
            return
        elif msg_type == 'peer_banned':
            ip = str(payload.get('ip') or 'unknown')
            QtWidgets.QMessageBox.warning(self, 'Collaboration', 'You were banned by the host.\nIP: %s' % ip)
            self.HandleCollabStop()
            return
        elif msg_type == 'peer_rejected':
            reason = str(payload.get('message') or 'The host rejected your connection.')
            QtWidgets.QMessageBox.warning(self, 'Collaboration', reason)
            self.HandleCollabStop()
            return
        elif msg_type == 'ops':
            self.ApplyRemoteOps(payload, sender)
        elif msg_type == 'scene_patch':
            if self.collabHostSessionId is not None and sender != self.collabHostSessionId:
                return
            self.ApplyRemoteScenePatch(payload, sender)
        elif msg_type == 'meta_state':
            self.ApplyRemoteMetaState(payload, sender)
            # Tilesets are not part of the meta payload; request them separately.
            if self.collabHostSessionId is None or sender == self.collabHostSessionId:
                self._ScheduleCollabTilesetSync(150)
        elif msg_type == 'hist_sync_req':
            if hasattr(self, 'collabManager') and self.collabManager.mode == "host":
                self._CollabHostSendHistoryStateToPeer(sender)
        elif msg_type == 'hist_state':
            self._CollabApplyHistoryState(payload)
        elif msg_type == 'hist_submit_add':
            if hasattr(self, 'collabManager') and self.collabManager.mode == "host":
                self._CollabHostHandleHistorySubmitAdd(payload, sender)
        elif msg_type == 'hist_submit_upd':
            if hasattr(self, 'collabManager') and self.collabManager.mode == "host":
                self._CollabHostHandleHistorySubmitUpdate(payload, sender)
        elif msg_type == 'hist_req_undo':
            if hasattr(self, 'collabManager') and self.collabManager.mode == "host":
                self._CollabHostBroadcastUndo(origin=sender)
        elif msg_type == 'hist_req_redo':
            if hasattr(self, 'collabManager') and self.collabManager.mode == "host":
                self._CollabHostBroadcastRedo(origin=sender)
        elif msg_type in {'hist_add', 'hist_upd', 'hist_undo', 'hist_redo'}:
            # Only accept history events from the host in client mode.
            if self.IsCollabClientMode() and self.collabHostSessionId is not None and sender != self.collabHostSessionId:
                return
            # Apply only for the currently loaded level/area.
            try:
                hist_area = int(payload.get('area_num', 0) or 0)
            except Exception:
                hist_area = 0
            hist_level = str(payload.get('level_name') or '')
            if hist_area and hist_area != int(getattr(globals_.Area, 'areanum', 0) or 0):
                return
            if hist_level and hist_level != str(self._CollabCurrentLevelName() or ''):
                return
            try:
                rev = int(payload.get('rev', 0) or 0)
            except Exception:
                rev = 0
            if rev and rev <= int(getattr(self, '_collabHistoryLastAppliedRev', 0) or 0):
                return
            if rev:
                self._collabHistoryLastAppliedRev = rev
            if msg_type == 'hist_add':
                self._ApplyRemoteHistoryAdd(payload)
            elif msg_type == 'hist_upd':
                self._ApplyRemoteHistoryUpdate(payload)
            elif msg_type == 'hist_undo':
                self._ApplyRemoteHistoryUndo(payload)
            elif msg_type == 'hist_redo':
                self._ApplyRemoteHistoryRedo(payload)
        elif msg_type == 'level_switch':
            if self.collabHostSessionId is not None and sender != self.collabHostSessionId:
                return
            self.ApplyRemoteLevelSwitch(payload)
        elif msg_type == 'request_full_sync':
            if hasattr(self, 'collabManager') and self.collabManager.mode == "host":
                try:
                    target_area = int(payload.get('area_num', getattr(globals_.Area, 'areanum', 1)))
                except Exception:
                    target_area = getattr(globals_.Area, 'areanum', 1)
                self.BroadcastFullStateForArea(target_area)
        elif msg_type == 'tileset_sync_request':
            if hasattr(self, 'collabManager') and self.collabManager.mode == "host":
                area_num = payload.get('area_num')
                self._HostSendTilesetsToPeer(sender, area_num=area_num)
        elif msg_type in ('tileset_data', 'tileset_update'):
            name, data, slots = self._DecodeTilesetPayload(payload)
            if name and data:
                self._ApplyCollabTilesetBytes(name, data, slots=slots, broadcast=False)
                try:
                    self.TryApplyPendingRemoteSnapshot()
                except Exception:
                    pass
        elif msg_type == 'qpt_ui':
            return
        elif msg_type == 'sel':
            self._ApplyRemoteSelection(payload, sender)

    def BuildCollabSceneState(self):
        state = {'objects': [[], [], []], 'sprites': [], 'paths': [], 'entrances': [], 'locations': [], 'comments': []}

        for layer_idx, layer in enumerate(globals_.Area.layers):
            for obj in layer:
                if not hasattr(obj, '_collab_id'):
                    obj._collab_id = uuid.uuid4().hex
                state['objects'][layer_idx].append(
                    (obj._collab_id, obj.tileset, obj.type, obj.objx, obj.objy, obj.width, obj.height)
                )

        for spr in globals_.Area.sprites:
            if not hasattr(spr, '_collab_id'):
                spr._collab_id = uuid.uuid4().hex
            state['sprites'].append((
                spr._collab_id,
                spr.type,
                spr.objx,
                spr.objy,
                base64.b64encode(spr.spritedata).decode('ascii'),
            ))

        return state

    def BuildCollabMetaState(self):
        state = {'zones': [], 'options': {}, 'event_notes': '', 'paths': [], 'entrances': [], 'locations': [], 'comments': []}

        area_num = int(getattr(globals_.Area, 'areanum', 0))

        try:
            notes = globals_.Area.Metadata.binData('EventNotes_A%d' % area_num)
        except Exception:
            notes = None
        if notes:
            state['event_notes'] = base64.b64encode(notes).decode('ascii')

        try:
            state['options'] = {
                'defEvents': int(getattr(globals_.Area, 'defEvents', 0)),
                'timeLimit': int(getattr(globals_.Area, 'timeLimit', 300)),
                'creditsFlag': bool(getattr(globals_.Area, 'creditsFlag', False)),
                'startEntrance': int(getattr(globals_.Area, 'startEntrance', 0)),
                'faceLeftFlag': bool(getattr(globals_.Area, 'faceLeftFlag', False)),
                'toadHouseType': int(getattr(globals_.Area, 'toadHouseType', 0)),
                'wrapFlag': bool(getattr(globals_.Area, 'wrapFlag', False)),
                'unkFlag1': bool(getattr(globals_.Area, 'unkFlag1', False)),
                'unkFlag2': bool(getattr(globals_.Area, 'unkFlag2', False)),
                'unkVal1': int(getattr(globals_.Area, 'unkVal1', 0)),
                'unkVal2': int(getattr(globals_.Area, 'unkVal2', 0)),
                'tileset0': str(getattr(globals_.Area, 'tileset0', '')),
                'tileset1': str(getattr(globals_.Area, 'tileset1', '')),
                'tileset2': str(getattr(globals_.Area, 'tileset2', '')),
                'tileset3': str(getattr(globals_.Area, 'tileset3', '')),
            }
        except Exception:
            state['options'] = {}

        for z in getattr(globals_.Area, 'zones', []):
            try:
                state['zones'].append({
                    'objx': int(getattr(z, 'objx', 0)),
                    'objy': int(getattr(z, 'objy', 0)),
                    'width': int(getattr(z, 'width', 0)),
                    'height': int(getattr(z, 'height', 0)),
                    'modeldark': int(getattr(z, 'modeldark', 0)),
                    'terraindark': int(getattr(z, 'terraindark', 0)),
                    'id': int(getattr(z, 'id', 0)),
                    'cammode': int(getattr(z, 'cammode', 0)),
                    'camzoom': int(getattr(z, 'camzoom', 0)),
                    'visibility': int(getattr(z, 'visibility', 0)),
                    'camtrack': int(getattr(z, 'camtrack', 0)),
                    'music': int(getattr(z, 'music', 0)),
                    'sfxmod': int(getattr(z, 'sfxmod', 0)),
                    'yupperbound': int(getattr(z, 'yupperbound', 0)),
                    'ylowerbound': int(getattr(z, 'ylowerbound', 0)),
                    'yupperbound2': int(getattr(z, 'yupperbound2', 0)),
                    'ylowerbound2': int(getattr(z, 'ylowerbound2', 0)),
                    'mpcamzoomadjust': int(getattr(z, 'mpcamzoomadjust', 15)),
                    'yupperbound3': int(getattr(z, 'yupperbound3', 0)),
                    'ylowerbound3': int(getattr(z, 'ylowerbound3', 0)),
                    'XscrollA': int(getattr(z, 'XscrollA', 0)),
                    'YscrollA': int(getattr(z, 'YscrollA', 0)),
                    'YpositionA': int(getattr(z, 'YpositionA', 0)),
                    'XpositionA': int(getattr(z, 'XpositionA', 0)),
                    'bg1A': int(getattr(z, 'bg1A', 0)),
                    'bg2A': int(getattr(z, 'bg2A', 0)),
                    'bg3A': int(getattr(z, 'bg3A', 0)),
                    'ZoomA': int(getattr(z, 'ZoomA', 0)),
                    'XscrollB': int(getattr(z, 'XscrollB', 0)),
                    'YscrollB': int(getattr(z, 'YscrollB', 0)),
                    'YpositionB': int(getattr(z, 'YpositionB', 0)),
                    'XpositionB': int(getattr(z, 'XpositionB', 0)),
                    'bg1B': int(getattr(z, 'bg1B', 0)),
                    'bg2B': int(getattr(z, 'bg2B', 0)),
                    'bg3B': int(getattr(z, 'bg3B', 0)),
                    'ZoomB': int(getattr(z, 'ZoomB', 0)),
                })
            except Exception:
                continue

        for path in globals_.Area.paths:
            path_state = self._CollabBuildPathState(path)
            if path_state is not None:
                state['paths'].append(path_state)

        for ent in globals_.Area.entrances:
            state['entrances'].append({
                'entid': int(ent.entid),
                'x': int(ent.objx),
                'y': int(ent.objy),
                'destarea': int(ent.destarea),
                'destentrance': int(ent.destentrance),
                'enttype': int(ent.enttype),
                'entzone': int(ent.entzone),
                'entlayer': int(ent.entlayer),
                'entpath': int(ent.entpath),
                'entsettings': int(ent.entsettings),
                'leave_level': bool(getattr(ent, 'leave_level', False)),
                'cpdirection': int(getattr(ent, 'cpdirection', 0)),
            })

        for loc in globals_.Area.locations:
            state['locations'].append({
                'id': int(loc.id),
                'x': int(loc.objx),
                'y': int(loc.objy),
                'w': int(loc.width),
                'h': int(loc.height),
            })

        for com in globals_.Area.comments:
            state['comments'].append(self._BuildCollabCommentState(com))

        return state

    def ApplyRemoteScenePatch(self, payload, sender):
        area_num = int(payload.get('area_num', 0))
        if area_num < 1:
            return

        remote_state = payload.get('state')
        if not isinstance(remote_state, dict):
            return
        try:
            remote_rev = int(payload.get('rev', 0))
        except Exception:
            remote_rev = 0

        area_num = int(area_num)
        state_key = (sender, area_num)
        last_rev = self.collabPeerLastRev.get(state_key, 0)
        if remote_rev and remote_rev <= last_rev:
            return

        prev_state_for_sender_area = self.collabPeerLastState.get(state_key)

        # Cache state for this area even if we're not currently viewing it.
        self.collabPeerLastState[state_key] = remote_state
        if remote_rev:
            self.collabPeerLastRev[state_key] = remote_rev
        self.collabAreaState[area_num] = remote_state

        if area_num != globals_.Area.areanum:
            return

        self.collabApplyingRemote = True
        self.scene.blockSignals(True)
        try:
            globals_.DirtyOverride += 1
            self._CollabRebuildIndexes()
            current_scene_state = self.BuildCollabSceneState()
            # Prevent undo actions from being created during remote apply
            if prev_state_for_sender_area is None:
                self.ApplyRemoteSceneDelta(current_scene_state, remote_state)
            else:
                base_state = prev_state_for_sender_area
                if current_scene_state != prev_state_for_sender_area:
                    base_state = current_scene_state
                self.ApplyRemoteSceneDelta(base_state, remote_state)

            self._CollabPruneDuplicateIdsCurrentArea()

            self.scene.update()
            self.levelOverview.update()
            self.collabLastSceneSig = hash(repr(self.BuildCollabSceneState()))
            self._CollabRebuildIndexes()
            self.collabPeerLastState[state_key] = remote_state
            if remote_rev:
                self.collabPeerLastRev[state_key] = remote_rev
            try:
                level_data = globals_.Level.save()
                self.collabLastHash = hash(level_data)
                self.collabLastSentHash = self.collabLastHash
            except Exception:
                pass
        finally:
            globals_.DirtyOverride -= 1
            self.scene.blockSignals(False)
            try:
                self.ChangeSelectionHandler()
            except Exception:
                pass
            self.collabApplyingRemote = False

    def ApplyRemoteSceneDelta(self, prev_state, next_state):
        self.ApplyRemoteObjectsDelta(prev_state.get('objects', []), next_state.get('objects', []))
        self.ApplyRemoteSpritesDelta(prev_state.get('sprites', []), next_state.get('sprites', []))

    def ApplyRemoteEntrancesDelta(self, prev_ents, next_ents):
        if not isinstance(prev_ents, list) or not isinstance(next_ents, list):
            return
        next_map = {int(e.get('entid')): e for e in next_ents if isinstance(e, dict) and 'entid' in e}
        existing = {int(e.entid): e for e in globals_.Area.entrances}

        # Remove missing
        for entid, ent in list(existing.items()):
            if entid not in next_map:
                if self._CollabItemIsHot(ent):
                    continue
                try:
                    ent.delete()
                    self.scene.removeItem(ent)
                except Exception:
                    pass

        # Add/update
        for entid, data in next_map.items():
            ent = existing.get(entid)
            if ent is not None and self._CollabItemIsHot(ent):
                continue
            if ent is None:
                ent = self.CreateEntrance(int(data.get('x', 0)), int(data.get('y', 0)), id_=entid, add_to_scene=True)
                if ent is None:
                    continue
                existing[entid] = ent

            ent.autoPosChange = True
            try:
                ent.destarea = int(data.get('destarea', ent.destarea))
                ent.destentrance = int(data.get('destentrance', ent.destentrance))
                ent.enttype = int(data.get('enttype', ent.enttype))
                ent.entzone = int(data.get('entzone', ent.entzone))
                ent.entlayer = int(data.get('entlayer', ent.entlayer))
                ent.entpath = int(data.get('entpath', ent.entpath))
                ent.entsettings = int(data.get('entsettings', ent.entsettings))
                ent.leave_level = bool(data.get('leave_level', getattr(ent, 'leave_level', False)))
                ent.cpdirection = int(data.get('cpdirection', getattr(ent, 'cpdirection', 0)))

                ent.objx = int(data.get('x', ent.objx))
                ent.objy = int(data.get('y', ent.objy))
                ent.setPos(int(ent.objx * 1.5), int(ent.objy * 1.5))

                ent.UpdateRects()
                ent.aux.TypeChange()
                ent.UpdateTooltip()
                ent.UpdateListItem()
            finally:
                ent.autoPosChange = False

    def ApplyRemoteLocationsDelta(self, prev_locs, next_locs):
        if not isinstance(prev_locs, list) or not isinstance(next_locs, list):
            return
        next_map = {int(l.get('id')): l for l in next_locs if isinstance(l, dict) and 'id' in l}
        existing = {int(l.id): l for l in globals_.Area.locations}

        # Remove missing
        for locid, loc in list(existing.items()):
            if locid not in next_map:
                if self._CollabItemIsHot(loc):
                    continue
                try:
                    loc.delete()
                    self.scene.removeItem(loc)
                except Exception:
                    pass

        # Add/update
        for locid, data in next_map.items():
            loc = existing.get(locid)
            if loc is not None and self._CollabItemIsHot(loc):
                continue
            if loc is None:
                loc = self.CreateLocation(
                    int(data.get('x', 0)),
                    int(data.get('y', 0)),
                    int(data.get('w', 16)),
                    int(data.get('h', 16)),
                    id_=locid,
                    add_to_scene=True,
                )
                if loc is None:
                    continue
                existing[locid] = loc

            loc.autoPosChange = True
            try:
                loc.objx = int(data.get('x', loc.objx))
                loc.objy = int(data.get('y', loc.objy))
                loc.width = int(data.get('w', loc.width))
                loc.height = int(data.get('h', loc.height))
                loc.setPos(int(loc.objx * 1.5), int(loc.objy * 1.5))
                loc.UpdateTitle()
                loc.UpdateRects()
                loc.UpdateListItem()
            finally:
                loc.autoPosChange = False

    def CreateComment(self, x, y, text, add_to_scene=True, record_undo=True, save=True):
        com = CommentItem(int(x), int(y), str(text))
        com.positionChanged = self.HandleComPosChange
        com.textChanged = self.HandleComTxtChange
        com.listitem = QtWidgets.QListWidgetItem()
        if add_to_scene:
            self.commentList.addItem(com.listitem)
            self.scene.addItem(com)
            globals_.Area.comments.append(com)
        com.UpdateListItem()
        if add_to_scene:
            if not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False):
                self._CollabEnsureItemId(com)
                self._CollabMarkItemHot(com)
            try:
                SetDirty()
            except Exception:
                pass
            if save:
                try:
                    self.SaveComments()
                except Exception:
                    pass
            self.CollabQueueCommentUpsert(com, is_add=True)
            if record_undo and not self.UndoRedoInProgress and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False) and not globals_.DirtyOverride:
                from undo import CreateOrDeleteInstanceUndoAction
                self.undoStack.addAction(CreateOrDeleteInstanceUndoAction('create', com.instanceDef(com), collab_id=self._CollabEnsureItemId(com)))
        return com

    def CreateCommentRemote(self, x, y, text):
        return self.CreateComment(x, y, text, add_to_scene=True, record_undo=False, save=False)

    def ApplyRemoteCommentsDelta(self, prev_comments, next_comments):
        if not isinstance(prev_comments, list) or not isinstance(next_comments, list):
            return

        if any(isinstance(c, dict) and c.get('id') for c in prev_comments + next_comments):
            prev_map = {}
            for c in prev_comments:
                if not isinstance(c, dict):
                    continue
                comment_id = str(c.get('id') or '')
                if not comment_id:
                    continue
                prev_map[comment_id] = c

            next_map = {}
            for c in next_comments:
                if not isinstance(c, dict):
                    continue
                comment_id = str(c.get('id') or '')
                if not comment_id:
                    continue
                next_map[comment_id] = c

            existing = {}
            for comment in globals_.Area.comments:
                comment_id = getattr(comment, '_collab_id', None)
                if comment_id:
                    existing[str(comment_id)] = comment

            changed = False

            for comment_id, comment in list(existing.items()):
                if comment_id in next_map:
                    continue
                if self._CollabItemIsHot(comment):
                    continue
                try:
                    comment.delete()
                    self.scene.removeItem(comment)
                    changed = True
                except Exception:
                    pass

            for comment_id, data in next_map.items():
                comment = existing.get(comment_id)
                if comment is None:
                    prev_data = prev_map.get(comment_id) or {}
                    for candidate in globals_.Area.comments:
                        if getattr(candidate, '_collab_id', None):
                            continue
                        candidate_key = (
                            int(candidate.objx),
                            int(candidate.objy),
                            str(getattr(candidate, 'text', '')),
                        )
                        next_key = (
                            int(data.get('x', 0)),
                            int(data.get('y', 0)),
                            str(data.get('text', '')),
                        )
                        prev_key = (
                            int(prev_data.get('x', data.get('x', 0))),
                            int(prev_data.get('y', data.get('y', 0))),
                            str(prev_data.get('text', data.get('text', ''))),
                        )
                        if candidate_key in (next_key, prev_key):
                            candidate._collab_id = comment_id
                            comment = candidate
                            existing[comment_id] = candidate
                            break

                if comment is None:
                    comment = self.CreateCommentRemote(int(data.get('x', 0)), int(data.get('y', 0)), str(data.get('text', '')))
                    if comment is None:
                        continue
                    comment._collab_id = comment_id
                    existing[comment_id] = comment
                    changed = True
                    continue

                if self._CollabItemIsHot(comment):
                    continue

                oldx = int(getattr(comment, 'objx', 0))
                oldy = int(getattr(comment, 'objy', 0))
                newx = int(data.get('x', oldx))
                newy = int(data.get('y', oldy))
                newtext = str(data.get('text', getattr(comment, 'text', '')))

                if oldx != newx or oldy != newy:
                    comment.autoPosChange = True
                    try:
                        comment.objx = newx
                        comment.objy = newy
                        comment.setPos(int(newx * 1.5), int(newy * 1.5))
                    finally:
                        comment.autoPosChange = False
                    comment.handlePosChange(oldx, oldy)
                    comment.UpdateTooltip()
                    changed = True

                if str(getattr(comment, 'text', '')) != newtext:
                    try:
                        comment.TextEdit.blockSignals(True)
                        comment.TextEdit.setPlainText(newtext)
                    finally:
                        comment.TextEdit.blockSignals(False)
                    comment.text = newtext
                    changed = True

                comment.UpdateListItem()

            if changed:
                try:
                    self.SaveComments()
                except Exception:
                    pass
            return

        def norm(lst):
            out = []
            for c in lst:
                if not isinstance(c, dict):
                    continue
                out.append((int(c.get('x', 0)), int(c.get('y', 0)), str(c.get('text', ''))))
            return out

        prev = collections.Counter(norm(prev_comments))
        nxt = collections.Counter(norm(next_comments))
        removes = prev - nxt
        adds = nxt - prev

        for key, count in removes.items():
            x, y, text = key
            for _ in range(count):
                victim = None
                for c in globals_.Area.comments:
                    if int(c.objx) == x and int(c.objy) == y and str(getattr(c, 'text', '')) == text:
                        victim = c
                        break
                if victim is None:
                    continue
                try:
                    victim.delete()
                    self.scene.removeItem(victim)
                except Exception:
                    pass

        for key, count in adds.items():
            x, y, text = key
            for _ in range(count):
                self.CreateCommentRemote(x, y, text)

        if removes or adds:
            try:
                self.SaveComments()
            except Exception:
                pass

    def ReplaceAreaZonesFromMetaState(self, meta_state):
        items = self.scene.items()
        func_ii = isinstance
        type_zone = ZoneItem
        for item in items:
            if func_ii(item, type_zone):
                try:
                    self.scene.removeItem(item)
                except Exception:
                    pass

        zones_in = meta_state.get('zones', [])
        zones_out = []
        for zd in zones_in if isinstance(zones_in, list) else []:
            if not isinstance(zd, dict):
                continue
            try:
                objx = int(zd.get('objx', 16))
                objy = int(zd.get('objy', 16))
                width = int(zd.get('width', 408))
                height = int(zd.get('height', 224))
                modeldark = int(zd.get('modeldark', 0))
                terraindark = int(zd.get('terraindark', 0))
                zid = int(zd.get('id', 0))
                cammode = int(zd.get('cammode', 0))
                camzoom = int(zd.get('camzoom', 0))
                visibility = int(zd.get('visibility', 0))
                camtrack = int(zd.get('camtrack', 0))
                music = int(zd.get('music', 0))
                sfxmod = int(zd.get('sfxmod', 0))
            except Exception:
                continue

            bounding = [(
                int(zd.get('yupperbound', 0)),
                int(zd.get('ylowerbound', 0)),
                int(zd.get('yupperbound2', 0)),
                int(zd.get('ylowerbound2', 0)),
                0,
                int(zd.get('mpcamzoomadjust', 15)),
                int(zd.get('yupperbound3', 0)),
                int(zd.get('ylowerbound3', 0)),
            )]
            bgA = [(
                0,
                int(zd.get('XscrollA', 0)),
                int(zd.get('YscrollA', 0)),
                int(zd.get('YpositionA', 0)),
                int(zd.get('XpositionA', 0)),
                int(zd.get('bg1A', 0)),
                int(zd.get('bg2A', 0)),
                int(zd.get('bg3A', 0)),
                int(zd.get('ZoomA', 0)),
            )]
            bgB = [(
                0,
                int(zd.get('XscrollB', 0)),
                int(zd.get('YscrollB', 0)),
                int(zd.get('YpositionB', 0)),
                int(zd.get('XpositionB', 0)),
                int(zd.get('bg1B', 0)),
                int(zd.get('bg2B', 0)),
                int(zd.get('bg3B', 0)),
                int(zd.get('ZoomB', 0)),
            )]

            try:
                z = ZoneItem(
                    objx, objy, width, height,
                    modeldark, terraindark,
                    zid, 0,
                    cammode, camzoom, visibility,
                    0, 0,
                    camtrack, music, sfxmod,
                    bounding, bgA, bgB,
                    id_=zid,
                )
            except Exception:
                continue
            zones_out.append(z)
            try:
                self.scene.addItem(z)
            except Exception:
                pass

        globals_.Area.zones = zones_out
        try:
            self.actions['backgrounds'].setEnabled(len(globals_.Area.zones) > 0)
        except Exception:
            pass

        for spr in globals_.Area.sprites:
            try:
                spr.ImageObj.positionChanged()
            except Exception:
                pass

    def _ApplyMetaStateToCurrentArea(self, meta_state):
        prev_state = self.BuildCollabMetaState()

        self.collabApplyingRemote = True
        self.scene.blockSignals(True)
        try:
            globals_.DirtyOverride += 1
            options = meta_state.get('options') or {}
            if isinstance(options, dict):
                try:
                    globals_.Area.defEvents = int(options.get('defEvents', globals_.Area.defEvents))
                    globals_.Area.timeLimit = int(options.get('timeLimit', globals_.Area.timeLimit))
                    globals_.Area.creditsFlag = bool(options.get('creditsFlag', globals_.Area.creditsFlag))
                    globals_.Area.startEntrance = int(options.get('startEntrance', globals_.Area.startEntrance))
                    globals_.Area.faceLeftFlag = bool(options.get('faceLeftFlag', globals_.Area.faceLeftFlag))
                    globals_.Area.toadHouseType = int(options.get('toadHouseType', globals_.Area.toadHouseType))
                    globals_.Area.wrapFlag = bool(options.get('wrapFlag', globals_.Area.wrapFlag))
                    globals_.Area.unkFlag1 = bool(options.get('unkFlag1', globals_.Area.unkFlag1))
                    globals_.Area.unkFlag2 = bool(options.get('unkFlag2', globals_.Area.unkFlag2))
                    globals_.Area.unkVal1 = int(options.get('unkVal1', globals_.Area.unkVal1))
                    globals_.Area.unkVal2 = int(options.get('unkVal2', globals_.Area.unkVal2))
                except Exception:
                    pass

                try:
                    desired_tilesets = (
                        str(options.get('tileset0', getattr(globals_.Area, 'tileset0', ''))),
                        str(options.get('tileset1', getattr(globals_.Area, 'tileset1', ''))),
                        str(options.get('tileset2', getattr(globals_.Area, 'tileset2', ''))),
                        str(options.get('tileset3', getattr(globals_.Area, 'tileset3', ''))),
                    )
                    current_tilesets = (
                        str(getattr(globals_.Area, 'tileset0', '')),
                        str(getattr(globals_.Area, 'tileset1', '')),
                        str(getattr(globals_.Area, 'tileset2', '')),
                        str(getattr(globals_.Area, 'tileset3', '')),
                    )
                    if desired_tilesets != current_tilesets:
                        globals_.Area.tileset0, globals_.Area.tileset1, globals_.Area.tileset2, globals_.Area.tileset3 = desired_tilesets
                        suppress_missing_tileset_warnings = self.IsCollabClientMode()
                        for idx, fname in enumerate(desired_tilesets):
                            try:
                                if suppress_missing_tileset_warnings:
                                    self._SetCollabMissingTilesetWarningsSuppressed(True)
                                if fname:
                                    LoadTileset(idx, fname)
                                else:
                                    UnloadTileset(idx)
                            finally:
                                if suppress_missing_tileset_warnings:
                                    self._SetCollabMissingTilesetWarningsSuppressed(False)
                        try:
                            self.objPicker.LoadFromTilesets()
                            self.objAllTab.setTabEnabled(0, (globals_.Area.tileset0 != ''))
                            self.objAllTab.setTabEnabled(1, (globals_.Area.tileset1 != ''))
                            self.objAllTab.setTabEnabled(2, (globals_.Area.tileset2 != ''))
                            self.objAllTab.setTabEnabled(3, (globals_.Area.tileset3 != ''))
                        except Exception:
                            pass
                        try:
                            for layer in globals_.Area.layers:
                                for obj in layer:
                                    obj.updateObjCache()
                        except Exception:
                            pass
                        try:
                            self._RefreshQuickPaintTilesetState()
                        except Exception:
                            pass
                except Exception:
                    pass

            notes_b64 = meta_state.get('event_notes')
            if isinstance(notes_b64, str):
                try:
                    decoded = base64.b64decode(notes_b64) if notes_b64 else b""
                    globals_.Area.Metadata.setBinData('EventNotes_A%d' % getattr(globals_.Area, 'areanum', 0), decoded)
                except Exception:
                    pass

            try:
                self.LoadEventTabFromLevel()
            except Exception:
                pass

            self.ReplaceAreaZonesFromMetaState(meta_state)
            self.ApplyRemotePathsDelta(prev_state.get('paths', []), meta_state.get('paths', []))
            self.ApplyRemoteEntrancesDelta(prev_state.get('entrances', []), meta_state.get('entrances', []))
            self.ApplyRemoteLocationsDelta(prev_state.get('locations', []), meta_state.get('locations', []))
            self.ApplyRemoteCommentsDelta(prev_state.get('comments', []), meta_state.get('comments', []))

            try:
                self.UpdatePipeEntranceLinks()
            except Exception:
                pass
            try:
                if getattr(globals_, 'EventLinksShown', False):
                    self.UpdateEventLinks()
            except Exception:
                pass
            self.scene.update()
            self.levelOverview.update()
        finally:
            globals_.DirtyOverride -= 1
            self.scene.blockSignals(False)
            try:
                self.ChangeSelectionHandler()
            except Exception:
                pass
            self.collabApplyingRemote = False

    def ApplyRemoteMetaState(self, payload, sender):
        try:
            area_num = int(payload.get('area_num', 0))
        except Exception:
            area_num = 0
        if area_num < 1:
            return

        meta_state = payload.get('state')
        if not isinstance(meta_state, dict):
            return
        try:
            remote_rev = int(payload.get('rev', 0))
        except Exception:
            remote_rev = 0

        state_key = (sender, area_num)
        last_rev = self.collabPeerLastMetaRev.get(state_key, 0)
        if remote_rev and remote_rev <= last_rev:
            return
        if remote_rev:
            self.collabPeerLastMetaRev[state_key] = remote_rev
        self.collabPeerLastMetaState[state_key] = meta_state
        self.collabAreaMetaState[area_num] = meta_state

        if area_num != getattr(globals_.Area, 'areanum', None):
            return
        self._ApplyMetaStateToCurrentArea(meta_state)

    def ApplyRemoteObjectsDelta(self, prev_layers, next_layers):
        next_by_id = {}
        next_noid = []
        for layer_idx, layer in enumerate(next_layers[:3] if isinstance(next_layers, list) else []):
            for obj in layer:
                if not isinstance(obj, (list, tuple)) or len(obj) not in (6, 7):
                    continue
                if len(obj) == 7:
                    obj_id, tileset, obj_type, objx, objy, w, h = obj
                    obj_id = str(obj_id)
                    if obj_id:
                        next_by_id[obj_id] = {
                            'id': obj_id,
                            'layer': int(layer_idx),
                            'tileset': int(tileset),
                            'type': int(obj_type),
                            'x': int(objx),
                            'y': int(objy),
                            'w': int(w),
                            'h': int(h),
                        }
                        continue
                    obj = (tileset, obj_type, objx, objy, w, h)
                tileset, obj_type, objx, objy, w, h = obj
                next_noid.append((int(layer_idx), int(tileset), int(obj_type), int(objx), int(objy), int(w), int(h)))

        existing_by_id = {}
        for layer in globals_.Area.layers[:3]:
            for obj in layer:
                obj_id = getattr(obj, '_collab_id', None)
                if obj_id:
                    existing_by_id[str(obj_id)] = obj

        for obj_id, obj in list(existing_by_id.items()):
            if obj_id in next_by_id:
                continue
            if self._CollabItemIsHot(obj):
                continue
            try:
                obj.delete()
            except Exception:
                pass
            try:
                self.scene.removeItem(obj)
            except Exception:
                pass
            self._collabObjectById.pop(obj_id, None)

        for op in next_by_id.values():
            existing = existing_by_id.get(op['id'])
            if existing is not None and self._CollabItemIsHot(existing):
                continue
            self._ApplyRemoteObjectUpsert(op)

        def flatten_noid(layers):
            out = []
            for layer_idx, layer in enumerate(layers[:3] if isinstance(layers, list) else []):
                for obj in layer:
                    if not isinstance(obj, (list, tuple)) or len(obj) != 6:
                        continue
                    tileset, obj_type, objx, objy, w, h = obj
                    out.append((int(layer_idx), int(tileset), int(obj_type), int(objx), int(objy), int(w), int(h)))
            return out

        prev_noid = collections.Counter(flatten_noid(prev_layers))
        nxt_noid = collections.Counter(next_noid)
        removes = prev_noid - nxt_noid
        adds = nxt_noid - prev_noid

        for key, count in removes.items():
            layer_idx, tileset, obj_type, objx, objy, w, h = key
            for _ in range(count):
                layer_list = globals_.Area.layers[layer_idx]
                victim = None
                for candidate in layer_list:
                    if getattr(candidate, '_collab_id', None):
                        continue
                    if (candidate.tileset, candidate.type, candidate.objx, candidate.objy, candidate.width, candidate.height) == (tileset, obj_type, objx, objy, w, h):
                        victim = candidate
                        break
                if victim is None:
                    continue
                victim.delete()
                try:
                    self.scene.removeItem(victim)
                except Exception:
                    pass

        for key, count in adds.items():
            layer_idx, tileset, obj_type, objx, objy, w, h = key
            for _ in range(count):
                self.CreateObject(tileset, obj_type, layer_idx, objx, objy, w, h, add_to_scene=True)

    def ApplyRemoteSpritesDelta(self, prev_sprites, next_sprites):
        next_by_id = {}
        next_noid = []
        for spr in next_sprites if isinstance(next_sprites, list) else []:
            if not isinstance(spr, (list, tuple)) or len(spr) not in (4, 5):
                continue
            if len(spr) == 5:
                spr_id, spr_type, objx, objy, spr_data = spr
                spr_id = str(spr_id or '')
                if spr_id:
                    next_by_id[spr_id] = {
                        'op': 'spr_upd',
                        'id': spr_id,
                        'type': int(spr_type),
                        'x': int(objx),
                        'y': int(objy),
                        'data': str(spr_data),
                    }
                    continue
            else:
                spr_type, objx, objy, spr_data = spr
            next_noid.append((int(spr_type), int(objx), int(objy), str(spr_data)))

        existing_by_id = {}
        for spr in globals_.Area.sprites:
            spr_id = getattr(spr, '_collab_id', None)
            if spr_id:
                existing_by_id[str(spr_id)] = spr

        for spr_id, spr in list(existing_by_id.items()):
            if spr_id in next_by_id:
                continue
            if self._CollabItemIsHot(spr):
                continue
            try:
                spr.delete()
            except Exception:
                pass
            try:
                self.scene.removeItem(spr)
            except Exception:
                pass
            self._collabSpriteById.pop(spr_id, None)

        for op in next_by_id.values():
            existing = existing_by_id.get(op['id'])
            if existing is not None and self._CollabItemIsHot(existing):
                continue
            self._ApplyRemoteSpriteUpsert(op)

        def norm(lst):
            out = []
            if not isinstance(lst, list):
                return out
            for spr in lst:
                if not isinstance(spr, (list, tuple)) or len(spr) not in (4, 5):
                    continue
                if len(spr) == 5:
                    spr_id, spr_type, objx, objy, spr_data = spr
                    if str(spr_id or ''):
                        continue
                else:
                    spr_type, objx, objy, spr_data = spr
                out.append(("", int(spr_type), int(objx), int(objy), str(spr_data)))
            return out

        prev = collections.Counter(norm(prev_sprites))
        nxt = collections.Counter(next_noid)
        removes = prev - nxt
        adds = nxt - prev

        for key, count in removes.items():
            spr_type, objx, objy, spr_data = key
            for _ in range(count):
                victim = None
                for candidate in globals_.Area.sprites:
                    if getattr(candidate, '_collab_id', None):
                        continue
                    c_key = (int(candidate.type), int(candidate.objx), int(candidate.objy), base64.b64encode(candidate.spritedata).decode('ascii'))
                    if c_key == key:
                        victim = candidate
                        break
                if victim is None:
                    continue
                victim.delete()
                try:
                    self.scene.removeItem(victim)
                except Exception:
                    pass

        for key, count in adds.items():
            spr_type, objx, objy, spr_data = key
            try:
                decoded = base64.b64decode(spr_data)
            except (ValueError, TypeError):
                decoded = bytes(10)
            for _ in range(count):
                spr = self.CreateSprite(objx, objy, id_=spr_type, data=decoded, add_to_scene=True)

    def ApplyRemotePathsDelta(self, prev_paths, next_paths):
        try:
            prev_map = {int(p.get('path_id')): p for p in prev_paths if isinstance(p, dict) and 'path_id' in p}
            next_map = {int(p.get('path_id')): p for p in next_paths if isinstance(p, dict) and 'path_id' in p}
        except Exception:
            self.ReplaceAreaPathsFromState({'paths': next_paths})
            return

        existing = {getattr(p, '_id', None): p for p in globals_.Area.paths}

        # Remove paths that disappeared
        for pid, path_obj in list(existing.items()):
            if pid is None:
                continue
            if pid not in next_map:
                if self._CollabPathIsHot(path_obj):
                    continue
                if getattr(path_obj, '_has_line', False):
                    try:
                        self.scene.removeItem(path_obj._line_item)
                    except Exception:
                        pass
                # Delete nodes (each node.delete() updates lists)
                for node in list(getattr(path_obj, '_nodes', [])):
                    try:
                        node.delete()
                    except Exception:
                        pass
                    # node.delete() обычно уже снимает объект со сцены через Path.remove_node().
                    # Повторный removeItem() иногда приводит к крэшам Qt.
                    try:
                        if getattr(node, 'scene', None) is not None and node.scene() is not None:
                            self.scene.removeItem(node)
                    except Exception:
                        pass
                try:
                    globals_.Area.paths.remove(path_obj)
                except Exception:
                    pass

        # Add or update remaining paths
        for pid, next_def in next_map.items():
            loops = bool(next_def.get('loops', False))
            nodes = next_def.get('nodes', [])

            path_obj = existing.get(pid)
            if path_obj is not None and self._CollabPathIsHot(path_obj):
                continue
            if path_obj is None:
                path_obj = Path(pid, self.scene, loops)
                globals_.Area.paths.append(path_obj)
                path_obj.add_to_scene()
            else:
                try:
                    path_obj.set_loops(loops)
                except Exception:
                    pass

            desired_order = []
            for idx, node_def in enumerate(nodes if isinstance(nodes, list) else []):
                normalized = self._CollabNormalizePathNodeState(node_def, idx)
                desired_order.append(str(normalized.get('node_uid') or '') if normalized is not None else '')
            current_order = [str(getattr(node, '_collab_id', '') or '') for node in getattr(path_obj, '_nodes', []) or []]
            if not isinstance(nodes, list) or len(nodes) != len(getattr(path_obj, '_nodes', [])):
                if getattr(path_obj, '_has_line', False):
                    try:
                        self.scene.removeItem(path_obj._line_item)
                    except Exception:
                        pass
                for node in list(getattr(path_obj, '_nodes', [])):
                    try:
                        node.delete()
                    except Exception:
                        pass
                    try:
                        if getattr(node, 'scene', None) is not None and node.scene() is not None:
                            self.scene.removeItem(node)
                    except Exception:
                        pass
                try:
                    globals_.Area.paths.remove(path_obj)
                except Exception:
                    pass
                rebuilt = Path(pid, self.scene, loops)
                globals_.Area.paths.append(rebuilt)
                for idx, node_def in enumerate(nodes):
                    normalized = self._CollabNormalizePathNodeState(node_def, idx)
                    if normalized is None:
                        continue
                    created = rebuilt.add_node(
                        int(normalized.get('x', 0)),
                        int(normalized.get('y', 0)),
                        speed=float(normalized.get('speed', 0.5)),
                        accel=float(normalized.get('accel', 0.00498)),
                        delay=int(normalized.get('delay', 0)),
                        add_to_list=True,
                        add_to_scene=True,
                    )
                    if created is not None and str(normalized.get('node_uid') or ''):
                        created._collab_id = str(normalized.get('node_uid'))
                rebuilt.add_to_scene()
                continue
            if desired_order and all(desired_order) and desired_order != current_order:
                if getattr(path_obj, '_has_line', False):
                    try:
                        self.scene.removeItem(path_obj._line_item)
                    except Exception:
                        pass
                for node in list(getattr(path_obj, '_nodes', [])):
                    try:
                        node.delete()
                    except Exception:
                        pass
                    try:
                        if getattr(node, 'scene', None) is not None and node.scene() is not None:
                            self.scene.removeItem(node)
                    except Exception:
                        pass
                try:
                    globals_.Area.paths.remove(path_obj)
                except Exception:
                    pass
                rebuilt = Path(pid, self.scene, loops)
                globals_.Area.paths.append(rebuilt)
                for idx, node_def in enumerate(nodes):
                    normalized = self._CollabNormalizePathNodeState(node_def, idx)
                    if normalized is None:
                        continue
                    created = rebuilt.add_node(
                        int(normalized.get('x', 0)),
                        int(normalized.get('y', 0)),
                        speed=float(normalized.get('speed', 0.5)),
                        accel=float(normalized.get('accel', 0.00498)),
                        delay=int(normalized.get('delay', 0)),
                        add_to_list=True,
                        add_to_scene=True,
                    )
                    if created is not None and str(normalized.get('node_uid') or ''):
                        created._collab_id = str(normalized.get('node_uid'))
                rebuilt.add_to_scene()
                continue

            for idx, node_def in enumerate(nodes):
                normalized = self._CollabNormalizePathNodeState(node_def, idx)
                if normalized is None:
                    continue
                try:
                    node = path_obj._nodes[idx]
                    if str(normalized.get('node_uid') or ''):
                        node._collab_id = str(normalized.get('node_uid'))
                    node.autoPosChange = True
                    node.objx = int(normalized.get('x', 0))
                    node.objy = int(normalized.get('y', 0))
                    node.setPos(int(node.objx) * 1.5, int(node.objy) * 1.5)
                    node.autoPosChange = False
                    path_obj.set_node_data(
                        node,
                        speed=float(normalized.get('speed', 0.5)),
                        accel=float(normalized.get('accel', 0.00498)),
                        delay=int(normalized.get('delay', 0)),
                    )
                    node.UpdateListItem()
                except Exception:
                    pass
            try:
                path_obj._line_item.update_path()
            except Exception:
                pass

    def ReplaceAreaObjectsFromState(self, remote_state):
        try:
            self._collabObjectById = {}
        except Exception:
            pass
        for layer in globals_.Area.layers:
            for obj in list(layer):
                obj.delete()
                self.scene.removeItem(obj)

        object_layers = remote_state.get('objects', [])
        for layer_idx, objects in enumerate(object_layers[:3]):
            for obj in objects:
                if isinstance(obj, (list, tuple)) and len(obj) == 7:
                    obj_id, tileset, object_num, objx, objy, width, height = obj
                    created = self.CreateObject(tileset, object_num, layer_idx, objx, objy, width, height, add_to_scene=True)
                    if created is not None:
                        created._collab_id = str(obj_id)
                        try:
                            self._collabObjectById[str(obj_id)] = created
                        except Exception:
                            pass
                else:
                    tileset, object_num, objx, objy, width, height = obj
                    self.CreateObject(tileset, object_num, layer_idx, objx, objy, width, height, add_to_scene=True)

    def ReplaceAreaSpritesFromState(self, remote_state):
        try:
            self._collabSpriteById = {}
        except Exception:
            pass
        for spr in list(globals_.Area.sprites):
            spr.delete()
            self.scene.removeItem(spr)

        for sprite in remote_state.get('sprites', []):
            if isinstance(sprite, (list, tuple)) and len(sprite) == 5:
                spr_id, spr_type, objx, objy, spr_data = sprite
            else:
                spr_id, spr_type, objx, objy, spr_data = ("",) + tuple(sprite)
            try:
                decoded = base64.b64decode(spr_data)
            except (ValueError, TypeError):
                decoded = bytes(10)
            created = self.CreateSprite(objx, objy, id_=spr_type, data=decoded, add_to_scene=True)
            if created is not None and spr_id:
                created._collab_id = str(spr_id)
                try:
                    self._collabSpriteById[str(spr_id)] = created
                except Exception:
                    pass

    def ReplaceAreaPathsFromState(self, remote_state):
        # Remove existing paths (nodes + connector lines)
        for path in list(globals_.Area.paths):
            if getattr(path, '_has_line', False):
                try:
                    self.scene.removeItem(path._line_item)
                except Exception:
                    pass
            for node in list(getattr(path, '_nodes', [])):
                try:
                    node.delete()
                except Exception:
                    pass
                # node.delete() уже удаляет со сцены; повторный removeItem() может крэшить Qt
                try:
                    if getattr(node, 'scene', None) is not None and node.scene() is not None:
                        self.scene.removeItem(node)
                except Exception:
                    pass
        globals_.Area.paths = []

        for path_data in remote_state.get('paths', remote_state.get('paths', [])):
            path_id = int(path_data.get('path_id', 0))
            loops = bool(path_data.get('loops', False))
            nodes = path_data.get('nodes', [])
            path_obj = Path(path_id, self.scene, loops)
            globals_.Area.paths.append(path_obj)
            for idx, node_def in enumerate(nodes):
                normalized = self._CollabNormalizePathNodeState(node_def, idx)
                if normalized is None:
                    continue
                created = path_obj.add_node(
                    int(normalized.get('x', 0)),
                    int(normalized.get('y', 0)),
                    speed=float(normalized.get('speed', 0.5)),
                    accel=float(normalized.get('accel', 0.00498)),
                    delay=int(normalized.get('delay', 0)),
                    add_to_list=True,
                    add_to_scene=True,
                )
                if created is not None and str(normalized.get('node_uid') or ''):
                    created._collab_id = str(normalized.get('node_uid'))
            path_obj._line_item.update_path()

    def ApplyRemoteLevelSwitch(self, payload):
        level_name = payload.get('level_name')
        if not level_name:
            return

        area_num = int(payload.get('area_num', 1))
        if self.fileSavePath:
            target_path = os.path.join(os.path.dirname(self.fileSavePath), level_name)
        else:
            target_path = os.path.join(globals_.gamedef.GetStageGamePath(), level_name)

        if not os.path.isfile(target_path):
            return

        self.collabApplyingRemote = True
        try:
            if self.LoadLevel(target_path, True, max(1, min(4, area_num))):
                self.collabLastLevelName = os.path.basename(target_path)
                self.collabLastSceneSig = hash(repr(self.BuildCollabSceneState()))
        finally:
            self.collabApplyingRemote = False

    def HandleRemoteSnapshot(self, level_data, area_num, sender):
        if globals_.Area is None or globals_.Level is None:
            return
        if self.collabApplyingRemote:
            return
        if self.IsLocalEditInProgress():
            self.collabPendingSnapshot = (level_data, area_num, sender)
            if hasattr(self, 'hoverLabel'):
                self.hoverLabel.setText('Queued peer update (area %d) while editing' % area_num)
            return
        if self.IsCollabClientMode():
            missing_tilesets = self._GetMissingTilesetsForLevelData(level_data, area_num)
            if missing_tilesets:
                self.collabPendingSnapshot = (level_data, area_num, sender)
                self._ScheduleCollabTilesetSync(50)
                if hasattr(self, 'hoverLabel'):
                    self.hoverLabel.setText('Waiting for host tilesets: %s' % ', '.join(missing_tilesets))
                return
        try:
            new_digest = hash(level_data)
            if self.collabLastHash == new_digest:
                return

            suppress_missing_tileset_warnings = self.IsCollabClientMode()
            if suppress_missing_tileset_warnings:
                self._SetCollabMissingTilesetWarningsSuppressed(True)
            self.collabApplyingRemote = True
            self.collabLastRemoteSender = sender
            has_local_conflict = self.HasUnsyncedLocalChanges()
            merge_applied, merge_changed = self.TryMergeConcurrentCurrentArea(level_data, area_num)
            if (merge_applied is not None) and has_local_conflict:
                if merge_changed:
                    self.LoadLevelFromNetwork(merge_applied, globals_.Area.areanum)
                    self.collabLastHash = hash(merge_applied)
                else:
                    self.collabLastHash = new_digest
                self.collabLastSentHash = self.collabLastHash
            elif self.CanApplyRemoteAreaWithoutReload(level_data, area_num):
                self.ApplyRemoteAreaWithoutReload(level_data, area_num)
                self.collabLastHash = new_digest
                self.collabLastSentHash = self.collabLastHash
            else:
                self.LoadLevelFromNetwork(level_data, globals_.Area.areanum)
                self.collabLastHash = new_digest
                self.collabLastSentHash = self.collabLastHash
            if hasattr(self, 'hoverLabel'):
                self.hoverLabel.setText('Applied update from peer (area %d)' % area_num)
        finally:
            if self.IsCollabClientMode():
                self._SetCollabMissingTilesetWarningsSuppressed(False)
            self.collabApplyingRemote = False
            try:
                self._ApplyPendingTilesetPayloads()
            except Exception:
                pass
            try:
                if self.IsCollabClientMode():
                    self._ScheduleCollabTilesetSync(200)
            except Exception:
                pass

    def HasUnsyncedLocalChanges(self):
        """
        True if local level differs from the last snapshot we sent.
        """
        if globals_.Level is None:
            return False
        if self.collabLastSentHash is None:
            return False
        try:
            current_hash = hash(globals_.Level.save())
        except Exception:
            return True
        return current_hash != self.collabLastSentHash

    def IsLocalEditInProgress(self):
        """
        Returns True while user is actively editing with mouse input.
        """
        if not hasattr(self, 'view'):
            return False

        if self.view.currentobj is not None:
            return True

        buttons = QtWidgets.QApplication.mouseButtons()
        return buttons != QtCore.Qt.MouseButton.NoButton

    def TryApplyPendingRemoteSnapshot(self):
        """
        Applies a queued remote update when local editing is idle.
        """
        if self.collabPendingSnapshot is None:
            return False
        if self.collabApplyingRemote:
            return False
        if self.IsLocalEditInProgress():
            return False

        level_data, area_num, sender = self.collabPendingSnapshot
        self.collabPendingSnapshot = None
        self.HandleRemoteSnapshot(level_data, area_num, sender)
        return True

    def CanApplyRemoteAreaWithoutReload(self, levelData, areaNum):
        """
        Returns True if we can patch only one area without reloading scene.
        """
        if areaNum < 1:
            return False

        snapshot_info = self.ExtractSnapshotAreaData(levelData, areaNum)
        if snapshot_info is None:
            return False
        remote_area_count, _ = snapshot_info

        if areaNum > len(globals_.Level.areas):
            return False
        if remote_area_count != len(globals_.Level.areas):
            return False
        return areaNum != globals_.Area.areanum

    def ApplyRemoteAreaWithoutReload(self, levelData, areaNum):
        """
        Applies one remote area into the current level without scene reload.
        """
        snapshot_info = self.ExtractSnapshotAreaData(levelData, areaNum)
        if snapshot_info is None:
            return
        _, area_data = snapshot_info
        if area_data is None:
            return

        course, l0, l1, l2 = area_data

        target_area = globals_.Level.areas[areaNum - 1]
        if getattr(target_area, '_is_loaded', False):
            target_area.unload()
        target_area.set_data(course, l0, l1, l2)

    def ExtractSnapshotAreaData(self, levelData, areaNum):
        """
        Extracts raw files for one area from a snapshot without loading tilesets.
        """
        try:
            arc = archive.U8.load(levelData)
        except Exception:
            return None

        if "course" not in arc:
            return None

        area_data = [[None, None, None, None], [None, None, None, None], [None, None, None, None], [None, None, None, None]]
        for name, val in arc.files:
            if val is None:
                continue

            name = name.replace('\\', '/').split('/')[-1]
            if not name.startswith('course'):
                continue
            if not name.endswith('.bin'):
                continue

            if '_bgdatL' in name:
                if len(name) != 19:
                    continue
                try:
                    this_area = int(name[6])
                    lay_num = int(name[14])
                except ValueError:
                    continue
                if not (0 < this_area < 5):
                    continue
                area_data[this_area - 1][lay_num + 1] = val
            else:
                if len(name) != 11:
                    continue
                try:
                    this_area = int(name[6])
                except ValueError:
                    continue
                if not (0 < this_area < 5):
                    continue
                area_data[this_area - 1][0] = val

        loaded_area_count = 0
        for data in area_data:
            if data[0] is not None:
                loaded_area_count += 1

        if not (0 < areaNum < 5):
            return None
        if area_data[areaNum - 1][0] is None:
            return None

        area_tuple = tuple(area_data[areaNum - 1])
        return (loaded_area_count, area_tuple)

    def TryMergeConcurrentCurrentArea(self, remoteLevelData, areaNum):
        return None, False

    def MergeLayerPlacements(self, localLayerData, remoteLayerData):
        """
        Merges layer object streams by union of object records.
        """
        local_objects = self.DecodeLayerObjects(localLayerData)
        remote_objects = self.DecodeLayerObjects(remoteLayerData)

        local_object_set = set(local_objects)
        merged_objects = list(local_objects)
        changed = False
        for obj in remote_objects:
            if obj in local_object_set:
                continue
            merged_objects.append(obj)
            local_object_set.add(obj)
            changed = True

        return self.EncodeLayerObjects(merged_objects), changed

    def DecodeLayerObjects(self, layerData):
        """
        Decodes layer bytes to a list of object tuples.
        Tuple format: (tileset_type, objx, objy, width, height)
        """
        if layerData is None:
            return []

        obj_struct = struct.Struct('>HHHHH')
        objects = []
        for offset in range(0, len(layerData) - 2, 10):
            objects.append(obj_struct.unpack_from(layerData, offset))
        return objects

    def EncodeLayerObjects(self, objects):
        """
        Encodes a list of object tuples back to layer bytes.
        """
        if not objects:
            return None

        obj_struct = struct.Struct('>HHHHH')
        buffer = bytearray((len(objects) * 10) + 2)
        offset = 0
        for obj in objects:
            obj_struct.pack_into(buffer, offset, *obj)
            offset += 10
        buffer[offset] = 0xFF
        buffer[offset + 1] = 0xFF
        return bytes(buffer)

    def BuildSnapshotWithAreaData(self, levelData, areaNum, courseData, layer0, layer1, layer2):
        """
        Returns a copy of snapshot bytes with a single area replaced.
        """
        try:
            arc = archive.U8.load(levelData)
        except Exception:
            return None

        arc['course/course%d.bin' % areaNum] = courseData
        arc['course/course%d_bgdatL1.bin' % areaNum] = layer1

        layer_paths = (
            ('course/course%d_bgdatL0.bin' % areaNum, layer0),
            ('course/course%d_bgdatL2.bin' % areaNum, layer2),
        )
        for path, data in layer_paths:
            if data is None:
                arc.files = [(name, val) for name, val in arc.files if name != path]
            else:
                arc[path] = data

        return arc._dump()

    def CheckDirty(self):
        """
        Checks if the level is unsaved and attempts to save it if so.
        Returns whether the level still contains unsaved changes.
        """
        if self.IsCollabClientMode():
            globals_.Dirty = False
            globals_.AutoSaveDirty = False
            return False
        if not globals_.Dirty:
            return False

        msg = QtWidgets.QMessageBox()
        msg.setText(globals_.trans.string('AutoSaveDlg', 2))
        msg.setInformativeText(globals_.trans.string('AutoSaveDlg', 3))
        msg.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Save | QtWidgets.QMessageBox.StandardButton.Discard | QtWidgets.QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Save)
        ret = msg.exec()

        if ret == QtWidgets.QMessageBox.StandardButton.Save:
            # If the save failed, the file is still dirty, so we need to negate
            # the return value.
            return not self.HandleSave()

        elif ret == QtWidgets.QMessageBox.StandardButton.Cancel:
            return True

        return False

    def LoadEventTabFromLevel(self):
        """
        Configures the Events tab from the data in globals_.Area.defEvents
        """
        defEvents = globals_.Area.defEvents
        checked = Qt.CheckState.Checked
        unchecked = Qt.CheckState.Unchecked

        data = globals_.Area.Metadata.binData('EventNotes_A%d' % globals_.Area.areanum)
        eventTexts = {}
        if data is not None:
            # Iterate through the data
            idx = 0

            while idx < len(data):
                event_id, str_len = struct.unpack_from(">2I", data, idx)
                eventTexts[event_id] = data[idx + 8:idx + 8 + str_len].decode('utf-8')

                idx += 8 + str_len

        for i, item in enumerate(self.eventChooserItems):
            item.setCheckState(0, checked if (defEvents & (1 << i)) != 0 else unchecked)
            item.setText(1, eventTexts.get(i, ""))
            item.setSelected(False)

        self.eventChooserItems[0].setSelected(True)
        self.eventNotesEditor.setText(eventTexts.get(0, ""))

    def handleEventTabItemClick(self, item):
        """
        Handles an item being clicked in the Events tab
        """
        # Write the current note to the event note editor
        noteText = item.text(1)
        self.eventNotesEditor.setText(noteText)

        selIdx = self.eventChooserItems.index(item)
        isOn = (globals_.Area.defEvents & 1 << selIdx) == 1 << selIdx
        if item.checkState(0) == Qt.CheckState.Checked and not isOn:
            # Turn a bit on
            globals_.Area.defEvents |= 1 << selIdx
            SetDirty()
        elif item.checkState(0) == Qt.CheckState.Unchecked and isOn:
            # Turn a bit off (mask out 1 bit)
            globals_.Area.defEvents &= ~(1 << selIdx)
            SetDirty()
        self.CollabQueueMetaUpdate()

    def handleEventNotesEdit(self):
        """
        Handles the text within self.eventNotesEditor changing
        """
        newText = self.eventNotesEditor.text()

        # Set the text to the event chooser
        currentItem = self.eventChooser.selectedItems()[0]
        currentItem.setText(1, newText)

        # Save all the events to the metadata
        data = b""
        for i in range(64):
            event_note = str(self.eventChooserItems[i].text(1))
            if not event_note: continue

            encoded = event_note.encode('utf-8')

            # Add the event id, note length and note to the data.
            data += struct.pack(">2I", i, len(encoded))
            data += encoded

        globals_.Area.Metadata.setBinData('EventNotes_A%d' % globals_.Area.areanum, data)
        SetDirty()
        self.CollabQueueMetaUpdate()

    def handleStampsAdd(self):
        """
        Handles the "Add Stamp" btn being clicked
        """
        # Create a ReggieClip
        selitems = self.scene.selectedItems()
        if not selitems: return
        clipboard_o = []
        clipboard_s = []
        ii = isinstance
        type_obj = ObjectItem
        type_spr = SpriteItem
        for obj in selitems:
            if ii(obj, type_obj):
                clipboard_o.append(obj)
            elif ii(obj, type_spr):
                clipboard_s.append(obj)
        RegClp = self.encodeObjects(clipboard_o, clipboard_s)

        # Create a Stamp
        self.stampChooser.addStamp(Stamp(RegClp, 'New Stamp'))

    def handleStampsRemove(self):
        """
        Handles the "Remove Stamp" btn being clicked
        """
        self.stampChooser.removeStamp(self.stampChooser.currentlySelectedStamp())
        self.handleStampSelectionChanged()

    def handleStampsOpen(self):
        """
        Handles the "Open Set..." btn being clicked
        """
        filetypes = ''
        filetypes += globals_.trans.string('FileDlgs', 7) + ' (*.stamps);;'  # *.stamps
        filetypes += globals_.trans.string('FileDlgs', 2) + ' (*)'  # *
        fn = QtWidgets.QFileDialog.getOpenFileName(self, globals_.trans.string('FileDlgs', 6), '', filetypes)[0]
        if fn == '': return

        with open(fn, 'r', encoding='utf-8') as file:
            filedata = file.read()

        if not filedata.startswith('stamps\n------\n'): return

        filesplit = filedata.split('\n')[3:]
        for i in range(0, len(filesplit), 3):
            try:
                # Get data
                name = filesplit[i]
                rc = filesplit[i + 1]
            except IndexError:
                break

            self.stampChooser.addStamp(Stamp(rc, name))

    def handleStampsSave(self):
        """
        Handles the "Save Set As..." btn being clicked
        """
        filetypes = ''
        filetypes += globals_.trans.string('FileDlgs', 7) + ' (*.stamps);;'  # *.stamps
        filetypes += globals_.trans.string('FileDlgs', 2) + ' (*)'  # *
        fn = QtWidgets.QFileDialog.getSaveFileName(self, globals_.trans.string('FileDlgs', 3), '', filetypes)[0]
        if fn == '': return

        newdata = ''
        newdata += 'stamps\n'
        newdata += '------\n'

        for stampobj in self.stampChooser.model.items:
            newdata += '\n'
            newdata += stampobj.Name + '\n'
            newdata += stampobj.ReggieClip + '\n'

        with open(fn, 'w', encoding='utf-8') as f:
            f.write(newdata)

    def handleStampSelectionChanged(self):
        """
        Called when the stamp selection is changed
        """
        newStamp = self.stampChooser.currentlySelectedStamp()
        stampSelected = newStamp is not None
        self.stampRemoveBtn.setEnabled(stampSelected)
        self.stampNameEdit.setEnabled(stampSelected)

        newName = '' if not stampSelected else newStamp.Name
        old_state = self.stampNameEdit.blockSignals(True)
        try:
            self.stampNameEdit.setText(newName)
        finally:
            self.stampNameEdit.blockSignals(old_state)
        try:
            self._autoTilingTryApplyFromStamp(newStamp if stampSelected else None)
        except Exception:
            pass
        try:
            self._randomFillTryApplyFromStamp(newStamp if stampSelected else None)
        except Exception:
            pass

    def handleStampNameEdited(self):
        """
        Called when the user edits the name of the current stamp
        """
        stamp = self.stampChooser.currentlySelectedStamp()
        if not stamp:
            return

        text = self.stampNameEdit.text()
        if text == stamp.Name:
            return
        stamp.Name = text
        stamp.update()

        # Try to get it to update!!! But fail. D:
        for i in range(3):
            self.stampChooser.updateGeometries()
            self.stampChooser.update(self.stampChooser.currentIndex())
            self.stampChooser.update()
            self.stampChooser.repaint()

    def handleAutoTiling(self):
        try:
            self._clearStampSelection()
        except Exception:
            pass
        if hasattr(self, '_randomFillPending'):
            self._randomFillPending = None
        sel = [x for x in self.scene.selectedItems() if isinstance(x, ObjectItem)]
        if not sel:
            if hasattr(self, '_autoTilingPending'):
                self._autoTilingPending = None
            return

        layer_set = set()
        occ = set()
        items = []
        for obj in sel:
            try:
                cid = self._CollabEnsureItemId(obj)
            except Exception:
                cid = str(getattr(obj, '_collab_id', '') or '')
            items.append({'cid': cid, 'def': obj.instanceDef(obj), 'z': float(obj.zValue())})
            try:
                layer_set.add(int(getattr(obj, 'layer', 0)))
            except Exception:
                layer_set.add(0)
            try:
                ox = int(getattr(obj, 'objx', 0))
                oy = int(getattr(obj, 'objy', 0))
                ow = int(getattr(obj, 'width', 1))
                oh = int(getattr(obj, 'height', 1))
            except Exception:
                continue
            for yy in range(oy, oy + max(1, oh)):
                for xx in range(ox, ox + max(1, ow)):
                    occ.add((xx, yy))

        if len(layer_set) != 1:
            QtWidgets.QMessageBox.warning(self, 'Reggie', 'Auto-tiling: выбери блоки только на одном слое.')
            return

        self._autoTilingPending = {
            'layer': int(next(iter(layer_set))),
            'occ': occ,
            'items': items,
        }

        self.SelectionUpdateFlag = True
        try:
            self.scene.clearSelection()
        finally:
            self.SelectionUpdateFlag = False
        try:
            self.creationTabs.setCurrentIndex(6)
        except Exception:
            pass

    def handleRandomFillFromStamp(self):
        try:
            self._clearStampSelection()
        except Exception:
            pass
        if hasattr(self, '_autoTilingPending'):
            self._autoTilingPending = None
        sel = [x for x in self.scene.selectedItems() if isinstance(x, ObjectItem)]
        if not sel:
            if hasattr(self, '_randomFillPending'):
                self._randomFillPending = None
            return

        layer_set = set()
        occ = set()
        items = []
        for obj in sel:
            try:
                cid = self._CollabEnsureItemId(obj)
            except Exception:
                cid = str(getattr(obj, '_collab_id', '') or '')
            items.append({'cid': cid, 'def': obj.instanceDef(obj), 'z': float(obj.zValue())})
            try:
                layer_set.add(int(getattr(obj, 'layer', 0)))
            except Exception:
                layer_set.add(0)
            try:
                ox = int(getattr(obj, 'objx', 0))
                oy = int(getattr(obj, 'objy', 0))
                ow = int(getattr(obj, 'width', 1))
                oh = int(getattr(obj, 'height', 1))
            except Exception:
                continue
            for yy in range(oy, oy + max(1, oh)):
                for xx in range(ox, ox + max(1, ow)):
                    occ.add((xx, yy))

        if len(layer_set) != 1:
            QtWidgets.QMessageBox.warning(self, 'Reggie', 'Random fill: выбери блоки только на одном слое.')
            return

        self._randomFillPending = {
            'layer': int(next(iter(layer_set))),
            'occ': occ,
            'items': items,
        }

        self.SelectionUpdateFlag = True
        try:
            self.scene.clearSelection()
        finally:
            self.SelectionUpdateFlag = False
        try:
            self.creationTabs.setCurrentIndex(6)
        except Exception:
            pass

    def _randomFillTryApplyFromStamp(self, stamp):
        pending = getattr(self, '_randomFillPending', None)
        if not pending or stamp is None:
            return
        clip = getattr(stamp, 'ReggieClip', None)
        if not isinstance(clip, str) or not clip.startswith('ReggieClip|') or not clip.endswith('|%'):
            return

        candidates = self._randomFillParseCandidatesFromStamp(clip)
        if candidates is None:
            return

        self._randomFillApply(pending, candidates)
        self._randomFillPending = None
        try:
            self._clearStampSelection()
        except Exception:
            pass

    def _randomFillParseCandidatesFromStamp(self, reggie_clip):
        raw = str(reggie_clip).strip()
        if not (raw.startswith('ReggieClip|') and raw.endswith('|%')):
            QtWidgets.QMessageBox.warning(self, 'Reggie', 'Random fill: некорректный stamp.')
            return None

        parts = raw[11:-2].split('|')
        candidates = []
        for item in parts:
            split = item.split(':')
            if not split or split[0] != '0':
                continue
            if len(split) != 8:
                continue
            try:
                tileset = int(split[1])
                obj_type = int(split[2])
                w = int(split[6])
                h = int(split[7])
            except Exception:
                continue
            if w < 1 or h < 1:
                continue
            candidates.append({'tileset': tileset, 'type': obj_type, 'w': w, 'h': h})

        if not candidates:
            QtWidgets.QMessageBox.warning(self, 'Reggie', 'Random fill: stamp должен содержать хотя бы один object.')
            return None

        return candidates

    def _randomFillBuildPlan(self, occ, candidates, max_attempts=40):
        occ_set = set(occ) if isinstance(occ, set) else set()
        if not occ_set:
            return []
        if not isinstance(candidates, list) or not candidates:
            return None

        cands_by_key = {}
        for c in candidates:
            if not isinstance(c, dict):
                continue
            try:
                tileset = int(c.get('tileset', 0))
                obj_type = int(c.get('type', 0))
                w = int(c.get('w', 1))
                h = int(c.get('h', 1))
            except Exception:
                continue
            if w < 1 or h < 1:
                continue
            key = (tileset, obj_type, w, h)
            if key not in cands_by_key:
                cands_by_key[key] = {'tileset': tileset, 'type': obj_type, 'w': w, 'h': h, 'weight': 0}
            cands_by_key[key]['weight'] += 1
        cands = list(cands_by_key.values())
        if not cands:
            return None

        max_nodes = max(250, int(max_attempts) * 220)
        explicit_single = any(c['w'] == 1 and c['h'] == 1 for c in cands)
        min_x = min(p[0] for p in occ_set)
        max_x = max(p[0] for p in occ_set)
        min_y = min(p[1] for p in occ_set)
        max_y = max(p[1] for p in occ_set)

        def fits_at(x, y, w, h, remaining):
            for dy in range(h):
                for dx in range(w):
                    if (x + dx, y + dy) not in remaining:
                        return False
            return True

        def build_anchor_rectangles(x, y, remaining):
            rects = []
            max_width = None
            height = 0
            while (x, y + height) in remaining:
                row_width = 0
                while (x + row_width, y + height) in remaining:
                    row_width += 1
                if row_width <= 0:
                    break
                max_width = row_width if max_width is None else min(max_width, row_width)
                if max_width <= 0:
                    break
                height += 1
                for width in range(1, max_width + 1):
                    rects.append((width, height))
            rects.sort(key=lambda wh: (wh[0] * wh[1], wh[1], wh[0]))
            return rects

        def build_exact_choices(x, y, remaining):
            choices = []
            shuffled = list(cands)
            random.shuffle(shuffled)
            for c in shuffled:
                width = int(c['w'])
                height = int(c['h'])
                if not fits_at(x, y, width, height, remaining):
                    continue
                base_area = int(width * height)
                choices.append({
                    'x': int(x),
                    'y': int(y),
                    'tileset': int(c['tileset']),
                    'type': int(c['type']),
                    'w': int(width),
                    'h': int(height),
                    'expanded': False,
                    'extra_area': 0,
                    'base_area': int(base_area),
                    'area': int(base_area),
                    'weight': int(c.get('weight', 1)),
                })

            choices.sort(
                key=lambda p: (
                    -((random.random() * 3.0) + (0.25 * p['weight']) - (0.08 * p['base_area'])),
                    random.random(),
                )
            )
            return choices

        def build_choices(x, y, remaining, allow_expansion):
            choices = build_exact_choices(x, y, remaining)
            if not allow_expansion:
                return choices[:48]

            solid_rects = build_anchor_rectangles(x, y, remaining)
            if not solid_rects:
                return choices[:48]

            seen = set((c['tileset'], c['type'], c['w'], c['h']) for c in choices)
            shuffled = list(cands)
            random.shuffle(shuffled)
            for c in shuffled:
                base_w = int(c['w'])
                base_h = int(c['h'])
                base_area = int(base_w * base_h)
                for width, height in solid_rects:
                    if width < base_w or height < base_h:
                        continue
                    if width == base_w and height == base_h:
                        continue
                    key = (int(c['tileset']), int(c['type']), int(width), int(height))
                    if key in seen:
                        continue
                    seen.add(key)
                    area = int(width * height)
                    choices.append({
                        'x': int(x),
                        'y': int(y),
                        'tileset': int(c['tileset']),
                        'type': int(c['type']),
                        'w': int(width),
                        'h': int(height),
                        'expanded': True,
                        'extra_area': int(area - base_area),
                        'base_area': int(base_area),
                        'area': int(area),
                        'weight': int(c.get('weight', 1)),
                    })

            # Exact sizes from the stamp are always preferred. Expansions are used
            # only as a fallback to absorb leftover gaps when an exact tiling fails.
            choices.sort(
                key=lambda p: (
                    p['expanded'],
                    p['expanded'] and p['extra_area'],
                    -((random.random() * 3.0) + (0.20 * p['weight']) - (0.05 * p['base_area']) - (0.03 * p['extra_area'])),
                    random.random(),
                )
            )
            return choices[:64]

        def search(remaining, nodes_left, failed_states, allow_expansion):
            if not remaining:
                return []
            if nodes_left <= 0:
                return None

            key = None
            if len(remaining) <= 96:
                key = tuple(sorted(remaining))
                if key in failed_states:
                    return None

            sx, sy = min(remaining, key=lambda p: (p[1], p[0]))
            choices = build_choices(sx, sy, remaining, allow_expansion)
            if not choices:
                if key is not None:
                    failed_states.add(key)
                return None

            for choice in choices:
                w = int(choice['w'])
                h = int(choice['h'])
                if not fits_at(sx, sy, w, h, remaining):
                    continue
                next_remaining = set(remaining)
                for dy in range(h):
                    for dx in range(w):
                        next_remaining.discard((sx + dx, sy + dy))
                tail = search(next_remaining, nodes_left - 1, failed_states, allow_expansion)
                if tail is not None:
                    cleaned = dict(choice)
                    cleaned.pop('expanded', None)
                    cleaned.pop('extra_area', None)
                    cleaned.pop('base_area', None)
                    cleaned.pop('area', None)
                    cleaned.pop('weight', None)
                    return [cleaned] + tail

            if key is not None:
                failed_states.add(key)
            return None

        def plan_score(plan):
            if not plan:
                return -999999.0

            counts = {}
            score = random.random() * 0.25
            single_count = 0
            single_inner_bonus = 0.0

            for piece in plan:
                key = (int(piece['tileset']), int(piece['type']), int(piece['w']), int(piece['h']))
                counts[key] = counts.get(key, 0) + 1

                area = int(piece['w']) * int(piece['h'])
                left_gap = int(piece['x']) - min_x
                right_gap = max_x - (int(piece['x']) + int(piece['w']) - 1)
                top_gap = int(piece['y']) - min_y
                bottom_gap = max_y - (int(piece['y']) + int(piece['h']) - 1)
                edge_distance = float(max(0, min(left_gap, right_gap, top_gap, bottom_gap)))

                if area == 1:
                    single_count += 1
                    single_inner_bonus += min(edge_distance, 4.0)
                    score += min(edge_distance, 4.0) * 1.2
                elif area <= 4:
                    score += min(edge_distance, 3.0) * 0.25

            used_ratio = float(len(counts)) / float(max(1, len(cands)))
            score += used_ratio * 14.0

            if counts:
                total = float(len(plan))
                score -= (float(max(counts.values())) / total) * 6.0
                for cnt in counts.values():
                    score += min(cnt, 4) * 0.6

            if explicit_single and single_count > 0:
                target_singles = max(2, len(occ_set) // 12)
                score += min(single_count, target_singles) * 1.2
                score += min(single_inner_bonus, 8.0) * 0.9

            return score

        def find_best_plan(allow_expansion, attempts, nodes_left):
            best_plan = None
            best_score = None
            success_count = 0

            for _ in range(max(1, int(attempts))):
                failed_states = set()
                plan = search(set(occ_set), int(nodes_left), failed_states, allow_expansion)
                if plan is None:
                    continue
                success_count += 1
                score = plan_score(plan)
                if best_plan is None or best_score is None or score > best_score:
                    best_plan = plan
                    best_score = score
                if success_count >= 8:
                    break

            return best_plan

        plan = find_best_plan(False, max_attempts, max_nodes)
        if plan is not None:
            return plan

        return find_best_plan(True, max(6, int(max_attempts) // 2), max_nodes * 2)

    def _randomFillApply(self, pending, candidates):
        occ = pending.get('occ') if isinstance(pending, dict) else None
        layer = pending.get('layer') if isinstance(pending, dict) else None
        items = pending.get('items') if isinstance(pending, dict) else None
        if not isinstance(occ, set) or layer is None or not isinstance(items, list):
            return

        plan = self._randomFillBuildPlan(occ, candidates)
        if plan is None:
            QtWidgets.QMessageBox.warning(self, 'Reggie', 'Random fill: не получилось заполнить область выбранными блоками из stamp. Попробуй добавить в stamp больше совместимых размеров или более универсальные блоки.')
            return

        created = []
        try:
            self.SelectionUpdateFlag = True
            self.scene.clearSelection()
        finally:
            self.SelectionUpdateFlag = False

        try:
            for it in items:
                cid = str(it.get('cid') or '')
                inst = None
                if cid:
                    try:
                        from undo import _find_instance_by_collab_id
                        inst = _find_instance_by_collab_id(cid)
                    except Exception:
                        inst = None
                if inst is None:
                    try:
                        inst = it.get('def').findInstance()
                    except Exception:
                        inst = None
                if inst is None:
                    continue
                try:
                    inst.delete()
                except Exception:
                    pass
                try:
                    self.scene.removeItem(inst)
                except Exception:
                    pass
        except Exception:
            pass

        for p in plan:
            try:
                obj = self.CreateObject(int(p['tileset']), int(p['type']), int(layer), int(p['x']), int(p['y']), int(p['w']), int(p['h']), add_to_scene=True, record_undo=False)
            except Exception:
                obj = None
            if obj is not None:
                try:
                    self._CollabEnsureItemId(obj)
                except Exception:
                    pass
                created.append(obj)

        SetDirty()
        try:
            self.levelOverview.update()
        except Exception:
            pass
        try:
            self.CollabQueueMetaUpdate()
        except Exception:
            pass

        if not created:
            return

        if self.UndoRedoInProgress or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False) or globals_.DirtyOverride:
            return
        try:
            from undo import CreateOrDeleteInstanceUndoAction, SimultaneousUndoAction
            acts = []
            for it in items:
                cid = str(it.get('cid') or '')
                inst_def = it.get('def')
                z = it.get('z')
                extra = {'z': z} if z is not None else {}
                acts.append(CreateOrDeleteInstanceUndoAction('delete', inst_def, collab_id=cid, extra=extra))
            for obj in created:
                acts.append(CreateOrDeleteInstanceUndoAction('create', obj.instanceDef(obj), collab_id=getattr(obj, '_collab_id', None), extra={'z': obj.zValue()}))
            if acts:
                self.undoStack.addAction(SimultaneousUndoAction(acts) if len(acts) > 1 else acts[0])
        except Exception:
            pass

    def _clearStampSelection(self):
        try:
            self.stampChooser.clearSelection()
        except Exception:
            pass
        try:
            self.stampChooser.setCurrentIndex(QtCore.QModelIndex())
        except Exception:
            pass

    def _autoTilingTryApplyFromStamp(self, stamp):
        pending = getattr(self, '_autoTilingPending', None)
        if not pending or stamp is None:
            return
        clip = getattr(stamp, 'ReggieClip', None)
        if not isinstance(clip, str) or not clip.startswith('ReggieClip|') or not clip.endswith('|%'):
            return

        rule = self._autoTilingParseRuleStamp(clip)
        if rule is None:
            return

        self._autoTilingApply(pending, rule)
        self._autoTilingPending = None
        try:
            self._clearStampSelection()
        except Exception:
            pass

    def _autoTilingParseRuleStamp(self, reggie_clip):
        raw = str(reggie_clip).strip()
        if not (raw.startswith('ReggieClip|') and raw.endswith('|%')):
            QtWidgets.QMessageBox.warning(self, 'Reggie', 'Auto-tiling: некорректный stamp.')
            return None

        parts = raw[11:-2].split('|')
        objs = []
        for item in parts:
            split = item.split(':')
            if not split or split[0] != '0':
                continue
            if len(split) != 8:
                continue
            try:
                tileset = int(split[1])
                obj_type = int(split[2])
                layer = int(split[3])
                x = int(split[4])
                y = int(split[5])
                w = int(split[6])
                h = int(split[7])
            except Exception:
                continue
            if w != 1 or h != 1:
                QtWidgets.QMessageBox.warning(self, 'Reggie', 'Auto-tiling: stamp должен состоять из блоков 1x1.')
                return None
            objs.append({'tileset': tileset, 'type': obj_type, 'layer': layer, 'x': x, 'y': y})

        if len(objs) != 9:
            QtWidgets.QMessageBox.warning(self, 'Reggie', 'Auto-tiling: stamp должен содержать ровно 9 блоков (3x3).')
            return None

        minx = min(o['x'] for o in objs)
        miny = min(o['y'] for o in objs)
        maxx = max(o['x'] for o in objs)
        maxy = max(o['y'] for o in objs)
        if (maxx - minx) != 2 or (maxy - miny) != 2:
            QtWidgets.QMessageBox.warning(self, 'Reggie', 'Auto-tiling: размер stamp должен быть 3x3.')
            return None

        mapping = {}
        for o in objs:
            dx = o['x'] - minx
            dy = o['y'] - miny
            key = (dx, dy)
            if key in mapping:
                QtWidgets.QMessageBox.warning(self, 'Reggie', 'Auto-tiling: в stamp есть дубликаты позиций.')
                return None
            mapping[key] = o

        if len(mapping) != 9:
            QtWidgets.QMessageBox.warning(self, 'Reggie', 'Auto-tiling: stamp должен покрывать все 9 клеток 3x3.')
            return None

        return mapping

    def _autoTilingApply(self, pending, rule):
        occ = pending.get('occ') if isinstance(pending, dict) else None
        layer = pending.get('layer') if isinstance(pending, dict) else None
        items = pending.get('items') if isinstance(pending, dict) else None
        if not isinstance(occ, set) or layer is None or not isinstance(items, list):
            return

        def get_key_for_cell(x, y):
            n = (x, y - 1) in occ
            s = (x, y + 1) in occ
            w = (x - 1, y) in occ
            e = (x + 1, y) in occ

            if (not n) and (not w):
                return (0, 0)
            if (not n) and (not e):
                return (2, 0)
            if (not s) and (not w):
                return (0, 2)
            if (not s) and (not e):
                return (2, 2)
            if not n:
                return (1, 0)
            if not s:
                return (1, 2)
            if not w:
                return (0, 1)
            if not e:
                return (2, 1)
            return (1, 1)

        desired = {}
        for (x, y) in occ:
            tile = rule.get(get_key_for_cell(x, y))
            if tile is None:
                continue
            desired[(x, y)] = (int(tile['tileset']), int(tile['type']))

        created = []
        try:
            self.SelectionUpdateFlag = True
            self.scene.clearSelection()
        finally:
            self.SelectionUpdateFlag = False

        try:
            for it in items:
                cid = str(it.get('cid') or '')
                inst = None
                if cid:
                    try:
                        from undo import _find_instance_by_collab_id
                        inst = _find_instance_by_collab_id(cid)
                    except Exception:
                        inst = None
                if inst is None:
                    try:
                        inst = it.get('def').findInstance()
                    except Exception:
                        inst = None
                if inst is None:
                    continue
                try:
                    inst.delete()
                except Exception:
                    pass
                try:
                    self.scene.removeItem(inst)
                except Exception:
                    pass
        except Exception:
            pass

        processed = set()
        cells = sorted(desired.keys(), key=lambda p: (p[1], p[0]))
        for (sx, sy) in cells:
            if (sx, sy) in processed:
                continue
            tile_id = desired.get((sx, sy))
            if tile_id is None:
                processed.add((sx, sy))
                continue

            w = 1
            while True:
                nx = sx + w
                if (nx, sy) in processed:
                    break
                if desired.get((nx, sy)) != tile_id:
                    break
                w += 1

            h = 1
            while True:
                ny = sy + h
                ok = True
                for dx in range(w):
                    if (sx + dx, ny) in processed:
                        ok = False
                        break
                    if desired.get((sx + dx, ny)) != tile_id:
                        ok = False
                        break
                if not ok:
                    break
                h += 1

            for dy in range(h):
                for dx in range(w):
                    processed.add((sx + dx, sy + dy))

            tileset, obj_type = tile_id
            try:
                obj = self.CreateObject(int(tileset), int(obj_type), int(layer), int(sx), int(sy), int(w), int(h), add_to_scene=True, record_undo=False)
            except Exception:
                obj = None
            if obj is not None:
                try:
                    self._CollabEnsureItemId(obj)
                except Exception:
                    pass
                created.append(obj)

        SetDirty()
        try:
            self.levelOverview.update()
        except Exception:
            pass
        try:
            self.CollabQueueMetaUpdate()
        except Exception:
            pass

        if not created:
            return

        if self.UndoRedoInProgress or self.collabApplyingRemote or self.collabApplyingRemoteHistory or getattr(self, 'collabSwitchingArea', False) or globals_.DirtyOverride:
            return
        try:
            from undo import CreateOrDeleteInstanceUndoAction, SimultaneousUndoAction
            acts = []
            for it in items:
                cid = str(it.get('cid') or '')
                inst_def = it.get('def')
                z = it.get('z')
                extra = {'z': z} if z is not None else {}
                acts.append(CreateOrDeleteInstanceUndoAction('delete', inst_def, collab_id=cid, extra=extra))
            for obj in created:
                acts.append(CreateOrDeleteInstanceUndoAction('create', obj.instanceDef(obj), collab_id=getattr(obj, '_collab_id', None), extra={'z': obj.zValue()}))
            if acts:
                self.undoStack.addAction(SimultaneousUndoAction(acts) if len(acts) > 1 else acts[0])
        except Exception:
            pass

    def AboutBox(self):
        """
        Shows the about box
        """
        AboutDialog().exec()

    def HandleInfo(self):
        """
        Records the Level Meta Information
        """
        if globals_.Area.areanum == 1:
            dlg = MetaInfoDialog()
            if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                globals_.Area.Metadata.setStrData('Title', dlg.levelName.text())
                globals_.Area.Metadata.setStrData('Author', dlg.Author.text())
                globals_.Area.Metadata.setStrData('Group', dlg.Group.text())
                globals_.Area.Metadata.setStrData('Website', dlg.Website.text())

                SetDirty()
                return
        else:
            dlg = QtWidgets.QMessageBox()
            dlg.setText(globals_.trans.string('InfoDlg', 14))
            dlg.exec()

    def HelpBox(self):
        """
        Shows the help box
        """
        mod_path = module_path()

        file_path = os.path.join('reggiedata', 'help', 'index.html')
        if mod_path is None:
            file_path = os.path.join(os.getcwd(), file_path)
        else:
            file_path = os.path.join(mod_path, file_path)

        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(file_path))

    def TipBox(self):
        """
        Reggie Next Tips and Commands
        """
        mod_path = module_path()

        file_path = os.path.join('reggiedata', 'help', 'tips.html')
        if mod_path is None:
            file_path = os.path.join(os.getcwd(), file_path)
        else:
            file_path = os.path.join(mod_path, file_path)

        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(file_path))

    def SelectAll(self):
        """
        Select all objects in the current area
        """
        paintRect = QtGui.QPainterPath()
        paintRect.addRect(0, 0, 1024 * 24, 512 * 24)
        self.scene.setSelectionArea(paintRect)

    def Deselect(self):
        """
        Deselect all currently selected items
        """
        items = self.scene.selectedItems()
        for obj in items:
            obj.setSelected(False)

    def Undo(self):
        """
        Undoes something
        """
        if self._CollabHistoryEnabled() and not self._CollabHistoryBlocked():
            if self.IsCollabClientMode():
                self.collabManager.broadcast_message('hist_req_undo', {
                    'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
                    'level_name': self._CollabCurrentLevelName(),
                })
                return
            if hasattr(self, 'collabManager') and self.collabManager.mode == "host":
                self._CollabHostBroadcastUndo(origin=str(getattr(self.collabManager, 'session_id', '') or ''))
                return
        self.undoStack.undo()

    def Redo(self):
        """
        Redoes something previously undone
        """
        if self._CollabHistoryEnabled() and not self._CollabHistoryBlocked():
            if self.IsCollabClientMode():
                self.collabManager.broadcast_message('hist_req_redo', {
                    'area_num': int(getattr(globals_.Area, 'areanum', 0) or 0),
                    'level_name': self._CollabCurrentLevelName(),
                })
                return
            if hasattr(self, 'collabManager') and self.collabManager.mode == "host":
                self._CollabHostBroadcastRedo(origin=str(getattr(self.collabManager, 'session_id', '') or ''))
                return
        self.undoStack.redo()

    def Cut(self):
        """
        Cuts the selected items
        """
        self.SelectionUpdateFlag = True
        selitems = self.scene.selectedItems()
        self.scene.clearSelection()

        if selitems:
            clipboard_o = []
            clipboard_s = []
            ii = isinstance
            type_obj = ObjectItem
            type_spr = SpriteItem

            try:
                from undo import CreateOrDeleteInstanceUndoAction, SimultaneousUndoAction
                acts = []
                for obj in selitems:
                    if ii(obj, type_obj):
                        try:
                            self._CollabEnsureItemId(obj)
                        except Exception:
                            pass
                        acts.append(CreateOrDeleteInstanceUndoAction('delete', obj.instanceDef(obj), collab_id=getattr(obj, '_collab_id', None), extra={'z': obj.zValue()}))
                    elif ii(obj, type_spr):
                        try:
                            self._CollabEnsureItemId(obj)
                        except Exception:
                            pass
                        acts.append(CreateOrDeleteInstanceUndoAction('delete', obj.instanceDef(obj), collab_id=getattr(obj, '_collab_id', None)))
                if acts and not self.UndoRedoInProgress and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not globals_.DirtyOverride:
                    if len(acts) == 1:
                        self.undoStack.addAction(acts[0])
                    else:
                        self.undoStack.addAction(SimultaneousUndoAction(acts))
            except Exception:
                pass

            for obj in selitems:
                if ii(obj, type_obj):
                    obj.delete()
                    obj.setSelected(False)
                    self.scene.removeItem(obj)
                    clipboard_o.append(obj)
                elif ii(obj, type_spr):
                    obj.delete()
                    obj.setSelected(False)
                    self.scene.removeItem(obj)
                    clipboard_s.append(obj)

            if clipboard_o or clipboard_s:
                SetDirty()
                self.actions['cut'].setEnabled(False)
                self.actions['paste'].setEnabled(True)
                self.clipboard = self.encodeObjects(clipboard_o, clipboard_s)
                self.systemClipboard.setText(self.clipboard)

        self.levelOverview.update()
        self.SelectionUpdateFlag = False
        self.ChangeSelectionHandler()

    def Copy(self):
        """
        Copies the selected items
        """
        selitems = self.scene.selectedItems()
        if selitems:
            clipboard_o = []
            clipboard_s = []
            ii = isinstance
            type_obj = ObjectItem
            type_spr = SpriteItem

            for obj in selitems:
                if ii(obj, type_obj):
                    clipboard_o.append(obj)
                elif ii(obj, type_spr):
                    clipboard_s.append(obj)

            if clipboard_o or clipboard_s:
                self.actions['paste'].setEnabled(True)
                self.clipboard = self.encodeObjects(clipboard_o, clipboard_s)
                self.systemClipboard.setText(self.clipboard)

    def Paste(self):
        """
        Paste the selected items
        """
        if self.clipboard is not None:
            self.placeEncodedObjects(self.clipboard)

    def encodeObjects(self, clipboard_o, clipboard_s):
        """
        Encode a set of objects and sprites into a string
        """
        convclip = ['ReggieClip']

        # get objects
        clipboard_o.sort(key=lambda x: x.zValue())

        for item in clipboard_o:
            convclip.append('0:%d:%d:%d:%d:%d:%d:%d' % (
            item.tileset, item.type, item.layer, item.objx, item.objy, item.width, item.height))

        # get sprites
        for item in clipboard_s:
            data = item.spritedata
            convclip.append('1:%d:%d:%d:%d:%d:%d:%d:%d:%d:%d' % (
            item.type, item.objx, item.objy, data[0], data[1], data[2], data[3], data[4], data[5], data[7]))

        convclip.append('%')
        return '|'.join(convclip)

    def placeEncodedObjects(self, encoded, select=True, xOverride=None, yOverride=None, record_undo=True):
        """
        Decode and place a set of objects
        """
        self.SelectionUpdateFlag = True
        self.scene.clearSelection()
        added = []

        # Remove leading and trailing whitespace
        encoded = encoded.strip()

        if not (encoded.startswith('ReggieClip|') and encoded.endswith('|%')):
            self.SelectionUpdateFlag = False
            return added

        clip = encoded.split('|')

        if len(clip) > 300 + 2:
            result = QtWidgets.QMessageBox.warning(self, 'Reggie', globals_.trans.string('MainWindow', 1),
                                                   QtWidgets.QMessageBox.StandardButton.Yes, QtWidgets.QMessageBox.StandardButton.No)
            if result == QtWidgets.QMessageBox.StandardButton.No:
                self.SelectionUpdateFlag = False
                return added

        globals_.OverrideSnapping = True

        layers, sprites = self.getEncodedObjects(encoded)

        # Find the bounding box of all created objects
        bounding = QtCore.QRectF()

        for spr in sprites:
            bounding |= spr.LevelRect

        for layer in layers:
            for obj in layer:
                bounding |= obj.LevelRect

        x1, y1, width, height = bounding.getRect()

        # now center everything
        zoomscaler = self.ZoomLevel / 100
        viewportx = (self.view.XScrollBar.value() / zoomscaler) / 24
        viewporty = (self.view.YScrollBar.value() / zoomscaler) / 24
        viewportwidth = (self.view.width() / zoomscaler) / 24
        viewportheight = (self.view.height() / zoomscaler) / 24

        # tiles
        if xOverride is None:
            xoffset = int(0 - x1 + viewportx + ((viewportwidth / 2) - (width / 2)))
            xpixeloffset = xoffset * 16
        else:
            xoffset = int(0 - x1 + (xOverride / 16) - (width / 2))
            xpixeloffset = xoffset * 16
        if yOverride is None:
            yoffset = int(0 - y1 + viewporty + ((viewportheight / 2) - (height / 2)))
            ypixeloffset = yoffset * 16
        else:
            yoffset = int(0 - y1 + (yOverride / 16) - (height / 2))
            ypixeloffset = yoffset * 16

        # Center and select everything
        for item in sprites:
            item.setNewObjPos(item.objx + xpixeloffset, item.objy + ypixeloffset)
            item.UpdateRects()
            if select: item.setSelected(True)

        for layer in layers:
            for item in layer:
                item.setPos((item.objx + xoffset) * 24, (item.objy + yoffset) * 24)
                item.UpdateRects()
                if select: item.setSelected(True)

        globals_.OverrideSnapping = False

        self.levelOverview.update()
        SetDirty()
        self.SelectionUpdateFlag = False
        self.ChangeSelectionHandler()

        # Combine the sprites and layers
        added = sprites
        for layer in layers:
            added += layer

        if record_undo:
            try:
                from undo import CreateOrDeleteInstanceUndoAction, SimultaneousUndoAction
                acts = []
                for item in added:
                    if isinstance(item, ObjectItem):
                        try:
                            self._CollabEnsureItemId(item)
                        except Exception:
                            pass
                        acts.append(CreateOrDeleteInstanceUndoAction('create', item.instanceDef(item), collab_id=getattr(item, '_collab_id', None), extra={'z': item.zValue()}))
                    elif isinstance(item, SpriteItem):
                        try:
                            self._CollabEnsureItemId(item)
                        except Exception:
                            pass
                        acts.append(CreateOrDeleteInstanceUndoAction('create', item.instanceDef(item), collab_id=getattr(item, '_collab_id', None)))
                if acts and not self.UndoRedoInProgress and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not globals_.DirtyOverride:
                    if len(acts) == 1:
                        self.undoStack.addAction(acts[0])
                    else:
                        self.undoStack.addAction(SimultaneousUndoAction(acts))
            except Exception:
                pass

        return added

    def getEncodedObjects(self, encoded, add_to_scene=True):
        """
        Create the objects from a ReggieClip
        """

        layers = ([], [], [])
        sprites = []

        if not (encoded.startswith('ReggieClip|') and encoded.endswith('|%')):
            return layers, sprites

        clip = encoded[11:-2].split('|')

        if add_to_scene:
            self.spriteList.prepareBatchAdd()
        for item in clip:

            try:
                # Check to see whether it's an object or sprite
                # and add it to the correct stack
                split = item.split(':')
                if split[0] == '0':
                    # object
                    if len(split) != 8: continue

                    tileset = int(split[1])
                    type = int(split[2])
                    layer = int(split[3])
                    objx = int(split[4])
                    objy = int(split[5])
                    width = int(split[6])
                    height = int(split[7])

                    # basic sanity checks
                    if tileset < 0 or tileset > 3: continue
                    if type < 0 or type > 255: continue
                    if layer < 0 or layer > 2: continue
                    if objx < 0 or objx > 1023: continue
                    if objy < 0 or objy > 511: continue
                    if width < 1 or width > 1023: continue
                    if height < 1 or height > 511: continue

                    newitem = self.CreateObject(tileset, type, layer, objx, objy, width, height, add_to_scene=add_to_scene, record_undo=False)

                    layers[layer].append(newitem)

                elif split[0] == '1':
                    # sprite
                    if len(split) != 11: continue

                    objx = int(split[2])
                    objy = int(split[3])
                    type = int(split[1])
                    data = bytes(map(int, [split[4], split[5], split[6], split[7], split[8], split[9], '0', split[10]]))

                    # Check if sprite data exists for this type
                    if not (0 <= type < globals_.NumSprites) or globals_.Sprites[type] is None:
                        # Unknown sprite, skip it
                        continue

                    newitem = self.CreateSprite(objx, objy, type, data, add_to_scene=add_to_scene, record_undo=False)
                    sprites.append(newitem)

            except ValueError:
                # an int() probably failed somewhere
                pass

        if add_to_scene:
            self.spriteList.endBatchAdd()

        return layers, sprites

    def ShiftItems(self):
        """
        Shifts the selected object(s)
        """
        items = self.scene.selectedItems()
        if not items: return

        dlg = ObjectShiftDialog()
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        xoffset = dlg.XOffset.value()
        yoffset = dlg.YOffset.value()
        if xoffset == 0 and yoffset == 0: return

        if ((xoffset % 16) != 0) or ((yoffset % 16) != 0):
            # warn if any objects exist
            objectsExist = False
            type_obj = ObjectItem

            for obj in items:
                if isinstance(obj, type_obj):
                    objectsExist = True
                    break

            if objectsExist:
                # Objects are selected and the offset is not a multiple of 16.
                # We should warn the user that we will round the offset to the
                # nearest multiple of 16, because objects can only be placed on
                # the grid.
                result = QtWidgets.QMessageBox.information(None, globals_.trans.string('ShftItmDlg', 5),
                                                            globals_.trans.string('ShftItmDlg', 6), QtWidgets.QMessageBox.StandardButton.Yes,
                                                            QtWidgets.QMessageBox.StandardButton.No)

                if result == QtWidgets.QMessageBox.StandardButton.No:
                    return

                # Round the offset to the nearest multiple of 16
                xoffset = 16 * round(xoffset / 16)
                yoffset = 16 * round(yoffset / 16)

        xpoffset = xoffset * 1.5
        ypoffset = yoffset * 1.5

        globals_.OverrideSnapping = True

        for obj in items:
            obj.setPos(obj.x() + xpoffset, obj.y() + ypoffset)

        globals_.OverrideSnapping = False

        SetDirty()

    def SwapObjectsTilesets(self):
        """
        Swaps objects' tilesets
        """
        dlg = ObjectTilesetSwapDialog()
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        from_tileset = dlg.FromTS.value() - 1
        to_tileset = dlg.ToTS.value() - 1
        do_exchange = dlg.DoExchange.isChecked()

        if from_tileset == to_tileset:
            return

        for layer in globals_.Area.layers:
            for nsmbobj in layer:
                if nsmbobj.tileset == from_tileset:
                    nsmbobj.SetType(to_tileset, nsmbobj.type)
                    SetDirty()
                elif do_exchange and nsmbobj.tileset == to_tileset:
                    nsmbobj.SetType(from_tileset, nsmbobj.type)
                    SetDirty()

    def SwapObjectsTypes(self):
        """
        Swaps objects' types
        """
        ObjectTypeSwapDialog().exec()

    def MergeLocations(self):
        """
        Merges selected sprite locations
        """
        items = self.scene.selectedItems()
        if not items: return

        new_rect = QtCore.QRectF()

        type_loc = LocationItem
        for obj in items:
            if not isinstance(obj, type_loc):
                continue

            new_rect |= obj.ZoneRect

            obj.delete()
            obj.setSelected(False)
            self.scene.removeItem(obj)
            self.levelOverview.update()
            SetDirty()

        if not new_rect.isValid():
            return

        loc = self.CreateLocation(*new_rect.getRect())
        loc.setSelected(True)

    ###########################################################################
    # Functions that create items
    ###########################################################################
    # Maybe move these as static methods to their respective classes
    def CreateLocation(self, x, y, width = 16, height = 16, id_ = None, add_to_scene = True, record_undo = True):
        """
        Creates and returns a new location and makes sure it's added to the
        right lists, unless 'add_to_scene' is set to False. If 'id' is None, the
        smallest available id is used.
        This function returns None if there is no free location id available, and
        the created location otherwise.
        """
        if id_ is None:
            # This can be done more efficiently, but 255 is not that big, so it
            # does not really matter.
            all_ids = set(loc.id for loc in globals_.Area.locations)
            id_ = common.find_first_available_id(all_ids, 256, 1)

            if id_ is None:
                print("ReggieWindow#CreateLocation: No free location id")
                return None

        globals_.OverrideSnapping = True
        loc = LocationItem(x, y, width, height, id_)
        globals_.OverrideSnapping = False

        loc.positionChanged = self.HandleLocPosChange
        loc.sizeChanged = self.HandleLocSizeChange
        loc.listitem = ListWidgetItem_SortsByOther(loc)

        if add_to_scene:
            self.locationList.addItem(loc.listitem)
            self.scene.addItem(loc)
            globals_.Area.locations.append(loc)
            if not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False):
                self._CollabEnsureItemId(loc)
                self._CollabMarkItemHot(loc)

            loc.UpdateListItem()

            # We've changed the level, so set the dirty flag
            SetDirty()
            self.CollabQueueLocationUpsert(loc, is_add=True)
            if record_undo and not self.UndoRedoInProgress and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False) and not globals_.DirtyOverride:
                from undo import CreateOrDeleteInstanceUndoAction
                self.undoStack.addAction(CreateOrDeleteInstanceUndoAction('create', loc.instanceDef(loc), collab_id=self._CollabEnsureItemId(loc)))

        return loc

    def CreateObject(self, tileset, object_num, layer, x, y, width = None, height = None, add_to_scene = True, record_undo = True):
        """
        Creates and returns a new object and makes sure it's added to
        the right lists.
        """
        if width is None or height is None:
            if globals_.PlaceObjectsAtFullSize:
                try:
                    tile_def = globals_.ObjectDefinitions[tileset][object_num]
                    width = tile_def.width
                    height = tile_def.height
                except TypeError:  # Something was None
                    width = height = 1
            else:
                width = height = 1

        layer_list = globals_.Area.layers[layer]
        if not layer_list:
            z = (2 - layer) * 8192
        else:
            z = layer_list[-1].zValue() + 1

        obj = ObjectItem(tileset, object_num, layer, x, y, width, height, z)

        if add_to_scene:
            layer_list.append(obj)
            obj.positionChanged = self.HandleObjPosChange
            self.scene.addItem(obj)

            SetDirty()
            if self._CollabEnabled() and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False):
                obj_id = self._CollabEnsureItemId(obj)
                obj._collab_local_edit_ts = time.monotonic()
                self._collabObjectById[obj_id] = obj
                self._QueueCollabOp({
                    'op': 'obj_add',
                    'id': obj_id,
                    'layer': int(layer),
                    'tileset': int(tileset),
                    'type': int(object_num),
                    'x': int(obj.objx),
                    'y': int(obj.objy),
                    'w': int(obj.width),
                    'h': int(obj.height),
                })
            if record_undo and not self.UndoRedoInProgress and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False) and not globals_.DirtyOverride:
                from undo import CreateOrDeleteInstanceUndoAction
                try:
                    self._CollabEnsureItemId(obj)
                except Exception:
                    pass
                self.undoStack.addAction(CreateOrDeleteInstanceUndoAction('create', obj.instanceDef(obj), collab_id=getattr(obj, '_collab_id', None), extra={'z': obj.zValue()}))

        return obj

    def CreateEntrance(self, x, y, id_ = None, add_to_scene = True, record_undo = True):
        """
        Creates and returns a new entrance and makes sure it's added to the
        right lists. This function returns None if this entrance could not be
        created.
        """
        all_ids = set(ent.entid for ent in globals_.Area.entrances)
        if id_ is None:
            id_ = common.find_first_available_id(all_ids, 256)

        if id_ is None:
            print("ReggieWindow#CreateEntrance: No free entrance id")
            return None
        elif id_ in all_ids and add_to_scene:
            print("ReggieWindow#CreateEntrance: Given entrance id (%d) already in use" % id_)
            return None

        ent = EntranceItem(x, y, id_, 0, 0, 0, 0, 0, 0, 0x80, 0, 0)
        ent.positionChanged = self.HandleEntPosChange
        ent.listitem = ListWidgetItem_SortsByOther(ent)

        if add_to_scene:
            # If it's the first available ID, all the other indices should match, so
            # we can just use the ID to insert.
            self.entranceList.insertItem(id_, ent.listitem)
            globals_.Area.entrances.insert(id_, ent)
            if not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False):
                self._CollabEnsureItemId(ent)
                self._CollabMarkItemHot(ent)

            self.scene.addItem(ent)
            ent.UpdateListItem()

            SetDirty()
            self.CollabQueueEntranceUpsert(ent, is_add=True)
            if record_undo and not self.UndoRedoInProgress and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False) and not globals_.DirtyOverride:
                from undo import CreateOrDeleteInstanceUndoAction
                self.undoStack.addAction(CreateOrDeleteInstanceUndoAction('create', ent.instanceDef(ent), collab_id=self._CollabEnsureItemId(ent)))

            try:
                self.UpdatePipeEntranceLinks()
            except Exception:
                pass

        return ent

    def CreateSprite(self, x, y, id_ = None, data = None, add_to_scene = True, record_undo = True):
        """
        Creates and returns a new sprite and makes sure it's added to the right
        lists if 'add_to_scene' is set.
        If 'id_' is not set, the currently selected sprite id is used.
        If 'data' is not set, the current data of the default data editor is used.
        If 'data' is not set and the default data editor is configured for another
        sprite id than the id of the sprite that is created, a ValueError will
        be raised.
        """

        if id_ is None:
            id_ = globals_.CurrentSprite

        if data is None:
            if self.defaultDataEditor.spritetype != id_:
                raise ValueError("The default data editor was configured for sprite id %d while trying to use data for sprite id %d" % (self.defaultDataEditor.spritetype, id_))

            data = self.defaultDataEditor.data

        spr = SpriteItem(id_, x, y, data)
        spr.positionChanged = self.HandleSprPosChange

        if add_to_scene:
            # Check if sprite data exists for this type
            if not (0 <= id_ < globals_.NumSprites) or globals_.Sprites[id_] is None:
                # Unknown sprite, don't create
                return

            self.spriteList.addSprite(spr)
            globals_.Area.sprites.append(spr)

            # Add the ids for the idtype count
            decoder = SpriteEditorWidget.PropertyDecoder()
            sdef = globals_.Sprites[id_]

            # Find what values are used by this sprite
            for field in sdef.fields:
                if field[0] not in (1, 2):
                    # Only values and lists can be idtypes
                    continue

                idtype = field[-1]
                if idtype is None:
                    # Only look at settings with idtypes
                    continue

                value = decoder.retrieve(data, field[2])

                # 3. Add the value to self.sprite_idtypes
                try:
                    counter = globals_.Area.sprite_idtypes[idtype]
                except KeyError:
                    globals_.Area.sprite_idtypes[idtype] = {value: 1}
                    continue

                counter[value] = counter.get(value, 0) + 1

            self.scene.addItem(spr)
            spr.UpdateListItem()

            SetDirty()
            if self._CollabEnabled() and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False):
                spr_collab_id = self._CollabEnsureItemId(spr)
                self._CollabMarkItemHot(spr)
                self._collabSpriteById[spr_collab_id] = spr
                self._QueueCollabOp({
                    'op': 'spr_add',
                    'id': spr_collab_id,
                    'type': int(spr.type),
                    'x': int(spr.objx),
                    'y': int(spr.objy),
                    'data': base64.b64encode(spr.spritedata).decode('ascii'),
                })
            if record_undo and not self.UndoRedoInProgress and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False) and not globals_.DirtyOverride:
                from undo import CreateOrDeleteInstanceUndoAction
                try:
                    self._CollabEnsureItemId(spr)
                except Exception:
                    pass
                self.undoStack.addAction(CreateOrDeleteInstanceUndoAction('create', spr.instanceDef(spr), collab_id=getattr(spr, '_collab_id', None)))
            try:
                if int(getattr(spr, 'type', -1)) in (149, 252, 253, 254, 255, 256):
                    self.UpdateRotationControllerPreviews()
            except Exception:
                pass
            try:
                if getattr(globals_, 'EventLinksShown', False):
                    self.UpdateEventLinks()
            except Exception:
                pass

        return spr

    def CreateZone(self, x, y, width = 408, height = 224, id_ = None, add_to_scene = True, record_undo = True):
        """
        Creates and returns a new zone and makes sure it's added to the right
        lists if 'add_to_scene' is set.
        If 'id_' is not set, the current number of zones in this Area is used as
        an id.
        """
        if id_ is None:
            id_ = len(globals_.Area.zones) + 1

        default_bounding = [[0, 0, 0, 0, 0, 15, 0, 0]]
        default_bga = [[0, 2, 2, 0, 0, 10, 10, 10, 1]]
        default_bgb = [[0, 1, 1, 0, 0, 10, 10, 10, 2]]

        zone = ZoneItem(x, y, width, height, 0, 0, id_ - 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, default_bounding, default_bga, default_bgb)

        if add_to_scene:
            globals_.Area.zones.append(zone)
            self.scene.addItem(zone)

            self.scene.update()
            self.levelOverview.update()

            SetDirty()
            if record_undo and not self.UndoRedoInProgress and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False) and not globals_.DirtyOverride:
                from undo import ZoneUndoAction
                meta = self.BuildCollabMetaState()
                zone_data = None
                for zd in meta.get('zones', []) if isinstance(meta, dict) else []:
                    if isinstance(zd, dict) and int(zd.get('id', -999)) == int(getattr(zone, 'id', -999)):
                        zone_data = zd
                        break
                if zone_data is None:
                    zone_data = {
                        'objx': int(getattr(zone, 'objx', 0)),
                        'objy': int(getattr(zone, 'objy', 0)),
                        'width': int(getattr(zone, 'width', 0)),
                        'height': int(getattr(zone, 'height', 0)),
                        'modeldark': int(getattr(zone, 'modeldark', 0)),
                        'terraindark': int(getattr(zone, 'terraindark', 0)),
                        'id': int(getattr(zone, 'id', 0)),
                        'cammode': int(getattr(zone, 'cammode', 0)),
                        'camzoom': int(getattr(zone, 'camzoom', 0)),
                        'visibility': int(getattr(zone, 'visibility', 0)),
                        'camtrack': int(getattr(zone, 'camtrack', 0)),
                        'music': int(getattr(zone, 'music', 0)),
                        'sfxmod': int(getattr(zone, 'sfxmod', 0)),
                    }
                self.undoStack.addAction(ZoneUndoAction('create', zone_data))

        return zone

    def HandleAddNewArea(self):
        """
        Adds a new area to the level
        """
        if len(globals_.Level.areas) >= 4:
            QtWidgets.QMessageBox.warning(self, 'Reggie', globals_.trans.string('AreaChoiceDlg', 2))
            return

        if self.CheckDirty():
            # Level is still dirty
            return

        newID = len(globals_.Level.areas) + 1
        globals_.Level.appendArea(None, None, None, None)

        if not self.HandleSave():
            globals_.Level.deleteArea(newID)
            return

        self.LoadLevel(self.fileSavePath, True, newID)

    def HandleImportArea(self):
        """
        Imports an area from another level
        """
        if len(globals_.Level.areas) >= 4:
            QtWidgets.QMessageBox.warning(self, 'Reggie', globals_.trans.string('AreaChoiceDlg', 2))
            return

        if self.CheckDirty():
            return

        filetypes = ''
        filetypes += globals_.trans.string('FileDlgs', 1) + ' (*' + '.arc' + ');;'  # *.arc
        filetypes += globals_.trans.string('FileDlgs', 5) + ' (*' + '.arc' + '.LH);;'  # *.arc.LH
        filetypes += globals_.trans.string('FileDlgs', 10) + ' (*' + '.arc' + '.LZ);;'  # *.arc.LZ
        filetypes += globals_.trans.string('FileDlgs', 2) + ' (*)'  # *
        fn = QtWidgets.QFileDialog.getOpenFileName(self, globals_.trans.string('FileDlgs', 0), '', filetypes)[0]
        if fn == '': return

        with open(str(fn), 'rb') as fileobj:
            arcdata = fileobj.read()

        if (arcdata[0] & 0xF0) == 0x40:  # If LH-compressed
            try:
                arcdata = lh.UncompressLH(arcdata)
            except IndexError:
                QtWidgets.QMessageBox.warning(None, globals_.trans.string('Err_Decompress', 0),
                                              globals_.trans.string('Err_Decompress', 1, '[file]', str(fn)))
                return

        arc = archive.U8.load(arcdata)

        # get the area count
        areacount = 0

        for item, val in arc.files:
            if val is not None:
                # it's a file
                fname = item[item.rfind('/') + 1:]
                if fname.startswith('course'):
                    maxarea = int(fname[6])
                    if maxarea > areacount: areacount = maxarea

        # choose one
        dlg = AreaChoiceDialog(areacount)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Rejected:
            return

        area = dlg.areaCombo.currentIndex() + 1

        # get the required files
        reqcourse = 'course%d.bin' % area
        reqL0 = 'course%d_bgdatL0.bin' % area
        reqL1 = 'course%d_bgdatL1.bin' % area
        reqL2 = 'course%d_bgdatL2.bin' % area

        course = None
        L0 = None
        L1 = None
        L2 = None

        for item, val in arc.files:
            if val is not None:
                fname = item.split('/')[-1]
                if fname == reqcourse:
                    course = val
                elif fname == reqL0:
                    L0 = val
                elif fname == reqL1:
                    L1 = val
                elif fname == reqL2:
                    L2 = val

        # add them to our level
        globals_.Level.appendArea(course, L0, L1, L2)
        new_id = globals_.Level.areas[-1].areanum

        if not self.HandleSave():
            globals_.Level.deleteArea(new_id)
            return

        self.LoadLevel(self.fileSavePath, True, new_id)

    def HandleDeleteArea(self):
        """
        Deletes the current area
        """
        result = QtWidgets.QMessageBox.warning(self, 'Reggie', globals_.trans.string('DeleteArea', 0),
                                               QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                                               QtWidgets.QMessageBox.StandardButton.No)
        if result == QtWidgets.QMessageBox.StandardButton.No: return

        # Save the current area in case something goes wrong.
        if not self.HandleSave(): return

        area_to_delete = globals_.Area.areanum
        new_area_one = 1 if area_to_delete != 1 else 2

        # Load the new area 1 before deleting the old area to avoid glitches
        # when the old area was area 1.
        self.LoadLevel(self.fileSavePath, True, new_area_one)

        # Actually delete the area
        globals_.Level.deleteArea(area_to_delete)

        self.actions['deletearea'].setEnabled(len(globals_.Level.areas) > 1)

        # Update the area selection combobox
        self.areaComboBox.clear()

        for area in globals_.Level.areas:
            self.areaComboBox.addItem(globals_.trans.string('AreaCombobox', 0, '[num]', area.areanum))

        self.areaComboBox.setCurrentIndex(0)

        # Save the level without the area as promised
        self.HandleSave()

    def HandleChangeGamePath(self, auto=False):
        """
        Change the game path used by the current game definition
        """
        if self.CheckDirty(): return

        while True:
            stage_path = QtWidgets.QFileDialog.getExistingDirectory(
                None,
                globals_.trans.string('ChangeGamePath', 0, '[game]', globals_.gamedef.name)
            )

            if stage_path == '':
                return False

            stage_path = str(stage_path)
            texture_path = os.path.join(stage_path, "Texture")

            while not os.path.isdir(texture_path):
                texture_path = QtWidgets.QFileDialog.getExistingDirectory(
                    None,
                    globals_.trans.string('ChangeGamePath', 4, '[game]', globals_.gamedef.name)
                )

                if texture_path == "":
                    return False

            if (not areValidGamePaths(stage_path, texture_path)) and (not globals_.gamedef.custom):  # custom gamedefs can use incomplete folders
                QtWidgets.QMessageBox.information(
                    None, globals_.trans.string('ChangeGamePath', 1),
                    globals_.trans.string('ChangeGamePath', 2)
                )
            else:
                SetGamePaths(stage_path, texture_path)
                break

        if not auto:
            # Try loading 01-01. If that fails, load up an empty canvas.
            ok = self.LoadLevel('01-01', False, 1)
            if not ok:
                self.LoadLevel(None, False, 1)

        return True

    def HandlePreferences(self):
        """
        Edit Reggie Next preferences
        """
        # Show the dialog
        dlg = PreferencesDialog()
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Rejected:
            return

        # Get the translation
        name = str(dlg.generalTab.Trans.itemData(dlg.generalTab.Trans.currentIndex(), Qt.ItemDataRole.UserRole))
        setSetting('Translation', name)

        # Get the Zone Entrance Indicators setting
        globals_.DrawEntIndicators = dlg.generalTab.zEntIndicator.isChecked()
        setSetting('ZoneEntIndicators', globals_.DrawEntIndicators)

        # Get the Zone Bounds Indicators setting
        globals_.BoundsDrawn = dlg.generalTab.zBndIndicator.isChecked()
        setSetting('ZoneBoundIndicators', globals_.BoundsDrawn)

        # Get the reset data when hiding setting
        globals_.ResetDataWhenHiding = dlg.generalTab.rdhIndicator.isChecked()
        setSetting('ResetDataWhenHiding', globals_.ResetDataWhenHiding)

        # Get the reset data when hiding setting
        globals_.HideResetSpritedata = dlg.generalTab.erbIndicator.isChecked()
        setSetting('HideResetSpritedata', globals_.HideResetSpritedata)

        # Padding settings
        globals_.EnablePadding = dlg.generalTab.epbIndicator.isChecked()
        setSetting('EnablePadding', globals_.EnablePadding)

        globals_.PaddingLength = dlg.generalTab.psValue.value()
        setSetting('PaddingLength', globals_.PaddingLength)

        # Full object size settings
        globals_.PlaceObjectsAtFullSize = dlg.generalTab.fullObjSize.isChecked()
        setSetting('PlaceObjectsAtFullSize', globals_.PlaceObjectsAtFullSize)

        # Insert Path Node setting
        globals_.InsertPathNode = dlg.generalTab.insertPathNode.isChecked()
        setSetting('InsertPathNode', globals_.InsertPathNode)

        # Get the Toolbar tab settings
        boxes = (
            dlg.toolbarTab.FileBoxes, dlg.toolbarTab.EditBoxes, dlg.toolbarTab.ViewBoxes, dlg.toolbarTab.SettingsBoxes,
            dlg.toolbarTab.HelpBoxes
        )
        ToolbarSettings = {}
        for boxList in boxes:
            for box in boxList:
                ToolbarSettings[box.InternalName] = box.isChecked()
        setSetting('ToolbarActs', ToolbarSettings)

        # Get the theme settings
        setSetting('Theme', dlg.themesTab.themeBox.currentText())
        setSetting('uiStyle', dlg.themesTab.NonWinStyle.currentText())

        # Warn the user that they may need to restart
        QtWidgets.QMessageBox.warning(None, globals_.trans.string('PrefsDlg', 0), globals_.trans.string('PrefsDlg', 30))

    def HandleNewLevel(self):
        """
        Create a new level
        """
        if self.CheckDirty(): return
        self.LoadLevel(None, False, 1)

    def HandleOpenFromName(self):
        """
        Open a level using the level picker
        """
        if self.CheckDirty(): return
        if not self._EnsureGamePathsForLevelOpen(): return

        LoadLevelNames()
        dlg = ChooseLevelNameDialog()
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.LoadLevel(dlg.currentlevel, False, 1)

    def _IsReggieRawLevelPath(self, path):
        return bool(path) and str(path).lower().endswith('.rgl')

    def _SaveReggieRawLevel(self, path, u8_data):
        try:
            arc = archive.U8.load(u8_data)
            with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('_reggie_raw', struct.pack('>4sI', b'RGLV', 1))
                for name, val in arc.files:
                    if val is None:
                        continue
                    safe_name = name.replace('\\', '/').lstrip('/')
                    zf.writestr(safe_name, val)
            return True
        except Exception as e:
            try:
                err1 = e.args[0] if len(getattr(e, 'args', ())) > 0 else '0'
                err2 = e.args[1] if len(getattr(e, 'args', ())) > 1 else str(e)
            except Exception:
                err1, err2 = '0', str(e)
            QtWidgets.QMessageBox.warning(None, globals_.trans.string('Err_Save', 0),
                                          globals_.trans.string('Err_Save', 1, '[err1]', err1, '[err2]', err2))
            return False

    def _LoadReggieRawLevel(self, path):
        try:
            with zipfile.ZipFile(path, 'r') as zf:
                try:
                    header = zf.read('_reggie_raw')
                    magic, version = struct.unpack('>4sI', header[:8])
                    if magic != b'RGLV' or version != 1:
                        return None
                except KeyError:
                    return None

                names = [n for n in zf.namelist() if n and not n.endswith('/') and n != '_reggie_raw']
                new_archive = archive.U8()

                dirs = set()
                for n in names:
                    n = n.replace('\\', '/').lstrip('/')
                    parts = n.split('/')[:-1]
                    current = ''
                    for p in parts:
                        current = p if not current else (current + '/' + p)
                        dirs.add(current)

                for d in sorted(dirs, key=lambda s: (s.count('/'), s)):
                    new_archive[d] = None

                for n in sorted(names):
                    safe_name = n.replace('\\', '/').lstrip('/')
                    new_archive[safe_name] = zf.read(n)

                return new_archive._dump()
        except Exception:
            return None

    def _GetBackupsDir(self):
        base = module_path()
        if not base:
            base = os.path.dirname(os.path.abspath(__file__))
        backups_dir = os.path.join(base, 'Backups')
        try:
            os.makedirs(backups_dir, exist_ok=True)
        except Exception:
            pass
        return backups_dir

    def _LevelBackupId(self):
        source = self.fileSavePath if self.fileSavePath else (self.fileTitle if hasattr(self, 'fileTitle') else 'untitled')
        base = os.path.basename(str(source))
        base = re.sub(r'(\.arc(\.(?:lz|lh))?|\.rgl)$', '', base, flags=re.IGNORECASE)
        base = re.sub(r'[^0-9A-Za-z._-]+', '_', base).strip('._-')
        return base if base else 'untitled'

    def _IsAllNullBytes(self, data):
        return bool(data) and data.strip(b'\x00') == b''

    def _ConfirmIfNullSaveData(self, data, target_path):
        if not self._IsAllNullBytes(data):
            return True
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle(globals_.trans.string('Warn_NullSave', 0))
        box.setText(globals_.trans.string('Warn_NullSave', 1, '[file]', os.path.basename(str(target_path))))
        box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Cancel | QtWidgets.QMessageBox.StandardButton.Yes)
        box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        return box.exec() == QtWidgets.QMessageBox.StandardButton.Yes

    def _WarnIfFileLooksNull(self, path):
        try:
            with open(path, 'rb') as f:
                sample = f.read(4096)
            if self._IsAllNullBytes(sample):
                QtWidgets.QMessageBox.warning(self, globals_.trans.string('Warn_NullSave', 0),
                                              globals_.trans.string('Warn_NullSave', 2, '[file]', os.path.basename(str(path))))
        except Exception:
            pass

    def LevelBackupTick(self):
        if self.IsCollabClientMode():
            return
        if globals_.Level is None:
            return
        if not globals_.Dirty and not globals_.AutoSaveDirty:
            return

        try:
            u8_data = globals_.Level.save()
        except Exception:
            return

        if self._IsAllNullBytes(u8_data):
            QtWidgets.QMessageBox.warning(self, globals_.trans.string('Warn_NullSave', 0),
                                          globals_.trans.string('Warn_NullSave', 3))
            return

        new_hash = hash(u8_data)
        if getattr(self, '_levelBackupLastHash', None) == new_hash:
            return

        backups_dir = self._GetBackupsDir()
        level_id = self._LevelBackupId()
        ts = time.strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backups_dir, '%s_%s.rgl' % (level_id, ts))

        if not self._SaveReggieRawLevel(backup_path, u8_data):
            return

        self._levelBackupLastHash = new_hash

        try:
            existing = []
            prefix = level_id + '_'
            for fn in os.listdir(backups_dir):
                if fn.startswith(prefix) and fn.lower().endswith('.rgl'):
                    existing.append(os.path.join(backups_dir, fn))
            existing.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            for old in existing[3:]:
                try:
                    os.remove(old)
                except Exception:
                    pass
        except Exception:
            pass

    def HandleOpenFromFile(self):
        """
        Open a level using the filename
        """
        if self.CheckDirty(): return
        if not self._EnsureGamePathsForLevelOpen(): return

        filetypes = ''
        filetypes += globals_.trans.string('FileDlgs', 9) + ' (*.arc *.arc.LH *.arc.LZ *.rgl);;'   # *.arc, *arc.LH, *.arc.LZ, *.rgl
        filetypes += globals_.trans.string('FileDlgs', 1) + ' (*.arc);;'            # *.arc
        filetypes += globals_.trans.string('FileDlgs', 5) + ' (*.arc.LH);;'         # *.arc.LH
        filetypes += globals_.trans.string('FileDlgs', 10) + ' (*.arc.LZ);;'         # *.arc.LZ
        filetypes += globals_.trans.string('FileDlgs', 11) + ' (*.rgl);;'           # *.rgl
        filetypes += globals_.trans.string('FileDlgs', 2) + ' (*)'                  # *
        fn = QtWidgets.QFileDialog.getOpenFileName(self, globals_.trans.string('FileDlgs', 0), '', filetypes)[0]
        if fn == '': return
        self.LoadLevel(str(fn), True, 1)

    def HandleSave(self):
        """
        Save a level back to the archive. Returns whether saving was successful.
        """
        if self.IsCollabClientMode():
            return False
        if not self.fileSavePath or self.fileSavePath.endswith('.arc.LH'):
            # Delegate save to HandleSaveAs function
            return self.HandleSaveAs()

        data = globals_.Level.save()

        if self._IsReggieRawLevelPath(self.fileSavePath):
            if not self._ConfirmIfNullSaveData(data, self.fileSavePath):
                return False
            ok = self._SaveReggieRawLevel(self.fileSavePath, data)
            if not ok:
                return False
            self._WarnIfFileLooksNull(self.fileSavePath)
            globals_.Dirty = False
            globals_.AutoSaveDirty = False
            self.UpdateTitle()
            setSetting('AutoSaveFilePath', self.fileSavePath)
            setSetting('AutoSaveFileData', 'x')
            self._RememberLastOpenedLevel(self.fileSavePath)
            return True

        # maybe need to compress the data
        if self.fileSavePath.endswith(".arc.LZ"):
            compressed = lz77.CompressLZ77(data)

            if compressed is None:
                # Error during compression
                QtWidgets.QMessageBox.warning(None,
                    globals_.trans.string('Err_Save', 0),
                    globals_.trans.string('Err_Save', 3, '[file-size]', len(data))
                )

                # Delegate to HandleSaveAs
                return self.HandleSaveAs()

            data = compressed

        # maybe pad with null bytes
        if globals_.EnablePadding:
            pad_length = globals_.PaddingLength - len(data)

            if pad_length < 0:
                # err: orig data is longer than padding data
                QtWidgets.QMessageBox.warning(None, globals_.trans.string('Err_Save', 0), globals_.trans.string('Err_Save', 2, '[orig-len]', len(data), '[pad-len]', globals_.PaddingLength))
                return False

            data += bytes(pad_length)

        if not self._ConfirmIfNullSaveData(data, self.fileSavePath):
            return False

        try:
            with open(self.fileSavePath, 'wb') as f:
                f.write(data)
        except IOError as e:
            QtWidgets.QMessageBox.warning(None, globals_.trans.string('Err_Save', 0),
                                          globals_.trans.string('Err_Save', 1, '[err1]', e.args[0], '[err2]', e.args[1]))
            return False

        self._WarnIfFileLooksNull(self.fileSavePath)

        globals_.Dirty = False
        globals_.AutoSaveDirty = False
        self.UpdateTitle()

        setSetting('AutoSaveFilePath', self.fileSavePath)
        setSetting('AutoSaveFileData', 'x')
        self._RememberLastOpenedLevel(self.fileSavePath)
        return True

    def HandleSaveAs(self, copy = False):
        """
        Save a level back to the archive, with a new filename. Returns whether
        saving was successful.
        """
        if self.IsCollabClientMode():
            return False
        fn = QtWidgets.QFileDialog.getSaveFileName(self,
            globals_.trans.string('FileDlgs', 8 if copy else 3),
            '',
            globals_.trans.string('FileDlgs', 1) + ' (*' + '.arc' + ');;' +
            globals_.trans.string('FileDlgs', 10) + ' (*' + '.arc.LZ'+ ');;' +
            globals_.trans.string('FileDlgs', 11) + ' (*' + '.rgl'+ ');;' +
            globals_.trans.string('FileDlgs', 2) + ' (*)'
        )[0]

        if fn == '':  # No filename given - abort
            return False

        if not copy:
            globals_.AutoSaveDirty = False
            globals_.Dirty = False

            self.fileSavePath = fn
            self.fileTitle = os.path.basename(fn)

        data = globals_.Level.save()

        if fn.lower().endswith('.rgl'):
            if not self._ConfirmIfNullSaveData(data, fn):
                return False
            ok = self._SaveReggieRawLevel(fn, data)
            if not ok:
                return False
            self._WarnIfFileLooksNull(fn)
            if not copy:
                setSetting('AutoSaveFilePath', fn)
                setSetting('AutoSaveFileData', 'x')
                self.UpdateTitle()
                self.RecentMenu.AddToList(self.fileSavePath)
                self._RememberLastOpenedLevel(self.fileSavePath)
            return True

        # maybe need to compress the data
        if fn.endswith(".arc.LZ"):
            compressed = lz77.CompressLZ77(data)

            if compressed is None:
                # Error during compression
                QtWidgets.QMessageBox.warning(None,
                    globals_.trans.string('Err_Save', 0),
                    globals_.trans.string('Err_Save', 3, '[file-size]', len(data))
                )

                return False

            data = compressed

        # maybe pad with null bytes
        if globals_.EnablePadding:
            pad_length = globals_.PaddingLength - len(data)

            if pad_length < 0:
                # err: orig data is longer than padding data
                QtWidgets.QMessageBox.warning(None, globals_.trans.string('Err_Save', 0), globals_.trans.string('Err_Save', 2, '[orig-len]', len(data), '[pad-len]', globals_.PaddingLength))
                return False

            data += bytes(pad_length)

        if not self._ConfirmIfNullSaveData(data, fn):
            return False

        with open(fn, 'wb') as f:
            f.write(data)

        self._WarnIfFileLooksNull(fn)

        if not copy:
            setSetting('AutoSaveFilePath', fn)
            setSetting('AutoSaveFileData', 'x')

            self.UpdateTitle()
            self.RecentMenu.AddToList(self.fileSavePath)
            self._RememberLastOpenedLevel(self.fileSavePath)

        return True

    def HandleSaveCopyAs(self):
        """
        Save a level back to the archive, with a new filename, but does not store this filename
        """
        self.HandleSaveAs(True)

    def HandleExit(self):
        """
        Exit the editor. Why would you want to do this anyway?
        """
        self.close()

    def HandleSwitchArea(self, idx):
        """
        Handle activated signals for areaComboBox
        """
        old_idx = globals_.Area.areanum - 1

        if idx == old_idx:
            return

        if self.CheckDirty():
            self.areaComboBox.setCurrentIndex(old_idx)
            return

        try:
            self.undoStack.clear()
        except Exception:
            pass

        # In collaboration, avoid reloading from disk on area switch
        # (disk reload would drop in-memory changes and cached remote patches).
        if hasattr(self, 'collabManager') and self.collabManager.mode is not None:
            self.collabSwitchingArea = True
            try:
                # Cache current area's latest state so we can restore it later.
                self._CacheCurrentAreaCollabState(include_scene=True, include_meta=True)
            except Exception:
                pass

            try:
                level_bytes = globals_.Level.save() if globals_.Level is not None else None
            except Exception:
                level_bytes = None

            ok = False
            if level_bytes is not None:
                try:
                    if self.IsCollabClientMode():
                        self._SetCollabMissingTilesetWarningsSuppressed(True)
                    self.collabApplyingRemote = True
                    self.LoadLevelFromNetwork(level_bytes, idx + 1)
                    ok = True
                except Exception:
                    ok = False
                finally:
                    if self.IsCollabClientMode():
                        self._SetCollabMissingTilesetWarningsSuppressed(False)
                    self.collabApplyingRemote = False
                    self.collabSwitchingArea = False
            else:
                self.collabSwitchingArea = False
        else:
            ok = self.LoadLevel(self.fileSavePath, True, idx + 1)

        if not ok:
            # loading the new area failed, so reset the combobox
            self.areaComboBox.setCurrentIndex(old_idx)
            return

        if hasattr(self, 'collabManager') and self.collabManager.mode is not None and not self.collabApplyingRemote:
            target_area = int(idx + 1)
            try:
                self._CollabRebuildIndexes()
            except Exception:
                pass

            # Apply cached state for this area immediately (if we have it).
            cached = self.collabAreaState.get(target_area)
            if isinstance(cached, dict):
                try:
                    self.collabApplyingRemote = True
                    self.scene.blockSignals(True)
                    globals_.DirtyOverride += 1
                    self.ReplaceAreaObjectsFromState(cached)
                    self.ReplaceAreaSpritesFromState(cached)
                    # Paths / entrances / locations / comments are restored from
                    # meta-state cache below. Applying them from scene-state can
                    # resurrect stale data when meta changed after the last
                    # object/sprite sync.
                    self._CollabPruneDuplicateIdsCurrentArea()
                except Exception:
                    pass
                finally:
                    globals_.DirtyOverride -= 1
                    try:
                        self.scene.blockSignals(False)
                    except Exception:
                        pass
                    self.collabApplyingRemote = False

            cached_meta = self.collabAreaMetaState.get(target_area)
            if isinstance(cached_meta, dict):
                try:
                    self._ApplyMetaStateToCurrentArea(cached_meta)
                except Exception:
                    pass

            # Ask host for authoritative state when we're a client.
            if self.collabManager.mode == "host":
                try:
                    self.CollabEnsureCurrentAreaIds()
                except Exception:
                    pass
                self.BroadcastFullSceneState()
                self.BroadcastFullMetaState()
                try:
                    self.collabAreaState[int(target_area)] = self.BuildCollabSceneState()
                except Exception:
                    pass
                try:
                    self.collabAreaMetaState[int(target_area)] = self.BuildCollabMetaState()
                except Exception:
                    pass
            else:
                if self.collabHostSessionId is not None:
                    try:
                        self.collabPeerLastState[(str(self.collabHostSessionId), target_area)] = self.BuildCollabSceneState()
                    except Exception:
                        pass
                self.collabManager.broadcast_message('request_full_sync', {'area_num': target_area})
                self._ScheduleCollabTilesetSync(50)

            self.collabLastSceneSig = hash(repr(self.BuildCollabSceneState()))
            self.collabLastLevelName = os.path.basename(self.fileSavePath) if self.fileSavePath else None

    def HandleUpdateLayer0(self, checked):
        """
        Handle toggling of layer 0 being shown
        """
        globals_.Layer0Shown = checked

        if globals_.Area is None:
            return

        for obj in globals_.Area.layers[0]:
            obj.setVisible(checked)

        self.scene.update()

    def HandleUpdateLayer1(self, checked):
        """
        Handle toggling of layer 1 being shown
        """
        globals_.Layer1Shown = checked

        if globals_.Area is None:
            return

        for obj in globals_.Area.layers[1]:
            obj.setVisible(checked)

        self.scene.update()

    def HandleUpdateLayer2(self, checked):
        """
        Handle toggling of layer 2 being shown
        """
        globals_.Layer2Shown = checked

        if globals_.Area is None:
            return

        for obj in globals_.Area.layers[2]:
            obj.setVisible(checked)

        self.scene.update()

    def HandleTilesetAnimToggle(self, checked):
        """
        Handle toggling of tileset animations
        """
        globals_.TilesetsAnimating = checked

        for tile in globals_.Tiles:
            if tile is not None: tile.resetAnimation()

        self.scene.update()

    def HandleCollisionsToggle(self, checked):
        """
        Handle toggling of tileset collisions viewing
        """
        globals_.CollisionsShown = checked

        setSetting('ShowCollisions', globals_.CollisionsShown)
        self.scene.update()

    def HandleRealViewToggle(self, checked):
        """
        Handle toggling of Real View
        """
        globals_.RealViewEnabled = checked
        SLib.RealViewEnabled = globals_.RealViewEnabled

        setSetting('RealViewEnabled', globals_.RealViewEnabled)
        self.scene.update()

    def HandleSpritesVisibility(self, checked):
        """
        Handle toggling of sprite visibility
        """
        globals_.SpritesShown = checked
        setSetting('ShowSprites', globals_.SpritesShown)

        if globals_.Area is None:
            return

        for spr in globals_.Area.sprites:
            spr.setVisible(checked)

    def HandleSpriteImages(self, checked):
        """
        Handle toggling of sprite images
        """
        globals_.SpriteImagesShown = checked

        setSetting('ShowSpriteImages', globals_.SpriteImagesShown)

        self._ClearSpriteImageLoadQueue()

        if globals_.Area is None:
            return

        globals_.DirtyOverride += 1
        for spr in globals_.Area.sprites:
            spr.UpdateRects()

            if globals_.Initializing:
                continue

            # Prevents snapping the sprite to the grid
            spr.ChangingPos = True

            if checked:
                spr.setPos(
                    (spr.objx + spr.ImageObj.xOffset) * 1.5,
                    (spr.objy + spr.ImageObj.yOffset) * 1.5,
                )
            else:
                spr.setPos(
                    spr.objx * 1.5,
                    spr.objy * 1.5,
                )

            spr.ChangingPos = False
            spr.update()

        globals_.DirtyOverride -= 1

        if checked:
            self._QueueDeferredSpriteImageLoads()

        self.levelOverview.update()

    def HandleLocationsVisibility(self, checked):
        """
        Handle toggling of location visibility
        """
        globals_.LocationsShown = checked
        setSetting('ShowLocations', globals_.LocationsShown)

        if globals_.Area is None:
            return

        for loc in globals_.Area.locations:
            loc.setVisible(checked)

    def HandleCommentsVisibility(self, checked):
        """
        Handle toggling of comment visibility
        """
        globals_.CommentsShown = checked
        setSetting('ShowComments', globals_.CommentsShown)

        if globals_.Area is None:
            return

        for com in globals_.Area.comments:
            com.setVisible(checked)

    def HandlePathsVisibility(self, checked):
        """
        Handle toggling of path visibility
        """
        globals_.PathsShown = checked
        setSetting('ShowPaths', globals_.PathsShown)

        if globals_.Area is None:
            return

        for path in globals_.Area.paths:
            path.setVisible(checked)

    def HandlePipeLinksVisibility(self, checked):
        globals_.PipeLinksShown = checked
        setSetting('ShowPipeLinks', globals_.PipeLinksShown)
        try:
            self.UpdatePipeEntranceLinks()
        except Exception:
            pass

    def HandleEventLinksVisibility(self, checked):
        globals_.EventLinksShown = checked
        setSetting('ShowEventLinks', globals_.EventLinksShown)
        try:
            self.UpdateEventLinks()
        except Exception:
            pass

    def HandleObjectsFreeze(self, checked):
        """
        Handle toggling of objects being frozen
        """
        globals_.ObjectsFrozen = checked
        setSetting('FreezeObjects', globals_.ObjectsFrozen)

        if globals_.Area is None:
            return

        flag1 = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        flag2 = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        unfrozen = not checked

        for layer in globals_.Area.layers:
            for obj in layer:
                obj.setFlag(flag1, unfrozen)
                obj.setFlag(flag2, unfrozen)

    def HandleSpritesFreeze(self, checked):
        """
        Handle toggling of sprites being frozen
        """
        globals_.SpritesFrozen = checked
        setSetting('FreezeSprites', globals_.SpritesFrozen)

        if globals_.Area is None:
            return

        flag1 = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        flag2 = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        unfrozen = not checked

        for spr in globals_.Area.sprites:
            spr.setFlag(flag1, unfrozen)
            spr.setFlag(flag2, unfrozen)

    def HandleEntrancesFreeze(self, checked):
        """
        Handle toggling of entrances being frozen
        """
        globals_.EntrancesFrozen = checked
        setSetting('FreezeEntrances', globals_.EntrancesFrozen)

        if globals_.Area is None:
            return

        flag1 = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        flag2 = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        unfrozen = not checked

        for ent in globals_.Area.entrances:
            ent.setFlag(flag1, unfrozen)
            ent.setFlag(flag2, unfrozen)

    def HandleLocationsFreeze(self, checked):
        """
        Handle toggling of locations being frozen
        """
        globals_.LocationsFrozen = checked
        setSetting('FreezeLocations', globals_.LocationsFrozen)

        if globals_.Area is None:
            return

        flag1 = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        flag2 = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        unfrozen = not checked

        for loc in globals_.Area.locations:
            loc.setFlag(flag1, unfrozen)
            loc.setFlag(flag2, unfrozen)

    def HandlePathsFreeze(self, checked):
        """
        Handle toggling of path nodes being frozen
        """
        globals_.PathsFrozen = checked
        setSetting('FreezePaths', globals_.PathsFrozen)

        if globals_.Area is None:
            return

        for path in globals_.Area.paths:
            path.set_freeze(checked)

    def HandleCommentsFreeze(self, checked):
        """
        Handle toggling of comments being frozen
        """
        globals_.CommentsFrozen = checked
        setSetting('FreezeComments', globals_.CommentsFrozen)

        if globals_.Area is None:
            return

        flag1 = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        flag2 = QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        unfrozen = not checked

        for com in globals_.Area.comments:
            com.setFlag(flag1, unfrozen)
            com.setFlag(flag2, unfrozen)

    def HandleSwitchGrid(self):
        """
        Handle switching of the grid view
        """
        if globals_.GridType is None:
            globals_.GridType = 'grid'
        elif globals_.GridType == 'grid':
            globals_.GridType = 'checker'
        else:
            globals_.GridType = None

        setSetting('GridType', globals_.GridType)
        self.scene.update()

    def HandleUIScaling(self):
        """
        Handle opening the UI Scaling dialog
        """
        from ui_scaling import ScalingDialog

        dlg = ScalingDialog(self)
        dlg.exec()

    def HandleZoomIn(self, *, towardsCursor=False):
        """
        Handle zooming in
        """
        z = self.ZoomLevel
        zi = self.ZoomLevels.index(z) + 1
        if zi < len(self.ZoomLevels):
            self.ZoomTo(self.ZoomLevels[zi], towardsCursor=towardsCursor)

    def HandleZoomOut(self, *, towardsCursor=False):
        """
        Handle zooming out
        """
        z = self.ZoomLevel
        zi = self.ZoomLevels.index(z) - 1
        if zi >= 0:
            self.ZoomTo(self.ZoomLevels[zi], towardsCursor=towardsCursor)

    def HandleZoomActual(self):
        """
        Handle zooming to the actual size
        """
        self.ZoomTo(100.0)

    def HandleZoomMin(self):
        """
        Handle zooming to the minimum size
        """
        self.ZoomTo(self.ZoomLevels[0])

    def HandleZoomMax(self):
        """
        Handle zooming to the maximum size
        """
        self.ZoomTo(self.ZoomLevels[-1])

    def ZoomTo(self, z, *, towardsCursor=False):
        """
        Zoom to a specific level
        """
        if towardsCursor:
            self.view.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        tr = QtGui.QTransform()
        tr.scale(z / 100.0, z / 100.0)
        self.ZoomLevel = z
        self.view.setTransform(tr)
        self.levelOverview.mainWindowScale = z / 100.0

        if towardsCursor:
            # (reset back to original transformation anchor)
            self.view.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter)

        zi = self.ZoomLevels.index(z)
        self.actions['zoommax'].setEnabled(zi < len(self.ZoomLevels) - 1)
        self.actions['zoomin'].setEnabled(zi < len(self.ZoomLevels) - 1)
        self.actions['zoomactual'].setEnabled(z != 100.0)
        self.actions['zoomout'].setEnabled(zi > 0)
        self.actions['zoommin'].setEnabled(zi > 0)

        self.ZoomWidget.setZoomLevel(z)
        self.ZoomStatusWidget.setZoomLevel(z)

        # Update the zone grabber rects, to resize for the new zoom level
        for z in globals_.Area.zones:
            z.UpdateRects()

        self.scene.update()

    def HandleOverviewClick(self, x, y):
        """
        Handle position changes from the level overview
        """
        self.view.centerOn(x, y)
        self.levelOverview.update()

    def SaveComments(self):
        """
        Saves the comments data back to self.Metadata
        """
        b = b""
        for com in globals_.Area.comments:
            text_data = com.text.encode("utf-8")
            # A previous version of this format used the third integer to store
            # the length (number of characters) of the comment string. This
            # makes reading comments back very hard, as a single character can
            # consist of multiple points.
            # So, to indicate we're using the new version, we set a length of
            # 2 ** 32 - 1, and we add an extra int to store the number of bytes
            # in the utf-8 encoding of the comment text.
            b += struct.pack(">4I", com.objx, com.objy, 0xFFFF_FFFF, len(text_data))
            b += text_data

        globals_.Area.Metadata.setBinData('InLevelComments_A%d' % globals_.Area.areanum, b)

    def closeEvent(self, event):
        """
        Handler for the main window close event
        """
        if self.CheckDirty():
            event.ignore()
            return

        # save our state
        self.spriteEditorDock.setVisible(False)
        self.entranceEditorDock.setVisible(False)
        self.pathEditorDock.setVisible(False)
        self.locationEditorDock.setVisible(False)
        self.defaultPropDock.setVisible(False)

        # state: determines positions of docks
        # geometry: determines the main window position
        setSetting('MainWindowState', self.saveState(0))
        setSetting('MainWindowGeometry', self.saveGeometry())
        if hasattr(self, 'collabWindow') and self.collabWindow is not None:
            try:
                setSetting('CollabChatGeometry', self.collabWindow.saveGeometry())
            except Exception:
                pass

        if hasattr(self, 'HelpBoxInstance'):
            self.HelpBoxInstance.close()

        if hasattr(self, 'TipsBoxInstance'):
            self.TipsBoxInstance.close()

        self._RememberLastOpenedLevel(self.fileSavePath)

        setSetting('AutoSaveFilePath', None)
        setSetting('AutoSaveFileData', 'x')
        if hasattr(self, 'collabWindow') and self.collabWindow is not None:
            self.collabWindow.close()
        if hasattr(self, 'collabMonitorDialog') and self.collabMonitorDialog is not None:
            self.collabMonitorDialog.close()
        if hasattr(self, 'collabBanListDialog') and self.collabBanListDialog is not None:
            self.collabBanListDialog.close()
        if hasattr(self, 'collabManager'):
            self.collabManager.stop()

        event.accept()

    def LoadLevelFromNetwork(self, levelData, areaNum):
        """
        Reload level data from in-memory bytes without touching file paths.
        """
        ui_state = self.CaptureTransientUiState()
        self.view.setUpdatesEnabled(False)
        self.levelOverview.setUpdatesEnabled(False)
        self.scene.blockSignals(True)

        try:
            globals_.Dirty = False
            globals_.DirtyOverride += 1
            dirty_override_set = True

            self._PumpUiDuringAreaLoad('Loading area...')

            try:
                self.levelOverview.Reset()
            except Exception:
                pass
            self.scene.clearSelection()
            self.CurrentSelection = []
            self.scene.clear()

            for thingList in (self.spriteList, self.entranceList, self.locationList, self.pathList, self.commentList):
                thingList.clear()
                thingList.selectionModel().setCurrentIndex(QtCore.QModelIndex(), QtCore.QItemSelectionModel.SelectionFlag.Clear)

            self._PumpUiDuringAreaLoad('Preparing area...')

            globals_.CurrentLayer = 1
            globals_.Layer0Shown = True
            globals_.Layer1Shown = True
            globals_.Layer2Shown = True
            globals_.SpritesShown = True
            globals_.LocationsShown = True
            globals_.PathsShown = True
            globals_.CommentsShown = True
            globals_.OverrideSnapping = True

            self.LoadLevel_NSMBW(levelData, areaNum)
            self._PumpUiDuringAreaLoad('Finishing area...')

            self.areaComboBox.clear()
            for area in globals_.Level.areas:
                self.areaComboBox.addItem(globals_.trans.string('AreaCombobox', 0, '[num]', area.areanum))
            self.areaComboBox.setCurrentIndex(areaNum - 1)

            self.actions['addarea'].setEnabled(len(globals_.Level.areas) < 4)
            self.actions['importarea'].setEnabled(len(globals_.Level.areas) < 4)
            self.actions['deletearea'].setEnabled(len(globals_.Level.areas) > 1)
            self.actions['backgrounds'].setEnabled(len(globals_.Area.zones) > 0)

            self.UpdateTitle()
            self.levelOverview.Reset()
            self.levelOverview.update()
            self.RestoreTransientUiState(ui_state)
        finally:
            globals_.OverrideSnapping = False
            if 'dirty_override_set' in locals() and dirty_override_set:
                globals_.DirtyOverride -= 1
            self.scene.blockSignals(False)
            self.levelOverview.setUpdatesEnabled(True)
            self.view.setUpdatesEnabled(True)
            self.view.viewport().update()
            self.scene.update()
            if getattr(globals_, 'PipeLinksShown', True):
                self._SchedulePipeEntranceLinkRefresh(0)
            self._PumpUiDuringAreaLoad('')

    def CaptureTransientUiState(self):
        """
        Captures UI state that should survive remote sync refreshes.
        """
        return {
            'x_scroll': self.view.XScrollBar.value(),
            'y_scroll': self.view.YScrollBar.value(),
            'zoom': getattr(self, 'ZoomLevel', 100.0),
            'creation_tab': self.creationTabs.currentIndex(),
            'obj_tab': self.objAllTab.currentIndex(),
            'paint_type': globals_.CurrentPaintType,
            'current_layer': globals_.CurrentLayer,
            'current_object': globals_.CurrentObject,
            'current_sprite': globals_.CurrentSprite,
            'layer0_checked': self.objUseLayer0.isChecked(),
            'layer1_checked': self.objUseLayer1.isChecked(),
            'layer2_checked': self.objUseLayer2.isChecked(),
        }

    def RestoreTransientUiState(self, state):
        """
        Restores camera and tool/palette state after remote sync refreshes.
        """
        try:
            zoom = state.get('zoom', 100.0)
            if zoom not in self.ZoomLevels:
                zoom = min(self.ZoomLevels, key=lambda v: abs(v - zoom))
            self.ZoomTo(zoom)
        except Exception:
            pass

        self.view.XScrollBar.setValue(state.get('x_scroll', self.view.XScrollBar.value()))
        self.view.YScrollBar.setValue(state.get('y_scroll', self.view.YScrollBar.value()))

        self.creationTabs.setCurrentIndex(state.get('creation_tab', self.creationTabs.currentIndex()))
        obj_tab = state.get('obj_tab', self.objAllTab.currentIndex())
        if 0 <= obj_tab < self.objAllTab.count() and self.objAllTab.isTabEnabled(obj_tab):
            self.objAllTab.setCurrentIndex(obj_tab)

        globals_.CurrentPaintType = state.get('paint_type', globals_.CurrentPaintType)
        globals_.CurrentLayer = state.get('current_layer', globals_.CurrentLayer)
        globals_.CurrentObject = state.get('current_object', globals_.CurrentObject)
        globals_.CurrentSprite = state.get('current_sprite', globals_.CurrentSprite)

        self.objUseLayer0.setChecked(state.get('layer0_checked', False))
        self.objUseLayer1.setChecked(state.get('layer1_checked', True))
        self.objUseLayer2.setChecked(state.get('layer2_checked', False))

        self.levelOverview.update()

    def _PumpUiDuringAreaLoad(self, message=None):
        if message is not None and hasattr(self, 'hoverLabel'):
            try:
                self.hoverLabel.setText(str(message))
            except Exception:
                pass
        try:
            QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        except Exception:
            pass

    def _LoadObjectPickerForCurrentArea(self):
        tileset_key = (
            str(getattr(globals_.Area, 'tileset0', '')),
            str(getattr(globals_.Area, 'tileset1', '')),
            str(getattr(globals_.Area, 'tileset2', '')),
            str(getattr(globals_.Area, 'tileset3', '')),
        )
        if getattr(self, '_lastObjectPickerTilesets', None) != tileset_key:
            self.objPicker.LoadFromTilesets()
            self._lastObjectPickerTilesets = tileset_key

    def LoadLevel(self, name, isFullPath, areaNum):
        """
        Load a level from NSMBW into the editor.
        """
        new = name is None
        same = False
        restoring_autosave = bool(globals_.RestoredFromAutoSave)

        if not new:
            if not restoring_autosave:
                checknames = []
                if isFullPath:
                    checknames = [name]
                else:
                    for ext in globals_.FileExtentions:
                        checknames.append(os.path.join(globals_.gamedef.GetStageGamePath(), name + ext))

                for checkname in checknames:
                    if os.path.isfile(checkname):
                        break
                else:
                    QtWidgets.QMessageBox.warning(self, 'Reggie!',
                                                  globals_.trans.string('Err_CantFindLevel', 0, '[name]', checkname),
                                                  QtWidgets.QMessageBox.StandardButton.Ok)
                    return False

                if not IsNSMBLevel(checkname) and not self._IsReggieRawLevelPath(checkname):
                    QtWidgets.QMessageBox.warning(self, 'Reggie!', globals_.trans.string('Err_InvalidLevel', 0),
                                                  QtWidgets.QMessageBox.StandardButton.Ok)
                    return False

                name = checkname
                same = name == self.fileSavePath  # Just an area change

        # Get the file path, if possible
        if new:
            # Set the filepath variables
            self.fileSavePath = None
            self.fileTitle = 'untitled'

        elif not same:

            # Get the data
            if not globals_.RestoredFromAutoSave:

                # Set the filepath variables
                self.fileSavePath = name
                self.fileTitle = os.path.basename(self.fileSavePath)

                # Open the file
                if self._IsReggieRawLevelPath(self.fileSavePath):
                    levelData = self._LoadReggieRawLevel(self.fileSavePath)
                    if levelData is None:
                        QtWidgets.QMessageBox.warning(self, 'Reggie!', globals_.trans.string('Err_InvalidLevel', 0),
                                                      QtWidgets.QMessageBox.StandardButton.Ok)
                        return False
                else:
                    with open(self.fileSavePath, 'rb') as fileobj:
                        levelData = fileobj.read()

                    # Decompress, if needed
                    if (levelData[0] & 0xF0) == 0x40:  # If LH-compressed
                        try:
                            levelData = lh.UncompressLH(levelData)
                        except IndexError:
                            QtWidgets.QMessageBox.warning(None, globals_.trans.string('Err_Decompress', 0),
                                                          globals_.trans.string('Err_Decompress', 1, '[file]', name))
                            return False
                    elif not levelData.startswith(b"U\xAA8-"):  # If LZ-compressed
                        try:
                            levelData = lz77.UncompressLZ77(levelData)
                        except IndexError:
                            QtWidgets.QMessageBox.warning(None, globals_.trans.string('Err_Decompress', 0),
                                                          globals_.trans.string('Err_Decompress', 2, '[file]', name))
                            return False

            else:
                # Auto-saved level. Check if there's a path associated with it:

                if globals_.AutoSavePath == 'None':
                    self.fileSavePath = None
                    self.fileTitle = globals_.trans.string('WindowTitle', 0)
                else:
                    self.fileSavePath = globals_.AutoSavePath
                    self.fileTitle = os.path.basename(name)

                # Get the level data
                levelData = globals_.AutoSaveData
                SetDirty(noautosave=True)

                # Turn off the autosave flag
                globals_.RestoredFromAutoSave = False

        try:
            self.undoStack.clear()
        except Exception:
            pass

        ui_state = self.CaptureTransientUiState()
        self.view.setUpdatesEnabled(False)
        self.levelOverview.setUpdatesEnabled(False)
        self.scene.blockSignals(True)
        try:
            # Turn the dirty flag off, and keep it that way
            globals_.Dirty = False
            globals_.DirtyOverride += 1
            dirty_override_set = True

            self._PumpUiDuringAreaLoad('Loading area...')

            # First, clear out the existing level.
            try:
                self.levelOverview.Reset()
            except Exception:
                pass
            self.scene.clearSelection()
            self.CurrentSelection = []
            self.scene.clear()

            # Clear out all level-thing lists
            for thingList in (self.spriteList, self.entranceList, self.locationList, self.pathList, self.commentList):
                thingList.clear()
                thingList.selectionModel().setCurrentIndex(QtCore.QModelIndex(), QtCore.QItemSelectionModel.SelectionFlag.Clear)

            self._PumpUiDuringAreaLoad('Preparing area...')

            # Reset these here, because if they are set after
            # creating the objects, they use the old values.
            globals_.CurrentLayer = 1
            globals_.Layer0Shown = True
            globals_.Layer1Shown = True
            globals_.Layer2Shown = True

            # Also enable things that use 'True' by default
            globals_.SpritesShown = True
            globals_.LocationsShown = True
            globals_.PathsShown = True
            globals_.CommentsShown = True

            # Prevent things from snapping when they're created
            globals_.OverrideSnapping = True

            # Load the actual level
            if new:
                self.newLevel()
            elif not same:
                self.LoadLevel_NSMBW(levelData, areaNum)
            else:
                # We have already loaded this area's data - it's stored as
                # AbstractAreas in the Level. This means we do not have to open and
                # optionally decompress the level file. Hence, we can just relay
                # this to the level.
                globals_.Level.changeArea(areaNum)
                self.ResetPalette()

            self._PumpUiDuringAreaLoad('Finishing area...')

            # Fill up the area list
            self.areaComboBox.clear()

            for area in globals_.Level.areas:
                self.areaComboBox.addItem(globals_.trans.string('AreaCombobox', 0, '[num]', area.areanum))

            self.areaComboBox.setCurrentIndex(areaNum - 1)

            # Scroll to the initial entrance
            startEntID = globals_.Area.startEntrance
            startEnt = None
            for ent in globals_.Area.entrances:
                if ent.entid == startEntID:
                    self.view.centerOn(ent)
                    break
            else:
                self.view.centerOn(0, 0)

            self.ZoomTo(100.0)

            # Reset some editor things
            self.actions['showlay0'].setChecked(True)
            self.actions['showlay1'].setChecked(True)
            self.actions['showlay2'].setChecked(True)
            self.actions['showsprites'].setChecked(True)
            self.actions['showlocations'].setChecked(True)
            self.actions['showpaths'].setChecked(True)
            self.actions['showcomments'].setChecked(True)
            self.actions['addarea'].setEnabled(len(globals_.Level.areas) < 4)
            self.actions['importarea'].setEnabled(len(globals_.Level.areas) < 4)
            self.actions['deletearea'].setEnabled(len(globals_.Level.areas) > 1)
            self.actions['backgrounds'].setEnabled(len(globals_.Area.zones) > 0)

            # Turn snapping back on
            globals_.OverrideSnapping = False

            # Turn the dirty flag off
            globals_.DirtyOverride -= 1
            dirty_override_set = False
            self.UpdateTitle()

            # Update UI things
            self.scene.update()

            self.levelOverview.Reset()
            self.levelOverview.update()
            if same:
                self.RestoreTransientUiState(ui_state)

            if new:
                SetDirty()

            elif not same:
                # Add the path to Recent Files
                self.RecentMenu.AddToList(self.fileSavePath)
                self._RememberLastOpenedLevel(self.fileSavePath)

            if hasattr(self, 'qpt_palette') and self.qpt_palette is not None:
                try:
                    self.qpt_palette.reset()
                except Exception as e:
                    print(f"[QPT] Warning: Could not reset QPT: {e}")

            # If we got this far, everything worked! Return True.
            return True
        finally:
            globals_.OverrideSnapping = False
            if 'dirty_override_set' in locals() and dirty_override_set:
                globals_.DirtyOverride -= 1
            self.scene.blockSignals(False)
            self.levelOverview.setUpdatesEnabled(True)
            self.view.setUpdatesEnabled(True)
            self.view.viewport().update()
            self.scene.update()
            self._PumpUiDuringAreaLoad('')

    def newLevel(self):
        # Create the new level object
        globals_.Level = Level_NSMBW()

        # Load it
        globals_.Level.new()

        # Prepare the object picker
        self.objUseLayer1.setChecked(True)

        self.objPicker.LoadFromTilesets()

        self.objAllTab.setCurrentIndex(0)
        self.objAllTab.setTabEnabled(0, True)
        self.objAllTab.setTabEnabled(1, False)
        self.objAllTab.setTabEnabled(2, False)
        self.objAllTab.setTabEnabled(3, False)

        if hasattr(self, 'qpt_palette') and self.qpt_palette is not None:
            try:
                self.qpt_palette.reset()
            except Exception as e:
                print(f"[QPT] Warning: Could not reset QPT: {e}")

    def LoadLevel_NSMBW(self, levelData, areaNum):
        """
        Performs all level-loading tasks specific to New Super Mario Bros. Wii levels.
        Do not call this directly - use LoadLevel instead!
        """
        # Create the new level object
        globals_.Level = Level_NSMBW()

        # Load it
        if not globals_.Level.load(levelData, areaNum):
            raise Exception

        # https://github.com/Zement/Reggie/blob/master/reggie.py#L3630-L3637
        # Check for unknown sprite IDs and show warning message
        if hasattr(globals_.Area, 'unknown_sprite_ids') and globals_.Area.unknown_sprite_ids is not None:
            sprite_ids = sorted(globals_.Area.unknown_sprite_ids)

            title = globals_.trans.string('Err_UnknownSprite', 0)
            if len(sprite_ids) == 1:
                msg = globals_.trans.string('Err_UnknownSprite', 1, '[id]', str(sprite_ids[0]))
            else:
                if map(str, sprite_ids) is not None:
                    msg = globals_.trans.string('Err_UnknownSprite', 2, '[ids]', ', '.join(map(str, sprite_ids)))
            QtWidgets.QMessageBox.warning(None, title, msg)

        self.ResetPalette()

    def ResetPalette(self):
        """
        Resets the palette and initialises the scene from the currently loaded
        Area.
        """
        # Prepare the object picker
        self.objUseLayer1.setChecked(True)

        self._LoadObjectPickerForCurrentArea()

        self.objAllTab.setCurrentIndex(0)
        self.objAllTab.setTabEnabled(0, (globals_.Area.tileset0 != ''))
        self.objAllTab.setTabEnabled(1, (globals_.Area.tileset1 != ''))
        self.objAllTab.setTabEnabled(2, (globals_.Area.tileset2 != ''))
        self.objAllTab.setTabEnabled(3, (globals_.Area.tileset3 != ''))

        # Load events
        self.LoadEventTabFromLevel()
        self._PumpUiDuringAreaLoad('Building scene...')

        # Add all things to the scene
        pcEvent = self.HandleObjPosChange
        for layer_idx, layer in enumerate(reversed(globals_.Area.layers)):
            for obj_idx, obj in enumerate(layer, 1):
                obj.positionChanged = pcEvent
                self.scene.addItem(obj)
                if (obj_idx % 400) == 0:
                    self._PumpUiDuringAreaLoad()
            if layer_idx < 2:
                self._PumpUiDuringAreaLoad()

        pcEvent = self.HandleSprPosChange

        self.spriteList.prepareBatchAdd()
        for spr_idx, spr in enumerate(globals_.Area.sprites, 1):
            spr.positionChanged = pcEvent
            self.spriteList.addSprite(spr)
            self.scene.addItem(spr)
            spr.UpdateListItem()
            if (spr_idx % 200) == 0:
                self._PumpUiDuringAreaLoad()

        self.spriteList.endBatchAdd()
        self._PumpUiDuringAreaLoad()

        pcEvent = self.HandleEntPosChange
        for ent_idx, ent in enumerate(globals_.Area.entrances, 1):
            ent.positionChanged = pcEvent
            ent.listitem = ListWidgetItem_SortsByOther(ent)
            ent.listitem.entid = ent.entid
            self.entranceList.addItem(ent.listitem)
            self.scene.addItem(ent)
            ent.UpdateListItem()
            if (ent_idx % 100) == 0:
                self._PumpUiDuringAreaLoad()
        self._PumpUiDuringAreaLoad()

        for zone_idx, zone in enumerate(globals_.Area.zones, 1):
            self.scene.addItem(zone)
            if (zone_idx % 50) == 0:
                self._PumpUiDuringAreaLoad()

        pcEvent = self.HandleLocPosChange
        scEvent = self.HandleLocSizeChange
        for loc_idx, location in enumerate(globals_.Area.locations, 1):
            location.positionChanged = pcEvent
            location.sizeChanged = scEvent
            location.listitem = ListWidgetItem_SortsByOther(location)
            self.locationList.addItem(location.listitem)
            self.scene.addItem(location)
            location.UpdateListItem()
            if (loc_idx % 100) == 0:
                self._PumpUiDuringAreaLoad()
        self._PumpUiDuringAreaLoad()

        for path_idx, path in enumerate(globals_.Area.paths, 1):
            path.add_to_scene()
            if (path_idx % 50) == 0:
                self._PumpUiDuringAreaLoad()
        self._PumpUiDuringAreaLoad()

        for com_idx, com in enumerate(globals_.Area.comments, 1):
            com.positionChanged = self.HandleComPosChange
            com.textChanged = self.HandleComTxtChange
            com.listitem = QtWidgets.QListWidgetItem()
            self.commentList.addItem(com.listitem)
            self.scene.addItem(com)
            com.UpdateListItem()
            if (com_idx % 100) == 0:
                self._PumpUiDuringAreaLoad()
        self._PumpUiDuringAreaLoad()

        self.UpdatePipeEntranceLinks()
        self.UpdateEventLinks()
        self.UpdateRotationControllerPreviews()

    def ReloadTilesets(self, soft=False):
        """
        Reloads all the tilesets. If soft is True, they will not be reloaded if the filepaths have not changed.
        """
        LoadTilesetInfo(True)

        tilesets = [globals_.Area.tileset0, globals_.Area.tileset1, globals_.Area.tileset2, globals_.Area.tileset3]
        for idx, name in enumerate(tilesets):
            if (name is not None) and (name != ''):
                LoadTileset(idx, name, not soft)

        self.objPicker.LoadFromTilesets()

        for layer in globals_.Area.layers:
            for obj in layer:
                obj.updateObjCache()

        self.scene.update()
        if hasattr(self, 'collabManager') and self.collabManager.mode is not None and not self.collabApplyingRemote:
            self.BroadcastFullLevelSnapshot()

    def ReloadSpritedata(self):
        LoadSpriteData()
        self.sprPicker.clearPreviewCache()

        # Reload spritedata editor
        cur_sel_sprite = self.spriteDataEditor.spritetype
        self.spriteDataEditor.setSprite(cur_sel_sprite, True)

        # Update list
        self.sprPicker.UpdateSpriteNames()

        # Redo the search if a search was made
        search = self.spriteSearchTerm.text()
        if search != "":
            self.sprPicker.SetSearchString(search)

    def ChangeSelectionHandler(self):
        """
        Update the visible panels whenever the selection changes
        """
        if self.SelectionUpdateFlag: return

        try:
            selitems = self.scene.selectedItems()
        except RuntimeError:
            # must catch this error: if you close the app while something is selected,
            # you get a RuntimeError about the 'underlying C++ object being deleted'
            return

        # do this to avoid flicker
        showSpritePanel = False
        showEntrancePanel = False
        showLocationPanel = False
        showPathPanel = False
        updateModeInfo = False

        # clear our variables
        self.selObj = None
        self.selObjs = None

        self.spriteList.clearSelection()
        self.entranceList.setCurrentItem(None)
        self.locationList.setCurrentItem(None)
        self.pathList.setCurrentItem(None)
        self.commentList.setCurrentItem(None)

        # possibly a small optimization
        func_ii = isinstance
        type_obj = ObjectItem
        type_spr = SpriteItem
        type_ent = EntranceItem
        type_loc = LocationItem
        type_path = PathItem
        type_com = CommentItem

        if not selitems:
            # nothing is selected
            self.actions['cut'].setEnabled(False)
            self.actions['copy'].setEnabled(False)
            self.actions['shiftitems'].setEnabled(False)
            self.actions['mergelocations'].setEnabled(False)

        elif len(selitems) == 1:
            # only one item, check the type
            self.actions['cut'].setEnabled(True)
            self.actions['copy'].setEnabled(True)
            self.actions['shiftitems'].setEnabled(True)
            self.actions['mergelocations'].setEnabled(False)

            item = selitems[0]
            self.selObj = item
            if func_ii(item, type_spr):
                showSpritePanel = True
                updateModeInfo = True
            elif func_ii(item, type_ent):
                self.creationTabs.setCurrentIndex(2)
                self.UpdateFlag = True
                self.entranceList.setCurrentItem(item.listitem)
                self.UpdateFlag = False
                showEntrancePanel = True
                updateModeInfo = True
            elif func_ii(item, type_loc):
                self.creationTabs.setCurrentIndex(3)
                self.UpdateFlag = True
                self.locationList.setCurrentItem(item.listitem)
                self.UpdateFlag = False
                showLocationPanel = True
                updateModeInfo = True
            elif func_ii(item, type_path):
                self.creationTabs.setCurrentIndex(4)
                self.UpdateFlag = True
                self.pathList.setCurrentItem(item.listitem)
                self.UpdateFlag = False
                showPathPanel = True
                updateModeInfo = True
            elif func_ii(item, type_com):
                self.creationTabs.setCurrentIndex(7)
                self.UpdateFlag = True
                self.commentList.setCurrentItem(item.listitem)
                self.UpdateFlag = False
                updateModeInfo = True

        else:
            updateModeInfo = True

            # more than one item
            self.actions['cut'].setEnabled(True)
            self.actions['copy'].setEnabled(True)
            self.actions['shiftitems'].setEnabled(True)

        # turn on the Stamp Add btn if applicable
        self.stampAddBtn.setEnabled(bool(selitems))

        # count the # of each type, for the statusbar label
        spr = 0
        ent = 0
        obj = 0
        loc = 0
        path = 0
        com = 0
        for item in selitems:
            if func_ii(item, type_spr): spr += 1
            if func_ii(item, type_ent): ent += 1
            if func_ii(item, type_obj): obj += 1
            if func_ii(item, type_loc): loc += 1
            if func_ii(item, type_path): path += 1
            if func_ii(item, type_com): com += 1

        self.actions['mergelocations'].setEnabled(loc >= 2)
        self.layerChangeButton.setEnabled(obj != 0)

        # write the statusbar label text
        text = ''
        if selitems:
            singleitem = len(selitems) == 1
            if singleitem:
                if obj:
                    text = globals_.trans.string('Statusbar', 0)  # 1 object selected
                elif spr:
                    text = globals_.trans.string('Statusbar', 1)  # 1 sprite selected
                elif ent:
                    text = globals_.trans.string('Statusbar', 2)  # 1 entrance selected
                elif loc:
                    text = globals_.trans.string('Statusbar', 3)  # 1 location selected
                elif path:
                    text = globals_.trans.string('Statusbar', 4)  # 1 path node selected
                else:
                    text = globals_.trans.string('Statusbar', 29)  # 1 comment selected
            else:  # multiple things selected; see if they're all the same type
                if not any((spr, ent, loc, path, com)):
                    text = globals_.trans.string('Statusbar', 5, '[x]', obj)  # x objects selected
                elif not any((obj, ent, loc, path, com)):
                    text = globals_.trans.string('Statusbar', 6, '[x]', spr)  # x sprites selected
                elif not any((obj, spr, loc, path, com)):
                    text = globals_.trans.string('Statusbar', 7, '[x]', ent)  # x entrances selected
                elif not any((obj, spr, ent, path, com)):
                    text = globals_.trans.string('Statusbar', 8, '[x]', loc)  # x locations selected
                elif not any((obj, spr, ent, loc, com)):
                    text = globals_.trans.string('Statusbar', 9, '[x]', path)  # x path nodes selected
                elif not any((obj, spr, ent, path, loc)):
                    text = globals_.trans.string('Statusbar', 30, '[x]', com)  # x comments selected
                else:  # different types
                    text = globals_.trans.string('Statusbar', 10, '[x]', len(selitems))  # x items selected
                    types = (
                        (obj, 12, 13),  # variable, translation string ID if var == 1, translation string ID if var > 1
                        (spr, 14, 15),
                        (ent, 16, 17),
                        (loc, 18, 19),
                        (path, 20, 21),
                        (com, 31, 32),
                    )
                    first = True
                    for var, singleCode, multiCode in types:
                        if var > 0:
                            if not first: text += globals_.trans.string('Statusbar', 11)
                            first = False
                            text += globals_.trans.string('Statusbar', (singleCode if var == 1 else multiCode), '[x]', var)
                            # above: '[x]', var) can't hurt if var == 1

                    text += globals_.trans.string('Statusbar', 22)  # ')'

        self.selectionLabel.setText(text)

        self.CurrentSelection = selitems

        for thing in selitems:
            # This helps sync non-objects with objects while dragging
            if not isinstance(thing, ObjectItem):
                thing.dragoffsetx = (((thing.objx // 16) * 16) - thing.objx) * 1.5
                thing.dragoffsety = (((thing.objy // 16) * 16) - thing.objy) * 1.5

        self.spriteEditorDock.setVisible(showSpritePanel)
        self.entranceEditorDock.setVisible(showEntrancePanel)
        self.locationEditorDock.setVisible(showLocationPanel)
        self.pathEditorDock.setVisible(showPathPanel)

        self.actions['deselect'].setEnabled(bool(selitems))

        if updateModeInfo:
            globals_.DirtyOverride += 1
            self.UpdateModeInfo()
            globals_.DirtyOverride -= 1

        # Collaboration: show remote selection as a per-player outline and transfer
        # ownership when we select an item that somebody else currently owns.
        if self._CollabEnabled():
            ownership_changed = self._CollabAdoptLocalSelection(selitems)
            self._ScheduleCollabSelectionBroadcast(delay_ms=(0 if ownership_changed else 40), force=ownership_changed)

    def HandleObjPosChange(self, obj, oldx, oldy, x, y):
        """
        Handle the object being dragged
        """
        if obj == self.selObj:
            if oldx == x and oldy == y: return
            SetDirty()
        self.levelOverview.update()
        if self._CollabEnabled() and not self.collabApplyingRemote and not getattr(self, 'collabSwitchingArea', False):
            self.CollabQueueObjectUpdate(obj)

    def CreationTabChanged(self, nt):
        """
        Handles the selected palette tab changing
        """
        CPT = -1

        if nt == 0:  # objects
            CPT = self.objAllTab.currentIndex()
        elif nt == 1:  # sprites
            # Ensure the user can't paint sprites
            # when the 'current sprites' tab is
            # opened.
            if self.sprAllTab.currentIndex() != 1:
                CPT = 4
        elif nt == 2:
            CPT = 5  # entrances
        elif nt == 3:
            CPT = 7  # locations
        elif nt == 4:
            CPT = 6  # paths
        elif nt == 6:
            CPT = 8  # stamp pad
        elif nt == 7:
            CPT = 9  # comment

        globals_.CurrentPaintType = CPT

        if hasattr(self, 'qpt_palette') and self.qpt_palette:
            qpt_tab_index = -1
            for i in range(self.creationTabs.count()):
                if self.creationTabs.widget(i) == self.qpt_palette:
                    qpt_tab_index = i
                    break

            if qpt_tab_index != -1:
                if nt != qpt_tab_index:
                    try:
                        quick_paint_tab = self.qpt_palette.get_quick_paint_tab()
                        if quick_paint_tab and quick_paint_tab.is_painting():
                            quick_paint_tab.qpt_widget.on_stop_painting()
                    except Exception:
                        pass

                    try:
                        from quickpaint.core.tool_manager import get_tool_manager
                        tool_manager = get_tool_manager()
                        tool_manager.deactivate_all()
                    except Exception:
                        pass

                    if self.view:
                        self.view.setCursor(QtCore.Qt.CursorShape.ArrowCursor)

                    qpt_funcs = getattr(globals_, 'qpt_functions', None)
                    if qpt_funcs and qpt_funcs.get('hide_overlay'):
                        qpt_funcs['hide_overlay']()
                else:
                    try:
                        self._RestoreQuickPaintToolState()
                    except Exception:
                        pass

                    qpt_funcs = getattr(globals_, 'qpt_functions', None)
                    if qpt_funcs and qpt_funcs.get('show_overlay'):
                        qpt_funcs['show_overlay']()

    def ObjTabChanged(self, nt):
        """
        Handles the selected slot tab in the object palette changing
        """
        if hasattr(self, 'objPicker'):
            if 0 <= nt <= 3:
                self.objPicker.ShowTileset(nt)
                eval('self.objTS%dTab' % nt).setLayout(self.createObjectLayout)
            self.defaultPropDock.setVisible(False)

        globals_.CurrentPaintType = nt
        self._UpdateTilesetEditButtonState()

    def SprTabChanged(self, nt):
        """
        Handles the selected tab in the sprite palette changing
        """
        if nt == 0:
            cpt = 4
        else:
            cpt = -1

        globals_.CurrentPaintType = cpt

    def ChangeSelectionLayer(self, checked):
        """
        Changes the layer of the selection to the current layer.
        """
        self.ChangeSelectedObjectsLayer(globals_.CurrentLayer)

    def LayerChoiceChanged(self, nl):
        """
        Handles the selected layer changing
        """
        globals_.CurrentLayer = nl

        if hasattr(self, 'qpt_palette') and self.qpt_palette:
            qpt_tab = self.qpt_palette.get_quick_paint_tab()
            if qpt_tab and hasattr(qpt_tab, 'qpt_widget'):
                qpt_tab.qpt_widget.set_layer_silent(nl)
            fill_tab = self.qpt_palette.get_fill_paint_tab()
            if fill_tab:
                fill_tab.set_layer_silent(nl)

        # should we replace?
        if QtWidgets.QApplication.keyboardModifiers() == Qt.KeyboardModifier.AltModifier:
            self.ChangeSelectedObjectsLayer(nl)

    def ChangeSelectedObjectsLayer(self, new_layer_id):
        """
        Changes the layer of the selected objects to the new layer.
        """
        assert new_layer_id in (0, 1, 2)

        items = self.scene.selectedItems()
        type_obj = ObjectItem
        area = globals_.Area
        change = []

        for x in items:
            if isinstance(x, type_obj) and x.layer != new_layer_id:
                change.append(x)

        if not change:
            return

        change.sort(key=lambda x: x.zValue())
        newLayer = area.layers[new_layer_id]

        if not newLayer:
            z_value = (2 - new_layer_id) * 8192
        else:
            z_value = newLayer[-1].zValue() + 1

        if new_layer_id == 0:
            newVisibility = globals_.Layer0Shown
        elif new_layer_id == 1:
            newVisibility = globals_.Layer1Shown
        else:
            newVisibility = globals_.Layer2Shown

        for item in change:
            area.RemoveFromLayer(item)
            item.layer = new_layer_id
            newLayer.append(item)

            item.setZValue(z_value)
            item.setVisible(newVisibility)
            item.update()
            item.UpdateTooltip()
            self.CollabQueueObjectUpdate(item)

            z_value += 1

        self.scene.update()
        SetDirty()

    def ObjectChoiceChanged(self, type_):
        """
        Handles a new object being chosen
        """
        globals_.CurrentObject = type_

    def ObjectReplace(self, type):
        """
        Handles a new object being chosen to replace the selected objects
        """
        items = self.scene.selectedItems()
        type_obj = ObjectItem
        tileset = globals_.CurrentPaintType
        changed = False

        for x in items:
            if isinstance(x, type_obj) and (x.tileset != tileset or x.type != type):
                x.SetType(tileset, type)
                x.update()
                changed = True

        if changed:
            SetDirty()

    def SpriteChoiceChanged(self, type):
        """
        Handles a new sprite being chosen
        """
        globals_.CurrentSprite = type

        if type != 1000 and type >= 0:
            self.defaultDataEditor.setSprite(type, initial_data=bytes(10))
            self.defaultPropButton.setEnabled(True)
        else:
            self.defaultPropButton.setEnabled(False)
            self.defaultPropDock.setVisible(False)
            self.defaultDataEditor.update()

    def SpriteReplace(self, type):
        """
        Handles a new sprite type being chosen to replace the selected sprites
        """
        items = self.scene.selectedItems()
        type_spr = SpriteItem
        changed = False

        for x in items:
            if isinstance(x, type_spr):
                x.spritedata = self.defaultDataEditor.data  # change this first or else images get messed up
                x.SetType(type)
                x.update()
                changed = True

        if changed:
            SetDirty()

        self.ChangeSelectionHandler()

    def SelectNewSpriteView(self, type):
        """
        Handles a new sprite view being chosen
        """
        cat = globals_.SpriteCategories[type]
        self.sprPicker.SwitchView(cat)

        isSearch = (type == 0)
        layout = self.spriteSearchLayout
        layout.itemAt(0).widget().setVisible(isSearch)
        layout.itemAt(1).widget().setVisible(isSearch)

    def NewSearchTerm(self, text):
        """
        Handles a new sprite search term being entered
        """
        self.sprPicker.SetSearchString(text)

    def ShowDefaultProps(self):
        """
        Handles the Show Default Properties button being clicked
        """
        self.defaultPropDock.setVisible(True)

    def HandleSprPosChange(self, obj, oldx, oldy, x, y):
        """
        Handle the sprite being dragged
        """
        if obj == self.selObj:
            if oldx == x and oldy == y: return
            obj.UpdateListItem()
            SetDirty()

            # The sprite has changed position, so its LevelRect changed, so the
            # level overview needs to be redrawn.
            self.levelOverview.update()
        try:
            if int(getattr(obj, 'type', -1)) in (149, 252, 253, 254, 255, 256):
                self.UpdateRotationControllerPreviews()
        except Exception:
            pass
        try:
            if getattr(globals_, 'EventLinksShown', False):
                self.UpdateEventLinks()
        except Exception:
            pass
        if self._CollabEnabled() and not self.collabApplyingRemote and not getattr(self, 'collabSwitchingArea', False):
            self.CollabQueueSpriteUpdate(obj)

    def SpriteDataUpdated(self, data):
        """
        Handle the current sprite's data being updated
        """
        if self.spriteEditorDock.isVisible():
            obj = self.selObj
            old_def = obj.instanceDef(obj)
            self._CollabEnsureItemId(obj)
            obj.spritedata = data
            obj.UpdateListItem()
            SetDirty()

            obj.UpdateDynamicSizing()
            self.spriteList.updateSprite(obj)
            try:
                if int(getattr(obj, 'type', -1)) in (149, 252, 253, 254, 255, 256):
                    self.UpdateRotationControllerPreviews()
            except Exception:
                pass
            try:
                if getattr(globals_, 'EventLinksShown', False):
                    self.UpdateEventLinks()
            except Exception:
                pass
            if not self.UndoRedoInProgress and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False) and not globals_.DirtyOverride:
                try:
                    from undo import ModifyInstanceUndoAction
                    new_def = obj.instanceDef(obj)
                    self.undoStack.addOrExtendAction(ModifyInstanceUndoAction(old_def, new_def, collab_id=getattr(obj, '_collab_id', None)))
                except Exception:
                    pass
            if self._CollabEnabled() and not self.collabApplyingRemote and not getattr(self, 'collabSwitchingArea', False):
                self.CollabQueueSpriteUpdate(obj, include_data=True)

    def HandleEntPosChange(self, obj, oldx, oldy, x, y):
        """
        Handle the entrance being dragged
        """
        if oldx == x and oldy == y: return
        obj.UpdateListItem()
        if obj == self.selObj:
            SetDirty()
        self._CollabMarkItemHot(obj)
        self.CollabQueueEntranceUpsert(obj, is_add=False)

    def HandlePathPosChange(self, obj, oldx, oldy, x, y):
        """
        Handle the path being dragged
        """
        if oldx == x and oldy == y: return
        obj.path.node_moved(obj)
        obj.UpdateListItem()
        if obj == self.selObj:
            SetDirty()
        self._CollabMarkItemHot(obj)
        self._CollabMarkItemHot(getattr(obj, 'path', None))
        self.CollabQueuePathNodeUpdate(obj)

    def HandleComPosChange(self, obj, oldx, oldy, x, y):
        """
        Handle the comment being dragged
        """
        if oldx == x and oldy == y: return
        obj.UpdateTooltip()
        obj.handlePosChange(oldx, oldy)
        obj.UpdateListItem()
        if obj == self.selObj:
            self.SaveComments()
            SetDirty()
        self._CollabMarkItemHot(obj)
        self.CollabQueueCommentUpsert(obj, is_add=False)

    def HandleComTxtChange(self, obj):
        """
        Handle the comment's text being changed
        """
        obj.UpdateListItem()
        obj.UpdateTooltip()
        self.SaveComments()
        SetDirty()
        self._CollabMarkItemHot(obj)
        self.CollabQueueCommentUpsert(obj, is_add=False)

    def HandleEntranceSelectByList(self, item):
        """
        Handle an entrance being selected from the list
        """
        if self.UpdateFlag: return

        ent = item.reference
        ent.ensureVisible(xMargin=192, yMargin=192)
        self.scene.clearSelection()
        ent.setSelected(True)

    def HandleEntranceToolTipAboutToShow(self, item):
        """
        Handle an entrance being hovered in the list
        """
        for ent in globals_.Area.entrances:
            if ent.listitem == item:
                ent.UpdateListItem(True)
                break

    def HandleLocationSelectByList(self, item):
        """
        Handle a location being selected from the list
        """
        if self.UpdateFlag: return

        loc = item.reference
        loc.ensureVisible(xMargin=192, yMargin=192)
        self.scene.clearSelection()
        loc.setSelected(True)

    def HandleLocationToolTipAboutToShow(self, item):
        """
        Handle a location being hovered in the list
        """
        item.reference.UpdateListItem(True)

    def HandlePathSelectByList(self, item):
        """
        Handle a path node being selected
        """
        if self.UpdateFlag:
            return
        try:
            path_item = item.reference
        except Exception:
            return
        if path_item is None:
            return
        try:
            path_item.ensureVisible(xMargin=192, yMargin=192)
            self.scene.clearSelection()
            path_item.setSelected(True)
        except RuntimeError:
            return

    def HandlePathToolTipAboutToShow(self, item):
        """
        Handle a path node being hovered in the list
        """
        item.reference.UpdateListItem(True)

    def HandleCommentSelectByList(self, item):
        """
        Handle a comment being selected
        """
        for comment in globals_.Area.comments:
            if comment.listitem == item:
                comment.ensureVisible(xMargin=192, yMargin=192)
                self.scene.clearSelection()
                comment.setSelected(True)
                break

    def HandleCommentToolTipAboutToShow(self, item):
        """
        Handle a comment being hovered in the list
        """
        for comment in globals_.Area.comments:
            if comment.listitem == item:
                comment.UpdateListItem(True)
                break

    def HandleLocPosChange(self, loc, oldx, oldy, x, y):
        """
        Handle the location being dragged
        """
        if loc == self.selObj:
            if oldx == x and oldy == y: return
            self.locationEditor.setLocation(loc)
            SetDirty()

        loc.UpdateListItem()
        self.levelOverview.update()
        self._CollabMarkItemHot(loc)
        self.CollabQueueLocationUpsert(loc, is_add=False)
        try:
            if getattr(globals_, 'EventLinksShown', False):
                self.UpdateEventLinks()
        except Exception:
            pass

    def HandleLocSizeChange(self, loc, width, height):
        """
        Handle the location being resized
        """
        if loc == self.selObj:
            self.locationEditor.setLocation(loc)
            SetDirty()

        loc.UpdateListItem()
        self.levelOverview.update()
        self._CollabMarkItemHot(loc)
        self.CollabQueueLocationUpsert(loc, is_add=False)
        try:
            if getattr(globals_, 'EventLinksShown', False):
                self.UpdateEventLinks()
        except Exception:
            pass

    def UpdateModeInfo(self):
        """
        Change the info in the currently visible panel
        """
        self.UpdateFlag = True

        if self.spriteEditorDock.isVisible():
            obj = self.selObj
            self.spriteDataEditor.setSprite(obj.type, initial_data=obj.spritedata)
        elif self.entranceEditorDock.isVisible():
            self.entranceEditor.setEntrance(self.selObj)
        elif self.pathEditorDock.isVisible():
            self.pathEditor.setPath(self.selObj)
        elif self.locationEditorDock.isVisible():
            self.locationEditor.setLocation(self.selObj)

        self.UpdateFlag = False

    def _SchedulePipeEntranceLinkRefresh(self, delay=0):
        if getattr(self, '_pipeEntranceLinkRefreshPending', False):
            return

        self._pipeEntranceLinkRefreshPending = True

        def refresh():
            self._pipeEntranceLinkRefreshPending = False
            try:
                self.UpdatePipeEntranceLinks()
            except TypeError as exc:
                err = str(exc)
                if ('QPen' in err) and ('NoneType' in err):
                    QtCore.QTimer.singleShot(50, lambda: self._SchedulePipeEntranceLinkRefresh(0))
                    return
                raise
            except Exception:
                pass

        QtCore.QTimer.singleShot(delay, refresh)

    def _CreateFallbackPipeEntranceLinkItem(self, ent, dest, is_pipe_link):
        try:
            start_rect = ent.sceneBoundingRect()
            end_rect = dest.sceneBoundingRect()
            start = start_rect.center()
            end = end_rect.center()
        except Exception:
            start = QtCore.QPointF(float(getattr(ent, 'objx', 0)), float(getattr(ent, 'objy', 0)))
            end = QtCore.QPointF(float(getattr(dest, 'objx', 0)), float(getattr(dest, 'objy', 0)))

        line = QtWidgets.QGraphicsLineItem(QtCore.QLineF(start, end))
        color = QtGui.QColor(0, 200, 255, 220) if is_pipe_link else QtGui.QColor(255, 170, 0, 220)
        pen = QtGui.QPen(
            color,
            3,
            QtCore.Qt.PenStyle.SolidLine,
            QtCore.Qt.PenCapStyle.RoundCap,
            QtCore.Qt.PenJoinStyle.RoundJoin,
        )
        line.setPen(pen)
        try:
            line.setZValue(-100000)
        except Exception:
            pass
        return line

    def UpdatePipeEntranceLinks(self):
        try:
            items = getattr(self, '_pipeEntranceLinkItems', None)
            if items:
                for it in items:
                    try:
                        self.scene.removeItem(it)
                    except Exception:
                        pass
        finally:
            self._pipeEntranceLinkItems = []

        area = getattr(globals_, 'Area', None)
        if area is None:
            return
        if not getattr(globals_, 'PipeLinksShown', True):
            return

        current_area = int(getattr(area, 'areanum', 0) or 0)
        entrances = [e for e in getattr(area, 'entrances', []) if e is not None]
        by_id = {int(e.entid): e for e in entrances}

        pipe_types = {3, 4, 5, 6, 16, 17, 18, 19}
        door_types = {2, 27}

        from levelitems import PipeEntranceLinkItem

        for ent in entrances:
            is_pipe_link = ent.enttype in pipe_types
            is_door_link = ent.enttype in door_types
            if not (is_pipe_link or is_door_link):
                continue
            if int(ent.destentrance) == 0:
                continue

            # `Dest. area = 0` means "current area".
            # So if area is not explicitly set, show the link inside the
            # currently opened area.
            dest_area = int(getattr(ent, 'destarea', 0) or 0)
            if dest_area == 0:
                dest_area = current_area
            if dest_area != current_area:
                continue

            dest = by_id.get(int(ent.destentrance))
            if dest is None:
                continue
            if is_pipe_link and dest.enttype not in pipe_types:
                continue
            if is_door_link and dest.enttype not in door_types:
                continue

            try:
                li = PipeEntranceLinkItem(ent, dest, ent.destentrance)
            except TypeError as exc:
                err = str(exc)
                if ('QPen' in err) and ('NoneType' in err):
                    li = self._CreateFallbackPipeEntranceLinkItem(ent, dest, is_pipe_link)
                else:
                    raise
            self.scene.addItem(li)
            self._pipeEntranceLinkItems.append(li)

    def UpdateEventLinks(self):
        try:
            items = getattr(self, '_eventLinkItems', None)
            if items:
                for it in items:
                    try:
                        self.scene.removeItem(it)
                    except Exception:
                        pass
        finally:
            self._eventLinkItems = []

        area = getattr(globals_, 'Area', None)
        if area is None:
            return
        if not getattr(globals_, 'EventLinksShown', False):
            return

        sprites = [s for s in getattr(area, 'sprites', []) if s is not None]
        if not sprites:
            return

        try:
            from spriteeditor import SpriteEditorWidget
            decoder = SpriteEditorWidget.PropertyDecoder()
        except Exception:
            return

        triggering_map = {}
        for spr in sprites:
            try:
                type_ = int(getattr(spr, 'type', -1))
                if not 0 <= type_ < globals_.NumSprites:
                    continue
                sdef = globals_.Sprites[type_]
                data = spr.spritedata
            except Exception:
                continue

            for field in getattr(sdef, 'fields', []):
                if field[0] not in (1, 2):
                    continue
                if field[-1] != 'Triggering Event':
                    continue
                try:
                    val = int(decoder.retrieve(data, field[2]))
                except Exception:
                    continue
                if val == 0:
                    continue
                triggering_map.setdefault(val, []).append(spr)

        locations = [l for l in getattr(area, 'locations', []) if l is not None]
        location_by_id = {}
        for loc in locations:
            try:
                location_by_id[int(getattr(loc, 'id', 0))] = loc
            except Exception:
                pass

        from levelitems import EventLinkItem, LocationLinkItem

        for spr in sprites:
            try:
                type_ = int(getattr(spr, 'type', -1))
                if not 0 <= type_ < globals_.NumSprites:
                    continue
                sdef = globals_.Sprites[type_]
                data = spr.spritedata
            except Exception:
                continue

            loc_ids = set()
            for field in getattr(sdef, 'fields', []):
                if field[0] not in (1, 2):
                    continue
                if field[-1] != 'Location':
                    continue
                try:
                    val = int(decoder.retrieve(data, field[2]))
                except Exception:
                    continue
                if val != 0:
                    loc_ids.add(val)
            for loc_id in loc_ids:
                loc = location_by_id.get(int(loc_id))
                if loc is None:
                    continue
                li = LocationLinkItem(spr, loc, loc_id)
                self.scene.addItem(li)
                self._eventLinkItems.append(li)

            if not triggering_map:
                continue

            targets = set()
            for field in getattr(sdef, 'fields', []):
                if field[0] not in (1, 2):
                    continue
                if field[-1] != 'Target Event':
                    continue
                try:
                    val = int(decoder.retrieve(data, field[2]))
                except Exception:
                    continue
                if val != 0:
                    targets.add(val)

            for ev in targets:
                for dst in triggering_map.get(ev, []):
                    if dst is spr:
                        continue
                    li = EventLinkItem(spr, dst, ev)
                    self.scene.addItem(li)
                    self._eventLinkItems.append(li)

    def UpdateRotationControllerPreviews(self):
        try:
            items = getattr(self, '_rotationControllerPreviewItems', None)
            if items:
                for it in items:
                    try:
                        self.scene.removeItem(it)
                    except Exception:
                        pass
        finally:
            self._rotationControllerPreviewItems = []

        area = getattr(globals_, 'Area', None)
        if area is None:
            return

        sprites = [s for s in getattr(area, 'sprites', []) if s is not None]
        if not sprites:
            return

        try:
            from spriteeditor import SpriteEditorWidget
            decoder = SpriteEditorWidget.PropertyDecoder()
        except Exception:
            return

        try:
            sdef = globals_.Sprites[149]
        except Exception:
            return

        bits_mode = None
        bits_distance = None
        bits_dir = None
        bits_rotid = None
        for f in getattr(sdef, 'fields', []):
            if f[0] == 1 and f[1] == 'Rotation Mode':
                bits_mode = f[2]
            elif f[0] == 1 and f[1] == 'Event Triggered - Rotation Distance':
                bits_distance = f[2]
            elif f[0] == 5 and f[1] == 'Spins Counter-Clockwise' and f[2] == 'Spins Clockwise':
                bits_dir = f[3]
            elif f[0] == 2 and f[1] == 'Rotation ID':
                bits_rotid = f[2]

        if bits_mode is None or bits_distance is None or bits_dir is None or bits_rotid is None:
            return

        import math
        from levelitems import RotationControllerPreviewItem

        controlled_types = {252, 253, 254, 255, 256}

        for ctrl in sprites:
            if int(getattr(ctrl, 'type', -1)) != 149:
                continue

            data = getattr(ctrl, 'spritedata', None)
            if data is None:
                continue

            try:
                mode = int(decoder.retrieve(data, bits_mode))
                rotation_id = int(decoder.retrieve(data, bits_rotid))
                distance = int(decoder.retrieve(data, bits_distance))
                dir_val = int(decoder.retrieve(data, bits_dir))
            except Exception:
                continue

            if mode != 0 or rotation_id == 0 or distance == 0:
                continue

            theta = distance * 22.5
            if dir_val == 0:
                theta = -theta

            pivot = ctrl.sceneBoundingRect().center()
            rad = math.radians(theta)
            c = math.cos(rad)
            s = math.sin(rad)

            rects = []
            for spr in sprites:
                if int(getattr(spr, 'type', -1)) not in controlled_types:
                    continue
                try:
                    if int(getattr(spr, 'spritedata', b'')[5]) != rotation_id:
                        continue
                except Exception:
                    continue

                r = spr.sceneBoundingRect()
                p = r.center()
                vx = p.x() - pivot.x()
                vy = p.y() - pivot.y()
                nx = (vx * c) - (vy * s)
                ny = (vx * s) + (vy * c)

                nr = QtCore.QRectF(r)
                nr.moveCenter(QtCore.QPointF(pivot.x() + nx, pivot.y() + ny))
                rects.append(nr)

            if not rects:
                continue

            preview_color = QtGui.QColor(150, 150, 150, 190)
            preview_fill = QtGui.QColor(150, 150, 150, 60)
            it = RotationControllerPreviewItem(ctrl, rects, color=preview_color, fill=preview_fill)
            self.scene.addItem(it)
            self._rotationControllerPreviewItems.append(it)

    def BeginPipeEntranceLink(self, ent):
        self._pipeEntranceLinkSource = ent

    def CancelPipeEntranceLink(self):
        self._pipeEntranceLinkSource = None

    def HandlePipeEntranceLinkClick(self, target):
        source = getattr(self, '_pipeEntranceLinkSource', None)
        self._pipeEntranceLinkSource = None

        if source is None or target is None or source is target:
            return

        try:
            from undo import ModifyInstanceUndoAction, SimultaneousUndoAction
        except Exception:
            ModifyInstanceUndoAction = None
            SimultaneousUndoAction = None

        before_src = source.instanceDef(source)
        before_dst = target.instanceDef(target)

        current_area = int(getattr(globals_.Area, 'areanum', 0) or 0)

        source.destentrance = int(target.entid)
        source.destarea = current_area
        target.destentrance = int(source.entid)
        target.destarea = current_area

        try:
            source.UpdateTooltip()
            source.UpdateListItem()
            source.update()
        except Exception:
            pass
        try:
            target.UpdateTooltip()
            target.UpdateListItem()
            target.update()
        except Exception:
            pass

        SetDirty()
        self.CollabQueueMetaUpdate()
        self.UpdatePipeEntranceLinks()

        try:
            if self.selObj in (source, target):
                self.UpdateModeInfo()
        except Exception:
            pass

        if (
            ModifyInstanceUndoAction is not None
            and SimultaneousUndoAction is not None
            and not self.UndoRedoInProgress
            and not self.collabApplyingRemote
            and not self.collabApplyingRemoteHistory
            and not getattr(self, 'collabSwitchingArea', False)
            and not globals_.DirtyOverride
        ):
            after_src = source.instanceDef(source)
            after_dst = target.instanceDef(target)
            acts = []
            try:
                acts.append(ModifyInstanceUndoAction(before_src, after_src, collab_id=self._CollabEnsureItemId(source)))
            except Exception:
                acts.append(ModifyInstanceUndoAction(before_src, after_src))
            try:
                acts.append(ModifyInstanceUndoAction(before_dst, after_dst, collab_id=self._CollabEnsureItemId(target)))
            except Exception:
                acts.append(ModifyInstanceUndoAction(before_dst, after_dst))
            self.undoStack.addAction(SimultaneousUndoAction(acts))

    def BeginEventLink(self, sprite):
        try:
            from spriteeditor import SpriteEditorWidget
            decoder = SpriteEditorWidget.PropertyDecoder()
        except Exception:
            return

        if sprite is None:
            return
        if not 0 <= int(getattr(sprite, 'type', -1)) < globals_.NumSprites:
            return

        sdef = globals_.Sprites[sprite.type]
        data = sprite.spritedata

        value = None
        for field in getattr(sdef, 'fields', []):
            if field[0] not in (1, 2):
                continue
            if field[-1] != 'Target Event':
                continue
            try:
                value = int(decoder.retrieve(data, field[2]))
            except Exception:
                value = None
            break

        if value is None:
            self._eventLinkSource = None
            return
        red_coin_value = None
        if int(getattr(sprite, 'type', -1)) == 156:
            for field in getattr(sdef, 'fields', []):
                if field[0] not in (1, 2):
                    continue
                if field[-1] != 'Red Coin':
                    continue
                try:
                    red_coin_value = int(decoder.retrieve(data, field[2]))
                except Exception:
                    red_coin_value = None
                break

        if red_coin_value is None:
            self._eventLinkSource = (sprite, value)
        else:
            self._eventLinkSource = (sprite, value, red_coin_value)

    def CancelEventLink(self):
        self._eventLinkSource = None

    def BeginRotationLink(self, sprite):
        try:
            from spriteeditor import SpriteEditorWidget
            decoder = SpriteEditorWidget.PropertyDecoder()
        except Exception:
            return

        if sprite is None:
            return
        if int(getattr(sprite, 'type', -1)) not in (96, 149):
            return
        if not 0 <= int(getattr(sprite, 'type', -1)) < globals_.NumSprites:
            return

        sdef = globals_.Sprites[sprite.type]
        data = sprite.spritedata

        value = None
        for field in getattr(sdef, 'fields', []):
            if field[0] not in (1, 2):
                continue
            if field[-1] != 'Rotation' or field[1] != 'Rotation ID':
                continue
            try:
                value = int(decoder.retrieve(data, field[2]))
            except Exception:
                value = None
            break

        if value is None:
            self._rotationLinkSource = None
            return

        self._rotationLinkSource = (sprite, value)

    def CancelRotationLink(self):
        self._rotationLinkSource = None

    def BeginLocationLink(self, sprite):
        try:
            from spriteeditor import SpriteEditorWidget
            decoder = SpriteEditorWidget.PropertyDecoder()
        except Exception:
            return

        if sprite is None:
            return
        if not 0 <= int(getattr(sprite, 'type', -1)) < globals_.NumSprites:
            return

        sdef = globals_.Sprites[sprite.type]

        bits = None
        for field in getattr(sdef, 'fields', []):
            if field[0] not in (1, 2):
                continue
            if field[-1] != 'Location':
                continue
            if field[1] == 'Location ID':
                bits = field[2]
                break
            if bits is None:
                bits = field[2]

        if bits is None:
            self._locationLinkSource = None
            return

        self._locationLinkSource = (sprite, bits)

    def CancelLocationLink(self):
        self._locationLinkSource = None

    def HandleLocationLinkClick(self, location):
        source = getattr(self, '_locationLinkSource', None)
        self._locationLinkSource = None

        if source is None or location is None:
            return

        sprite, bits = source
        try:
            location_id = int(getattr(location, 'id', 0))
        except Exception:
            location_id = 0

        try:
            from spriteeditor import SpriteEditorWidget
            decoder = SpriteEditorWidget.PropertyDecoder()
        except Exception:
            return

        before_def = sprite.instanceDef(sprite)
        before_data = sprite.spritedata
        try:
            after_data = decoder.insertvalue(before_data, int(location_id), bits)
        except Exception:
            return

        if after_data == before_data:
            return

        sprite.spritedata = after_data
        sprite.UpdateListItem()
        sprite.UpdateDynamicSizing()
        try:
            self.spriteList.updateSprite(sprite)
        except Exception:
            pass

        SetDirty()
        try:
            self.CollabQueueSpriteUpdate(sprite, include_data=True)
        except Exception:
            pass

        try:
            if self.selObj is sprite and self.spriteEditorDock.isVisible():
                self.UpdateModeInfo()
        except Exception:
            pass

        try:
            if getattr(globals_, 'EventLinksShown', False):
                self.UpdateEventLinks()
        except Exception:
            pass

        if not self.UndoRedoInProgress and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False) and not globals_.DirtyOverride:
            try:
                from undo import ModifyInstanceUndoAction
                after_def = sprite.instanceDef(sprite)
                self.undoStack.addOrExtendAction(ModifyInstanceUndoAction(before_def, after_def, collab_id=getattr(sprite, '_collab_id', None)))
            except Exception:
                pass

    def HandleRotationLinkClick(self, target):
        source = getattr(self, '_rotationLinkSource', None)
        self._rotationLinkSource = None

        if source is None:
            return

        src_sprite, rotation_id = source
        targets = []
        try:
            for it in getattr(self, 'CurrentSelection', []) or []:
                if isinstance(it, SpriteItem) and it is not src_sprite:
                    targets.append(it)
        except Exception:
            targets = []
        if target is not None and isinstance(target, SpriteItem) and target is not src_sprite and target not in targets:
            targets.append(target)
        if not targets:
            return

        try:
            from spriteeditor import SpriteEditorWidget
            decoder = SpriteEditorWidget.PropertyDecoder()
        except Exception:
            return

        changed_defs = []
        for tgt in targets:
            if not 0 <= int(getattr(tgt, 'type', -1)) < globals_.NumSprites:
                continue

            sdef = globals_.Sprites[tgt.type]
            bits = None
            for field in getattr(sdef, 'fields', []):
                if field[0] not in (1, 2):
                    continue
                if field[-1] == 'Rotation' and field[1] == 'Rotation ID':
                    bits = field[2]
                    break
            if bits is None:
                continue

            before_data = tgt.spritedata
            try:
                after_data = decoder.insertvalue(before_data, int(rotation_id), bits)
            except Exception:
                continue
            if after_data == before_data:
                continue

            before_def = tgt.instanceDef(tgt)
            tgt.spritedata = after_data
            tgt.UpdateListItem()
            tgt.UpdateDynamicSizing()
            try:
                self.spriteList.updateSprite(tgt)
            except Exception:
                pass
            try:
                self.CollabQueueSpriteUpdate(tgt, include_data=True)
            except Exception:
                pass
            after_def = tgt.instanceDef(tgt)
            changed_defs.append((tgt, before_def, after_def))

        if not changed_defs:
            return

        SetDirty()

        try:
            self.UpdateRotationControllerPreviews()
        except Exception:
            pass

        try:
            if self.spriteEditorDock.isVisible() and any(self.selObj is t for (t, _, _) in changed_defs):
                self.UpdateModeInfo()
        except Exception:
            pass

        if not self.UndoRedoInProgress and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False) and not globals_.DirtyOverride:
            try:
                from undo import ModifyInstanceUndoAction, SimultaneousUndoAction
                if len(changed_defs) == 1:
                    tgt, before_def, after_def = changed_defs[0]
                    self.undoStack.addOrExtendAction(ModifyInstanceUndoAction(before_def, after_def, collab_id=getattr(tgt, '_collab_id', None)))
                else:
                    acts = []
                    for tgt, before_def, after_def in changed_defs:
                        acts.append(ModifyInstanceUndoAction(before_def, after_def, collab_id=getattr(tgt, '_collab_id', None)))
                    self.undoStack.addAction(SimultaneousUndoAction(acts))
            except Exception:
                pass

    def HandleEventLinkClick(self, target):
        source = getattr(self, '_eventLinkSource', None)
        self._eventLinkSource = None

        if source is None:
            return

        src_sprite = source[0]
        event_id = source[1]
        red_coin_id = source[2] if len(source) >= 3 else None
        targets = []
        try:
            for it in getattr(self, 'CurrentSelection', []) or []:
                if isinstance(it, SpriteItem) and it is not src_sprite:
                    targets.append(it)
        except Exception:
            targets = []
        if target is not None and isinstance(target, SpriteItem) and target is not src_sprite and target not in targets:
            targets.append(target)
        if not targets:
            return

        try:
            from spriteeditor import SpriteEditorWidget
            decoder = SpriteEditorWidget.PropertyDecoder()
        except Exception:
            return

        changed_defs = []
        for tgt in targets:
            if not 0 <= int(getattr(tgt, 'type', -1)) < globals_.NumSprites:
                continue

            sdef = globals_.Sprites[tgt.type]
            triggering_bits = []
            red_coin_bits = []
            for field in getattr(sdef, 'fields', []):
                if field[0] not in (1, 2):
                    continue
                if field[-1] == 'Triggering Event':
                    triggering_bits.append(field[2])
                elif red_coin_id is not None and field[-1] == 'Red Coin':
                    red_coin_bits.append(field[2])
            if not triggering_bits:
                continue

            before_data = tgt.spritedata
            after_data = before_data
            before_def = None

            bits = triggering_bits[0] if len(triggering_bits) == 1 else None
            if bits is None:
                for b in triggering_bits:
                    try:
                        val = int(decoder.retrieve(before_data, b))
                    except Exception:
                        continue
                    if val == 0:
                        bits = b
                        break
            if bits is None:
                continue

            old_event_id = None
            try:
                old_event_id = int(decoder.retrieve(before_data, bits))
            except Exception:
                old_event_id = None

            try:
                after_data = decoder.insertvalue(after_data, int(event_id), bits)
            except Exception:
                continue

            new_event_id = None
            try:
                new_event_id = int(decoder.retrieve(after_data, bits))
            except Exception:
                new_event_id = None

            if red_coin_id is not None and red_coin_bits:
                rb = red_coin_bits[0]
                old_red_coin_id = None
                try:
                    old_red_coin_id = int(decoder.retrieve(before_data, rb))
                except Exception:
                    old_red_coin_id = None
                try:
                    after_data = decoder.insertvalue(after_data, int(red_coin_id), rb)
                except Exception:
                    after_data = after_data
                new_red_coin_id = None
                try:
                    new_red_coin_id = int(decoder.retrieve(after_data, rb))
                except Exception:
                    new_red_coin_id = None
                if old_red_coin_id is not None and new_red_coin_id == int(red_coin_id) and old_red_coin_id != int(red_coin_id):
                    used = getattr(globals_.Area, 'sprite_idtypes', {}).get('Red Coin')
                    if isinstance(used, dict):
                        used[int(red_coin_id)] = used.get(int(red_coin_id), 0) + 1
                        if old_red_coin_id in used:
                            if used.get(old_red_coin_id, 0) <= 1:
                                try:
                                    del used[old_red_coin_id]
                                except Exception:
                                    pass
                            else:
                                used[old_red_coin_id] -= 1

            if old_event_id is not None and new_event_id == int(event_id) and old_event_id != int(event_id):
                used = getattr(globals_.Area, 'sprite_idtypes', {}).get('Triggering Event')
                if isinstance(used, dict):
                    used[int(event_id)] = used.get(int(event_id), 0) + 1
                    if old_event_id in used:
                        if used.get(old_event_id, 0) <= 1:
                            try:
                                del used[old_event_id]
                            except Exception:
                                pass
                        else:
                            used[old_event_id] -= 1

            if after_data == before_data:
                continue

            before_def = tgt.instanceDef(tgt)
            tgt.spritedata = after_data
            tgt.UpdateListItem()
            tgt.UpdateDynamicSizing()
            try:
                self.spriteList.updateSprite(tgt)
            except Exception:
                pass
            try:
                self.CollabQueueSpriteUpdate(tgt, include_data=True)
            except Exception:
                pass
            after_def = tgt.instanceDef(tgt)
            changed_defs.append((tgt, before_def, after_def))

        if not changed_defs:
            return

        SetDirty()

        try:
            if self.spriteEditorDock.isVisible() and any(self.selObj is t for (t, _, _) in changed_defs):
                self.UpdateModeInfo()
        except Exception:
            pass

        try:
            self.UpdateEventLinks()
        except Exception:
            pass

        if not self.UndoRedoInProgress and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not getattr(self, 'collabSwitchingArea', False) and not globals_.DirtyOverride:
            try:
                from undo import ModifyInstanceUndoAction, SimultaneousUndoAction
                if len(changed_defs) == 1:
                    tgt, before_def, after_def = changed_defs[0]
                    self.undoStack.addOrExtendAction(ModifyInstanceUndoAction(before_def, after_def, collab_id=getattr(tgt, '_collab_id', None)))
                else:
                    acts = []
                    for tgt, before_def, after_def in changed_defs:
                        acts.append(ModifyInstanceUndoAction(before_def, after_def, collab_id=getattr(tgt, '_collab_id', None)))
                    self.undoStack.addAction(SimultaneousUndoAction(acts))
            except Exception:
                pass

    def PositionHovered(self, x, y):
        """
        Handle a position being hovered in the view
        """
        self.collabLastMouseScenePos = QtCore.QPointF(float(x), float(y))
        self._MaybeBroadcastCollabCursorState(self.collabLastMouseScenePos)
        info = ''
        hovereditems = self.scene.items(QtCore.QPointF(x, y))
        hovered = None
        type_zone = ZoneItem
        type_peline = PathEditorLineItem
        try:
            from levelitems import PipeEntranceLinkItem
            type_pipe_link = PipeEntranceLinkItem
        except Exception:
            type_pipe_link = None
        for item in hovereditems:
            hover = item.hover if hasattr(item, 'hover') else True
            if type_pipe_link is not None:
                skip = isinstance(item, (type_zone, type_peline, type_pipe_link))
            else:
                skip = isinstance(item, (type_zone, type_peline))
            if (not skip) and hover:
                hovered = item
                break

        if hovered is not None:
            if isinstance(hovered, ObjectItem):  # Object
                info = globals_.trans.string('Statusbar', 23, '[width]', hovered.width, '[height]', hovered.height, '[xpos]',
                                    hovered.objx, '[ypos]', hovered.objy, '[layer]', hovered.layer, '[type]',
                                    hovered.type, '[tileset]', hovered.tileset + 1)
            elif isinstance(hovered, SpriteItem):  # Sprite
                info = globals_.trans.string('Statusbar', 24, '[name]', hovered.name, '[xpos]', hovered.objx, '[ypos]',
                                    hovered.objy)
            elif isinstance(hovered, SLib.AuxiliaryItem):  # Sprite (auxiliary thing) (treat it like the actual sprite)
                info = globals_.trans.string('Statusbar', 24, '[name]', hovered.parentItem().name, '[xpos]',
                                    hovered.parentItem().objx, '[ypos]', hovered.parentItem().objy)
            elif isinstance(hovered, EntranceItem):  # Entrance
                info = globals_.trans.string('Statusbar', 25, '[name]', hovered.name, '[xpos]', hovered.objx, '[ypos]',
                                    hovered.objy, '[dest]', hovered.destination)
            elif isinstance(hovered, LocationItem):  # Location
                info = globals_.trans.string('Statusbar', 26, '[id]', int(hovered.id), '[xpos]', int(hovered.objx), '[ypos]',
                                    int(hovered.objy), '[width]', int(hovered.width), '[height]', int(hovered.height))
            elif isinstance(hovered, PathItem):  # Path
                info = globals_.trans.string('Statusbar', 27, '[path]', hovered.pathid, '[node]', hovered.nodeid, '[xpos]',
                                    hovered.objx, '[ypos]', hovered.objy)
            elif isinstance(hovered, CommentItem):  # Comment
                info = globals_.trans.string('Statusbar', 33, '[xpos]', hovered.objx, '[ypos]', hovered.objy, '[text]',
                                    hovered.OneLineText())

        self.posLabel.setText(
            globals_.trans.string('Statusbar', 28, '[objx]', int(x / 24), '[objy]', int(y / 24), '[sprx]', int(x / 1.5),
                         '[spry]', int(y / 1.5)))
        self.hoverLabel.setText(info)

    def _CanHandleCollabPKeyEvent(self, event):
        modifiers = event.modifiers()
        blocked = (
            QtCore.Qt.KeyboardModifier.ControlModifier
            | QtCore.Qt.KeyboardModifier.AltModifier
            | QtCore.Qt.KeyboardModifier.MetaModifier
        )
        if modifiers & blocked:
            return False
        focus = QtWidgets.QApplication.focusWidget()
        text_types = (
            QtWidgets.QLineEdit,
            QtWidgets.QTextEdit,
            QtWidgets.QPlainTextEdit,
            QtWidgets.QAbstractSpinBox,
            QtWidgets.QComboBox,
        )
        if isinstance(focus, text_types):
            return False
        return True

    def _HandleCollabPKeyPress(self, event):
        if not self._CanHandleCollabPKeyEvent(event):
            return False
        mode = self._NormalizeCollabCursorDisplayMode(getattr(self, 'collabCursorDisplayMode', COLLAB_CURSOR_DISPLAY_ALWAYS))
        if mode == COLLAB_CURSOR_DISPLAY_NEVER:
            event.accept()
            return True

        if mode == COLLAB_CURSOR_DISPLAY_ON_P:
            self.collabCursorPKeyHeld = True
            try:
                if hasattr(self, 'view') and self.view is not None:
                    self.view.viewport().update()
            except Exception:
                pass

        if not event.isAutoRepeat():
            self.HandleCollabPingShortcut()
        event.accept()
        return True

    def keyPressEvent(self, event):
        """
        Handles key press events for the main window if needed
        """
        if event.key() == Qt.Key.Key_P and self._HandleCollabPKeyPress(event):
            return

        qpt_keys = (
            Qt.Key.Key_Escape.value,
            Qt.Key.Key_Q.value,
            Qt.Key.Key_S.value,
            Qt.Key.Key_C.value,
            Qt.Key.Key_E.value,
            Qt.Key.Key_F.value,
            Qt.Key.Key_D.value,
            Qt.Key.Key_F1.value,
            Qt.Key.Key_F2.value,
            Qt.Key.Key_F3.value,
        )
        if event.key() in qpt_keys:
            qpt_tab_active = False
            if hasattr(self, 'qpt_palette') and self.qpt_palette and hasattr(self, 'creationTabs'):
                for i in range(self.creationTabs.count()):
                    if self.creationTabs.widget(i) == self.qpt_palette:
                        qpt_tab_active = (self.creationTabs.currentIndex() == i)
                        break

            if qpt_tab_active:
                try:
                    qpt_funcs = getattr(globals_, 'qpt_functions', None)
                    if qpt_funcs and qpt_funcs.get('key_press') and qpt_funcs['key_press'](event.key()):
                        event.accept()
                        return
                except Exception as e:
                    print(f"[Reggie] Error forwarding key to QPT: {e}")

        if event.key() == Qt.Key.Key_Delete or event.key() == Qt.Key.Key_Backspace:
            sel = self.scene.selectedItems()

            if sel:

                self.SelectionUpdateFlag = True
                try:
                    from undo import CreateOrDeleteInstanceUndoAction, PathNodeUndoAction, ZoneUndoAction, SimultaneousUndoAction
                    acts = []
                    meta = None
                    for obj in sel:
                        if isinstance(obj, ObjectItem):
                            try:
                                self._CollabEnsureItemId(obj)
                            except Exception:
                                pass
                            acts.append(CreateOrDeleteInstanceUndoAction('delete', obj.instanceDef(obj), collab_id=getattr(obj, '_collab_id', None), extra={'z': obj.zValue()}))
                        elif isinstance(obj, SpriteItem):
                            try:
                                self._CollabEnsureItemId(obj)
                            except Exception:
                                pass
                            acts.append(CreateOrDeleteInstanceUndoAction('delete', obj.instanceDef(obj), collab_id=getattr(obj, '_collab_id', None)))
                        elif isinstance(obj, EntranceItem):
                            acts.append(CreateOrDeleteInstanceUndoAction('delete', obj.instanceDef(obj), collab_id=self._CollabEnsureItemId(obj)))
                        elif isinstance(obj, LocationItem):
                            acts.append(CreateOrDeleteInstanceUndoAction('delete', obj.instanceDef(obj), collab_id=self._CollabEnsureItemId(obj)))
                        elif isinstance(obj, CommentItem):
                            acts.append(CreateOrDeleteInstanceUndoAction('delete', obj.instanceDef(obj), collab_id=self._CollabEnsureItemId(obj)))
                        elif isinstance(obj, PathItem):
                            try:
                                path = obj.path
                                node_collab_id = self._CollabEnsureItemId(obj)
                                idx = path.get_index(obj)
                                node_data = path.get_node_data(idx)
                                loops = path.get_loops()
                                acts.append(PathNodeUndoAction('delete', int(path._id), int(idx), node_data, bool(loops), node_collab_id=node_collab_id))
                            except Exception:
                                pass
                        elif isinstance(obj, ZoneItem):
                            if meta is None:
                                meta = self.BuildCollabMetaState()
                            zone_data = None
                            for zd in meta.get('zones', []) if isinstance(meta, dict) else []:
                                if isinstance(zd, dict) and int(zd.get('id', -999)) == int(getattr(obj, 'id', -999)):
                                    zone_data = zd
                                    break
                            if zone_data is not None:
                                acts.append(ZoneUndoAction('delete', zone_data))
                    if acts and not self.UndoRedoInProgress and not self.collabApplyingRemote and not self.collabApplyingRemoteHistory and not globals_.DirtyOverride:
                        if len(acts) == 1:
                            self.undoStack.addAction(acts[0])
                        else:
                            self.undoStack.addAction(SimultaneousUndoAction(acts))
                except Exception:
                    pass

                for obj in sel:
                    obj.delete()
                    obj.setSelected(False)
                    self.scene.removeItem(obj)

                SetDirty()
                event.accept()
                self.levelOverview.update()
                self.SelectionUpdateFlag = False
                self.ChangeSelectionHandler()
                return

        self.levelOverview.update()

        QtWidgets.QMainWindow.keyPressEvent(self, event)

    def keyReleaseEvent(self, event):
        if (
            event.key() == Qt.Key.Key_P
            and self._CanHandleCollabPKeyEvent(event)
            and self._NormalizeCollabCursorDisplayMode(getattr(self, 'collabCursorDisplayMode', COLLAB_CURSOR_DISPLAY_ALWAYS)) == COLLAB_CURSOR_DISPLAY_NEVER
        ):
            event.accept()
            return
        if (
            event.key() == Qt.Key.Key_P
            and not event.isAutoRepeat()
            and self._NormalizeCollabCursorDisplayMode(getattr(self, 'collabCursorDisplayMode', COLLAB_CURSOR_DISPLAY_ALWAYS)) == COLLAB_CURSOR_DISPLAY_ON_P
            and getattr(self, 'collabCursorPKeyHeld', False)
        ):
            self.collabCursorPKeyHeld = False
            try:
                if hasattr(self, 'view') and self.view is not None:
                    self.view.viewport().update()
            except Exception:
                pass
            event.accept()
            return
        QtWidgets.QMainWindow.keyReleaseEvent(self, event)

    def HandleAreaOptions(self):
        """
        Pops up the options for Area Dialogue
        """
        dlg = AreaOptionsDialog()
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        SetDirty()

        # Sprites
        # Extracting the sprite id from the sprite name is hacky, but it works.
        globals_.Area.loaded_sprites = set(int(desc.split(']')[0][1:]) for desc in dlg.LoadedSpritesTab.auto_model.stringList())
        globals_.Area.force_loaded_sprites = set(int(desc.split(']')[0][1:]) for desc in dlg.LoadedSpritesTab.custom_model.stringList())

        # Settings
        globals_.Area.timeLimit = dlg.LoadingTab.timer.value() - 200
        globals_.Area.startEntrance = dlg.LoadingTab.entrance.value()
        globals_.Area.toadHouseType = dlg.LoadingTab.toadHouseType.currentIndex()
        globals_.Area.wrapFlag = dlg.LoadingTab.wrap.isChecked()
        globals_.Area.creditsFlag = dlg.LoadingTab.credits.isChecked()
        globals_.Area.faceLeftFlag = dlg.LoadingTab.faceLeft.isChecked()
        globals_.Area.unkFlag1 = dlg.LoadingTab.unk1.isChecked()
        globals_.Area.unkFlag2 = dlg.LoadingTab.unk2.isChecked()
        globals_.Area.unkVal1 = dlg.LoadingTab.unk3.value()
        globals_.Area.unkVal2 = dlg.LoadingTab.unk4.value()

        # Tilesets
        for idx, fname in enumerate(dlg.TilesetsTab.values()):

            if fname in ('', None):
                fname = ''
            elif fname.startswith(globals_.trans.string('AreaDlg', 16)):
                fname = fname[len(globals_.trans.string('AreaDlg', 17, '[name]', '')):]

            if idx == 0:
                globals_.Area.tileset0 = fname
            elif idx == 1:
                globals_.Area.tileset1 = fname
            elif idx == 2:
                globals_.Area.tileset2 = fname
            else:
                globals_.Area.tileset3 = fname

            if fname != '':
                LoadTileset(idx, fname)
            else:
                UnloadTileset(idx)

        self.objPicker.LoadFromTilesets()
        self.objAllTab.setCurrentIndex(0)
        self.objAllTab.setTabEnabled(0, (globals_.Area.tileset0 != ''))
        self.objAllTab.setTabEnabled(1, (globals_.Area.tileset1 != ''))
        self.objAllTab.setTabEnabled(2, (globals_.Area.tileset2 != ''))
        self.objAllTab.setTabEnabled(3, (globals_.Area.tileset3 != ''))

        for layer in globals_.Area.layers:
            for obj in layer:
                obj.updateObjCache()

        self.scene.update()
        if hasattr(self, 'qpt_palette') and self.qpt_palette is not None:
            try:
                self.qpt_palette.reset()
            except Exception as e:
                print(f"[QPT] Warning: Could not reset QPT: {e}")
        if hasattr(self, 'collabManager') and self.collabManager.mode is not None and not self.collabApplyingRemote:
            self.CollabQueueMetaUpdate()

    def HandleZones(self):
        """
        Pops up the options for Zone dialog
        """
        LoadZoneThemes()

        dlg = ZonesDialog()
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            self.levelOverview.update()
            return

        SetDirty()

        # resync the zones
        items = self.scene.items()
        func_ii = isinstance
        type_zone = ZoneItem

        for item in items:
            if func_ii(item, type_zone):
                self.scene.removeItem(item)

        globals_.Area.zones = []

        for i, tab in enumerate(dlg.zoneTabs):
            z = tab.zoneObj
            z.id = i
            z.UpdateTitle()
            globals_.Area.zones.append(z)
            self.scene.addItem(z)

            z.objx = common.clamp(16, 24560, tab.Zone_xpos.value())
            z.objy = common.clamp(16, 12272, tab.Zone_ypos.value())
            z.width = min(24560 - z.objx, tab.Zone_width.value())
            z.height = min(12272 - z.objy, tab.Zone_height.value())

            z.prepareGeometryChange()
            z.UpdateRects()
            z.setPos(z.objx * 1.5, z.objy * 1.5)

            z.modeldark = tab.Zone_modeldark.currentIndex()
            z.terraindark = tab.Zone_terraindark.currentIndex()
            z.cammode = tab.Zone_cammodezoom.modeButtonGroup.checkedId()
            z.camzoom = tab.Zone_cammodezoom.screenSizes.currentIndex()
            z.camtrack = tab.Zone_direction.currentIndex()

            if tab.Zone_yrestrict.isChecked():
                z.mpcamzoomadjust = tab.Zone_mpzoomadjust.value()
            else:
                z.mpcamzoomadjust = 15

            z.visibility = 0

            if tab.Zone_vspotlight.isChecked():
                z.visibility |= 1 << 4
            if tab.Zone_vfulldark.isChecked():
                z.visibility |= 1 << 5

            z.visibility |= tab.Zone_visibility.currentIndex()

            z.yupperbound = tab.Zone_yboundup.value()
            z.ylowerbound = tab.Zone_ybounddown.value()
            z.yupperbound2 = tab.Zone_yboundup2.value()
            z.ylowerbound2 = tab.Zone_ybounddown2.value()
            z.yupperbound3 = tab.Zone_yboundup3.value()
            z.ylowerbound3 = tab.Zone_ybounddown3.value()

            z.music = tab.Zone_musicid.value()
            z.sfxmod = tab.Zone_sfx.currentIndex() << 4
            if tab.Zone_boss.isChecked():
                z.sfxmod |= 1

        for spr in globals_.Area.sprites:
            spr.ImageObj.positionChanged()

        self.actions['backgrounds'].setEnabled(len(globals_.Area.zones) > 0)
        self.levelOverview.update()
        if hasattr(self, 'collabManager') and self.collabManager.mode is not None and not self.collabApplyingRemote:
            self.CollabQueueMetaUpdate()

    # Handles setting the backgrounds
    def HandleBG(self):
        """
        Pops up the Background settings Dialog
        """
        dlg = BGDialog()
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        SetDirty()
        for tab, z in zip(dlg.BGTabs, globals_.Area.zones):
            # first index: BGA/BGB
            # second index: X/Y
            z.XpositionA = tab.pos_boxes[0][0].value()
            z.YpositionA = -tab.pos_boxes[0][1].value()
            z.XpositionB = tab.pos_boxes[1][0].value()
            z.YpositionB = -tab.pos_boxes[1][1].value()

            z.XscrollA = tab.scroll_boxes[0][0].currentIndex()
            z.YscrollA = tab.scroll_boxes[0][1].currentIndex()
            z.XscrollB = tab.scroll_boxes[1][0].currentIndex()
            z.YscrollB = tab.scroll_boxes[1][1].currentIndex()

            z.ZoomA = tab.zoom_boxes[0].currentIndex()
            z.ZoomB = tab.zoom_boxes[1].currentIndex()

            z.bg1A = tab.hex_boxes[0][0].value()
            z.bg2A = tab.hex_boxes[0][1].value()
            z.bg3A = tab.hex_boxes[0][2].value()

            z.bg1B = tab.hex_boxes[1][0].value()
            z.bg2B = tab.hex_boxes[1][1].value()
            z.bg3B = tab.hex_boxes[1][2].value()
        if hasattr(self, 'collabManager') and self.collabManager.mode is not None and not self.collabApplyingRemote:
            self.CollabQueueMetaUpdate()

    def HandleScreenshot(self):
        """
        Takes a screenshot of the entire level and saves it
        """

        dlg = ScreenCapChoiceDialog()
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        screenshot_type = dlg.zoneCombo.currentIndex()
        hide_background = dlg.hide_background.isChecked()
        do_save = dlg.save_img.isChecked()

        if do_save:
            fn = QtWidgets.QFileDialog.getSaveFileName(self,
                globals_.trans.string('FileDlgs', 3), 'untitled.png',
                globals_.trans.string('FileDlgs', 4) + ' (*.png)')[0]

            if fn == '':
                return

        if screenshot_type == 0:  # Current view
            screenshot_rect = QtCore.QRect(QtCore.QPoint(), self.view.size())
            renderer = self.view
            ss_img = QtGui.QImage(screenshot_rect.size(), QtGui.QImage.Format.Format_ARGB32)

        else:
            if screenshot_type == 1:  # All zones together
                screenshot_rect = QtCore.QRectF()

                for z in globals_.Area.zones:
                    screenshot_rect |= z.ZoneRect

            else:  # One specific zone
                screenshot_rect = globals_.Area.zones[screenshot_type - 2].ZoneRect

            # Map the zone rects to the scene coordinate system
            screenshot_rect = (QtGui.QTransform() * 1.5).mapRect(screenshot_rect)
            # Add 40 pixels of padding on all sides
            screenshot_rect += QtCore.QMarginsF(40, 40, 40, 40)
            # Make sure the rectangle doesn't go out of bounds
            screenshot_rect &= QtCore.QRectF(0, 0, 1024 * 24, 512 * 24)

            renderer = self.scene
            ss_img = QtGui.QImage(screenshot_rect.size().toSize(), QtGui.QImage.Format.Format_ARGB32)

        ss_img.fill(Qt.GlobalColor.transparent)
        ss_painter = QtGui.QPainter(ss_img)

        if hide_background:
            # Remove the background
            brush = self.scene.backgroundBrush()
            style = brush.style()
            brush.setStyle(Qt.BrushStyle.NoBrush)
            self.scene.setBackgroundBrush(brush)

            # Render
            renderer.render(ss_painter, source=screenshot_rect)

            # Restore the background
            brush.setStyle(style)
            self.scene.setBackgroundBrush(brush)

        else:
            # Render with background
            renderer.render(ss_painter, source=screenshot_rect)

        ss_painter.end()

        if do_save:
            ss_img.save(fn, 'PNG', 50)
        else:
            globals_.app.clipboard().setImage(ss_img)

    @staticmethod
    def HandleDiagnostics():
        """
        Checks the level for any obvious problems and provides options to autofix them
        """
        DiagnosticToolDialog().exec()

    def HandleCameraProfiles(self):
        """Pops up the options for camera profiles"""
        dlg = CameraProfilesDialog()
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        camprofiles = []
        for row in range(dlg.list.count()):
            item = dlg.list.item(row)
            camprofiles.append(item.data(QtCore.Qt.ItemDataRole.UserRole))

        globals_.Area.camprofiles = camprofiles
        SetDirty()


def main():
    """
    Main startup function for Reggie
    """

    # set High-DPI-Displays-related attributes before creating an application
    # QtGui.QGuiApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    if hasattr(QtGui.QGuiApplication, 'setHighDpiScaleFactorRoundingPolicy'):
        QtGui.QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Round)

    qt_gl = os.environ.get("REGGIE_QT_GL")
    if qt_gl == "desktop":
        QtGui.QGuiApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    elif qt_gl == "gles":
        QtGui.QGuiApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseOpenGLES)
    elif qt_gl == "software":
        QtGui.QGuiApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)

    # Create an application
    globals_.app = QtWidgets.QApplication(sys.argv)

    global _qpt_functions, QPT_AVAILABLE
    try:
        from quickpaint.reggie_hook import (
            initialize_qpt,
            handle_qpt_mouse_press,
            handle_qpt_mouse_move,
            handle_qpt_mouse_release,
            handle_qpt_key_press,
            update_qpt_outline,
            get_tile_type,
            show_hotkey_overlay,
            hide_hotkey_overlay,
        )
        from quickpaint.reggie_hook import _get_qpt_hook
        _qpt_functions = {
            'initialize': initialize_qpt,
            'press': handle_qpt_mouse_press,
            'move': handle_qpt_mouse_move,
            'release': handle_qpt_mouse_release,
            'key_press': handle_qpt_key_press,
            'get_hook': _get_qpt_hook,
            'update_outline': update_qpt_outline,
            'get_tile_type': get_tile_type,
            'show_overlay': show_hotkey_overlay,
            'hide_overlay': hide_hotkey_overlay,
        }
        globals_.qpt_functions = _qpt_functions
    except Exception as e:
        print(f"[QPT] Warning: Could not import QPT functions: {e}")
        traceback.print_exc()
        QPT_AVAILABLE = False
        globals_.qpt_functions = None

    dump_after = os.environ.get("REGGIE_DUMP_STACK_AFTER")
    if dump_after:
        try:
            import faulthandler
            faulthandler.enable()
            faulthandler.dump_traceback_later(int(dump_after), repeat=True)
        except Exception:
            pass

    # Go to the script path
    path = module_path()
    if path is not None:
        os.chdir(path)

    # Create backup of settings
    if os.path.isfile('settings.ini'):
        from shutil import copy2
        copy2('settings.ini', 'settings.ini.bak')
        del copy2

    # Try to get the last commit id - if it failed, we're in a build.
    import subprocess

    try:
        commit_id = subprocess.check_output(["git", "describe", "--always"], stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL).decode('utf-8').strip()
        globals_.ReggieVersionShort += "-" + commit_id
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    del subprocess

    # Load the settings
    globals_.settings = QtCore.QSettings('settings.ini', QtCore.QSettings.Format.IniFormat)

    # Check the version and set the UI style to Fusion by default
    if setting("ReggieVersion") is None:
        setSetting("ReggieVersion", globals_.ReggieVersionFloat)
        setSetting('uiStyle', "Fusion")

    # 4.0 -> oldest version with settings.ini compatible with the current version
    if setting("ReggieVersion") < 4.0 or setting("ReggieVersion") > globals_.ReggieVersionFloat:
        warningBox = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.NoIcon, 'Unsupported settings file', 'Your settings.ini file is unsupported. Please remove it and run Reggie again.')
        warningBox.exec()
        sys.exit(1)

    # Load the translation (needs to happen first)
    LoadTranslation()

    # Check if required files are missing
    if FilesAreMissing():
        sys.exit(1)

    # Load some requirements for spritelib
    LoadTheme()
    LoadOverrides()

    from ui_scaling import ScalingManager
    globals_.scalingManager = ScalingManager()
    globals_.scalingManager.loadSettings()

    # Initialise spritelib
    SLib.OutlineColor = globals_.theme.color('smi')
    SLib.main()
    sprites.LoadBasics()

    # Load the gamedef (including sprite image path, for which we need spritelib)
    LoadGameDef(setting('LastGameDef'), prompt_for_stage_path=False)

    qpt_tilesets = _register_quickpaint_tileset_overrides()
    if qpt_tilesets:
        print(f"[QPT] Registered {len(qpt_tilesets)} prepared quickpaint tileset(s)")

    # Load remaining requirements
    LoadActionsLists()
    LoadNumberFont()
    SetAppStyle()
    globals_.scalingManager.applyScaling()

    # Set the default window icon (used for random popups and stuff)
    globals_.app.setWindowIcon(GetIcon('reggie'))
    globals_.app.setApplicationDisplayName('Reggie! Next %s' % globals_.ReggieVersionShort)

    gt = setting('GridType')

    if gt not in ('checker', 'grid'):
        globals_.GridType = None
    else:
        globals_.GridType = gt

    globals_.CollisionsShown = setting('ShowCollisions', False)
    globals_.RealViewEnabled = setting('RealViewEnabled', True)
    globals_.ObjectsFrozen = setting('FreezeObjects', False)
    globals_.SpritesFrozen = setting('FreezeSprites', False)
    globals_.EntrancesFrozen  = setting('FreezeEntrances', False)
    globals_.LocationsFrozen = setting('FreezeLocations', False)
    globals_.PathsFrozen = setting('FreezePaths', False)
    globals_.CommentsFrozen = setting('FreezeComments', False)
    globals_.SpritesShown = setting('ShowSprites', True)
    globals_.SpriteImagesShown = setting('ShowSpriteImages', True)
    globals_.LocationsShown = setting('ShowLocations', True)
    globals_.CommentsShown = setting('ShowComments', True)
    globals_.PathsShown = setting('ShowPaths', True)
    globals_.PipeLinksShown = setting('ShowPipeLinks', True)
    globals_.EventLinksShown = setting('ShowEventLinks', False)
    globals_.DrawEntIndicators = setting('ZoneEntIndicators', False)
    globals_.BoundsDrawn = setting('ZoneBoundIndicators', False)
    globals_.ResetDataWhenHiding = setting('ResetDataWhenHiding', False)
    globals_.HideResetSpritedata = setting('HideResetSpritedata', False)
    globals_.EnablePadding = setting('EnablePadding', False)
    globals_.PaddingLength = int(setting('PaddingLength', 0))
    globals_.PlaceObjectsAtFullSize = setting('PlaceObjectsAtFullSize', True)
    globals_.InsertPathNode = setting('InsertPathNode', False)
    globals_.CollabNickname = str(setting('CollabNickname', getattr(globals_, 'CollabNickname', 'Player')) or 'Player')
    globals_.CollabHighlightColor = normalize_collab_color(setting('CollabHighlightColor', getattr(globals_, 'CollabHighlightColor', DEFAULT_COLLAB_HIGHLIGHT_COLOR)))
    globals_.CollabCursorDisplayMode = str(setting('CollabCursorDisplayMode', getattr(globals_, 'CollabCursorDisplayMode', COLLAB_CURSOR_DISPLAY_ALWAYS)) or COLLAB_CURSOR_DISPLAY_ALWAYS)
    SLib.RealViewEnabled = globals_.RealViewEnabled

    # Check to see if we have anything saved
    autofile = setting('AutoSaveFilePath')
    autofiledata = setting('AutoSaveFileData', 'x')
    if autofile is not None and autofiledata != 'x':
        result = AutoSavedInfoDialog(autofile).exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            globals_.RestoredFromAutoSave = True
            globals_.AutoSavePath = autofile
            globals_.AutoSaveData = bytes(autofiledata)
        else:
            setSetting('AutoSaveFilePath', None)
            setSetting('AutoSaveFileData', 'x')

    # Create and show the main window
    globals_.mainWindow = ReggieWindow()
    globals_.mainWindow.__init2__()  # fixes bugs
    if getattr(globals_.mainWindow, '_startupExitRequested', False):
        globals_.mainWindow.deleteLater()
        globals_.app.deleteLater()
        sys.exit(0)
    globals_.mainWindow.show()

    if '-generatestringsxml' in sys.argv:
        globals_.trans.generateXML()

    exitcodesys = globals_.app.exec()
    globals_.app.deleteLater()
    sys.exit(exitcodesys)


if __name__ == '__main__': main()
