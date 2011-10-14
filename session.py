# Copyright (C) 2011 by Stacey Ell
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
import sys
sys.path.append('/home/sell/dev/libsre/src')

import libsre.python.functools as sre_ft
import time
import re
import operator
import logging
from twisted.internet import reactor, defer
import twisted.web.client
from twisted.python import failure
import libtorrent
from rarity.utils import serialize_torrent_metainfo, \
    serialize_torrent_status, serialize_torrent

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)
logger = logging.getLogger('ClientCore')
logger.setLevel(logging.INFO)

class TimeoutError(RuntimeError):
    pass

import os
class ResumeStorage(object):
    def __init__(self, basepath):
        self._basepath = basepath

    def __setitem__(self, infohash, entry):
        return self.get_saver(infohash)(entry)

    def get_saver(self, infohash):
        def saver(entry):
            ih = str(infohash)
            with open(os.path.join(self._basepath, ih), 'w') as f:
                f.write(libtorrent.bencode(entry))
        return saver

    def __getitem__(self, infohash):
        infohash = str(infohash)
        with open(os.path.join(self._basepath, infohash), 'r') as f:
            return libtorrent.bdecode(f.read())

class IStaticAlertHandler(object): pass # interface

class AbstractAlertDeferred(object):
    def __init__(self, match_func):
        self.match_func = match_func
        self.deferred = defer.Deferred()

    def match(self, alert):
        return self.match_func(alert)

class AlertDeferred(AbstractAlertDeferred):
    def __init__(self, match_func, expire_after=None):
        super(AlertDeferred, self).__init__(match_func)
        self.created_at = time.time()
        self.expire_after = expire_after or 600

    def is_expired(self):
        return (time.time() - self.created_at) > self.expire_after

def signature_match(*sig_args):
    def decorator(func):
        def decorated(*f_args):
            if not reduce(operator.and_, (
                    isinstance(a, b) for (a, b) in zip(f_args, sig_args))):
                return False
            return func(*f_args)
        return decorated
    return decorator

def maybe_handle(func):
    def decorated(self, infohash, *args, **kwargs):
        if isinstance(infohash, libtorrent.torrent_handle):
            infohash = str(infohash.info_hash())
        assert isinstance(infohash, str)
        return func(self, infohash, *args, **kwargs)
    return decorated


