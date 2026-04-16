const express = require('express');
const router = express.Router();
const authMiddleware = require('../middleware/auth');

const emailStore = {};

// Save a sent email
router.post('/save', authMiddleware, async (req, res) => {
  try {
    const { emailId, to, subject, body, recipientName, recipientCompany } = req.body;
    const userId = req.user.id;
    if (!emailStore[userId]) emailStore[userId] = [];
    const email = {
      id: emailId || Date.now().toString(),
      to, subject, body, recipientName, recipientCompany,
      sentAt: new Date().toISOString(),
      opened: false, openedAt: null,
      clicked: false, clickedAt: null,
      replied: false, repliedAt: null,
      status: 'sent',
    };
    emailStore[userId].push(email);
    res.json({ success: true, email });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Get all tracked emails
router.get('/list', authMiddleware, async (req, res) => {
  try {
    const userId = req.user.id;
    const emails = emailStore[userId] || [];
    res.json({ emails: emails.sort((a, b) => new Date(b.sentAt) - new Date(a.sentAt)) });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Track email open via 1x1 pixel
router.get('/open/:emailId', async (req, res) => {
  try {
    const { emailId } = req.params;
    for (const userId in emailStore) {
      const email = emailStore[userId].find(e => e.id === emailId);
      if (email && !email.opened) {
        email.opened = true;
        email.openedAt = new Date().toISOString();
        email.status = 'opened';
      }
    }
    const pixel = Buffer.from('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7', 'base64');
    res.set('Content-Type', 'image/gif');
    res.send(pixel);
  } catch (e) {
    res.status(200).send('');
  }
});

// Mark as replied
router.post('/reply/:emailId', authMiddleware, async (req, res) => {
  try {
    const { emailId } = req.params;
    for (const userId in emailStore) {
      const email = emailStore[userId].find(e => e.id === emailId);
      if (email) {
        email.replied = true;
        email.repliedAt = new Date().toISOString();
        email.status = 'replied';
      }
    }
    res.json({ success: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Get stats
router.get('/stats', authMiddleware, async (req, res) => {
  try {
    const userId = req.user.id;
    const emails = emailStore[userId] || [];
    res.json({
      total: emails.length,
      sent: emails.filter(e => e.status === 'sent').length,
      opened: emails.filter(e => e.opened).length,
      clicked: emails.filter(e => e.clicked).length,
      replied: emails.filter(e => e.replied).length,
      openRate: emails.length ? Math.round((emails.filter(e => e.opened).length / emails.length) * 100) : 0,
      replyRate: emails.length ? Math.round((emails.filter(e => e.replied).length / emails.length) * 100) : 0,
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

module.exports = router;