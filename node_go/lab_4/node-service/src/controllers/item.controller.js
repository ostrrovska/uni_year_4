// Translates between HTTP and the Service: reads the parsed request, calls one
// Service method, picks the status code and shapes the response. It never
// touches a repository or the data store, and it holds no business rule.
//
// Errors are not caught here. Express 5 forwards both thrown and rejected
// handler errors to the error-handling middleware, which is the single place
// that maps them to status codes.
class ItemController {
  constructor(service) {
    this.service = service;
  }

  list = async (req, res) => {
    res.status(200).json(await this.service.list());
  };

  getById = async (req, res) => {
    res.status(200).json(await this.service.get(req.itemId));
  };

  create = async (req, res) => {
    const item = await this.service.create(req.body);
    res.status(201).location(`/api/items/${item.id}`).json(item);
  };

  update = async (req, res) => {
    res.status(200).json(await this.service.update(req.itemId, req.body));
  };

  remove = async (req, res) => {
    await this.service.remove(req.itemId);
    res.status(204).end();
  };
}

module.exports = { ItemController };
