from twisted.internet import reactor
from twisted.web import server, resource
from twisted.cred import portal, checkers
from twisted.conch import manhole, manhole_ssh

def getManholeFactory(namespace, **passwords):
    realm = manhole_ssh.TerminalRealm()
    def getManhole(_): return manhole.Manhole(namespace)
    realm.chainedProtocolFactory.protocolFactory = getManhole
    p = portal.Portal(realm)
    p.registerChecker(
        checkers.InMemoryUsernamePasswordDatabaseDontUse(**passwords))
    f = manhole_ssh.ConchFactory(p)
    return f

if __name__ == '__main__':
    reactor.listenTCP(2222, getManholeFactory(globals(), admin='aaa'))
    reactor.run()
