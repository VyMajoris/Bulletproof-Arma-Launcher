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

import json
import os

class MetadataFile(object):
    """File that contains metadata about mods and is located in the root directory of each mod"""
    file_name = '.tacbf_meta'
    _encoding = 'utf-8'

    def __init__(self, dir_path):
        super(MetadataFile, self).__init__()

        self.dir_path = os.path.realpath(dir_path)
        self.data = {}

    def get_file_name(self):
        """Returns the full path to the metadata file"""
        return os.path.join(self.dir_path, self.file_name)

    def read_data(self, ignore_read_errors=False):
        """Open the file and read its data to an internal variable"""
        try:
            with open(self.get_file_name(), 'rb') as file_handle:
                self.data = json.load(file_handle, encoding=MetadataFile._encoding)
        except:
            if ignore_read_errors:
                pass
            else:
                raise

    def write_data(self):
        """Open the file and write the contents of the internal data variable to the file"""
        with open(self.get_file_name(), 'wb') as file_handle:
            json.dump(self.data, file_handle, ensure_ascii=False, encoding=MetadataFile._encoding, indent=2)

    def set_version(self, version):
        self.data['version'] = version

    def get_version(self):
        return self.data.setdefault('version', "0")

    def set_torrent_resume_data(self, data):
        self.data['torrent_resume_data'] = data

    def get_torrent_resume_data(self):
        return self.data.setdefault('torrent_resume_data', None)
