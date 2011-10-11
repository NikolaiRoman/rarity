import libtorrent as lt
import time
import operator

from twisted.internet import reactor
from twisted.internet import defer

class TimeoutError(RuntimeError):
    pass


class AlertDeferred(defer.Deferred):
    def __init__(self, match_func, expire_after=None):
        self.match_func = match_func
        self.created_at = time.time()
        self.expire_after = expire_after or 600

    def is_expired(self):
        return (time.time() - self.created_at) > self.expire_after

    def match(self, alert):
        return self.match_func(alert)


class Session(object):
    MONITOR_ALERTS = reduce(operator.or_, (
        lt.alert.category_t.error_notification,
        lt.alert.category_t.status_notification,
        lt.alert.category_t.storage_notification,
        ))

    def __init__(self):
        self._ses = lt.session()
        self._ses.set_alert_mask(self.MONITOR_ALERTS)
        self._waiting_deferreds = set()
        self._pop_alerts() # start alert popping loop
        self._handles = dict()

    def _pop_alerts(self):
        try:
            while True:
                alert = self._ses.pop_alert()
                if alert is None: break
                self._process_alert(alert)
        finally:
            reactor.callLater(1, self._pop_alerts)

    def _process_alert(self, alert):
        print repr(alert.message())

        for wd in self._waiting_deferreds:
            if wd.matches(alert):
                wd.deferred.callback(alert)
                self._waiting_deferreds.remove(wd)

    def _expire_deferreds(self):
        for wd in self._waiting_deferreds:
            if wd.is_expired():
                wd.deferred.errback(TimeoutError("The callback expired."))
                self._waiting_deferreds.remove(wd)

    def _add_deferred(self, func):
        ad = AlertDeferred(alert_match_func)
        self._waiting_deferreds.add(ad)
        return ad

    def add_torrent(self, url):
        """
        returns Deferred.  callback arg is a torrent handle.
        """
        deferred = defer.Deferred()
        def add_torrent(buf):
            info = lt.torrent_info(lt.bdecode(buf))
            deferred.callback(self._ses.add_torrent(info, "/tmp"))
        libsre.twisted.http.buf_get(url).addBoth(add_torrent, deferred.errback)
        return deferred

    # @derpderp # : args=(self, handle) -> args=(self, infohash)
    def resume_torrent(self, handle):
        """
        returns a Deferred.  callback arg is a libtorrent.torrent_resumed_alert
        """
        infohash = str(handle.info_hash())
        def alert_match_func(alert):
            if isinstance(alert, lt.torrent_resumed_alert):
                return infohash == str(alert.handle.info_hash)
            return False
        return self._add_deferred(alert_match_func)

    # @derpderp # : args=(self, handle) -> args=(self, infohash)
    def pause_torrent(self, handle):
        """
        returns a Deferred.  callback arg is a libtorrent.torrent_paused_alert
        """
        infohash = str(handle.info_hash())
        def alert_match_func(alert):
            if isinstance(alert, lt.torrent_paused_alert):
                return infohash == str(alert.handle.info_hash)
            return False
        return self._add_deferred(alert_match_func)

    # @derpderp # : args=(self, handle) -> args=(self, infohash)
    def remove_torrent(self, handle):
        """
        returns a Deferred.  callback arg is a libtorrent.???
        """
        infohash = str(handle.info_hash())
        def alert_match_func(alert):
            if isinstance(alert, None):
                return infohash == str(alert.handle.info_hash)
            return False
        return self._add_deferred(alert_match_func)

    def torrent_metainfo(self):
        def get_torrent_key(torrent):
            return str(torrent.info_hash())
        def get_torrent_data(torrent):
            torrent_info = torrent.get_torrent_info()
            return {
                    'name': torrent.name(),
                    'pieces': torrent_info.num_pieces(),
                    'private': torrent_info.priv(),
                }
        return dict((get_torrent_key(torrent), get_torrent_data(torrent))
                for torrent in self._ses.get_torrents())

    def torrent_state(self):
        def get_torrent_key(torrent):
            return str(torrent.info_hash())
        def get_torrent_data(torrent):
            status = torrent.status()
            return {
                    'name': torrent.name(),
                    'paused': torrent.is_paused(),
                    'progress': status.progress,
                    'upload_rate': status.upload_rate,
                    'download_rate': status.download_rate
                    }
        return dict( (get_torrent_key(torrent), get_torrent_data(torrent))
                for torrent in self._ses.get_torrents())
            (torrent, dict(name=torrent.name()))


class ClientRemote(pb.Root):
    def __init__(self, session):
        self.session = session

    def remote_add_torrent(self, url):
        return self.session.add_torrent(url)

    def remote_pause_torrent(self, infohash):
        # FIXME: signature mismatch
        return self.session.pause_torrent(infohash)

    def remote_resume_torrent(self, infohash):
        # FIXME: signature mismatch
        return self.session.resume_torrent(infohash)

    def remote_remove_torrent(self, infohash):
        # FIXME: signature mismatch
        return self.session.remove_torrent(infohash)


session = Session()
session._ses.listen_on(23866, 23866)
session._ses.add_dht_router('router.bittorrent.com', 6881)
session._ses.load_country_db('/home/sell/dev/dht_overlord/GeoIP.dat')
session._ses.start_lsd()


reactor.start()

try:
    with open('/tmp/dht-info.b', 'r') as f:
        session._ses.start_dht(lt.bdecode(f.read()))
except IOError:
    session._ses.start_dht({})

while True:
    with open('/tmp/dht-info.b', 'w') as f:
        f.write(lt.bencode(ses.dht_state()))
    try:
        time.sleep(300)
    except KeyboardInterrupt:
        with open('/tmp/dht-info.b', 'w') as f:
            f.write(lt.bencode(ses.dht_state()))
        print "wrote. exiting."
        break




