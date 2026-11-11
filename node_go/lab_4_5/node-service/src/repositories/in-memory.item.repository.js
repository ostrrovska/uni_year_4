const { RepositoryNotFoundError } = require('./item.repository');

// DataStore: a process-local array. Everything is lost on restart. Items are
// copied in and out so a caller cannot mutate stored state by holding a
// reference - the same isolation a real database gives for free.
class InMemoryItemRepository {
  constructor(seed = []) {
    this.items = seed.map((item) => ({ ...item }));
    this.nextId = this.items.reduce((max, item) => Math.max(max, item.id), 0) + 1;
  }

  async create(draft) {
    const item = { id: this.nextId, name: draft.name, description: draft.description };
    this.nextId += 1;
    this.items.push(item);
    return { ...item };
  }

  async findAll() {
    return this.items.map((item) => ({ ...item }));
  }

  async findById(id) {
    const item = this.items.find((candidate) => candidate.id === id);
    if (!item) {
      throw new RepositoryNotFoundError(id);
    }
    return { ...item };
  }

  async findByName(name) {
    const needle = name.toLowerCase();
    const item = this.items.find((candidate) => candidate.name.toLowerCase() === needle);
    return item ? { ...item } : null;
  }

  async update(item) {
    const index = this.items.findIndex((candidate) => candidate.id === item.id);
    if (index === -1) {
      throw new RepositoryNotFoundError(item.id);
    }
    this.items[index] = { id: item.id, name: item.name, description: item.description };
    return { ...this.items[index] };
  }

  async delete(id) {
    const index = this.items.findIndex((candidate) => candidate.id === id);
    if (index === -1) {
      throw new RepositoryNotFoundError(id);
    }
    this.items.splice(index, 1);
  }
}

module.exports = { InMemoryItemRepository };
