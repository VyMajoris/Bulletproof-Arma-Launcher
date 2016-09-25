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

import multiprocessing
from multiprocessing import Queue

import kivy
import kivy.app  # To keep PyDev from complaining
import os
import sys
import textwrap
import time
import torrent_utils

from config import config
from datetime import datetime
from distutils.version import LooseVersion
from kivy.logger import Logger
from third_party import teamspeak
from utils.devmode import devmode
from utils.primitive_git import get_git_sha1_auto
from utils.process import Para
from utils.requests_wrapper import download_url, DownloadException
from utils.testtools_compat import _format_exc_info
from sync import integrity
from sync.mod import Mod
from sync.torrentsyncer import TorrentSyncer


def parse_timestamp(ts):
    """
    Parse a timestamp that looks like this:
    YYYY-MM-DD_Epoch

    we parse Epoch in utc time. After that make sure to use it like utc
    """
    s = ts.split('_')
    stamp = s[1]
    return datetime.utcfromtimestamp(float(stamp))


def create_timestamp(epoch):
    """
    Create a timestamp that looks like this:
    YYYY-MM-DD_Epoch
    """
    return datetime.fromtimestamp(int(epoch)).strftime('%Y-%m-%d_') + str(int(epoch))


def _make_torrent(messagequeue, launcher_basedir, mods):
    """Create torrents from mods on the disk."""

    files_created = []
    # announces = ['http://{}/announce.php'.format(config.domain)]
    announces = ['http://5.79.83.193:2710/announce']
    web_seeds = ['http://{}{}/'.format(config.domain, config.web_seeds_path)]

    counter = 0
    for mod in mods:
        counter += 1
        if mod.up_to_date:
            continue

        output_file = '{}-{}.torrent'.format(mod.foldername, create_timestamp(time.time()))
        output_path = os.path.join(launcher_basedir, output_file)
        comment = '{} dependency on mod {}'.format(config.launcher_name, mod.foldername)
        directory = os.path.join(mod.parent_location, mod.foldername)

        messagequeue.progress({'msg': 'Creating file: {}'.format(output_file)}, counter / len(mods))
        file_created = torrent_utils.create_torrent(directory, announces, output_path, comment, web_seeds)
        files_created.append(file_created)
        file_created_dir = os.path.dirname(file_created)

    if files_created:
        from utils import browser
        browser.open_hyperlink(file_created_dir)

    messagequeue.resolve({'msg': 'Torrents created: {}'.format(len(files_created))})


def _get_mod_descriptions(para):
    # WARNING: This methods gets called in a different process
    """
    helper function to get the moddescriptions from the server

    this function is ment be used threaded or multiprocesses, you have
    to pass in a queue
    """
    para.progress({'msg': 'Downloading mod descriptions'})

    domain = devmode.get_launcher_domain(default=config.domain)
    metadata_path = devmode.get_metadata_path(default=config.metadata_path)
    url = 'http://{}{}'.format(domain, metadata_path)

    try:
        res = download_url(domain, url, timeout=10)
    except DownloadException as ex:
        para.reject({'msg': 'Downloading metadata: {}'.format(ex.args[0])})


    if res.status_code == 404:
        message = textwrap.dedent('''\
            Metadata could not be downloaded from the master server.
            Reason: file not found on the server (HTTP 404).

            This may be because the mods are updated on the server right now.
            Please try again in a few minutes.
            ''')
        para.reject({'msg': message})

    elif res.status_code != 200:
        message = textwrap.dedent('''\
            Metadata could not be downloaded from the master server.
            HTTP error code: {}

            Contact the master server owner to fix this issue.
            '''.format(unicode(res.status_code)))
        para.reject({'msg': message})

    else:
        try:
            data = res.json()
        except ValueError:
            Logger.error('ModManager: Failed to parse mods descriptions json!')
            message = textwrap.dedent('''
                Failed to parse metadata received from the master server.

                Contact the server owner to fix this issue.
                '''.format(unicode(res.status_code)))
            para.reject({'msg': message})

        # Protection in case autoupdate is messed up and we have to force a manual update
        protocol = '1.0'
        required_protocol = data.get('protocol')
        if not required_protocol or LooseVersion(protocol) < LooseVersion(required_protocol):
            error_message = 'This launcher is out of date! You won\'t be able to download mods until you update to the latest version!'
            Logger.error(error_message)
            para.reject({'msg': error_message})
            return ''

    para.resolve({'msg': 'Downloading mods descriptions finished',
                  'data': data})

    return data


