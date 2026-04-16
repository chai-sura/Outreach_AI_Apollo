/**
 * Module: contact_discovery_linkedin
 * Finds prospect people in Apollo, then enriches them to retrieve LinkedIn URLs.
 *
 * Flow:
 * 1) People Search: /api/v1/mixed_people/api_search
 * 2) Enrichment:    /api/v1/people/bulk_match
 *
 * Env vars:
 * - API_KEY_CONTACT_DISCOVERY (required)
 * - LLM_PROVIDER + related keys (for llm planning step)
 */

import { llmGenerateJson } from './llm_client.js';

const APOLLO_BASE_URL = 'https://api.apollo.io';

function getEnv(name) {
  return typeof process !== 'undefined' ? process.env?.[name] : undefined;
}

function getApolloKey() {
  const apiKey = getEnv('API_KEY_CONTACT_DISCOVERY');
  if (!apiKey) {
    throw new Error(
      'Missing Apollo API key. Set API_KEY_CONTACT_DISCOVERY in your environment.'
    );
  }
  return apiKey;
}

async function buildLinkedinSearchSpecFromIntent(intentText) {
  const prompt = `
You convert outreach goals into Apollo People API filters.

User goal:
"""
${intentText}
"""

Return ONLY valid JSON with this exact shape:
{
  "titles": ["<string>"],
  "seniorities": ["<owner|founder|c_suite|partner|vp|head|director|manager|senior|entry|intern>"],
  "person_locations": ["<string>"],
  "organization_domains": ["<domain like nvidia.com>"],
  "keywords": ["<string>"]
}

Rules:
- Focus titles on people to contact (recruiters, talent acquisition, hiring managers).
- If user mentions a company, prefer organization_domains when possible.
- Keep arrays concise and high-signal.
`;

  const raw = await llmGenerateJson({ prompt });
  let parsed;
  try {
    const cleaned =
      typeof raw === 'string'
        ? raw.replace(/```json|```/g, '').trim()
        : JSON.stringify(raw);
    parsed = JSON.parse(cleaned);
  } catch {
    throw new Error(
      'contact_discovery_linkedin: LLM returned malformed JSON search spec'
    );
  }

  const arr = v => (Array.isArray(v) ? v : v ? [String(v)] : []);
  return {
    titles: arr(parsed.titles),
    seniorities: arr(parsed.seniorities),
    person_locations: arr(parsed.person_locations),
    organization_domains: arr(parsed.organization_domains),
    keywords: arr(parsed.keywords),
  };
}

async function apolloPeopleSearch({ spec, page = 1, per_page = 10 }) {
  const endpoint = new URL(`${APOLLO_BASE_URL}/api/v1/mixed_people/api_search`);
  endpoint.searchParams.set('page', String(page));
  endpoint.searchParams.set('per_page', String(per_page));
  endpoint.searchParams.set('include_similar_titles', 'true');

  const keywords = spec.keywords.join(' ').trim();
  if (keywords) endpoint.searchParams.set('q_keywords', keywords);

  for (const title of spec.titles) {
    endpoint.searchParams.append('person_titles[]', title);
  }
  for (const seniority of spec.seniorities) {
    endpoint.searchParams.append('person_seniorities[]', seniority);
  }
  for (const location of spec.person_locations) {
    endpoint.searchParams.append('person_locations[]', location);
  }
  for (const domain of spec.organization_domains) {
    endpoint.searchParams.append('q_organization_domains_list[]', domain);
  }

  const res = await fetch(endpoint.toString(), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-cache',
      accept: 'application/json',
      'x-api-key': getApolloKey(),
    },
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Apollo People Search error (${res.status}): ${text}`);
  }
  return await res.json();
}

function cloneSpec(spec) {
  return {
    titles: [...(spec.titles || [])],
    seniorities: [...(spec.seniorities || [])],
    person_locations: [...(spec.person_locations || [])],
    organization_domains: [...(spec.organization_domains || [])],
    keywords: [...(spec.keywords || [])],
  };
}

function buildRelaxedSpecLevels(baseSpec) {
  const s0 = cloneSpec(baseSpec); // strict

  // Relax level 1: remove location constraints
  const s1 = cloneSpec(baseSpec);
  s1.person_locations = [];

  // Relax level 2: remove seniority + locations
  const s2 = cloneSpec(baseSpec);
  s2.person_locations = [];
  s2.seniorities = [];

  // Relax level 3: keep company + recruiter titles only
  const s3 = cloneSpec(baseSpec);
  s3.person_locations = [];
  s3.seniorities = [];
  s3.keywords = [];

  return [s0, s1, s2, s3];
}

async function apolloBulkMatchByIds(peopleIds) {
  const res = await fetch(`${APOLLO_BASE_URL}/api/v1/people/bulk_match`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-cache',
      accept: 'application/json',
      'x-api-key': getApolloKey(),
    },
    body: JSON.stringify({
      details: peopleIds.map(id => ({ id })),
    }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Apollo Bulk Match error (${res.status}): ${text}`);
  }
  return await res.json();
}

