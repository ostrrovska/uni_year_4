// HTTP face of the streaming module. Same shape as ItemController: arrow class
// fields so a method can be passed as a handler reference, one service call per
// method, no try/catch - Express 5 forwards a rejected handler to the error
// middleware, which is still the only place that knows status codes.
//
// 202 rather than 200 on job creation, because the work has not been done when
// the response is written: a 256 MB run outlives any request. The response
// carries the job id and a Location, and the actual result arrives over the
// WebSocket or from a later GET.
class StreamController {
  constructor(service) {
    this.service = service;
  }

  dataset = async (req, res) => {
    res.status(200).json(await this.service.dataset());
  };

  list = async (req, res) => {
    res.status(200).json(this.service.list());
  };

  getById = async (req, res) => {
    res.status(200).json(this.service.get(req.jobId));
  };

  create = async (req, res) => {
    const job = await this.service.start(req.streamJob);
    res.status(202).location(`/api/stream/jobs/${job.id}`).json(job);
  };

  abort = async (req, res) => {
    this.service.abort(req.jobId);
    res.status(204).end();
  };
}

module.exports = { StreamController };
