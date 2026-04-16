const express = require('express');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const router = express.Router();

// In-memory user store for demo (replace with Supabase in production)
const users = {};

// Signup
router.post('/signup', async (req, res) => {
  const { email, password, name } = req.body;
  try {
    if (users[email]) return res.status(400).json({ error: 'User already exists' });
    const hashedPassword = await bcrypt.hash(password, 10);
    const user = { id: Date.now().toString(), email, name, password: hashedPassword, plan: 'free', emailsUsed: 0 };
    users[email] = user;
    const token = jwt.sign({ id: user.id, email: user.email }, process.env.JWT_SECRET, { expiresIn: '30d' });
    res.json({ token, user: { id: user.id, email: user.email, name: user.name, plan: user.plan } });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Login
router.post('/login', async (req, res) => {
  const { email, password } = req.body;
  try {
    const user = users[email];
    if (!user) return res.status(400).json({ error: 'User not found' });
    const valid = await bcrypt.compare(password, user.password);
    if (!valid) return res.status(400).json({ error: 'Wrong password' });
    const token = jwt.sign({ id: user.id, email: user.email }, process.env.JWT_SECRET, { expiresIn: '30d' });
    res.json({ token, user: { id: user.id, email: user.email, name: user.name, plan: user.plan } });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Get current user
router.get('/me', require('../middleware/auth'), async (req, res) => {
  const user = Object.values(users).find(u => u.id === req.user.id);
  if (!user) return res.status(404).json({ error: 'User not found' });
  res.json({ id: user.id, email: user.email, name: user.name, plan: user.plan, emailsUsed: user.emailsUsed });
});

module.exports = router;