def convert_metadata_to_mod(md, torrent_url_prefix):
    # TODO: This should be a constructor of the Mod class
    # parse timestamp
    tsstr = md.get('torrent-timestamp')
    md['torrent-timestamp'] = parse_timestamp(tsstr)
    md['torrent_url'] = "{}{}-{}.torrent".format(torrent_url_prefix,
                                                 md['foldername'],
                                                 tsstr)

    mod = Mod.fromDict(md)

    return mod


def get_launcher_description(para, launcher_basedir, metadata):
    domain = devmode.get_launcher_domain(default=config.domain)
    torrents_path = devmode.get_torrents_path(default=config.torrents_path)
    torrent_url_prefix = 'http://{}{}/'.format(domain, torrents_path)

    if 'launcher' not in metadata:
        return None

    launcher = metadata['launcher']
    launcher_mod = convert_metadata_to_mod(launcher, torrent_url_prefix)
    launcher_mod.parent_location = launcher_basedir

    return launcher_mod


def process_description_data(para, data, launcher_moddir):
    domain = devmode.get_launcher_domain(default=config.domain)
    torrents_path = devmode.get_torrents_path(default=config.torrents_path)
    torrent_url_prefix = 'http://{}{}/'.format(domain, torrents_path)
    mods = []

    for md in data['mods']:
        mod = convert_metadata_to_mod(md, torrent_url_prefix)
        mod.parent_location = launcher_moddir
        mods.append(mod)

        Logger.debug('ModManager: Got mods descriptions: ' + repr(md))

    return mods


def _prepare_and_check(messagequeue, launcher_moddir, launcher_basedir, mod_descriptions_data):
    # WARNING: This methods gets called in a different process
    launcher = get_launcher_description(messagequeue, launcher_basedir, mod_descriptions_data)
    mod_list = process_description_data(messagequeue, mod_descriptions_data, launcher_moddir)

    # Debug mode: decrease the number of mods to download
    mods_filter = devmode.get_mods_filter()
    if mods_filter:
        # Keep only the mods with names starting with any of the giver filters
        mod_list = [mod for mod in mod_list if any(mod.full_name.startswith(prefix) for prefix in mods_filter)]

    if launcher:
        # TODO: Perform a better check here. Should compare md5sum with actual launcher, etc...
        launcher.up_to_date = torrent_utils.is_complete_quick(launcher)

    # check if any of the the mods is installed with withSix
    messagequeue.progress({'msg': 'Checking mods'})
    for m in mod_list:
        m.up_to_date = torrent_utils.is_complete_quick(m)

    messagequeue.resolve({'msg': 'Checking mods finished', 'mods': mod_list, 'launcher': launcher})


def _tsplugin_wait_for_requirements(message_queue):
    """Wait until the user clicks OK and they close any running TeamSpeak instance.
    Ugly workaround but it works ;)
    During this time, any other messages save for 'terminate' are DISCARDED!
    As a workaround, return the message received (has to be then checked if
    equal to 'terminate')

    This is required because if we don't wait until the user does *something*
    and just show the UAC prompt, the prompt is going to timeout automatically
    after 2 minutes of inactivity.
    By requiring the user to click OK, we are ensuring that he actually is in
    front of the computer and can act upon the UAC prompt before it timeouts.
    """

    run_tsplugin_install_message = textwrap.dedent("""
        A mod containing a Teamspeak plugin has been downloaded or updated.

        The launcher will next prompt you and ask you for permission to install the
        plugin as Administrator.

        Close TeamSpeak if it is running to continue with the installation.
        """)

    message_queue.progress({'msg': 'Installing TeamSpeak plugin...',
                            'tsplugin_request_action': True,
                            'message_box': {
                                'text': run_tsplugin_install_message,
                                'title': 'Run TeamSpeak plugin installer!',
                                'markup': False
                            }
                            }, 1.0)

    Logger.info('TS installer: Waiting for the user to acknowledge TS plugin installation.')
    user_acknowledged = False
    while True:

        message = message_queue.receive_message()
        if not message:

            if user_acknowledged:
                if teamspeak.is_teamspeak_running():
                    message = 'Waiting for TeamSpeak to be closed. Close TeamSpeak to continue the installation!'
                    Logger.info('TS installer: {}'.format(message))
                    message_queue.progress({'msg': message}, 1.0)
                else:
                    break  # We can continue the installation

            time.sleep(0.5)
            continue

        command = message.get('command')

        if command == 'tsplugin_install_as_admin':
            Logger.info('TS installer: Received continue command. Installing TS plugin...')
            user_acknowledged = True

        if command == 'terminate':
            Logger.info('TS installer: Caller wants termination')
            return command

    return 'tsplugin_install_as_admin'


