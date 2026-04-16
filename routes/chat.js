const express = require('express');
const axios = require('axios');
const router = express.Router();
const authMiddleware = require('../middleware/auth');

const claudeHeaders = {
  'Content-Type': 'application/json',
  'x-api-key': process.env.ANTHROPIC_API_KEY,
  'anthropic-version': '2023-06-01',
};

async function callClaude(prompt, maxTokens = 1200) {
  const response = await axios.post('https://api.anthropic.com/v1/messages', {
    model: 'claude-sonnet-4-20250514',
    max_tokens: maxTokens,
    messages: [{ role: 'user', content: prompt }],
  }, { headers: claudeHeaders });
  return response.data.content[0].text;
}

function parseJSON(raw) {
  try { return JSON.parse(raw.replace(/```json|```/g, '').trim()); }
  catch { return null; }
}

router.post('/message', authMiddleware, async (req, res) => {
  const { message, resumeText } = req.body;
  try {
    // Step 1: Understand intent
    const intentPrompt = `You are an AI assistant for a sales outreach tool.
Analyze this message and extract intent.

User message: "${message}"

Intents:
- "find_people" — user wants to find contacts
- "generate_email" — user wants to write an email
- "meeting_prep" — user wants meeting prep
- "analyze_reply" — user wants to analyze a reply
- "general" — general question

Respond ONLY as JSON:
{
  "intent": "find_people|generate_email|meeting_prep|analyze_reply|general",
  "searchParams": {
    "title": "job title or null",
    "company": "company name or null",
    "location": "city or null",
    "limit": 3
  },
  "personName": "specific person name or null",
  "companyName": "specific company or null",
  "response": "friendly response to show user"
}`;

    const intentRaw = await callClaude(intentPrompt, 600);
    const intent = parseJSON(intentRaw);

    if (!intent) {
      return res.json({ type: 'text', message: "Try saying something like 'Find me 3 recruiters at Google' or 'Write an email to John Smith at Stripe'." });
    }

    // Step 2: Find people
    if (intent.intent === 'find_people' && intent.searchParams) {
      const searchBody = {
        api_key: process.env.APOLLO_API_KEY,
        per_page: intent.searchParams.limit || 3,
      };
      if (intent.searchParams.title) searchBody.person_titles = [intent.searchParams.title];
      if (intent.searchParams.company) searchBody.organization_names = [intent.searchParams.company];
      if (intent.searchParams.location) searchBody.person_locations = [intent.searchParams.location];

      let people = [];
      try {
        const apolloRes = await axios.post('https://api.apollo.io/v1/mixed_people/search', searchBody);
        people = apolloRes.data.people || [];
      } catch (e) {}

      // Generate background + email for each person
      const results = await Promise.all(people.slice(0, intent.searchParams.limit || 3).map(async (p) => {
        const personData = {
          name: `${p.first_name || ''} ${p.last_name || ''}`.trim(),
          email: p.email || null,
          emailConfidence: p.email_confidence || null,
          title: p.title || null,
          company: p.organization?.name || null,
          linkedin: p.linkedin_url || null,
          city: p.city || null,
          industry: p.organization?.industry || null,
          companyDescription: p.organization?.short_description || null,
        };

        const emailPrompt = `Write a personalized cold outreach email.

Person: ${personData.name}
Title: ${personData.title || 'unknown'}
Company: ${personData.company || 'unknown'}
Location: ${personData.city || 'unknown'}
Industry: ${personData.industry || 'unknown'}
${personData.companyDescription ? `Company: ${personData.companyDescription}` : ''}
${resumeText ? `\nSender resume:\n${resumeText.slice(0, 800)}` : ''}

Respond ONLY as JSON:
{
  "background": "2 sentence description of this person",
  "subject": "email subject",
  "email": "full email body"
}`;

        try {
          const emailRaw = await callClaude(emailPrompt, 800);
          const emailData = parseJSON(emailRaw) || {};
          return { ...personData, ...emailData };
        } catch {
          return personData;
        }
      }));

      return res.json({
        type: 'people_results',
        message: intent.response || `Found ${results.length} people for you!`,
        people: results,
      });
    }

    // Step 3: Generate single email
    if (intent.intent === 'generate_email') {
      let personData = {
        name: intent.personName || 'Unknown',
        company: intent.companyName || null,
        email: null,
        title: null,
        linkedin: null,
      };

      if (intent.personName) {
        const nameParts = intent.personName.split(' ');
        try {
          const apolloBody = {
            api_key: process.env.APOLLO_API_KEY,
            first_name: nameParts[0],
            last_name: nameParts.slice(1).join(' '),
          };
          if (intent.companyName) apolloBody.organization_name = intent.companyName;
          const apolloRes = await axios.post('https://api.apollo.io/v1/people/match', apolloBody);
          const p = apolloRes.data.person || {};
          personData = {
            name: intent.personName,
            email: p.email || null,
            emailConfidence: p.email_confidence || null,
            title: p.title || null,
            company: p.organization?.name || intent.companyName || null,
            linkedin: p.linkedin_url || null,
            city: p.city || null,
          };
        } catch {}
      }

      const emailPrompt = `Write a hyper-personalized cold outreach email.

Person: ${personData.name}
Title: ${personData.title || 'unknown'}
Company: ${personData.company || 'unknown'}
${resumeText ? `\nSender resume:\n${resumeText.slice(0, 800)}` : ''}

Respond ONLY as JSON:
{
  "background": "2 sentence description",
  "subject": "...",
  "email": "full email body"
}`;

      const emailRaw = await callClaude(emailPrompt, 800);
      const emailData = parseJSON(emailRaw) || {};

      return res.json({
        type: 'single_email',
        message: intent.response || `Here's a personalized email for ${personData.name}!`,
        person: { ...personData, ...emailData },
      });
    }

    // General response
    const generalPrompt = `You are a helpful AI assistant for a sales outreach tool called Outreach AI.
You help users find contacts, write emails, prep for meetings, and analyze replies.
User said: "${message}"
Respond helpfully in under 3 sentences.`;

    const generalResponse = await callClaude(generalPrompt, 300);
    return res.json({ type: 'text', message: generalResponse });

  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

module.exports = router;