class Session(object):
    MONITOR_ALERTS = reduce(operator.or_, (
        libtorrent.alert.category_t.error_notification,
        libtorrent.alert.category_t.status_notification,
        libtorrent.alert.category_t.storage_notification,
        libtorrent.alert.category_t.progress_notification,
        ))

    def __init__(self):
        self._waiting_deferreds = list()
        self._static_alert_handlers = list()
        self._add_static_handlers()

        self._ses = libtorrent.session()
        self._ses.set_alert_mask(self.MONITOR_ALERTS)
        self._pop_alerts() # start alert popping loop
        self._resume_storage = ResumeStorage("/tmp/resume")

    def _pop_alerts(self):
        try:
            while True:
                alert = self._ses.pop_alert()
                if alert is None: break
                self._process_alert(alert)
        finally:
            reactor.callLater(1, self._pop_alerts)

    def _process_alert(self, alert):
        logger.info("%s: %s" % (type(alert), alert.message()))
        for sah in self._static_alert_handlers:
            sah(alert)

        for wd in self._waiting_deferreds:
            if wd.match(alert):
                wd.deferred.callback(alert)
                self._waiting_deferreds.remove(wd)

    def _expire_deferreds(self):
        for wd in self._waiting_deferreds:
            if wd.is_expired():
                wd.deferred.errback(TimeoutError("The callback expired."))
                self._waiting_deferreds.remove(wd)

    def _add_deferred(self, alert_match_func):
        ad = AlertDeferred(alert_match_func)
        self._waiting_deferreds.append(ad)
        return ad.deferred

    def add_static_handler(self):
        def decorator(func):
            self._static_alert_handlers.append(func)
            return func
        return decorator

    def _add_static_handlers(self):
        @self.add_static_handler()
        @signature_match(libtorrent.save_resume_data_alert)
        def save_resume_handler(alert):
            self._resume_storage[alert.handle.info_hash()] = alert.resume_data

        @self.add_static_handler()
        @signature_match(libtorrent.torrent_paused_alert)
        def save_resume_data_on_pause(alert):
            alert.handle.save_resume_data()

    def _make_torrent_alert_handler(self, infohash, alert_cls):
        """
        returns a Deferred.  callback arg is a alert_cls
        """
        def alert_match_func(alert):
            if isinstance(alert, alert_cls):
                return infohash == str(alert.handle.info_hash())
            return False
        return self._add_deferred(alert_match_func)

    def add_torrent(self, url):
        """
        returns Deferred.  callback arg is a libtorrent.torrent_alert
        """
        deferred = defer.Deferred()
        def _add_torrent(buf):
            try:
                info = libtorrent.torrent_info(libtorrent.bdecode(buf))
            except RuntimeError as e:
                deferred.errback(e)
                return
            def wait_for_event(alert):
                if isinstance(alert, libtorrent.torrent_alert):
                    return info.info_hash() == alert.handle.info_hash()
                return False
            self._add_deferred(wait_for_event).chainDeferred(deferred)
            try:
                self._ses.add_torrent(info, "/tmp")
            except RuntimeError as e:
                deferred.errback(e)
                return
        twisted.web.client.getPage(url).addCallbacks(_add_torrent, deferred.errback)
        return deferred

    def load_torrent(self, infohash):
        d = self._make_torrent_alert_handler(infohash, (
                # libtorrent.torrent_loaded_alert,
                type('AnonymousType', (object, ), {}),
            ))
        handle = self._ses.find_torrent(libtorrent.big_number(infohash.decode('hex')))
        try:
            handle.infohash()
        except RuntimeError as e:
            d.errback(failure.Failure(ValueError("Invalid handle")))

        if infohash not in self._metainfo_torrent:
            d.errback(failure.Failure(ValueError("Unknown infohash")))
        else:
            if infohash in self._resume_storage:
                pass
        return d

    @maybe_handle # : args=(self, infohash | handle) -> args=(self, infohash)
    def resume_torrent(self, infohash):
        """
        returns a Deferred.  callback arg is a libtorrent.torrent_resumed_alert
        """
        retval = self._make_torrent_alert_handler(infohash, libtorrent.torrent_resumed_alert)
        torrent = self._ses.find_torrent(libtorrent.big_number(infohash.encode('hex')))
        torrent.resume()
        return retval

    @maybe_handle # : args=(self, infohash | handle) -> args=(self, infohash)
    def pause_torrent(self, infohash):
        """
        returns a Deferred.  callback arg is a libtorrent.torrent_paused_alert
        """
        retval = self._make_torrent_alert_handler(infohash, libtorrent.torrent_paused_alert)
        torrent = self._ses.find_torrent(libtorrent.big_number(infohash.decode('hex')))
        torrent.pause()
        return retval

    @maybe_handle # : args=(self, infohash | handle) -> args=(self, infohash)
    def remove_torrent(self, infohash):
        """
        returns a Deferred.  callback arg is a libtorrent.torrent_deleted_alert
        """
        return self._make_torrent_alert_handler(
                libtorrent.torrent_deleted_alert, lambda a: self._ses.remove_torrent(a.handle))

    def _find_torrents_re(self, regexp):
        print regexp
        print map(libtorrent.torrent_handle.name, self._ses.get_torrents())
        regexp = re.compile(regexp)
        torrent_filter = sre_ft.compose(regexp.match, libtorrent.torrent_handle.name)
        return filter(torrent_filter, self._ses.get_torrents())

    def find_torrents(self, regexp):
        torrents = self._find_torrents_re(regexp)
        get_torrent_key = lambda t: str(t.info_hash())
        return dict((get_torrent_key(t), serialize_torrent(t)) for t in torrents)

    def torrent_metainfo(self):
        def get_torrent_key(torrent):
            return str(torrent.info_hash())
        return dict((get_torrent_key(torrent), serialize_torrent_metainfo(torrent))
                for torrent in self._ses.get_torrents())

    def torrent_state(self):
        def get_torrent_key(torrent):
            return str(torrent.info_hash())
        return dict( (get_torrent_key(torrent), serialize_torrent_status(torrent))
                for torrent in self._ses.get_torrents())

    def stop_session(self):
        pass


