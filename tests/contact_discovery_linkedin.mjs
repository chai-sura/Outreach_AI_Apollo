import { runContactDiscoveryLinkedin } from '../modules/contact_discovery_linkedin.js';

const intentText =
  'I want to work as a machine learning engineer at NVIDIA and reach out to recruiters located in the united states';

try {
  const result = await runContactDiscoveryLinkedin({
    intent_text: intentText,
    page: 1,
    per_page: 10,
  });

  console.log('module_status:', result.module_status);
  console.log('retry_count:', result.retry_count);
  console.log('search_spec:', JSON.stringify(result.search_spec, null, 2));
  console.log(
    'prospects_count:',
    Array.isArray(result.prospects_with_linkedin)
      ? result.prospects_with_linkedin.length
      : 0
  );
  console.log(
    'sample_prospects_with_linkedin:',
    JSON.stringify((result.prospects_with_linkedin || []).slice(0, 5), null, 2)
  );
} catch (err) {
  console.error(
    'CONTACT DISCOVERY LINKEDIN TEST FAILED:',
    err?.message || err
  );
  console.error('Full error object:', err);
  process.exit(1);
}