def _try_installing_teamspeak_plugins(message_queue, mod):
    """Install any Teamspeak plugins found in the mod files.
    In case of errors, show the appropriate message box.
    """
    # WARNING: This methods gets called in a different process

    def _show_message_box(message_queue, title, message, markup=True):
        message_queue.progress({'msg': 'Installing TeamSpeak plugin...',
                                'message_box': {
                                    'text': message,
                                    'title': title,
                                    'markup': markup
                                }
                                }, 1.0)

    ts3_plugin_files_to_process = []
    ts3_plugins_files = [file_path for file_path in mod.files_list if file_path.endswith('.ts3_plugin')]

    # Ignore Those files if everything is already installed
    for ts3_plugin_file in ts3_plugins_files:
        ts3_plugin_full_path = os.path.join(mod.parent_location, ts3_plugin_file)

        if not integrity.is_ts3_plugin_installed(ts3_plugin_full_path):
            ts3_plugin_files_to_process.append(ts3_plugin_file)

    if not ts3_plugin_files_to_process:
        return

    # Inform the user he is about to be asked to install TS plugins
    command = _tsplugin_wait_for_requirements(message_queue)
    if command == 'terminate':  # Workaround for termination request while waiting
        message_queue.reject({'details': 'Para was asked to terminate by the caller'})
        return False

    message_queue.progress({'msg': 'Waiting for permission to install the plugin as Administrator...'}, 1.0)

    for ts3_plugin_file in ts3_plugin_files_to_process:

        ts3_plugin_full_path = os.path.join(mod.parent_location, ts3_plugin_file)

        installation_failed_message = textwrap.dedent("""
            A mod containing a Teamspeak plugin has been downloaded or updated.

            Automatic installation of a Teamspeak plugin failed.


            To finish the installation of the Teamspeak plugin, you need to:

            Manually install the plugin: [ref={}][color=3572b0]>> Click here! <<[/color][/ref]
            """.format(ts3_plugin_full_path))

        run_admin_message = textwrap.dedent("""
            A mod containing a Teamspeak plugin has been downloaded or updated.

            In order to install the TeamSpeak plugin you need to run the
            plugin installer as Administrator.


            If you do not want to do that, you need to:

            Manually install the plugin: [ref={}][color=3572b0]>> Click here! <<[/color][/ref]
            """.format(ts3_plugin_full_path))

        #install_instance = teamspeak.install_unpackaged_plugin(path=path_ts3_addon)
        install_instance = teamspeak.install_ts3_plugin(path=ts3_plugin_full_path)

        if not install_instance:
            _show_message_box(message_queue, title='Run TeamSpeak plugin installer!', message=run_admin_message)
            #install_instance = teamspeak.install_unpackaged_plugin(path=path_ts3_addon)
            install_instance = teamspeak.install_ts3_plugin(path=ts3_plugin_full_path)

        if install_instance:
            exit_code = install_instance.wait()
            if exit_code != 0:
                _show_message_box(message_queue, title='TeamSpeak plugin installation failed!', message=installation_failed_message)
                message_queue.reject({'details': 'TeamSpeak plugin installation terminated with code: {}'.format(exit_code)})
                return False

        else:
            message_queue.reject({'msg': 'The user cancelled the TeamSpeak plugin installation.'})
            return False

    return True


