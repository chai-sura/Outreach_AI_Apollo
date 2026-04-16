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
  const r = await axios.post('https://api.anthropic.com/v1/messages', {
    model: 'claude-sonnet-4-20250514',
    max_tokens: maxTokens,
    messages: [{ role: 'user', content: prompt }],
  }, { headers: claudeHeaders });
  return r.data.content[0].text;
}

function parseJSON(raw) {
  try { return JSON.parse(raw.replace(/```json|```/g, '').trim()); }
  catch { return null; }
}

// Generate single email
router.post('/generate', authMiddleware, async (req, res) => {
  const { personData, tone, goal, resumeText, includeWhy } = req.body;
  try {
    const toneDesc = {
      casual: 'friendly and conversational',
      formal: 'professional and polished',
      sales: 'compelling and benefit-focused',
      partnership: 'collaborative',
      job: 'enthusiastic about the opportunity',
      investor: 'concise and data-driven',
    }[tone] || 'professional';

    let ctx = `Name: ${personData.name}\n`;
    if (personData.title) ctx += `Title: ${personData.title}\n`;
    if (personData.company) ctx += `Company: ${personData.company}\n`;
    if (personData.city) ctx += `Location: ${personData.city}\n`;
    if (personData.companyDetails) ctx += `Company Info: ${JSON.stringify(personData.companyDetails)}\n`;
    if (resumeText) ctx += `\nSender's Resume:\n${resumeText.slice(0, 800)}\n`;

    const prompt = `You are an expert at writing hyper-personalized cold outreach emails.

${ctx}
Tone: ${toneDesc}
${goal ? `Goal: ${goal}` : ''}

Write a personalized cold email using specific details. Keep body under 150 words.

Respond ONLY as JSON:
{"subject":"...","opening":"...","body":"...","closing":"..."}`;

    const raw = await callClaude(prompt);
    const email = parseJSON(raw) || { subject: 'Reaching Out', body: raw };

    let why = null;
    if (includeWhy) {
      const whyPrompt = `You wrote this cold email. Explain WHY it will work with 4 specific insights.
Person: ${personData.name}, ${personData.title || ''} at ${personData.company || ''}
Subject: ${email.subject}
Body: ${email.body}
Tone: ${tone}
Goal: ${goal || 'general outreach'}

Respond ONLY as JSON:
{"insights":["reason 1","reason 2","reason 3","reason 4"]}`;
      const whyRaw = await callClaude(whyPrompt, 600);
      why = parseJSON(whyRaw);
    }

    res.json({ email, why });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Generate A/B variants
router.post('/ab-test', authMiddleware, async (req, res) => {
  const { personData, goal, resumeText } = req.body;
  try {
    const prompt = `Generate 3 cold email variations for the same person with different angles.

Person: ${personData.name}, ${personData.title || ''} at ${personData.company || ''}
Goal: ${goal || 'introduce and request a meeting'}
${resumeText ? `Sender resume: ${resumeText.slice(0, 500)}` : ''}

Variations:
1. "Pain Point" - lead with a problem they likely have
2. "Social Proof" - lead with credibility
3. "Curiosity" - lead with an intriguing question

Score each out of 100 for predicted open rate.

Respond ONLY as JSON:
{"variants":[{"angle":"Pain Point","score":82,"subject":"...","body":"...","reasoning":"..."},{"angle":"Social Proof","score":75,"subject":"...","body":"...","reasoning":"..."},{"angle":"Curiosity","score":90,"subject":"...","body":"...","reasoning":"..."}]}`;

    const raw = await callClaude(prompt, 2000);
    res.json(parseJSON(raw));
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Meeting prep
router.post('/meeting-prep', authMiddleware, async (req, res) => {
  const { personData, goal } = req.body;
  try {
    const prompt = `Create a pre-meeting brief.

Person: ${personData.name}
Role: ${personData.title || 'unknown'}
Company: ${personData.company || 'unknown'}
Meeting purpose: ${goal || 'general meeting'}

Respond ONLY as JSON:
{"talkingPoints":["..."],"painPoints":["..."],"thingsToAvoid":["..."],"quickFacts":["..."],"openingLine":"...","closingAsk":"..."}`;

    const raw = await callClaude(prompt, 1500);
    res.json(parseJSON(raw));
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Reply analyzer
router.post('/analyze-reply', authMiddleware, async (req, res) => {
  const { replyText, senderName, context } = req.body;
  try {
    const prompt = `Analyze this email reply and draft the perfect follow-up.

Reply${senderName ? ' from ' + senderName : ''}:
"${replyText}"
${context ? `Context: ${context}` : ''}

Respond ONLY as JSON:
{"sentiment":"Positive/Negative/Neutral/Mixed","intent":"...","keySignals":["..."],"recommendedApproach":"...","followUpSubject":"...","followUpEmail":"..."}`;

    const raw = await callClaude(prompt, 1200);
    res.json(parseJSON(raw));
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

module.exports = router;