// HTTP face of the task-by-task walkthrough. Same shape as the other
// controllers: arrow class fields, one service call per method, no try/catch -
// a failed task throws a DomainError and the single error middleware maps it.
//
// A task runs synchronously from the request's point of view, because the page
// is built around "press, wait, read the result". Jobs that outlive a request
// still live behind /api/stream/jobs and 202.
class LabController {
  constructor(service) {
    this.service = service;
  }

  list = async (req, res) => {
    res.status(200).json(this.service.list());
  };

  run = async (req, res) => {
    res.status(200).json(await this.service.run(req.params.taskId));
  };
}

module.exports = { LabController };
