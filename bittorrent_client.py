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

import logging
import libtorrent
import time
import operator
import re
import functools
import itertools

from twisted.internet import reactor
from twisted.internet import defer
from twisted.spread import pb
import twisted.web.client
import sshsimpleserver

from rarity.utils import serialize_torrent_metainfo, \
        serialize_torrent_status, serialize_torrent
from rarity.session import Session

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)
logger = logging.getLogger('ClientCore')
logger.setLevel(logging.INFO)

def alert_to_infohash(func):
    def decorated(*args, **kwargs):
        d = defer.Deferred()
        def convert(item):
            d.callback(str(item.handle.info_hash()))
        tmp = func(*args, **kwargs)
        tmp.addCallbacks(convert, d.errback)
        return d
    return decorated

# View 
class ClientRemote(pb.Root):
    def __init__(self, session):
        self.session = session

    @alert_to_infohash
    def remote_add_torrent(self, url):
        return self.session.add_torrent(url)

    @alert_to_infohash
    def remote_pause_torrent(self, infohash):
        return self.session.pause_torrent(infohash)

    @alert_to_infohash
    def remote_resume_torrent(self, infohash):
        return self.session.resume_torrent(infohash)

    @alert_to_infohash
    def remote_remove_torrent(self, infohash):
        return self.session.remove_torrent(infohash)

    @alert_to_infohash
    def remote_get_torrent_info(self, infohash):
        return self.session.torrent_state()[infohash]

    def remote_get_torrent_metainfo(self, infohash):
        return self.session.torrent_metainfo()[infohash]

    def remote_find_torrent(self, regexp):
        return self.session.find_torrents(regexp)

    def remote_get_torrent_name(self, infohash):
        tmp = self.session.torrent_metainfo()
        print repr(tmp)
        return tmp[infohash]['name']

session = Session()
session._ses.listen_on(23866, 23866)
session._ses.add_dht_router('router.bittorrent.com', 6881)
session._ses.load_country_db('/home/sell/dev/rarity/GeoIP.dat')
session._ses.start_lsd()

try:
    with open('/tmp/dht-info.b', 'r') as f:
        info = libtorrent.bdecode(f.read())
        if 'nodes' in info:
            session._ses.start_dht(info)
            logger.info("started DHT with %d nodes" % len(info['nodes']))
except IOError:
    session._ses.start_dht({})
    logger.info("started DHT without any nodes.")

def write_dht_info():
    with open('/tmp/dht-info.b', 'w') as f:
        f.write(libtorrent.bencode(session._ses.dht_state()))
        logger.info("Wrote DHT info")
    reactor.callLater(60, write_dht_info)

reactor.callLater(120, write_dht_info)
reactor.listenTCP(8800, pb.PBServerFactory(ClientRemote(session)))

reactor.listenTCP(5022, sshsimpleserver.getManholeFactory({
        'session': session,
        'libtorrent': libtorrent,
    }, sell='dicks'))

reactor.run()

#with open('/tmp/dht-info.b', 'w') as f:
#    f.write(libtorrent.bencode(session._ses.dht_state()))
#    logger.info("Wrote DHT info")