def _sync_all(message_queue, mods, max_download_speed, max_upload_speed, seed):
    """Run syncers for all the mods in parallel and then their post-download hooks."""
    # WARNING: This methods gets called in a different process

    syncer = TorrentSyncer(message_queue, mods, max_download_speed, max_upload_speed)
    sync_ok = syncer.sync(force_sync=False, intend_to_seed=seed)  # Use force_sync to force full recheck of all the files' checksums

    # If we had an error or we're closing the launcher, don't call post_download_hooks
    if sync_ok is False or syncer.force_termination:
        # If termination has been forced, issue a resolve so no error is raised.
        # If not sync_ok, a reject has already been issued
        if syncer.force_termination:
            message_queue.resolve({'msg': 'Syncing stopped.'})
            return

    # Perform post-download hooks for updated mods
    for m in mods:
        # If the mod had to be updated and the download was performed successfully
        if not m.up_to_date and m.finished_hook_ran:
            # Will only fire up if mod == TFR
            if _try_installing_teamspeak_plugins(message_queue, m) == False:
                return  # Alpha undocumented feature: stop processing on a reject()

            message_queue.progress({'msg': '[%s] Mod synchronized.' % (m.foldername,),
                                    'workaround_finished': m.foldername}, 1.0)

    message_queue.resolve({'msg': 'Downloading mods finished.'})


def _protected_call(messagequeue, function, *args, **kwargs):
    try:
        return function(messagequeue, *args, **kwargs)
    except Exception:
        stacktrace = "".join(_format_exc_info(*sys.exc_info()))
        error = 'An error occurred in a subprocess:\nBuild: {}\n{}'.format(get_git_sha1_auto(), stacktrace).rstrip()
        messagequeue.reject({'details': error})


class ModManager(object):
    """docstring for ModManager"""
    def __init__(self):
        super(ModManager, self).__init__()
        self.para = None
        self.sync_para = None
        self.launcher_sync_para = None
        self.mods = []
        self.launcher = None
        self.settings = kivy.app.App.get_running_app().settings

    def download_mod_description(self):
        self.para = Para(_protected_call, (_get_mod_descriptions,), 'download_description')
        self.para.run()
        return self.para

    def make_torrent(self, mods):
        para = Para(_protected_call, (
            _make_torrent,
            self.settings.get('launcher_basedir'),
            mods
        ), 'make_torrent')
        para.run()
        return para

    def prepare_and_check(self, data):
        self.para = Para(_protected_call, (
            _prepare_and_check,
            self.settings.get('launcher_moddir'),
            self.settings.get('launcher_basedir'),
            data
        ), 'checkmods')
        self.para.then(self.on_prepare_and_check_resolve, None, None)
        self.para.run()
        return self.para

    def sync_all(self, seed):
        synced_elements = list(self.mods)
        if self.launcher:
            synced_elements.append(self.launcher)

        self.sync_para = Para(_protected_call, (
            _sync_all,
            synced_elements,
            self.settings.get('max_download_speed'),
            self.settings.get('max_upload_speed'),
            seed
        ), 'sync')
        self.sync_para.then(None, None, self.on_sync_all_progress)
        self.sync_para.run()
        return self.sync_para

    def sync_launcher(self, seed=False):
        self.launcher_sync_para = Para(_protected_call, (
            _sync_all,
            [self.launcher],
            self.settings.get('max_download_speed'),
            self.settings.get('max_upload_speed'),
            seed
        ), 'sync')
        self.launcher_sync_para.then(None, None, self.on_sync_all_progress)
        self.launcher_sync_para.run()
        return self.launcher_sync_para

    def on_prepare_and_check_resolve(self, data):
        Logger.info('ModManager: Got mods ' + repr(data['mods']))
        self.mods = data['mods']
        self.launcher = data['launcher']

    def on_sync_all_progress(self, data, progress):
        Logger.debug('ModManager: Sync progress ' + repr(data))
        # Todo: modlist could be a class of its own

        mod_synchronised = data.get('workaround_finished')
        if mod_synchronised:
            for mod in self.mods:
                if mod.foldername == mod_synchronised:
                    mod.up_to_date = True


if __name__ == '__main__':
    pass
