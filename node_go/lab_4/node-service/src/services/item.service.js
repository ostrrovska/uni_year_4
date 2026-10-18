const { DomainError } = require('../errors/domain-error');
const { RepositoryNotFoundError, assertItemRepository } = require('../repositories/item.repository');
const { validateDraft, normalizeDraft } = require('../models/item');

// Business logic. Knows nothing about HTTP, Express, SQL or how items are
// stored - only the ItemRepository contract it was constructed with. That is
// what makes it testable without starting a server.
class ItemService {
  constructor(repository) {
    this.repository = assertItemRepository(repository);
  }

  async list() {
    return this.repository.findAll();
  }

  async get(id) {
    this.#assertId(id);
    try {
      return await this.repository.findById(id);
    } catch (error) {
      throw this.#translate(error, id);
    }
  }

  async create(draft) {
    const fields = this.#validate(draft);
    await this.#assertNameAvailable(fields.name, null);
    return this.repository.create(fields);
  }

  async update(id, draft) {
    this.#assertId(id);
    const fields = this.#validate(draft);
    await this.#assertNameAvailable(fields.name, id);
    try {
      return await this.repository.update({ id, ...fields });
    } catch (error) {
      throw this.#translate(error, id);
    }
  }

  async remove(id) {
    this.#assertId(id);
    try {
      await this.repository.delete(id);
    } catch (error) {
      throw this.#translate(error, id);
    }
  }

  // The validation middleware already rejects a bad id at the HTTP edge. This
  // guard is for every other caller: the Service defends its own contract.
  #assertId(id) {
    if (!Number.isInteger(id) || id < 1) {
      throw DomainError.validation('invalid_id', `Item id must be a positive integer, got "${id}"`);
    }
  }

  #validate(draft) {
    if (!draft || typeof draft !== 'object' || Array.isArray(draft)) {
      throw DomainError.validation('invalid_body', 'Request body must be a JSON object');
    }

    const problems = validateDraft(draft);
    if (problems.length > 0) {
      throw DomainError.validation('invalid_item', problems.join('; '));
    }

    return normalizeDraft(draft);
  }

  // Business rule: names are unique, compared case-insensitively. It lives here
  // and not in the Controller, which cannot know it without querying data.
  async #assertNameAvailable(name, ownId) {
    const existing = await this.repository.findByName(name);
    if (existing && existing.id !== ownId) {
      throw DomainError.conflict('item_name_taken', `Item with name "${name}" already exists`);
    }
  }

  // Storage vocabulary stops here: "row absent" becomes a domain not-found.
  // Anything else is an infrastructure failure and travels on untouched, so the
  // HTTP layer reports 500 instead of inventing a 4xx.
  #translate(error, id) {
    if (error instanceof RepositoryNotFoundError) {
      return DomainError.notFound('item_not_found', `Item with id ${id} was not found`);
    }
    return error;
  }
}

module.exports = { ItemService };
