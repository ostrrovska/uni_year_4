// Service-layer tests. No HTTP server, no Express, no port: the Service is
// constructed directly with a repository, which is the whole point of keeping
// it free of transport concerns.
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');

const { ItemService } = require('../src/services/item.service');
const { InMemoryItemRepository } = require('../src/repositories/in-memory.item.repository');
const { DomainError } = require('../src/errors/domain-error');

function newService(seed = []) {
  return new ItemService(new InMemoryItemRepository(seed));
}

async function expectDomainError(action, kind, code) {
  await assert.rejects(action, (error) => {
    assert.ok(error instanceof DomainError, `expected DomainError, got ${error.name}: ${error.message}`);
    assert.equal(error.kind, kind, `wrong kind for code ${error.code}`);
    assert.equal(error.code, code);
    assert.ok(error.message.length > 0, 'message must not be empty');
    return true;
  });
}

describe('ItemService: creating', () => {
  it('assigns an id and returns the stored item', async () => {
    const service = newService();

    const item = await service.create({ name: 'Keyboard', description: 'Mechanical' });

    assert.deepEqual(item, { id: 1, name: 'Keyboard', description: 'Mechanical' });
  });

  it('trims the fields and defaults a missing description', async () => {
    const service = newService();

    const item = await service.create({ name: '  Mouse  ' });

    assert.equal(item.name, 'Mouse');
    assert.equal(item.description, '');
  });

  it('numbers items consecutively', async () => {
    const service = newService();

    await service.create({ name: 'First' });
    const second = await service.create({ name: 'Second' });

    assert.equal(second.id, 2);
  });
});

describe('ItemService: validation', () => {
  it('rejects a missing name', async () => {
    const service = newService();

    await expectDomainError(() => service.create({ description: 'no name' }), 'validation', 'invalid_item');
  });

  it('rejects a whitespace-only name', async () => {
    const service = newService();

    await expectDomainError(() => service.create({ name: '   ' }), 'validation', 'invalid_item');
  });

  it('rejects a name of the wrong type', async () => {
    const service = newService();

    await expectDomainError(() => service.create({ name: 42 }), 'validation', 'invalid_item');
  });

  it('rejects a description of the wrong type', async () => {
    const service = newService();

    await expectDomainError(() => service.create({ name: 'Ok', description: [] }), 'validation', 'invalid_item');
  });

  it('rejects a body that is not an object', async () => {
    const service = newService();

    await expectDomainError(() => service.create('not an object'), 'validation', 'invalid_body');
  });

  it('rejects an identifier that is not a positive integer', async () => {
    const service = newService();

    await expectDomainError(() => service.get(0), 'validation', 'invalid_id');
    await expectDomainError(() => service.get(-1), 'validation', 'invalid_id');
    await expectDomainError(() => service.get(1.5), 'validation', 'invalid_id');
    await expectDomainError(() => service.get('abc'), 'validation', 'invalid_id');
  });
});

describe('ItemService: business rule - names are unique', () => {
  it('rejects a duplicate name regardless of case', async () => {
    const service = newService();
    await service.create({ name: 'Keyboard' });

    await expectDomainError(() => service.create({ name: 'KEYBOARD' }), 'conflict', 'item_name_taken');
  });

  it('rejects renaming an item onto another item name', async () => {
    const service = newService();
    await service.create({ name: 'Keyboard' });
    const mouse = await service.create({ name: 'Mouse' });

    await expectDomainError(() => service.update(mouse.id, { name: 'keyboard' }), 'conflict', 'item_name_taken');
  });

  it('allows an item to keep its own name while editing the description', async () => {
    const service = newService();
    const item = await service.create({ name: 'Keyboard', description: 'old' });

    const updated = await service.update(item.id, { name: 'Keyboard', description: 'new' });

    assert.deepEqual(updated, { id: item.id, name: 'Keyboard', description: 'new' });
  });
});

describe('ItemService: reading', () => {
  it('lists every stored item', async () => {
    const service = newService();
    await service.create({ name: 'First' });
    await service.create({ name: 'Second' });

    const items = await service.list();

    assert.equal(items.length, 2);
    assert.deepEqual(items.map((item) => item.name), ['First', 'Second']);
  });

  it('returns an empty list for an empty store', async () => {
    const service = newService();

    assert.deepEqual(await service.list(), []);
  });

  it('finds an item by id', async () => {
    const service = newService();
    const created = await service.create({ name: 'Keyboard' });

    assert.deepEqual(await service.get(created.id), created);
  });

  it('reports a missing item as not found', async () => {
    const service = newService();

    await expectDomainError(() => service.get(404), 'not_found', 'item_not_found');
  });
});

describe('ItemService: updating and deleting', () => {
  it('updates both fields', async () => {
    const service = newService();
    const created = await service.create({ name: 'Keyboard', description: 'old' });

    const updated = await service.update(created.id, { name: 'Keypad', description: 'new' });

    assert.deepEqual(updated, { id: created.id, name: 'Keypad', description: 'new' });
    assert.deepEqual(await service.get(created.id), updated);
  });

  it('reports updating a missing item as not found', async () => {
    const service = newService();

    await expectDomainError(() => service.update(404, { name: 'Ghost' }), 'not_found', 'item_not_found');
  });

  it('deletes an item, after which it can no longer be found', async () => {
    const service = newService();
    const created = await service.create({ name: 'Keyboard' });

    await service.remove(created.id);

    assert.deepEqual(await service.list(), []);
    await expectDomainError(() => service.get(created.id), 'not_found', 'item_not_found');
  });

  it('reports deleting a missing item as not found', async () => {
    const service = newService();

    await expectDomainError(() => service.remove(404), 'not_found', 'item_not_found');
  });

  it('frees the name of a deleted item', async () => {
    const service = newService();
    const created = await service.create({ name: 'Keyboard' });
    await service.remove(created.id);

    const recreated = await service.create({ name: 'Keyboard' });

    assert.equal(recreated.name, 'Keyboard');
  });
});

describe('ItemService: dependency inversion', () => {
  it('refuses a repository that does not implement the contract', () => {
    assert.throws(
      () => new ItemService({ create() {} }),
      /missing findAll, findById, findByName, update, delete/,
    );
  });

  it('works against any object satisfying the contract', async () => {
    // A hand-written stub, neither of the two shipped implementations. The
    // Service accepts it because it depends on the contract, not on a class.
    const stub = {
      async create(draft) { return { id: 7, ...draft }; },
      async findAll() { return []; },
      async findById() { throw new Error('unused'); },
      async findByName() { return null; },
      async update() { throw new Error('unused'); },
      async delete() {},
    };

    const item = await new ItemService(stub).create({ name: 'Stubbed' });

    assert.equal(item.id, 7);
  });

  it('propagates an infrastructure failure untranslated, so the HTTP layer reports 500', async () => {
    const unreachable = () => { throw new Error('data store is unreachable'); };
    const broken = {
      create: unreachable,
      findAll: unreachable,
      findById: unreachable,
      async findByName() { return null; },
      update: unreachable,
      delete: unreachable,
    };
    const service = new ItemService(broken);

    await assert.rejects(() => service.list(), (error) => {
      assert.ok(!(error instanceof DomainError), 'an infrastructure failure must not become a DomainError');
      assert.match(error.message, /unreachable/);
      return true;
    });
  });
});
