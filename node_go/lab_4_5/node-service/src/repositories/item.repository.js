// The contract every repository implementation must satisfy. JavaScript has no
// interfaces, so the contract is a named method list plus a wire-up assertion -
// the structural equivalent of Go's repository.ItemRepository.
//
//   create(draft)  -> item          assigns the id
//   findAll()      -> item[]
//   findById(id)   -> item          throws RepositoryNotFoundError
//   findByName(nm) -> item | null   case-insensitive
//   update(item)   -> item          throws RepositoryNotFoundError
//   delete(id)     -> void          throws RepositoryNotFoundError
const ITEM_REPOSITORY_METHODS = ['create', 'findAll', 'findById', 'findByName', 'update', 'delete'];

// Storage-level "row is absent" signal. The Service translates it into a
// DomainError, so no layer above the Service ever sees storage vocabulary.
class RepositoryNotFoundError extends Error {
  constructor(id) {
    super(`repository: item ${id} not found`);
    this.name = 'RepositoryNotFoundError';
    this.id = id;
  }
}

function assertItemRepository(candidate) {
  if (!candidate || typeof candidate !== 'object') {
    throw new TypeError('repository must be an object implementing ItemRepository');
  }

  const missing = ITEM_REPOSITORY_METHODS.filter((name) => typeof candidate[name] !== 'function');
  if (missing.length > 0) {
    throw new TypeError(`repository does not implement ItemRepository: missing ${missing.join(', ')}`);
  }

  return candidate;
}

module.exports = { ITEM_REPOSITORY_METHODS, RepositoryNotFoundError, assertItemRepository };
