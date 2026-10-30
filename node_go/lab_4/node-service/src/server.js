const path = require('node:path');
const { createApp } = require('./app');
const { InMemoryItemRepository } = require('./repositories/in-memory.item.repository');
const { FileItemRepository } = require('./repositories/file.item.repository');

const PORT = Number(process.env.PORT) || 3100;
const REPOSITORY = process.env.ITEM_REPO || 'memory';
const DATA_FILE = process.env.ITEM_DATA_FILE || path.join(__dirname, '..', 'data', 'items.json');

// The single decision that picks a DataStore. Service, Controller and Router
// code is byte-identical in both modes.
function createRepository(kind) {
  switch (kind) {
    case 'memory':
      return new InMemoryItemRepository();
    case 'file':
      return new FileItemRepository(DATA_FILE);
    default:
      throw new Error(`unknown ITEM_REPO "${kind}", expected "memory" or "file"`);
  }
}

const app = createApp({ repository: createRepository(REPOSITORY), repositoryName: REPOSITORY });

app.listen(PORT, () => {
  console.log(`Node service running on http://localhost:${PORT} (repository: ${REPOSITORY})`);
  if (REPOSITORY === 'file') {
    console.log(`Data store: ${DATA_FILE}`);
  }
});
