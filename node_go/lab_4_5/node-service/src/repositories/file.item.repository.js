const fs = require('node:fs/promises');
const path = require('node:path');
const { RepositoryNotFoundError } = require('./item.repository');

// DataStore: a JSON file on disk. Satisfies exactly the same contract as
// InMemoryItemRepository, so wiring this one in instead changes nothing in the
// Service, Controller or Router.
class FileItemRepository {
  constructor(filePath) {
    this.filePath = filePath;
    // Serializes read-modify-write cycles. Two concurrent writes would
    // otherwise both read the same snapshot and one would overwrite the other.
    this.queue = Promise.resolve();
  }

  async create(draft) {
    return this.#transaction(async () => {
      const state = await this.#load();
      const item = { id: state.nextId, name: draft.name, description: draft.description };
      state.items.push(item);
      state.nextId += 1;
      await this.#save(state);
      return item;
    });
  }

  async findAll() {
    return this.#transaction(async () => (await this.#load()).items);
  }

  async findById(id) {
    return this.#transaction(async () => {
      const { items } = await this.#load();
      const item = items.find((candidate) => candidate.id === id);
      if (!item) {
        throw new RepositoryNotFoundError(id);
      }
      return item;
    });
  }

  async findByName(name) {
    const needle = name.toLowerCase();
    return this.#transaction(async () => {
      const { items } = await this.#load();
      return items.find((candidate) => String(candidate.name).toLowerCase() === needle) ?? null;
    });
  }

  async update(item) {
    return this.#transaction(async () => {
      const state = await this.#load();
      const index = state.items.findIndex((candidate) => candidate.id === item.id);
      if (index === -1) {
        throw new RepositoryNotFoundError(item.id);
      }
      state.items[index] = { id: item.id, name: item.name, description: item.description };
      await this.#save(state);
      return state.items[index];
    });
  }

  async delete(id) {
    return this.#transaction(async () => {
      const state = await this.#load();
      const index = state.items.findIndex((candidate) => candidate.id === id);
      if (index === -1) {
        throw new RepositoryNotFoundError(id);
      }
      state.items.splice(index, 1);
      await this.#save(state);
    });
  }

  #transaction(work) {
    const result = this.queue.then(work);
    // The chain must survive a rejected unit of work, or every later call fails.
    this.queue = result.catch(() => undefined);
    return result;
  }

  // A missing file is an empty store. A corrupt one is an infrastructure
  // failure: it propagates untranslated and the error handler reports 500.
  async #load() {
    let raw;
    try {
      raw = await fs.readFile(this.filePath, 'utf8');
    } catch (error) {
      if (error.code === 'ENOENT') {
        return { items: [], nextId: 1 };
      }
      throw error;
    }

    if (raw.trim() === '') {
      return { items: [], nextId: 1 };
    }

    const parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.items)) {
      throw new Error(`corrupt data store at ${this.filePath}: "items" array is missing`);
    }

    return { items: parsed.items, nextId: Number(parsed.nextId) || parsed.items.length + 1 };
  }

  // Write to a temporary file and rename, so a crash mid-write cannot leave a
  // half-written store behind.
  async #save(state) {
    await fs.mkdir(path.dirname(this.filePath), { recursive: true });
    const temp = `${this.filePath}.tmp`;
    await fs.writeFile(temp, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
    await fs.rename(temp, this.filePath);
  }
}

module.exports = { FileItemRepository };
