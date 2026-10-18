// Both repository implementations are run through the same table. Passing it
// is what makes the memory -> file swap safe: the Service cannot tell them
// apart, because by this contract they behave identically.
const { after, before, describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const { InMemoryItemRepository } = require('../src/repositories/in-memory.item.repository');
const { FileItemRepository } = require('../src/repositories/file.item.repository');
const {
  ITEM_REPOSITORY_METHODS,
  RepositoryNotFoundError,
  assertItemRepository,
} = require('../src/repositories/item.repository');
const { ItemService } = require('../src/services/item.service');

let tempDir;
let fileCounter = 0;

before(async () => {
  tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'lab4-repo-'));
});

after(async () => {
  await fs.rm(tempDir, { recursive: true, force: true });
});

// Each case gets its own file, so one case cannot see another one's rows.
function newDataFile() {
  fileCounter += 1;
  return path.join(tempDir, `items-${fileCounter}.json`);
}

const implementations = [
  { name: 'InMemoryItemRepository', create: () => new InMemoryItemRepository() },
  { name: 'FileItemRepository', create: () => new FileItemRepository(newDataFile()) },
];

for (const implementation of implementations) {
  describe(`${implementation.name}: the ItemRepository contract`, () => {
    it('implements every method of the contract', () => {
      const repository = implementation.create();

      assert.doesNotThrow(() => assertItemRepository(repository));
      for (const method of ITEM_REPOSITORY_METHODS) {
        assert.equal(typeof repository[method], 'function', `${method} is missing`);
      }
    });

    it('starts empty', async () => {
      const repository = implementation.create();

      assert.deepEqual(await repository.findAll(), []);
    });

    it('assigns consecutive ids on create', async () => {
      const repository = implementation.create();

      const first = await repository.create({ name: 'First', description: '' });
      const second = await repository.create({ name: 'Second', description: '' });

      assert.equal(first.id, 1);
      assert.equal(second.id, 2);
    });

    it('finds a stored row by id', async () => {
      const repository = implementation.create();
      const created = await repository.create({ name: 'Keyboard', description: 'Mechanical' });

      assert.deepEqual(await repository.findById(created.id), created);
    });

    it('signals a missing row with RepositoryNotFoundError', async () => {
      const repository = implementation.create();

      await assert.rejects(() => repository.findById(404), RepositoryNotFoundError);
      await assert.rejects(() => repository.update({ id: 404, name: 'x', description: '' }), RepositoryNotFoundError);
      await assert.rejects(() => repository.delete(404), RepositoryNotFoundError);
    });

    it('matches findByName case-insensitively and returns null when absent', async () => {
      const repository = implementation.create();
      await repository.create({ name: 'Keyboard', description: '' });

      assert.equal((await repository.findByName('KEYBOARD')).name, 'Keyboard');
      assert.equal(await repository.findByName('Mouse'), null);
    });

    it('updates a row in place', async () => {
      const repository = implementation.create();
      const created = await repository.create({ name: 'Keyboard', description: 'old' });

      const updated = await repository.update({ id: created.id, name: 'Keypad', description: 'new' });

      assert.deepEqual(updated, { id: created.id, name: 'Keypad', description: 'new' });
      assert.deepEqual(await repository.findById(created.id), updated);
    });

    it('removes a row', async () => {
      const repository = implementation.create();
      const created = await repository.create({ name: 'Keyboard', description: '' });

      await repository.delete(created.id);

      assert.deepEqual(await repository.findAll(), []);
    });

    it('does not let a caller mutate stored state through a returned object', async () => {
      const repository = implementation.create();
      const created = await repository.create({ name: 'Keyboard', description: '' });

      created.name = 'tampered';

      assert.equal((await repository.findById(created.id)).name, 'Keyboard');
    });

    it('serves the same ItemService without a single change to it', async () => {
      const service = new ItemService(implementation.create());

      const item = await service.create({ name: 'Keyboard', description: 'Mechanical' });

      assert.deepEqual(await service.get(item.id), item);
      await assert.rejects(() => service.create({ name: 'keyboard' }), /already exists/);
    });
  });
}

describe('FileItemRepository: storage-specific behaviour', () => {
  it('survives being reopened, which the in-memory one cannot', async () => {
    const dataFile = newDataFile();

    await new FileItemRepository(dataFile).create({ name: 'Persisted', description: '' });
    const reopened = await new FileItemRepository(dataFile).findAll();

    assert.deepEqual(reopened, [{ id: 1, name: 'Persisted', description: '' }]);
  });

  it('serializes concurrent writes instead of losing them', async () => {
    const repository = new FileItemRepository(newDataFile());

    await Promise.all(
      Array.from({ length: 10 }, (_, index) => repository.create({ name: `Item ${index}`, description: '' })),
    );

    const stored = await repository.findAll();
    assert.equal(stored.length, 10);
    assert.deepEqual(stored.map((item) => item.id).sort((a, b) => a - b), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  });

  it('reports a corrupt store as an ordinary failure, not as a missing row', async () => {
    const dataFile = newDataFile();
    await fs.writeFile(dataFile, '{ not json', 'utf8');
    const repository = new FileItemRepository(dataFile);

    await assert.rejects(() => repository.findAll(), (error) => {
      assert.ok(!(error instanceof RepositoryNotFoundError));
      return true;
    });
  });
});

describe('assertItemRepository', () => {
  it('names every missing method', () => {
    assert.throws(() => assertItemRepository({ create() {}, findAll() {} }), /missing findById, findByName, update, delete/);
  });

  it('rejects a non-object', () => {
    assert.throws(() => assertItemRepository(null), /must be an object/);
  });
});
