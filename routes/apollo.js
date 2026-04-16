const express = require('express');
const axios = require('axios');
const router = express.Router();
const authMiddleware = require('../middleware/auth');

// Find a single person by name + company
router.post('/find-person', authMiddleware, async (req, res) => {
  const { firstName, lastName, company } = req.body;
  try {
    const body = {
      api_key: process.env.APOLLO_API_KEY,
      first_name: firstName,
      last_name: lastName,
    };
    if (company) body.organization_name = company;
    const response = await axios.post('https://api.apollo.io/v1/people/match', body);
    const person = response.data.person || {};
    res.json({
      name: `${person.first_name || ''} ${person.last_name || ''}`.trim(),
      email: person.email || null,
      emailConfidence: person.email_confidence || null,
      title: person.title || null,
      company: person.organization?.name || company || null,
      linkedin: person.linkedin_url || null,
      city: person.city || null,
      country: person.country || null,
      companyDetails: person.organization ? {
        industry: person.organization.industry,
        employees: person.organization.estimated_num_employees,
        description: person.organization.short_description,
        revenue: person.organization.annual_revenue_printed,
      } : null,
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Search people by role + company/industry (for chatbot)
router.post('/search', authMiddleware, async (req, res) => {
  const { title, company, industry, location, limit = 5 } = req.body;
  try {
    const body = {
      api_key: process.env.APOLLO_API_KEY,
      per_page: limit,
    };
    if (title) body.person_titles = [title];
    if (company) body.organization_names = [company];
    if (location) body.person_locations = [location];

    const response = await axios.post('https://api.apollo.io/v1/mixed_people/search', body);
    const people = (response.data.people || []).map(p => ({
      name: `${p.first_name || ''} ${p.last_name || ''}`.trim(),
      email: p.email || null,
      emailConfidence: p.email_confidence || null,
      title: p.title || null,
      company: p.organization?.name || null,
      linkedin: p.linkedin_url || null,
      city: p.city || null,
      companyDetails: p.organization ? {
        industry: p.organization.industry,
        employees: p.organization.estimated_num_employees,
        description: p.organization.short_description,
      } : null,
    }));
    res.json({ people });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

module.exports = router;