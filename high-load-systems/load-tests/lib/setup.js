// Lab5
// One-time discovery of the seeded entity ids, run in k6's setup() and shared with every VU.
//
// scripts/seed.py derives every id with UUIDv5 from a fixed namespace precisely so a load test
// can address seeded entities by literal id, and its docstring says so. Fetching them instead
// of hardcoding them costs one request outside the measured window and keeps the suite correct
// if the seed set ever changes - the determinism that matters for clause 2.2 is that two runs
// see the same data, not that the ids are typed into the script.

import http from 'k6/http';
import { API } from './config.js';

export function discover() {
  const nodes = http.get(`${API}/nodes?limit=200`);
  if (nodes.status !== 200) {
    throw new Error(`setup: GET /nodes answered ${nodes.status} - is the stack seeded?`);
  }
  const assets = http.get(`${API}/assets?limit=200`);
  if (assets.status !== 200) {
    throw new Error(`setup: GET /assets answered ${assets.status}`);
  }

  const regions = ['eu-central', 'eu-west', 'us-east', 'us-west', 'ap-southeast', 'sa-east'];
  const allNodes = nodes.json('items');
  const allAssets = assets.json('items');

  // Only healthy nodes may receive a heartbeat in Scenario B: a draining or degraded node is a
  // different write path (it can trigger a status transition and a cache invalidation), and
  // mixing the two would make the write scenario measure two things at once.
  const healthy = allNodes.filter((n) => n.status === 'healthy');
  if (healthy.length === 0) {
    throw new Error('setup: no healthy nodes - run `docker compose run --rm seed` first');
  }
  if (allAssets.length === 0) {
    throw new Error('setup: no assets - run `docker compose run --rm seed` first');
  }

  // Resolvable assets only, decided by probing rather than by a rule.
  //
  // Two kinds of asset in this database do not resolve: one pinned by a distribution rule to a
  // region the request does not come from, and one created by an earlier demo run that has no
  // replicas on any node. Both answer 503 "no eligible node", which is correct behaviour and
  // useless load. Worse than useless: proxy.conf lists http_503 in proxy_next_upstream, so a
  // burst of them ejects every peer and the run measures nginx's health policy instead of the
  // system. The first smoke run found 24 assets in the database where seed.py creates 8.
  //
  // So each candidate is probed once, here in setup(), outside the measured window, and only
  // those that answer 200 for every region enter the working set. Probing beats filtering on
  // origin_path because it stays correct as the seed set changes, and it is the only check
  // that actually answers the question the scenarios need answered.
  const paths = [];
  for (const asset of allAssets) {
    if (asset.status !== 'published') {
      continue;
    }
    const resolvable = regions.every((region) => {
      const probe = http.get(
        `${API}/routing/resolve?path=${encodeURIComponent(asset.origin_path)}` +
          `&client_region=${region}`,
      );
      return probe.status === 200;
    });
    if (resolvable) {
      paths.push(asset.origin_path);
    }
  }
  if (paths.length === 0) {
    throw new Error(
      'setup: no asset resolves in every region - run `docker compose run --rm seed`' +
        ' and `docker compose run --rm refresh`',
    );
  }

  return {
    nodeIds: healthy.map((n) => n.id),
    // Scenario C publishes versions, so it must only touch assets whose routes resolve -
    // otherwise its step 1 records a 503 that has nothing to do with the write path.
    assetIds: allAssets.filter((a) => paths.includes(a.origin_path)).map((a) => a.id),
    paths,
    regions,
    nodeCount: healthy.length,
    assetCount: paths.length,
    assets_in_database: allAssets.length,
  };
}
