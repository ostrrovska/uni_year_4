// The Item shape and the rules for its fields, in one place, so Service,
// repositories and tests agree on a single definition. validateDraft returns
// plain messages; wrapping them in a DomainError is the Service's job.
const MAX_NAME_LENGTH = 100;
const MAX_DESCRIPTION_LENGTH = 500;

function validateDraft(draft) {
  const problems = [];

  if (typeof draft.name !== 'string') {
    problems.push('name is required and must be a string');
  } else if (draft.name.trim() === '') {
    problems.push('name must not be empty');
  } else if (draft.name.trim().length > MAX_NAME_LENGTH) {
    problems.push(`name must be at most ${MAX_NAME_LENGTH} characters`);
  }

  if (draft.description !== undefined && typeof draft.description !== 'string') {
    problems.push('description must be a string when present');
  } else if (typeof draft.description === 'string' && draft.description.length > MAX_DESCRIPTION_LENGTH) {
    problems.push(`description must be at most ${MAX_DESCRIPTION_LENGTH} characters`);
  }

  return problems;
}

function normalizeDraft(draft) {
  return {
    name: draft.name.trim(),
    description: typeof draft.description === 'string' ? draft.description.trim() : '',
  };
}

module.exports = { validateDraft, normalizeDraft, MAX_NAME_LENGTH, MAX_DESCRIPTION_LENGTH };
