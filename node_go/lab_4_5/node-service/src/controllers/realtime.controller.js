// HTTP window into the WebSocket module: the list of active connections that
// requirement 7.1 asks the server to keep, readable without opening a socket.
//
// It is useful beyond the demo - this is how the state of a real-time server
// gets monitored - and it is the clearest proof that the registry is one shared
// structure rather than something each transport keeps for itself.
class RealtimeController {
  constructor(service) {
    this.service = service;
  }

  clients = async (req, res) => {
    res.status(200).json(this.service.clients());
  };

  notify = async (req, res) => {
    res.status(202).json(this.service.notify(req.body.text));
  };
}

module.exports = { RealtimeController };
