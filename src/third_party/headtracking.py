# Tactical Battlefield Installer/Updater/Launcher
# Copyright (C) 2016 TacBF Installer Team.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

from __future__ import unicode_literals

import os
import subprocess
import utils.system_processes

from kivy.logger import Logger
from third_party import SoftwareNotInstalled
from utils import unicode_helpers
from utils.registry import Registry


class FaceTrackNoIRNotInstalled(SoftwareNotInstalled):
    pass


def get_faceTrackNoIR_path():
    """Get the path to FaceTrackNoIR installation."""

    try:
        key = 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\FaceTrackNoIR_is1'
        reg_val = Registry.ReadValueUserAndMachine(key, 'InstallLocation', True)

        Logger.info('FaceTrackNoIR: Install location: {}'.format(reg_val))

        path = os.path.join(reg_val, 'FaceTrackNoIR.exe')
        if not os.path.isfile(path):
            Logger.info('FaceTrackNoIR: Found install location but no expected exe file found: {}'.format(path))
            raise FaceTrackNoIRNotInstalled()

        return path

    except Registry.Error:
        raise FaceTrackNoIRNotInstalled()


def is_facetrackNoIR_running():
    """Check if there is a FaceTrackNoIR process already running."""
    return utils.system_processes.program_running('FaceTrackNoIR.exe')


def run_faceTrackNoIR():
    """Run faceTrackNoIR if installed and not already running."""

    try:
        faceTrackNoIR_path = get_faceTrackNoIR_path()

    except FaceTrackNoIRNotInstalled:
        return

    if is_facetrackNoIR_running():
        Logger.info('FaceTrackNoIR: FaceTrackNoIR found already running.')
        return

    Logger.info('FaceTrackNoIR: Running file: {}'.format(faceTrackNoIR_path))
    subprocess.Popen(unicode_helpers.u_to_fs_list([faceTrackNoIR_path]))