const { DomainError } = require('../errors/domain-error');
const { frames } = require('../realtime/ws-protocol');

// A thin service over the WebSocket hub, for the same reason the CRUD module
// has one: so the Controller talks to a service and not to the transport.
//
// It is thin because there is no business rule to hold - the rules about who
// receives what live in the policy and the broadcaster. What it does add is the
// boundary: the HTTP layer gets serialisable snapshots, never a socket, and the
// "WebSocket is not running" case becomes a domain error instead of a
// TypeError on null.
class RealtimeService {
  // hub is the object returned by createWebSocketServer, or null when the app
  // is built without the WebSocket module - which is how the lab 4 API tests
  // keep running unchanged.
  constructor(hub = null) {
    this.hub = hub;
  }

  #require() {
    if (this.hub === null) {
      throw DomainError.unavailable('ws_disabled', 'WebSocket module is not enabled on this instance');
    }
    return this.hub;
  }

  clients() {
    return this.#require().snapshot();
  }

  // Lets an HTTP caller push a notice to every connected client, which is the
  // shortest possible demonstration that the two transports share one state.
  notify(text) {
    const hub = this.#require();
    const result = hub.broadcaster.broadcast(frames.message({ from: 'server', clientId: 'server', text }));
    return { ...result, clients: hub.registry.size };
  }
}

module.exports = { RealtimeService };