function mapLinkedinResults(searchPeople, bulkData) {
  const bulkPeople =
    bulkData?.people || bulkData?.matches || bulkData?.match_results || [];
  const byId = new Map(
    bulkPeople
      .filter(p => p && p.id)
      .map(p => [p.id, p])
  );

  return (searchPeople || []).map(p => {
    const enriched = byId.get(p.id) || {};
    return {
      id: p.id,
      full_name:
        p.name ||
        [p.first_name, p.last_name].filter(Boolean).join(' ') ||
        null,
      title: p.title || null,
      organization_name: p.organization?.name || p.organization_name || null,
      linkedin_url:
        enriched.linkedin_url ||
        p.linkedin_url ||
        enriched.person_linkedin_url ||
        null,
      has_email: p.has_email ?? null,
    };
  });
}

/**
 * @param {object} params
 * @param {string} params.intent_text
 * @param {number} [params.page]
 * @param {number} [params.per_page]
 * @returns {Promise<{ prospects_with_linkedin: object[], search_spec: object, module_status: string, apollo_raw: object }>}
 */
export async function runContactDiscoveryLinkedin(params) {
  const { intent_text, page = 1, per_page = 10 } = params || {};
  if (!intent_text || !intent_text.trim()) {
    throw new Error('contact_discovery_linkedin: intent_text is required');
  }

  const search_spec = await buildLinkedinSearchSpecFromIntent(intent_text);
  const specLevels = buildRelaxedSpecLevels(search_spec);

  let peopleSearch = null;
  let people = [];
  let usedSearchSpec = search_spec;
  let retry_count = 0;

  for (let i = 0; i < specLevels.length; i += 1) {
    const candidateSpec = specLevels[i];
    const result = await apolloPeopleSearch({
      spec: candidateSpec,
      page,
      per_page,
    });
    const found = result?.people || [];
    if (found.length > 0) {
      peopleSearch = result;
      people = found;
      usedSearchSpec = candidateSpec;
      retry_count = i;
      break;
    }
    // Keep latest response in case all levels are empty.
    peopleSearch = result;
    retry_count = i;
  }

  const ids = people.map(p => p.id).filter(Boolean);

  if (ids.length === 0) {
    return {
      prospects_with_linkedin: [],
      search_spec: usedSearchSpec,
      retry_count,
      module_status: 'success',
      apollo_raw: { people_search: peopleSearch, bulk_match: null },
    };
  }

  const bulkMatch = await apolloBulkMatchByIds(ids);
  const prospects_with_linkedin = mapLinkedinResults(people, bulkMatch);

  return {
    prospects_with_linkedin,
    search_spec: usedSearchSpec,
    retry_count,
    module_status: 'success',
    apollo_raw: { people_search: peopleSearch, bulk_match: bulkMatch },
  };
}

