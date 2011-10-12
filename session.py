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
import operator
import logging
from twisted.internet import reactor
import libtorrent

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)
logger = logging.getLogger('ClientCore')
logger.setLevel(logging.INFO)

class TimeoutError(RuntimeError):
    pass


class AlertDeferred(object):
    def __init__(self, match_func, expire_after=None):
        self.match_func = match_func
        self.created_at = time.time()
        self.expire_after = expire_after or 600
        self.deferred = defer.Deferred()

    def is_expired(self):
        return (time.time() - self.created_at) > self.expire_after

    def match(self, alert):
        return self.match_func(alert)


def maybe_handle(func):
    def decorated(self, infohash, *args, **kwargs):
        if isinstance(infohash, libtorrent.torrent_handle):
            infohash = str(infohash.info_hash())
        assert isinstance(infohash, str)
        return func(self, infohash, *args, **kwargs)
    return decorated

def serialize_torrent_metainfo(handle):
    torrent_info = handle.get_torrent_info()
    return {
            'name': handle.name(),
            'pieces': torrent_info.num_pieces(),
            'private': torrent_info.priv(),
        }


def serialize_torrent_status(handle):
    status = handle.status()
    return {
            'paused': torrent.is_paused(),
            'progress': status.progress,
            'upload_rate': status.upload_rate,
            'download_rate': status.download_rate
        }

def serialize_torrent(handle):
    return dict(itertools.chain(
        serialize_torrent_status(handle).iteritems(),
        serialize_torrent_metainfo(handle).iteritems()))

class Session(object):
    MONITOR_ALERTS = reduce(operator.or_, (
        libtorrent.alert.category_t.error_notification,
        libtorrent.alert.category_t.status_notification,
        libtorrent.alert.category_t.storage_notification,
        libtorrent.alert.category_t.progress_notification,
        ))

    def __init__(self):
        self._ses = libtorrent.session()
        self._ses.set_alert_mask(self.MONITOR_ALERTS)
        self._waiting_deferreds = list()
        self._pop_alerts() # start alert popping loop
        self._handles = dict() # infohash -> handle

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
        # TODO: add torrent-added event to populate self._handles
        # TODO: add torrent-removed event to reclaim entries in self._handles
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

    @maybe_handle # : args=(self, infohash | handle) -> args=(self, infohash)
    def resume_torrent(self, infohash):
        """
        returns a Deferred.  callback arg is a libtorrent.torrent_resumed_alert
        """
        def alert_match_func(alert):
            if isinstance(alert, libtorrent.torrent_resumed_alert):
                return infohash == str(alert.handle.info_hash())
            return False
        d = self._add_deferred(alert_match_func)
        for torrent in self._ses.get_torrents():
            if infohash == str(torrent.info_hash()):
                torrent.resume()
        return d

    @maybe_handle # : args=(self, infohash | handle) -> args=(self, infohash)
    def pause_torrent(self, infohash):
        """
        returns a Deferred.  callback arg is a libtorrent.torrent_paused_alert
        """
        def alert_match_func(alert):
            if isinstance(alert, libtorrent.torrent_paused_alert):
                return infohash == str(alert.handle.info_hash())
            return False
        d = self._add_deferred(alert_match_func)
        for torrent in self._ses.get_torrents():
            if infohash == str(torrent.info_hash()):
                torrent.pause()
        return d

    @maybe_handle # : args=(self, infohash | handle) -> args=(self, infohash)
    def remove_torrent(self, infohash):
        """
        returns a Deferred.  callback arg is a libtorrent.torrent_deleted_alert
        """
        def alert_match_func(alert):
            if isinstance(alert, libtorrent.torrent_deleted_alert):
                print "==(%s, %s)" % (repr(infohash), repr(str(alert.info_hash())))
                return infohash == str(alert.info_hash())
            return False
        d = self._add_deferred(alert_match_func)
        for torrent in self._ses.get_torrents():
            if infohash == str(torrent.info_hash()):
                self._ses.remove_torrent(torrent)
        return d

    def find_torrents(self, regexp):
        compose = lambda *fx: reduce(lambda f, g: lambda *args, **kwargs: f(g(*args, **kwargs)), fx)
        regexp = re.compile(regexp)
        get_torrent_key = lambda t: str(t.info_hash())
        torrent_filter = compose(regexp.match, libtorrent.torrent_handle.name)
        torrents = filter(torrent_filter, self._ses.get_torrents())
        return map(serialize_torrent, torrents)

    def torrent_metainfo(self):
        def get_torrent_key(torrent):
            return str(torrent.info_hash())
        def get_torrent_data(torrent):
            torrent_info = torrent.get_torrent_info()
        return dict((get_torrent_key(torrent), serialize_torrent_metainfo(torrent))
                for torrent in self._ses.get_torrents())

    def torrent_state(self):
        def get_torrent_key(torrent):
            return str(torrent.info_hash())
        return dict( (get_torrent_key(torrent), serialize_torrent_status(torrent))
                for torrent in self._ses.get_torrents())


