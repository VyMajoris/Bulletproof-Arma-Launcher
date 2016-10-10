# Bulletproof Arma Launcher
# Copyright (C) 2016 Sascha Ebert
# Copyright (C) 2016 Lukasz Taczuk
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

import shutil
import os
import time
import torrent_utils

from kivy.logger import Logger
from sync import finder

# Everything in this file is run IN A DIFFERENT PROCESS!
# To communicate with the main program, you have to use the resolve(), reject()
# and progress() calls of the message queue!


class MessageHandler(object):
    def __init__(self, message_queue, owner):
        self.message_queue = message_queue
        self.owner = owner
        self.callbacks = {}

    def handle_messages(self):
        """Handle all incoming messages passed from the main process."""

        message = self.message_queue.receive_message()
        if not message:
            return

        command = message.get('command')
        params = message.get('params')

        try:
            callback = self.callbacks[command]
        except KeyError:
            Logger.error('MessageHandler: unknown command "{}" for object {}'.format(command, self.owner))

        if params is None:
            return callback()
        else:
            return callback(params)

    def send_message(self, command, params=None):
        data = {
            'special_message': {
                'command': command,
                'params': params
            }
        }
        self.message_queue.progress(data)

    def bind_message(self, command, callback):
        self.callbacks[command] = callback

class Preparer(object):
    def __init__(self, message_queue, mods):
        self.message_queue = message_queue
        self.mods = mods
        self.force_termination = False

        self.message_handler = MessageHandler(message_queue, self)
        self.message_handler.bind_message('terminate', self.on_terminate_message)
        self.message_handler.bind_message('mod_reuse', self.on_mod_reuse_message)

    def _get_mod_by_foldername(self, foldername):
        for mod in self.mods:
            if mod.foldername == foldername:
                return mod

        raise KeyError('Could not find mod {}'.format(foldername))

    def on_terminate_message(self):
        Logger.info('TorrentSyncer wants termination')
        self.force_termination = True

    def on_mod_reuse_message(self, params):
        mod_name = params['mod_name']
        mod = self._get_mod_by_foldername(mod_name)
        dest_location = os.path.join(mod.parent_location, mod_name)

        if params['action'] == 'use':
            Logger.info('Message: Mod reuse: symlink, mod: {}'.format(mod_name))
            self.result_queue.progress({'msg': 'Creating junction for mod {}...'.format(mod_name), 'log': []}, 0)
            torrent_utils.create_symlink(dest_location, params['location'])
            self.result_queue.progress({'msg': 'Creating junction for mod {} finished!'.format(mod_name), 'log': []}, 0)

            self.missing_mods.remove(mod_name)
            self.missing_responses -= 1

        elif params['action'] == 'copy':
            Logger.info('Message: Mod reuse: copy, mod: {}'.format(mod_name))
            self.result_queue.progress({'msg': 'Copying mod {}...'.format(mod_name), 'log': []}, 0)
            shutil.copytree(params['location'], dest_location)
            self.result_queue.progress({'msg': 'Copying mod {} finished!'.format(mod_name), 'log': []}, 0)

            self.missing_mods.remove(mod_name)
            self.missing_responses -= 1

        elif params['action'] == 'ignore':
            Logger.info('Message: Mod reuse: ignore, mod: {}'.format(mod_name))
            self.missing_responses -= 1

        # elif params['action'] == 'ignore_all':
        #    self.missing_mods = set()

        else:
            raise Exception('Unknown mod_reuse action: {}'.format(params['action']))

    def reject(self, msg):
        self.message_queue.reject({'msg': msg})

    def find_mods_and_ask(self, location=None):
        """UNUSED!!!"""
        self.result_queue.progress({'msg': 'Searching for missing mods on disk...',
                                    'log': [],
                                    }, 0)

        # Find potential mods on disk.
        found_mods = finder.find_mods(self.missing_mods, location)

        # For missing mods that have been found
        for mod_name in found_mods:
            self.result_queue.progress({'msg': 'Found possible places for {}'.format(mod_name),
                                        'log': [],
                                        'mod_found_action': {
                                            'mod_name': mod_name,
                                            'locations': found_mods[mod_name]
                                        }
                                        }, 0)

    def request_directory_to_search(self):
        mods_names = [mod.foldername for mod in self.missing_mods]
        self.message_handler.send_message('missing_mods', mods_names)
        self.missing_responses += 1

    def run(self):
        """First, ensure all mods directories that already exist are reachable
        and remove all those that are not (bad symlink).
        Then repeatedly ask the user to find missing mods until all mods are
        found or marked to be downloaded from the internet.
        """

        self.missing_mods = set()
        Logger.info('Preparer: Checking for missing mods.')

        try:
            for mod in self.mods:
                torrent_utils.prepare_mod_directory(mod.parent_location, mod.foldername)

                # If directory does not exist
                if not os.path.lexists(mod.get_full_path()):
                    self.missing_mods.add(mod)

        except torrent_utils.AdminRequiredError as ex:
            self.reject(ex.args[0])
            return


        self.missing_responses = 0
        while self.missing_mods:
            if not self.missing_responses:  # All responses have been processed
                # Print message about missing mods and ask for directory to search
                self.request_directory_to_search()

            self.message_handler.handle_messages()

            if self.force_termination:
                self.reject('Termination requested by parent')
                return

            time.sleep(0.1)

        self.reject('Dummy reject message')
        # self.message_queue.resolve()


def prepare_all(message_queue, mods):
    preparer = Preparer(message_queue, mods)
    preparer.run()