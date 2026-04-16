const express = require('express');
const multer = require('multer');
const pdfParse = require('pdf-parse');
const axios = require('axios');
const router = express.Router();
const authMiddleware = require('../middleware/auth');

const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 10 * 1024 * 1024 } });

async function callClaude(prompt) {
  const r = await axios.post('https://api.anthropic.com/v1/messages', {
    model: 'claude-sonnet-4-20250514',
    max_tokens: 800,
    messages: [{ role: 'user', content: prompt }],
  }, {
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': process.env.ANTHROPIC_API_KEY,
      'anthropic-version': '2023-06-01',
    }
  });
  return r.data.content[0].text;
}

// Upload and parse resume PDF
router.post('/upload', authMiddleware, upload.single('resume'), async (req, res) => {
  try {
    if (!req.file) return res.status(400).json({ error: 'No file uploaded' });

    const pdfData = await pdfParse(req.file.buffer);
    const rawText = pdfData.text;

    const prompt = `Extract key information from this resume.

Resume text:
${rawText.slice(0, 3000)}

Respond ONLY as JSON:
{
  "name": "person's name",
  "currentRole": "current job title",
  "currentCompany": "current company",
  "skills": ["top 5 skills"],
  "experience": "2-3 sentence summary",
  "education": "highest degree and school",
  "achievements": ["top 3 achievements"],
  "tone": "professional tone description"
}`;

    const raw = await callClaude(prompt);
    let parsed;
    try { parsed = JSON.parse(raw.replace(/```json|```/g, '').trim()); }
    catch { parsed = {}; }

    res.json({
      rawText: rawText.slice(0, 5000),
      parsed,
      filename: req.file.originalname,
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

module.exports = router;