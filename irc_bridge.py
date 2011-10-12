from twisted.words.protocols import irc
from twisted.internet import reactor, protocol, ssl, defer
import random, datetime
import time, sys
from twisted.spread import pb
import re

linkchannel = '#lolinano'

def parse_hostmask(hostmask):
    nick, rest = hostmask.split('!', 1)
    user, host = rest.split('@', 1)
    return nick, user, host

class DiscordBot(irc.IRCClient):
    nickname = 'Discord|nina'

    def connectionMade(self, *args, **kwargs):
        irc.IRCClient.connectionMade(self, *args, **kwargs)

    def signedOn(self):
        self.join(linkchannel)

    def _add_torrent(self, nick, channel, url):
        def reply_error(message):
            self.say(channel, "%s: Failed: %s" % (nick, message.getErrorMessage()))
        def reply_success(message):
            self.say(channel, "%s: Added: %s" % (nick, message))
        self.factory.add_torrent(url).addCallbacks(reply_success, reply_error)

    def _find_torrent(self, nick, channel, regexp):
        def reply_error(message):
            self.say(channel, "%s: Failed: %s" % (nick, message.getErrorMessage()))
        def reply_success(message):
            self.say(channel, "%s: Found: %s" % (nick, message))
        self.factory.find_torrent(regexp).addCallbacks(reply_success, reply_error)

    def privmsg(self, hostmask, channel, message):
        print "DEBUG - %s, %s, %s" % (hostmask, channel, message)
        try:
            nick, _, host = parse_hostmask(hostmask)
        except Exception:
            return
        if not (nick == 'InfinityB' and host == 'dicks.yshi.org'):
            return

        torrent_add_re = re.compile('^' + re.escape(self.nickname+': torrent add ') + '(.*?)$')
        if torrent_add_re.match(message):
            args = torrent_add_re.match(message).groups()
            self._add_torrent(nick, channel, *args)
        torrent_find_re = re.compile('^' + re.escape(self.nickname+': torrent find ')+ '(.*?)$')
        if torrent_find_re.match(message):
            args = torrent_find_re.match(message).groups()
            self._find_torrent(nick, channel, *args)


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
        d = defer.Deferred()
        self.session.callRemote("find_torrent", regexp).chainDeferred(d)
        return d

if __name__ == '__main__':
    def err(reason):
        print reason
        reactor.stop()
    pbfactory = pb.PBClientFactory()
    botfactory = DiscordBotFactory()
    reactor.connectTCP("localhost", 8800, pbfactory)
    reactor.connectTCP("localhost", 6667, botfactory)
    pbfactory.getRootObject().addCallbacks(botfactory.set_session, err)
    reactor.run()


