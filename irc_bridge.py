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
from twisted.words.protocols import irc
from twisted.internet import reactor, protocol, ssl, defer
import random, datetime
import time, sys
from twisted.spread import pb
import re

linkchannels = ['#', '#lolinano']

def fmt_torrent(torrent):
    return "%(name)s" % torrent

def parse_hostmask(hostmask):
    nick, rest = hostmask.split('!', 1)
    user, host = rest.split('@', 1)
    return nick, user, host

class DiscordBot(irc.IRCClient):
    nickname = 'Rarity|nina'

    def connectionMade(self, *args, **kwargs):
        irc.IRCClient.connectionMade(self, *args, **kwargs)

    def signedOn(self):
        for lc in linkchannels:
            self.join(lc)

    def _add_torrent(self, nick, channel, url):
        def reply_error(message):
            self.say(channel, "%s: Failed: %s" % (nick, message.getErrorMessage()))
        def reply_success(message):
            self.say(channel, "%s: Added: %s" % (nick, message))
        self.factory.add_torrent(url).addCallbacks(reply_success, reply_error)

    def _find_torrent(self, nick, channel, regexp):
        def reply_error(message):
            self.say(channel, "%s: Failed: %s" % (nick, message.getErrorMessage()))
        def reply_success(torrents):
            self.say(channel, "%s:" % nick)
            for t in torrents.values():
                self.say(channel, "  " + fmt_torrent(t))
        self.factory.find_torrent(regexp).addCallbacks(reply_success, reply_error)

    def _start_torrent(self, nick, channel, regexp):
        def reply_error(message): 
            self.say(channel, "%s: Failed: %s" % (nick, message.getErrorMessage()))
        def reply_success(message):
            self.say(channel, "%s: started: %s" % (nick, fmt_torrent(message)))
        def torrent_start_success(infohash):
            self.factory.get_torrent_metainfo(infohash).addCallback(reply_success)
        def get_torrents_success(torrents):
            for torrent_ih in torrents.keys():
                self.factory.start_torrent(torrent_ih).addCallback(torrent_start_success)
        self.factory.find_torrent(regexp).addCallbacks(get_torrents_success, reply_error)

    def _stop_torrent(self, nick, channel, regexp):
        def reply_error(message):
            self.say(channel, "%s: Failed: %s" % (nick, message.getErrorMessage()))
        def reply_success(message):
            self.say(channel, "%s: stopped: %s" % (nick, fmt_torrent(message)))
        def torrent_stop_success(infohash):
             self.factory.get_torrent_metainfo(infohash).addCallback(reply_success)
        def get_torrents_success(torrents):
            for torrent_ih in torrents.keys():
                self.factory.stop_torrent(torrent_ih).addCallback(torrent_stop_success)

        self.factory.find_torrent(regexp).addCallbacks(get_torrents_success, reply_error)

    def privmsg(self, hostmask, channel, message):
        print "DEBUG - %s, %s, %s" % (hostmask, channel, message)
        try:
            nick, _, host = parse_hostmask(hostmask)
        except Exception:
            return
        #if not (nick == 'InfinityB' and host == 'dicks.yshi.org'):
        #    return

        torrent_add_re = re.compile('^' + re.escape(self.nickname+': torrent add ') + '(.*?)$')
        if torrent_add_re.match(message):
            args = torrent_add_re.match(message).groups()
            self._add_torrent(nick, channel, *args)
        torrent_find_re = re.compile('^' + re.escape(self.nickname+': torrent find ')+ '(.*?)$')
        if torrent_find_re.match(message):
            args = torrent_find_re.match(message).groups()
            self._find_torrent(nick, channel, *args)
        torrent_stop_re = re.compile('^' + re.escape(self.nickname+': torrent stop ')+ '(.*?)$')
        if torrent_stop_re.match(message):
            args = torrent_stop_re.match(message).groups()
            self._stop_torrent(nick, channel, *args)
        torrent_start_re = re.compile('^' + re.escape(self.nickname+': torrent start ')+ '(.*?)$')
        if torrent_start_re.match(message):
            args = torrent_start_re.match(message).groups()
            self._start_torrent(nick, channel, *args)


class DiscordBotFactory(protocol.ClientFactory):
    protocol = DiscordBot

    def __init__(self):
        self.session = None

    def set_session(self, session):
        self.session = session

    def clientConnectionFailed(self, connector, reason):
        print "connection failed:", reason
        reactor.stop()

    def add_torrent(self, url):
        d = defer.Deferred()
        def get_name(infohash):
            self.session.callRemote("get_torrent_name", infohash).chainDeferred(d)
        self.session.callRemote("add_torrent", url).addCallbacks(get_name, d.errback)
        return d

    def find_torrent(self, regexp):
        return self.session.callRemote("find_torrent", ".*?%s.*?" % regexp)

    def stop_torrent(self, infohash):
        return self.session.callRemote("pause_torrent", infohash)

    def start_torrent(self, infohash):
        return self.session.callRemote("resume_torrent", infohash)

    def get_torrent_metainfo(self, infohash):
        return self.session.callRemote("get_torrent_metainfo", infohash)

if __name__ == '__main__':
    def err(reason):
        print reason
        reactor.stop()
    pbfactory = pb.PBClientFactory()
    botfactory = DiscordBotFactory()
    reactor.connectTCP("localhost", 8800, pbfactory)
    reactor.connectTCP("10.0.12.6", 6667, botfactory)
    pbfactory.getRootObject().addCallbacks(botfactory.set_session, err)
    reactor.run()


