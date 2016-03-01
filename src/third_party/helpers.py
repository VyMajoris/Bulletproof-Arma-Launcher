# Tactical Battlefield Installer/Updater/Launcher
# Copyright (C) 2015 TacBF Installer Team.
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

import kivy.app
import os
import textwrap
import utils.system_processes

from kivy.logger import Logger
from third_party import teamspeak
from third_party.arma import Arma, ArmaNotInstalled, SteamNotInstalled
from view.messagebox import MessageBox


def check_requirements(verbose=True):
    """Check if all the required third party programs are installed in the system.
    Return True if the check passed.
    If verbose == true, show a message box in case of a failed check.
    """

    # TODO: move me to a better place
    try:
        teamspeak.check_installed()
    except teamspeak.TeamspeakNotInstalled:
        if verbose:
            message = textwrap.dedent('''
                Teamspeak does not seem to be installed.
                Having Teamspeak is required in order to play Tactical Battlefield.

                [ref=https://www.teamspeak.com/downloads][color=3572b0]Get Teamspeak here.[/color][/ref]

                Install Teamspeak and restart the launcher.
                ''')
            box = MessageBox(message, title='Teamspeak required!', markup=True)
            box.chain_open()

        return False

    try:
        Arma.get_installation_path()
    except ArmaNotInstalled:
        if verbose:
            message = textwrap.dedent('''
                Arma 3 does not seem to be installed.

                Having Arma 3 is required in order to play Tactical Battlefield.
                ''')
            box = MessageBox(message, title='Arma 3 required!', markup=True)
            box.chain_open()

        return False

    try:
        Arma.get_steam_exe_path()
    except SteamNotInstalled:
        if verbose:
            message = textwrap.dedent('''
                Steam does not seem to be installed.
                Having Steam is required in order to play Tactical Battlefield.

                [ref=http://store.steampowered.com/about/][color=3572b0]Get Steam here.[/color][/ref]

                Install Steam and restart the launcher.
                ''')
            box = MessageBox(message, title='Steam required!', markup=True)
            box.chain_open()

        return False

    return True


def run_the_game(mods):
    """Run the game with the right parameters.
    Handle the exceptions by showing an appropriate message on error.
    """

    Logger.info('Third party: Running the game')

    settings = kivy.app.App.get_running_app().settings
    mod_dir = settings.get('launcher_moddir')  # Why from there? This should be in mod.clientlocation but it isn't!

    mods_paths = []
    for mod in mods:
        mod_full_path = os.path.join(mod_dir, mod.foldername)
        mods_paths.append(mod_full_path)

    try:
        custom_args = []  # TODO: Make this user selectable
        _ = Arma.run_game(mod_list=mods_paths, custom_args=custom_args)
        # Note: although run_game returns an object, due to the way steam works,
        # it is unreliable. You never know whether it is the handle to Arma,
        # Steam or Arma's own launcher.
        # The only way to be sure is to analyze the process list :(

    except ArmaNotInstalled:
        text = "Arma 3 does not seem to be installed."
        no_arma_info = MessageBox(text, title='Arma not installed!')
        no_arma_info.chain_open()

    except SteamNotInstalled:
        text = "Steam does not seem to be installed."
        no_steam_info = MessageBox(text, title='Steam not installed!')
        no_steam_info.chain_open()

    except OSError as ex:
        text = "Error while launching Arma 3: {}.".format(ex.strerror)
        error_info = MessageBox(text, title='Error while launching Arma 3!')
        error_info.chain_open()

    arma_may_be_running(newly_launched=True)

ARMA_PROCESS_EVER_SEEN = False
ARMA_PROCESS_TERMINATED = True


def arma_may_be_running(newly_launched=False):
    """Check if arma3.exe *may be* running in the system.

    If newly_launched = True, the function will assume that the process may
    still be being launched and will return True until the exe is found and then
    disappears from the list of the processes.

    This function returns False if Arma 3 has been found to be running in the
    past and is not running anymore. This answer is 100% sure.

    If the function returns True it either means Arma is running now (100% sure)
    or that the process is now being launched but arma3.exe has not yet been
    seen in the system. In case there is a problem while running Arma, this
    function will return True forever.
    It is unknown at this point if there is some other reliable way of telling
    whether Arma is being launched or not.
    """

    global ARMA_PROCESS_EVER_SEEN
    global ARMA_PROCESS_TERMINATED

    if newly_launched:
        ARMA_PROCESS_EVER_SEEN = False
        ARMA_PROCESS_TERMINATED = False

    if ARMA_PROCESS_TERMINATED:  # If it is known the process has already terminated, don't iterate through processes
        return False

    is_process_running = utils.system_processes.program_running('arma3.exe')

    if is_process_running:
        ARMA_PROCESS_EVER_SEEN = True

    if ARMA_PROCESS_EVER_SEEN and not is_process_running:
        ARMA_PROCESS_TERMINATED = True
        return False

    return True