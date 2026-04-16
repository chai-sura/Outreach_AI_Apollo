import { runContactDiscovery } from '../modules/contact_discovery.js';

function pickContactFields(p) {
  if (!p || typeof p !== 'object') return p;
  const joinedName = [p.first_name, p.last_name].filter(Boolean).join(' ');
  return {
    id: p.id ?? p.person_id ?? null,
    name: p.name ?? (joinedName || null),

    title: p.title ?? p.headline ?? null,
    company: p.organization_name ?? p.company?.name ?? p.company_name ?? null,
    location: p.location ?? p.city ?? p.state ?? p.country ?? null,
    linkedin_url: p.linkedin_url ?? p.linkedin ?? null,
    email: p.email ?? null,
  };
}

const intent =
  'I want to work as a machine learning engineer at NVIDIA and reach out to recruiters';

try {
  const result = await runContactDiscovery({
    intent_text: intent,
    page: 1,
    per_page: 10,
  });

  console.log('module_status:', result.module_status);
  console.log('retry_count:', result.retry_count);
  console.log('search_spec:', JSON.stringify(result.search_spec, null, 2));
  console.log('contacts_found:', Array.isArray(result.contacts) ? result.contacts.length : 0);
  console.log(
    'sample_contacts:',
    JSON.stringify((result.contacts || []).slice(0, 5).map(pickContactFields), null, 2)
  );
} catch (err) {
  console.error('CONTACT DISCOVERY TEST FAILED:', err?.message || err);
  console.error('Full error object:', err);
  process.exit(1);
}

