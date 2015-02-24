
import os
import requests
from datetime import datetime
import re
import tempfile
import shutil

from utils.sevenzfile import SevenZFile
from utils.process import Process

class HttpSyncer(object):
    """
    example syncer implementation

    the class basicly gets a message queue where it has to communicate
    its status back. This is done via an dict object looking like:

    msg = {
        status: 'downloading',
        progress: 0.5,
        kbpersec: 280
    }

    status:
        could be: 'downloading', 'finished', 'error'

    progress:
        percenttage progress from 0 to 1 as float
        or None to indicate that progressbar is not possible

    kbpersec:
        download rate in kilobyte per seconds or None if
        its not possible to calaculate the rate

    The reason for the message queue is multiprocessing
    """

    def __init__(self, result_queue, mod):
        """
        constructor

        Args:
            result_queue: the queue object where you can push the dict in
            mod: a mod instance you should care about

        """
        super(HttpSyncer, self).__init__()
        self.result_queue = result_queue
        self.mod = mod

    def _get_filename(self, response):

        if 'content-disposition' in response.headers:
            cd = response.headers['content-disposition']
            m = re.match(r'.*filename="(CBA_A3_RC4.7z)".*', cd)
            if m.group(1):
                return m.group(1)

        return 'unknown.dat'

    def sync(self):
        """
        implement this function

        do your download stuff here and report status over the message queue

        """
        print self.mod.name, self.mod


        # get file over http using requests stream mode
        response = requests.get(
            self.mod.downloadurl,
            stream=True
        )

        fname = self._get_filename(response)
        downloaddir = tempfile.mkdtemp(prefix='tacbflauncher')

        print "downloading ", self.mod.downloadurl, "to:", downloaddir

        # open file
        with open(os.path.join(downloaddir, fname), 'wb') as handle:

            # we can check the eventhandlers
            if not response.ok:
                 print 'response failed'

            start_time = datetime.now()
            length = float(response.headers['content-length'])
            downloaded = 0.0
            counter = 0

            # receive the response block by block
            for block in response.iter_content(1024):
                if not block:
                    break

                handle.write(block)
                downloaded = downloaded + 1024


                if counter >= 1000 and not downloaded < 1:
                    percent = downloaded / length
                    td = datetime.now() - start_time
                    kbpersec = (downloaded / 1024) / td.total_seconds()
                    print kbpersec

                    # here it reports back to the modmanager
                    self.result_queue.put({
                        'progress': percent,
                        'kbpersec': kbpersec,
                        'status': 'downloading'})

                    counter = 0

                counter += 1

        self.result_queue.put({
            'progress': 1.0,
            'kbpersec': 0,
            'status': 'finished'})


        zfile = SevenZFile(os.path.join(downloaddir, fname))
        zfile.extractall(downloaddir)

        shutil.move(os.path.join(downloaddir, self.mod.name), self.mod.clientlocation)
        shutil.rmtree(downloaddir)