const { DomainError } = require('../errors/domain-error');
const { LEVELS } = require('../streams/event-analyzer.transform');

// Validation for the lab 5 endpoints, kept beside the lab 4 validators and
// re-exported from validation.js, so routes keep importing one module.
//
// The job body is the widest input surface the service has: it sets buffer
// sizes and artificial delays, so every number needs a range. Without them a
// highWaterMark of 2 GB or a delay of an hour would be accepted by HTTP and
// only fail deep inside a stream, where the error says nothing useful.
const KiB = 1024;
const MiB = 1024 * KiB;

const MODES = ['analyze', 'slow', 'compare'];
const CHAINS = ['pipe', 'pipeline'];

const RANGES = {
  highWaterMark: { min: 1 * KiB, max: 16 * MiB },
  slowDelayMs: { min: 0, max: 5000 },
  delayMs: { min: 0, max: 5000 },
  minLatencyMs: { min: 0, max: 60000 },
  bytes: { min: 64 * KiB, max: 8 * 1024 * MiB },
  sampleEvery: { min: 0, max: 1000000 },
  chunkBatch: { min: 1, max: 500 },
};

function validateJobId(req, res, next, value) {
  if (!/^[0-9a-f]{8}$/.test(value)) {
    next(DomainError.validation('invalid_job_id', `Job id must be 8 hex characters, got "${value}"`));
    return;
  }

  req.jobId = value;
  next();
}

// Builds the sanitised job description on the request, so the controller passes
// a known-good object on and the service never sees a raw body.
// The task ids of the walkthrough page. A whitelist shape rather than a list of
// names, so adding a task does not mean editing the middleware.
function validateTaskId(req, res, next, value) {
  if (!/^[a-z][a-z-]{2,30}$/.test(value)) {
    next(DomainError.validation('invalid_task_id', `Task id must be lowercase letters and dashes, got "${value}"`));
    return;
  }

  req.params.taskId = value;
  next();
}

function validateStreamJob(req, res, next) {
  const body = req.body;
  const problems = [];
  const job = {};

  if (body.mode !== undefined) {
    if (!MODES.includes(body.mode)) {
      problems.push(`mode must be one of ${MODES.join(', ')}`);
    } else {
      job.mode = body.mode;
    }
  }

  if (body.chain !== undefined) {
    if (!CHAINS.includes(body.chain)) {
      problems.push(`chain must be one of ${CHAINS.join(', ')}`);
    } else {
      job.chain = body.chain;
    }
  }

  for (const [field, range] of Object.entries(RANGES)) {
    if (body[field] === undefined) {
      continue;
    }
    const value = Number(body[field]);
    if (!Number.isInteger(value) || value < range.min || value > range.max) {
      problems.push(`${field} must be an integer in [${range.min}, ${range.max}]`);
      continue;
    }
    job[field] = value;
  }

  if (body.levels !== undefined) {
    if (!Array.isArray(body.levels) || body.levels.length === 0) {
      problems.push('levels must be a non-empty array when present');
    } else {
      const unknown = body.levels.filter((level) => !LEVELS.includes(level));
      if (unknown.length > 0) {
        problems.push(`unknown levels: ${unknown.join(', ')}`);
      } else {
        job.levels = [...new Set(body.levels)];
      }
    }
  }

  if (body.grep !== undefined) {
    if (typeof body.grep !== 'string' || body.grep.length > 100) {
      problems.push('grep must be a string of at most 100 characters');
    } else if (body.grep.trim() !== '') {
      job.grep = body.grep.trim();
    }
  }

  if (problems.length > 0) {
    next(DomainError.validation('invalid_job', problems.join('; ')));
    return;
  }

  req.streamJob = job;
  next();
}

function requireText(req, res, next) {
  const text = req.body.text;

  if (typeof text !== 'string' || text.trim() === '' || text.length > 2000) {
    next(DomainError.validation('invalid_text', 'Body must carry a non-empty "text" of at most 2000 characters'));
    return;
  }

  req.body.text = text.trim();
  next();
}

module.exports = { validateJobId, validateTaskId, validateStreamJob, requireText, MODES, CHAINS, RANGES };
